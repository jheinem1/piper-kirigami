# SPDX-License-Identifier: GPL-2.0-or-later
"""Piper's original SVG artwork, rendered and hit-tested by Qt SVG.

Coordinates exposed to QML are *intrinsic image pixels*, not raw viewBox
coordinates.  Every hit mask is rendered from the original SVG subtree with
its complete ancestor chain.  This also handles transformed groups, curved
paths, even/odd holes, strokes, and the compound wheel/LED targets without a
second, incomplete SVG path parser.

Register ``DiagramCatalog`` as the ``diagrams`` context property and install
``DiagramImageProvider(catalog)`` as the ``piper-diagrams`` image provider.
``describe`` accepts either a ratbag model ID or a bundled SVG filename.
"""

from __future__ import annotations

import configparser
import copy
import math
import os
import re
import threading
from collections import OrderedDict
from dataclasses import dataclass
from pathlib import Path
from urllib.parse import parse_qs, quote, unquote, urlencode
from xml.etree import ElementTree as ET

from PySide6.QtCore import QByteArray, QObject, QRectF, QSize, Qt, Slot
from PySide6.QtGui import QColor, QImage, QPainter
from PySide6.QtQuick import QQuickImageProvider
from PySide6.QtSvg import QSvgRenderer

SVG_NS = "http://www.w3.org/2000/svg"
TARGET_RE = re.compile(r"^(button|led)(\d+)$")
_LAYER_NAMES = {
    "button": "buttons",
    "buttons": "buttons",
    "led": "leds",
    "leds": "leds",
}
ET.register_namespace("", SVG_NS)


def find_svg_directory() -> Path:
    """Find source-tree or installed artwork without requiring GTK resources."""
    candidates = []
    if os.environ.get("PIPER_SVG_DIR"):
        candidates.append(Path(os.environ["PIPER_SVG_DIR"]))
    candidates.append(Path(__file__).resolve().parent.parent / "data" / "svgs")
    data_home = Path(os.environ.get("XDG_DATA_HOME", Path.home() / ".local/share"))
    data_dirs = [
        data_home,
        *(
            Path(p)
            for p in os.environ.get(
                "XDG_DATA_DIRS", "/usr/local/share:/usr/share"
            ).split(":")
        ),
    ]
    for base in data_dirs:
        candidates.extend((base / "piper" / "svgs", base / "piper-qt" / "svgs"))
    for directory in candidates:
        if (directory / "svg-lookup.ini").is_file() and (
            directory / "fallback.svg"
        ).is_file():
            return directory
    raise FileNotFoundError(
        "Piper SVG artwork is missing; set PIPER_SVG_DIR to its svgs directory"
    )


def _tag(element: ET.Element) -> str:
    return element.tag.rsplit("}", 1)[-1]


def _length(value: str | None, default: float) -> float:
    match = re.match(r"^\s*([-+0-9.eE]+)", value or "")
    return float(match[1]) if match else default


