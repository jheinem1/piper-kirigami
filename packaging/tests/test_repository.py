import base64
import importlib.util
import json
from pathlib import Path
import subprocess
import tempfile
import unittest

ROOT = Path(__file__).parents[1] / 'repository'


def module(name):
    spec = importlib.util.spec_from_file_location(name, ROOT / (name + '.py'))
    result = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(result)
    return result


class RepositoryTests(unittest.TestCase):
    def test_private_test_daemon_supports_service_reactivation(self):
        recipe = json.loads((ROOT.parent / 'flatpak/dbus-test-daemon.json').read_text())
        self.assertIn('-Dtraditional_activation=true', recipe['build-commands'][0])
        self.assertEqual(recipe['cleanup'], ['*'])

    def test_promotion_rejects_older_but_not_draft_versions(self):
        check = module('check-promotion').check
        check('v0.1.3', [dict(tag_name='v0.1.2', draft=False), dict(tag_name='v9.0.0', draft=True)])
        with self.assertRaises(ValueError):
            check('v0.1.3', [dict(tag_name='v0.2.0', draft=False)])
        with self.assertRaises(ValueError):
            check('main', [])

    def test_descriptors_embed_trust_and_preserve_app_identity(self):
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            config = root / 'config.json'
            config.write_text(json.dumps(dict(url='https://example.test/repo/')))
            key = root / 'key.gpg'
            key.write_bytes(b'fixture-public-key')
            module('write-descriptors').write(config, key, root)
            text = (root / 'piper-kirigami.flatpakref').read_text()
            self.assertIn('Name=io.github.jheinem1.PiperKirigami\n', text)
            self.assertIn('Branch=development\n', text)
            self.assertIn('GPGKey=' + base64.b64encode(key.read_bytes()).decode(), text)
            self.assertIn('SuggestRemoteName=piper-kirigami', text)
            self.assertNotIn('Version=', text)

    def test_unprovisioned_trust_fails_before_build_or_publish(self):
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            (root / 'config.json').write_text(json.dumps(dict(gpg_fingerprint=None)))
            script = root / 'build-repository.sh'
            script.write_bytes((ROOT / 'build-repository.sh').read_bytes())
            result = subprocess.run(['bash', str(script), temp, str(root / 'out')],
                                    env={'PATH': '/usr/bin:/bin', 'GNUPGHOME': temp}, capture_output=True, text=True)
            self.assertNotEqual(result.returncode, 0)
            self.assertFalse((root / 'out').exists())
            self.assertIn('Provision', result.stderr)
