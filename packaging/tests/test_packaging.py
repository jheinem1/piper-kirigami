# SPDX-License-Identifier: GPL-2.0-or-later
"""Packaging contract tests requiring only Python's standard library and Git."""

import importlib.util
import ast
import json
import os
from pathlib import Path
import subprocess
import struct
import sys
from unittest.mock import patch
import tarfile
import tempfile
import unittest
import xml.etree.ElementTree as ET

ROOT = Path(__file__).resolve().parents[2]
SPEC = importlib.util.spec_from_file_location(
    "prepare_source", ROOT / "packaging/prepare-source.py"
)
prepare_source = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(prepare_source)


class SourceTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.base = Path(self.temp.name)
        self.repo = self.base / "repo"
        self.repo.mkdir()
        self.git("init", "-q")
        self.git("config", "user.name", "Packaging test")
        self.git("config", "user.email", "packaging-test@example.invalid")
        (self.repo / "qt-build").mkdir()
        (self.repo / "qt-build/meson.build").write_text(
            "project('piper-kirigami', version: '0.1.0')\n"
        )
        (self.repo / "packaging/fedora").mkdir(parents=True)
        (self.repo / "packaging/fedora/piper-kirigami.spec.in").write_text(
            "Version: @VERSION@\nRelease: @RELEASE@\n# @COMMIT@ @SOURCE_DATE_EPOCH@ @CHANGELOG_DATE@\n"
        )
        (self.repo / "device.svg").write_text("<svg/>\n")
        (self.repo / "alias.svg").symlink_to("device.svg")
        (self.repo / "launcher").write_text("#!/bin/sh\nexit 0\n")
        (self.repo / "launcher").chmod(0o755)
        self.commit()

    def git(self, *args):
        return subprocess.check_output(
            ["git", "-C", str(self.repo), *args], stderr=subprocess.DEVNULL
        )

    def commit(self):
        self.git("add", ".")
        env = dict(
            os.environ,
            GIT_AUTHOR_DATE="2026-10-12T00:00:00Z",
            GIT_COMMITTER_DATE="2026-10-12T00:00:00Z",
        )
        subprocess.run(
            ["git", "-C", str(self.repo), "commit", "-qm", "fixture"],
            check=True,
            env=env,
        )

    def test_same_commit_is_byte_reproducible(self):
        first = prepare_source.prepare(self.repo, "HEAD", self.base / "first")
        second = prepare_source.prepare(self.repo, "HEAD", self.base / "second")
        self.assertEqual(first, second)
        self.assertEqual(
            (self.base / "first/SOURCES" / first["source_archive"]).read_bytes(),
            (self.base / "second/SOURCES" / second["source_archive"]).read_bytes(),
        )
        self.assertTrue(first["release"].startswith("0.20261012000000.git"))
        self.assertEqual(first["source_date_epoch"], 1791763200)

    def test_archive_preserves_symlinks_and_modes_and_ignores_uncommitted_files(self):
        (self.repo / "secret-untracked").write_text("not part of the source commit")
        (self.repo / "device.svg").write_text("uncommitted content")
        info = prepare_source.prepare(self.repo, "HEAD", self.base / "output")
        with tarfile.open(
            self.base / "output/SOURCES" / info["source_archive"]
        ) as archive:
            prefix = "piper-kirigami-0.1.0/"
            self.assertTrue(archive.getmember(prefix + "alias.svg").issym())
            self.assertEqual(
                archive.getmember(prefix + "alias.svg").linkname, "device.svg"
            )
            self.assertEqual(archive.getmember(prefix + "launcher").mode & 0o777, 0o755)
            self.assertEqual(
                archive.extractfile(prefix + "device.svg").read(), b"<svg/>\n"
            )
            self.assertNotIn(prefix + "secret-untracked", archive.getnames())
            self.assertFalse(any("/.git/" in name for name in archive.getnames()))

    def test_source_version_is_single_authority(self):
        info = prepare_source.prepare(self.repo, "HEAD", self.base / "output")
        spec = (self.base / "output/SPECS/piper-kirigami.spec").read_text()
        self.assertIn("Version: 0.1.0", spec)
        self.assertIn(info["commit"], spec)
        self.assertNotIn("@VERSION@", spec)

    def test_invalid_project_version_is_rejected(self):
        (self.repo / "qt-build/meson.build").write_text(
            "project('piper-kirigami', version: 'bad')"
        )
        self.commit()
        with self.assertRaises(ValueError):
            prepare_source.prepare(self.repo, "HEAD", self.base / "output")