def _normalise_root(root: ET.Element) -> tuple[ET.Element, float, float]:
    """Turn SVG user units into intrinsic pixels, retaining SVG's aspect rule."""
    root = copy.deepcopy(root)
    # Qt SVG supports patterns, but does not resolve inherited pattern hrefs.
    # Materialize the SVG-standard inherited attributes/children so the two
    # striped Mars Gaming targets retain their original artwork under Qt.
    ids = {element.get("id"): element for element in root.iter() if element.get("id")}

    def expand_pattern(
        element: ET.Element, ancestors: frozenset[str] = frozenset()
    ) -> None:
        href = element.get(
            "{http://www.w3.org/1999/xlink}href", element.get("href", "")
        )
        if (
            _tag(element) != "pattern"
            or not href.startswith("#")
            or href[1:] in ancestors
        ):
            return
        base = ids.get(href[1:])
        if base is None or _tag(base) != "pattern":
            return
        expand_pattern(base, ancestors | {href[1:]})
        for key, value in base.attrib.items():
            if key not in element.attrib and key not in (
                "id",
                "href",
                "{http://www.w3.org/1999/xlink}href",
            ):
                element.set(key, value)
        if not len(element):
            for child in base:
                clone = copy.deepcopy(child)
                for descendant in clone.iter():
                    descendant.attrib.pop("id", None)
                element.append(clone)
        element.attrib.pop("{http://www.w3.org/1999/xlink}href", None)
        element.attrib.pop("href", None)

    for element in list(root.iter()):
        expand_pattern(element)
    view = [float(v) for v in re.split(r"[\s,]+", root.get("viewBox", "").strip()) if v]
    width = _length(root.get("width"), view[2] if view else 450.0)
    height = _length(root.get("height"), view[3] if view else 450.0)
    if width <= 0 or height <= 0:
        raise ValueError("SVG has an invalid intrinsic size")
    if not view:
        view = [0.0, 0.0, width, height]
    if len(view) != 4 or view[2] <= 0 or view[3] <= 0:
        raise ValueError("SVG has an invalid viewBox")
    sx, sy = width / view[2], height / view[3]
    aspect = root.get("preserveAspectRatio", "xMidYMid meet").replace("defer ", "")
    tx, ty = -view[0] * sx, -view[1] * sy
    if not aspect.startswith("none"):
        scale = max(sx, sy) if "slice" in aspect else min(sx, sy)
        align = aspect.split()[0]
        x_align = 0.0 if "xMin" in align else 1.0 if "xMax" in align else 0.5
        y_align = 0.0 if "YMin" in align else 1.0 if "YMax" in align else 0.5
        tx = (width - view[2] * scale) * x_align - view[0] * scale
        ty = (height - view[3] * scale) * y_align - view[1] * scale
        sx = sy = scale
    root.set("width", str(width))
    root.set("height", str(height))
    root.set("viewBox", f"0 0 {width} {height}")
    root.set("preserveAspectRatio", "none")
    wrapper = ET.Element(
        f"{{{SVG_NS}}}g", {"transform": f"matrix({sx},0,0,{sy},{tx},{ty})"}
    )
    for child in list(root):
        if _tag(child) not in ("defs", "metadata", "title", "desc", "style"):
            root.remove(child)
            wrapper.append(child)
    root.append(wrapper)
    # GTK renders these layers explicitly even when an Inkscape author hid one.
    for element in root.iter():
        if element.get("id") in ("Device", "Buttons", "LEDs"):
            style = re.sub(r"(?:^|;)\s*display\s*:[^;]*", "", element.get("style", ""))
            element.set("style", style.strip(";") + ";display:inline")
            element.set("display", "inline")
    return root, width, height


def _selected_svg(root: ET.Element, selected: set[str]) -> bytes:
    """Retain selected subtrees, their ancestors, definitions, and styles."""

    def keep(element: ET.Element) -> ET.Element | None:
        if element.get("id") in selected or _tag(element) in ("defs", "style"):
            return copy.deepcopy(element)
        children = [result for child in element if (result := keep(child)) is not None]
        if not children and element is not root:
            return None
        clone = ET.Element(element.tag, dict(element.attrib))
        clone.text = element.text
        clone.extend(children)
        return clone

    result = keep(root)
    assert result is not None
    return ET.tostring(result, encoding="utf-8", xml_declaration=True)


def _renderer(svg: bytes) -> QSvgRenderer:
    renderer = QSvgRenderer(QByteArray(svg))
    if not renderer.isValid():
        raise ValueError("Qt could not render the device SVG")
    renderer.setAspectRatioMode(Qt.AspectRatioMode.IgnoreAspectRatio)
    return renderer


