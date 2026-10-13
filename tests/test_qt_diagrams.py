# SPDX-License-Identifier: GPL-2.0-or-later
"""Exercise every upstream SVG without GTK, a display server, or hardware."""

import math
import os
from pathlib import Path
import tempfile
import unittest

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PySide6.QtCore import QSize  # noqa: E402
from PySide6.QtGui import QGuiApplication  # noqa: E402
from qt_piper.diagrams import (
    DiagramCatalog,
    DiagramImageProvider,
    SvgDiagram,
)  # noqa: E402

ROOT = Path(__file__).resolve().parents[1]


class DiagramTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.app = QGuiApplication.instance() or QGuiApplication([])
        cls.catalog = DiagramCatalog(ROOT / "data" / "svgs")

    def test_all_lookup_entries_resolve_to_bundled_svg(self):
        for section in self.catalog.config.sections():
            config = self.catalog.config[section]
            expected = config["Svg"]
            for model in filter(None, config["DeviceMatch"].split(";")):
                with self.subTest(section=section, model=model):
                    self.assertTrue((self.catalog.svg_directory / expected).is_file())
                    self.assertEqual(self.catalog.filename(model), expected)
                    if model.count(":") == 2:
                        self.assertEqual(self.catalog.filename(model + ":0"), expected)
                        self.assertEqual(
                            self.catalog.filename(model + ":0000"), expected
                        )

    def test_unknown_and_unsafe_names_use_fallback(self):
        for name in (
            "",
            "unknown",
            "usb:ffff:ffff:0",
            "../../private.svg",
            "/tmp/private.svg",
        ):
            self.assertEqual(self.catalog.filename(name), "fallback.svg")

    def test_every_svg_renders_and_has_valid_target_geometry(self):
        files = sorted(self.catalog.svg_directory.glob("*.svg"))
        self.assertGreaterEqual(len(files), 67)
        checked = 0
        for path in files:
            with self.subTest(svg=path.name):
                doc = self.catalog.document(path.name)
                self.assertGreater(doc.width, 0)
                self.assertGreater(doc.height, 0)
                self.assertTrue(doc.renderer.isValid())
                for layer in ("buttons", "leds"):
                    image = doc.render(layer, size=QSize(300, 300))
                    self.assertFalse(image.isNull())
                    self.assertTrue(any(bytes(image.constBits())[3::4]))
                    for hotspot in doc.hotspots(layer):
                        with self.subTest(svg=path.name, target=hotspot["id"]):
                            self.assertGreater(hotspot["width"], 0)
                            self.assertGreater(hotspot["height"], 0)
                            self.assertTrue(hotspot["hasLeader"])
                            self.assertIn(hotspot["pathId"], doc.elements)
                            self.assertIn(hotspot["leaderId"], doc.elements)
                            for key in (
                                "x",
                                "y",
                                "width",
                                "height",
                                "leaderX",
                                "leaderY",
                            ):
                                self.assertTrue(math.isfinite(hotspot[key]))
                            mask = doc.mask(hotspot["id"])
                            point = mask.interior_point()
                            self.assertIsNotNone(
                                point, "target must contain painted, clickable pixels"
                            )
                            self.assertTrue(mask.contains(*point))
                            checked += 1
        self.assertEqual(
            checked,
            sum(len(self.catalog.document(path.name).targets) for path in files),
        )
        self.assertGreater(checked, 600)

    def test_every_button_and_led_is_reachable(self):
        """Find a real clickable point for each ID, including overlapping parts."""
        for path in sorted(self.catalog.svg_directory.glob("*.svg")):
            doc = self.catalog.document(path.name)
            for layer in ("buttons", "leds"):
                for hotspot in doc.hotspots(layer):
                    with self.subTest(svg=path.name, target=hotspot["id"]):
                        mask = doc.mask(hotspot["id"])
                        point = mask.interior_point()
                        self.assertIsNotNone(point)
                        reachable = doc.hit_test(layer, *point) == hotspot["index"]
                        # Center may belong to a smaller target. Sample actual
                        # painted pixels throughout this target until it wins.
                        if not reachable:
                            step = max(1, min(mask.width, mask.height) // 24)
                            for py in range(0, mask.height, step):
                                for px in range(0, mask.width, step):
                                    if mask.alpha[py * mask.width + px] > 128:
                                        x, y = (
                                            mask.x + (px + 0.5) / mask.scale,
                                            mask.y + (py + 0.5) / mask.scale,
                                        )
                                        if (
                                            doc.hit_test(layer, x, y)
                                            == hotspot["index"]
                                        ):
                                            reachable = True
                                            break
                                if reachable:
                                    break
                        self.assertTrue(
                            reachable, "every target must be independently clickable"
                        )

    def test_g600_normal_and_shifted_mapping_skips_reserved_buffer(self):
        normal = self.catalog.describe("logitech-g600.svg", "buttons", 41, False)
        shifted = self.catalog.describe("logitech-g600.svg", "buttons", 41, True)
        self.assertEqual([h["index"] for h in normal["hotspots"]], list(range(20)))
        self.assertEqual([h["index"] for h in shifted["hotspots"]], list(range(21, 41)))
        self.assertEqual(
            [h["physicalIndex"] for h in shifted["hotspots"]], list(range(20))
        )
        self.assertEqual(
            [h["id"] for h in normal["hotspots"]],
            [h["id"] for h in shifted["hotspots"]],
        )
        self.assertTrue(shifted["supportsGShift"])
        self.assertEqual(
            len(
                self.catalog.describe("logitech-g600.svg", "buttons", 40, True)[
                    "hotspots"
                ]
            ),
            20,
        )
        doc = self.catalog.document("logitech-g600.svg")
        point = doc.mask("button0").interior_point()
        self.assertEqual(
            self.catalog.hitTest("logitech-g600.svg", "buttons", *point, 41, False), 0
        )
        self.assertEqual(
            self.catalog.hitTest("logitech-g600.svg", "buttons", *point, 41, True), 21
        )

    def test_masks_obey_nested_transforms_rotation_scale_and_holes(self):
        svg = """<svg xmlns="http://www.w3.org/2000/svg" width="200" height="200" viewBox="0 0 100 100">
        <g id="Device" transform="translate(10,20)"><g transform="scale(2)">
          <rect id="button0" x="0" y="0" width="10" height="5" transform="rotate(90)" fill="red"/>
          <path id="button1" fill="blue" fill-rule="evenodd" d="M10,10 h20 v20 h-20 z M15,15 v10 h10 v-10 z"/>
        </g></g><g id="Buttons"/><g id="LEDs"/></svg>"""
        with tempfile.TemporaryDirectory() as temp:
            path = Path(temp) / "transforms.svg"
            path.write_text(svg)
            doc = SvgDiagram(path)
            bounds = doc.bounds("button0")
            self.assertAlmostEqual(bounds.x(), 0)
            self.assertAlmostEqual(bounds.y(), 40)
            self.assertAlmostEqual(bounds.width(), 20)
            self.assertAlmostEqual(bounds.height(), 40)
            self.assertEqual(doc.hit_test("buttons", 10, 60), 0)
            self.assertEqual(doc.hit_test("buttons", 30, 60), -1)
            self.assertTrue(doc.mask("button1").contains(65, 85))
            self.assertFalse(doc.mask("button1").contains(100, 120))
            self.assertEqual(doc.hit_test("buttons", 100, 120), -1)
            image = doc.render(leaders=False)
            self.assertGreater(image.pixelColor(10, 60).alpha(), 0)
            self.assertEqual(image.pixelColor(100, 120).alpha(), 0)

    def test_invisible_hotspot_markers_and_inherited_patterns(self):
        doc = self.catalog.document("steelseries-senseiten.svg")
        point = doc.mask("button0").interior_point()
        self.assertEqual(doc.hit_test("buttons", *point), 0)
        self.assertIn("fill:none", doc.elements["button0"].get("style"))
        plain = doc.render(leaders=False)
        highlighted = doc.render(highlight="button0", leaders=False)
        x, y = (int(value) for value in point)
        self.assertNotEqual(plain.pixelColor(x, y), highlighted.pixelColor(x, y))
        mars = self.catalog.document("marsgaming-mm4.svg")
        for name in ("pattern49728", "pattern12773"):
            pattern = mars.elements[name]
            self.assertEqual(pattern.get("width"), "2")
            self.assertEqual(pattern.get("height"), "1")
            self.assertTrue(len(pattern))
            self.assertIsNone(pattern.get("{http://www.w3.org/1999/xlink}href"))

    def test_qml_hit_target_contract_and_leds_ignore_gshift(self):
        doc = self.catalog.document("logitech-g600.svg")
        point = doc.mask("button0").interior_point()
        hit = self.catalog.hitTarget("logitech-g600.svg", "buttons", *point, 40, True)
        self.assertEqual(hit["id"], "button0")
        self.assertEqual(hit["index"], 21)
        self.assertEqual(
            self.catalog.hitTarget("logitech-g600.svg", "buttons", -1, -1),
            {"id": "", "index": -1},
        )
        leds = self.catalog.describe("logitech-g600.svg", "leds", 40, True)["hotspots"]
        self.assertEqual([led["index"] for led in leds], [0])
        self.assertEqual(self.catalog.describe("")["filename"], "fallback.svg")
        self.assertEqual(
            self.catalog.describe("logitech-g600.svg", "leds", -1, False)["hotspots"],
            [],
        )
        self.assertEqual(
            self.catalog.hitTest("logitech-g600.svg", "leds", 150, 200, -1, False), -1
        )

    def test_highlight_retains_exact_mask_and_changes_only_target(self):
        doc = self.catalog.document("logitech-g600.svg")
        plain, highlighted = doc.render(leaders=False), doc.render(
            highlight="button0", leaders=False
        )
        x, y = doc.mask("button0").interior_point()
        self.assertNotEqual(
            plain.pixelColor(int(x), int(y)), highlighted.pixelColor(int(x), int(y))
        )
        self.assertEqual(plain.pixelColor(0, 0), highlighted.pixelColor(0, 0))
        self.assertEqual(
            bytes(plain.constBits())[3::4], bytes(highlighted.constBits())[3::4]
        )

    def test_qml_image_provider_size_and_highlight(self):
        provider = DiagramImageProvider(self.catalog)
        size = QSize()
        result = provider.requestImage(
            "logitech-g600.svg?layer=buttons&highlight=button0&count=41&shifted=1",
            size,
            QSize(936, 802),
        )
        self.assertEqual(result.size(), QSize(936, 802))
        self.assertEqual(size, QSize(468, 401))
        self.assertIn(
            "highlight=button0",
            self.catalog.imageSource(
                "logitech-g600.svg", "buttons", "#button0", 41, True
            ),
        )
        self.assertEqual(
            self.catalog.hitTest("logitech-g600.svg", "buttons", -1, 0), -1
        )
        self.assertEqual(
            self.catalog.hitTest("logitech-g600.svg", "buttons", float("nan"), 0), -1
        )


if __name__ == "__main__":
    unittest.main()