class FlatpakTests(unittest.TestCase):
    def setUp(self):
        self.directory = ROOT / "packaging/flatpak"
        self.manifest = json.loads(
            (self.directory / "io.github.jheinem1.PiperKirigami.json").read_text()
        )

    def test_runtime_and_separate_identity(self):
        m = self.manifest
        self.assertEqual(m["app-id"], "io.github.jheinem1.PiperKirigami")
        self.assertEqual(m["runtime"], "org.kde.Platform")
        self.assertEqual(m["sdk"], "org.kde.Sdk")
        self.assertEqual(m["base"], "io.qt.PySide.BaseApp")
        self.assertEqual(m["runtime-version"], m["base-version"])
        self.assertEqual(m["runtime-version"], "6.11")
        self.assertEqual(m["branch"], "development")
        self.assertEqual(m["command"], "piper-kirigami")
        metadata = ET.parse(self.directory / f'{m["app-id"]}.metainfo.xml').getroot()
        self.assertEqual(metadata.findtext("id"), m["app-id"])
        self.assertEqual(metadata.findtext("launchable"), m["app-id"] + ".desktop")

    def test_permissions_are_narrow(self):
        self.assertEqual(
            set(self.manifest["finish-args"]),
            {
                "--share=ipc",
                "--socket=wayland",
                "--socket=fallback-x11",
                "--device=dri",
                "--system-talk-name=org.freedesktop.ratbag1",
            },
        )

    def test_python_dependencies_are_hash_pinned_and_tests_removed(self):
        for filename in ("python-dbus-next.json", "python-test-tools.json"):
            module = json.loads((self.directory / filename).read_text())
            for source in module["sources"]:
                self.assertEqual(source["type"], "file")
                self.assertTrue(
                    source["url"].startswith("https://files.pythonhosted.org/packages/")
                )
                self.assertRegex(source["sha256"], r"^[0-9a-f]{64}$")
                self.assertNotIn("pyside", source["url"].lower())
            command = module["build-commands"][0]
            self.assertIn("--no-index", command)
            self.assertIn("--no-deps", command)
            if "test-tools" in filename:
                self.assertIn("--target=/app/test-tools", command)
                self.assertEqual(module["cleanup"], ["*"])

    def test_active_tests_and_installed_launch_are_required(self):
        commands = "\n".join(self.manifest["modules"][-1]["build-commands"])
        for test in (
            "test_backend.py",
            "test_qt_diagrams.py",
            "test_kde_ui.py",
            "test_handbook.py",
        ):
            self.assertIn(test, commands)
        self.assertIn("piper-kirigami --mock --headless --screenshot", commands)


class ScriptTests(unittest.TestCase):
    def heredoc(self, name):
        text = (ROOT / "packaging/flatpak" / name).read_text()
        return text.split("<<'PY'\n", 1)[1].split("\nPY\n", 1)[0]

    def test_build_metadata_is_valid_json(self):
        with tempfile.TemporaryDirectory() as temp:
            directory = Path(temp)
            (directory / "source-info.json").write_text('{"commit":"fixture"}')
            with patch.object(sys, "argv", ["-", temp]), patch.object(
                subprocess, "check_output", return_value="a" * 64 + "\n"
            ):
                exec(
                    compile(self.heredoc("build.sh"), "build-info-heredoc", "exec"), {}
                )
            info = json.loads((directory / "build-info.json").read_text())
            self.assertEqual(len(info["flatpak_refs"]), 3)
            self.assertEqual(info["commit"], "fixture")

    def test_png_validator_accepts_actual_png_signature(self):
        with tempfile.TemporaryDirectory() as temp:
            screenshot = Path(temp) / "test.png"
            screenshot.write_bytes(
                b"\x89PNG\r\n\x1a\n" + b"\0" * 8 + struct.pack(">II", 1200, 820)
            )
            result = subprocess.run(
                [sys.executable, "-", str(screenshot)],
                input=self.heredoc("smoke-installed.sh"),
                text=True,
                capture_output=True,
                check=False,
            )
            self.assertEqual(result.returncode, 0, result.stderr)


class IconSearchPathTests(unittest.TestCase):
    def test_standard_icon_roots_preserve_platform_paths_and_theme_selection(self):
        # Execute the real path helper without importing Qt in stdlib-only CI.
        # The fake exposes no theme/fallback setters: any such mutation fails.
        tree = ast.parse((ROOT / "qt_piper/desktop_style.py").read_text())
        helper = next(
            node
            for node in tree.body
            if isinstance(node, ast.FunctionDef)
            and node.name == "configure_icon_search_paths"
        )
        with tempfile.TemporaryDirectory() as temp:
            base = Path(temp)
            data = base / "share"
            (data / "icons").mkdir(parents=True)
            bad = base / "not-a-directory"
            bad.mkdir()
            (bad / "icons").write_text("not a directory")
            existing = [":/icons", "/custom/platform/icons"]

            class Icon:
                paths = existing.copy()

                @classmethod
                def themeSearchPaths(cls):
                    return cls.paths

                @classmethod
                def setThemeSearchPaths(cls, paths):
                    cls.paths = paths

            class StandardPaths:
                GenericDataLocation = object()

                @staticmethod
                def standardLocations(location):
                    self.assertIs(location, StandardPaths.GenericDataLocation)
                    return [str(data), str(data), str(base / "missing"), str(bad)]

            namespace = {"Path": Path, "QIcon": Icon, "QStandardPaths": StandardPaths}
            exec(
                compile(
                    ast.Module(body=[helper], type_ignores=[]),
                    "icon-path-helper",
                    "exec",
                ),
                namespace,
            )
            namespace["configure_icon_search_paths"]()
            self.assertEqual(Icon.paths, [*existing, str(data / "icons")])
            namespace["configure_icon_search_paths"]()
            self.assertEqual(Icon.paths, [*existing, str(data / "icons")])

    def test_runtime_probe_checks_rendering_with_shared_application_initializer(self):
        script = (ROOT / "packaging/flatpak/check-runtime.py").read_text()
        self.assertIn(
            "from qt_piper.desktop_style import configure_icon_search_paths", script
        )
        self.assertLess(
            script.index("configure_icon_search_paths()"),
            script.index('fromTheme("input-mouse")'),
        )
        self.assertIn("assert not mouse_icon.isNull()", script)
        self.assertRegex(
            script, r"assert not mouse_icon\.pixmap\(\s*32,\s*32\s*\)\.isNull\(\)"
        )


if __name__ == "__main__":
    unittest.main()