@dataclass(frozen=True)
class HitMask:
    """A tightly bounded antialiased alpha mask, at two samples per pixel."""

    x: float
    y: float
    width: int
    height: int
    scale: float
    alpha: bytes

    def contains(self, x: float, y: float) -> bool:
        px, py = math.floor((x - self.x) * self.scale), math.floor(
            (y - self.y) * self.scale
        )
        return (
            0 <= px < self.width
            and 0 <= py < self.height
            and self.alpha[py * self.width + px] > 16
        )

    def interior_point(self) -> tuple[float, float] | None:
        """Return an actual painted point, including for rings/compound paths."""
        cx, cy = (
            self.x + self.width / self.scale / 2,
            self.y + self.height / self.scale / 2,
        )
        if self.contains(cx, cy):
            return cx, cy
        for y in range(self.height):
            row = self.alpha[y * self.width : (y + 1) * self.width]
            for x, alpha in enumerate(row):
                if alpha > 128:
                    return (
                        self.x + (x + 0.5) / self.scale,
                        self.y + (y + 0.5) / self.scale,
                    )
        return None


class SvgDiagram:
    """One original Piper SVG and its selectable hardware targets."""

    def __init__(self, path: Path):
        self.path = Path(path)
        self.root, self.width, self.height = _normalise_root(ET.parse(path).getroot())
        self.elements = {
            element.get("id"): element
            for element in self.root.iter()
            if element.get("id")
        }
        self.svg = ET.tostring(self.root, encoding="utf-8")
        self.renderer = _renderer(self.svg)
        self.targets = sorted(
            (key for key in self.elements if TARGET_RE.fullmatch(key)),
            key=lambda value: (
                value.startswith("led"),
                int(TARGET_RE.fullmatch(value)[2]),
            ),
        )
        self._masks: dict[str, HitMask] = {}
        self._renderers: OrderedDict[tuple[str, ...], QSvgRenderer] = OrderedDict()
        self._lock = threading.RLock()

    def bounds(self, element_id: str) -> QRectF:
        element_id = element_id.lstrip("#")
        if not self.renderer.elementExists(element_id):
            return QRectF()
        # boundsOnElement includes the element's transform; transformForElement
        # supplies all ancestors. Applying only one of these breaks rotations.
        return self.renderer.transformForElement(element_id).mapRect(
            self.renderer.boundsOnElement(element_id)
        )

    def selected_renderer(
        self, element_ids: set[str], hit_target: bool = False
    ) -> QSvgRenderer:
        key = tuple(sorted(element_ids)) + (("@hit",) if hit_target else ())
        with self._lock:
            if key in self._renderers:
                self._renderers.move_to_end(key)
                return self._renderers[key]
            svg = _selected_svg(self.root, element_ids)
            if hit_target:
                # Sensei RAW/Ten use invisible rectangles solely as hit regions.
                # Paint those in masks/highlights while leaving the artwork intact.
                root = ET.fromstring(svg)
                for element in root.iter():
                    if element.get("id") not in element_ids or _tag(element) not in (
                        "rect",
                        "circle",
                        "ellipse",
                        "path",
                        "polygon",
                        "polyline",
                    ):
                        continue
                    style = dict(
                        item.split(":", 1)
                        for item in element.get("style", "").split(";")
                        if ":" in item
                    )
                    style = {k.strip(): v.strip() for k, v in style.items()}
                    fill = style.get("fill", element.get("fill", "black"))
                    stroke = style.get("stroke", element.get("stroke", "none"))
                    if fill == "none" and stroke == "none":
                        style.update({"fill": "black", "fill-opacity": "1"})
                        element.set(
                            "style", ";".join(f"{k}:{v}" for k, v in style.items())
                        )
                svg = ET.tostring(root, encoding="utf-8")
            renderer = _renderer(svg)
            self._renderers[key] = renderer
            while len(self._renderers) > 48:
                self._renderers.popitem(last=False)
            return renderer

    def mask(self, target: str) -> HitMask:
        target = target.lstrip("#")
        with self._lock:
            if target in self._masks:
                return self._masks[target]
            if target not in self.targets:
                raise KeyError(target)
            # Add a small antialias margin; clip to the actual image viewport.
            bounds = (
                self.bounds(target)
                .adjusted(-2, -2, 2, 2)
                .intersected(QRectF(0, 0, self.width, self.height))
            )
            scale = 2.0
            w, h = max(1, math.ceil(bounds.width() * scale)), max(
                1, math.ceil(bounds.height() * scale)
            )
            image = QImage(w, h, QImage.Format.Format_RGBA8888)
            image.fill(Qt.GlobalColor.transparent)
            painter = QPainter(image)
            painter.setRenderHint(QPainter.RenderHint.Antialiasing)
            painter.scale(scale, scale)
            painter.translate(-bounds.x(), -bounds.y())
            self.selected_renderer({target}, hit_target=True).render(
                painter, QRectF(0, 0, self.width, self.height)
            )
            painter.end()
            # RGBA8888 is byte-ordered on every architecture; no endian guess.
            pixels = bytes(image.constBits())
            alpha = b"".join(
                pixels[
                    row * image.bytesPerLine()
                    + 3 : row * image.bytesPerLine()
                    + w * 4 : 4
                ]
                for row in range(h)
            )
            mask = HitMask(bounds.x(), bounds.y(), w, h, scale, alpha)
            self._masks[target] = mask
            return mask

    def hotspots(
        self, layer: str = "buttons", count: int = 0, shifted: bool = False
    ) -> list[dict]:
        if count < 0:
            return []
        layer = _LAYER_NAMES.get(layer.lower(), "buttons")
        prefix = "button" if layer == "buttons" else "led"
        is_g600 = self.path.name == "logitech-g600.svg"
        offset = 21 if shifted and is_g600 and prefix == "button" and count > 20 else 0
        # Some callers have the 40 editable entries; the daemon has 41 raw
        # entries because index 20 is a reserved color buffer.
        raw_count = 41 if is_g600 and prefix == "button" and count == 40 else count
        result = []
        for target in self.targets:
            match = TARGET_RE.fullmatch(target)
            if match[1] != prefix:
                continue
            physical = int(match[2])
            index = physical + offset
            if raw_count > 0 and index >= raw_count:
                continue
            bounds = self.bounds(target)
            leader_id = target + "-leader"
            leader = self.bounds(leader_id)
            style = self.elements.get(leader_id, ET.Element("empty")).get("style", "")
            side = (
                "left"
                if re.search(r"text-align\s*:\s*end(?:\s*;|\s*$)", style)
                else "right"
            )
            result.append(
                {
                    "id": target,
                    "index": index,
                    "physicalIndex": physical,
                    "kind": prefix,
                    "x": bounds.x(),
                    "y": bounds.y(),
                    "width": bounds.width(),
                    "height": bounds.height(),
                    "centerX": bounds.center().x(),
                    "centerY": bounds.center().y(),
                    "leaderX": leader.center().x(),
                    "leaderY": leader.center().y(),
                    "side": side,
                    "hasLeader": not leader.isEmpty(),
                    "pathId": target + "-path",
                    "leaderId": leader_id,
                }
            )
        return result

    def hit_test(
        self, layer: str, x: float, y: float, count: int = 0, shifted: bool = False
    ) -> int:
        if (
            not math.isfinite(x)
            or not math.isfinite(y)
            or not (0 <= x < self.width and 0 <= y < self.height)
        ):
            return -1
        # Smaller targets win in the few drawings where wheel/LED outlines
        # overlap a large surrounding button. This keeps each target reachable.
        hotspots = sorted(
            self.hotspots(layer, count, shifted), key=lambda h: h["width"] * h["height"]
        )
        for hotspot in hotspots:
            if self.bounds(hotspot["id"]).adjusted(-1, -1, 1, 1).contains(
                x, y
            ) and self.mask(hotspot["id"]).contains(x, y):
                return hotspot["index"]
        return -1

    def render(
        self,
        layer: str = "buttons",
        highlight: str = "",
        size: QSize | None = None,
        count: int = 0,
        shifted: bool = False,
        color: str = "#4b95e8",
        leaders: bool = True,
    ) -> QImage:
        if size is None or size.width() <= 0 or size.height() <= 0:
            size = QSize(math.ceil(self.width), math.ceil(self.height))
        image = QImage(size, QImage.Format.Format_ARGB32_Premultiplied)
        image.fill(Qt.GlobalColor.transparent)
        active = self.hotspots(layer, count, shifted)
        selected = {"Device"}
        if leaders:
            for hotspot in active:
                selected.update((hotspot["pathId"], hotspot["leaderId"]))
        with self._lock:
            painter = QPainter(image)
            painter.setRenderHint(QPainter.RenderHint.Antialiasing)
            self.selected_renderer(selected).render(
                painter, QRectF(0, 0, size.width(), size.height())
            )
            highlight = highlight.lstrip("#")
            if highlight in {hotspot["id"] for hotspot in active}:
                overlay = QImage(size, QImage.Format.Format_ARGB32_Premultiplied)
                overlay.fill(Qt.GlobalColor.transparent)
                overlay_painter = QPainter(overlay)
                self.selected_renderer({highlight}, hit_target=True).render(
                    overlay_painter, QRectF(0, 0, size.width(), size.height())
                )
                overlay_painter.setCompositionMode(
                    QPainter.CompositionMode.CompositionMode_SourceIn
                )
                tint = QColor(color)
                if not tint.isValid():
                    tint = QColor("#4b95e8")
                tint.setAlpha(135)
                overlay_painter.fillRect(overlay.rect(), tint)
                overlay_painter.end()
                painter.drawImage(0, 0, overlay)
            painter.end()
        return image


