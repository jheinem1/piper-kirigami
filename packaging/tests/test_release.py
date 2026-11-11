import hashlib
import importlib.util
import json
from pathlib import Path
import tempfile
import unittest

spec = importlib.util.spec_from_file_location('release', Path(__file__).parents[1] / 'prepare-release.py')
release = importlib.util.module_from_spec(spec)
spec.loader.exec_module(release)


class ReleaseTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.path = Path(self.temp.name)
        info = dict(version='0.1.3', commit='a'*40, app_id=release.APP, arch='x86_64', branch='development')
        (self.path / 'build-info.json').write_text(json.dumps(info))
        (self.path / 'flatpak-app-commit.txt').write_text('b'*64)
        (self.path / 'runtime-check.json').write_text('{}')
        for name in ('installed-smoke.png', 'installed-permissions.ini', f'{release.APP}-x86_64-development.flatpak'):
            (self.path / name).write_bytes(b'fixture')
        (self.path / 'SHA256SUMS').write_text('')

    def test_emits_exact_bundle_and_commit_pins(self):
        result = release.prepare(self.path, 'v0.1.3')
        self.assertEqual(result['sha256'], hashlib.sha256(b'fixture').hexdigest())
        self.assertEqual(result['flatpak_commit'], 'b'*64)
        self.assertEqual(result['source_commit'], 'a'*40)
        self.assertIn('release.json', (self.path / 'SHA256SUMS').read_text())

    def test_wrong_tag_rejected(self):
        for tag in ('v0.1.2', 'v0.1.3/evil', '0.1.3'):
            with self.assertRaises(ValueError):
                release.prepare(self.path, tag)

    def test_missing_runtime_evidence_rejected(self):
        (self.path / 'runtime-check.json').unlink()
        with self.assertRaises(FileNotFoundError):
            release.prepare(self.path, 'v0.1.3')

    def test_invalid_commit_rejected(self):
        (self.path / 'flatpak-app-commit.txt').write_text('moving-ref')
        with self.assertRaises(ValueError):
            release.prepare(self.path, 'v0.1.3')