class DiagramCatalog(QObject):
    """QML-facing lookup, layout, and hit-testing service."""

    def __init__(
        self, svg_directory: str | Path | None = None, parent: QObject | None = None
    ):
        super().__init__(parent)
        self.svg_directory = (
            Path(svg_directory) if svg_directory else find_svg_directory()
        )
        self.config = configparser.ConfigParser()
        self.config.read(self.svg_directory / "svg-lookup.ini", encoding="utf-8")
        self._documents: OrderedDict[str, SvgDiagram] = OrderedDict()
        self._lock = threading.RLock()

    @Slot(str, result=str)
    def filename(self, model: str) -> str:
        """Resolve bundled names and the upstream USB/Bluetooth lookup table."""
        model = str(model or "")
        if (
            model.endswith(".svg")
            and Path(model).name == model
            and (self.svg_directory / model).is_file()
        ):
            return model
        if model.startswith(("usb:", "bluetooth:")):
            parts = model.lower().split(":")
            if len(parts) == 4:
                try:
                    if int(parts[3], 16) == 0:
                        parts = parts[:3]
                except ValueError:
                    pass
            match = ":".join(parts)
            for section in self.config.sections():
                values = (
                    value.strip().lower()
                    for value in self.config[section].get("DeviceMatch", "").split(";")
                )
                if match in values:
                    name = self.config[section].get("Svg", "fallback.svg")
                    if (
                        Path(name).name == name
                        and (self.svg_directory / name).is_file()
                    ):
                        return name
        return "fallback.svg"

    def document(self, model: str) -> SvgDiagram:
        name = self.filename(model)
        with self._lock:
            if name not in self._documents:
                self._documents[name] = SvgDiagram(self.svg_directory / name)
            self._documents.move_to_end(name)
            while len(self._documents) > 8:
                self._documents.popitem(last=False)
            return self._documents[name]

    @Slot(str, result="QVariantMap")
    @Slot(str, str, result="QVariantMap")
    @Slot(str, str, int, bool, result="QVariantMap")
    def describe(
        self,
        model: str,
        layer: str = "buttons",
        buttonCount: int = 0,
        shifted: bool = False,
    ) -> dict:
        doc = self.document(model)
        layer = _LAYER_NAMES.get(layer.lower(), "buttons")
        params = urlencode(
            {"layer": layer, "count": buttonCount, "shifted": int(shifted)}
        )
        return {
            "filename": doc.path.name,
            "width": doc.width,
            "height": doc.height,
            "source": f"image://piper-diagrams/{quote(doc.path.name)}?{params}",
            "hotspots": doc.hotspots(layer, buttonCount, shifted),
            "buttonCount": sum(target.startswith("button") for target in doc.targets),
            "ledCount": sum(target.startswith("led") for target in doc.targets),
            "supportsGShift": doc.path.name == "logitech-g600.svg" and buttonCount > 20,
        }

    @Slot(str, str, float, float, result=int)
    @Slot(str, str, float, float, int, bool, result=int)
    def hitTest(
        self,
        model: str,
        layer: str,
        x: float,
        y: float,
        buttonCount: int = 0,
        shifted: bool = False,
    ) -> int:
        return self.document(model).hit_test(layer, x, y, buttonCount, shifted)

    @Slot(str, str, float, float, result="QVariantMap")
    @Slot(str, str, float, float, int, bool, result="QVariantMap")
    def hitTarget(
        self,
        model: str,
        layer: str,
        x: float,
        y: float,
        buttonCount: int = 0,
        shifted: bool = False,
    ) -> dict:
        doc = self.document(model)
        index = doc.hit_test(layer, x, y, buttonCount, shifted)
        if index < 0:
            return {"id": "", "index": -1}
        for hotspot in doc.hotspots(layer, buttonCount, shifted):
            if hotspot["index"] == index:
                return hotspot
        return {"id": "", "index": -1}

    @Slot(str, str, str, result=str)
    @Slot(str, str, str, int, bool, result=str)
    def imageSource(
        self,
        model: str,
        layer: str = "buttons",
        highlight: str = "",
        buttonCount: int = 0,
        shifted: bool = False,
    ) -> str:
        return f"image://piper-diagrams/{quote(self.filename(model))}?" + urlencode(
            {
                "layer": layer,
                "highlight": highlight.lstrip("#"),
                "count": buttonCount,
                "shifted": int(shifted),
            }
        )


class DiagramImageProvider(QQuickImageProvider):
    def __init__(self, catalog: DiagramCatalog):
        super().__init__(QQuickImageProvider.ImageType.Image)
        self.catalog = catalog

    def requestImage(self, image_id: str, size: QSize, requestedSize: QSize) -> QImage:
        name, _, query = image_id.partition("?")
        params = parse_qs(query)
        doc = self.catalog.document(unquote(name))
        intrinsic = QSize(math.ceil(doc.width), math.ceil(doc.height))
        if size is not None:
            size.setWidth(intrinsic.width())
            size.setHeight(intrinsic.height())
        output_size = QSize(requestedSize)
        if output_size.width() <= 0 and output_size.height() <= 0:
            output_size = intrinsic
        elif output_size.width() <= 0:
            output_size.setWidth(round(output_size.height() * doc.width / doc.height))
        elif output_size.height() <= 0:
            output_size.setHeight(round(output_size.width() * doc.height / doc.width))
        # Do not let malformed sourceSize values allocate unbounded images.
        if output_size.width() > 4096 or output_size.height() > 4096:
            output_size.scale(4096, 4096, Qt.AspectRatioMode.KeepAspectRatio)

        def value(key: str, default: str) -> str:
            return params.get(key, [default])[0]

        try:
            count = max(-1, int(value("count", "0")))
        except ValueError:
            count = 0
        return doc.render(
            value("layer", "buttons"),
            value("highlight", ""),
            output_size,
            count,
            value("shifted", "0") == "1",
            value("color", "#4b95e8"),
            value("leaders", "1") != "0",
        )
