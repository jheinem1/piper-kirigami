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
    def test_release_creates_exact_tag_before_draft(self):
        workflow = (ROOT.parents[1] / '.github/workflows/build-artifacts.yml').read_text()
        create_ref = workflow.index('gh api --method POST "repos/$GITHUB_REPOSITORY/git/refs"')
        create_draft = workflow.index('gh release create "$RELEASE_TAG"')
        self.assertLess(create_ref, create_draft)
        self.assertIn('-f ref="refs/tags/$RELEASE_TAG" -f sha="$GITHUB_SHA"', workflow)

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

    def test_update_fixture_advances_http_metadata_without_changing_bytes(self):
        script = (ROOT / 'smoke-update.sh').read_text()
        body = script.split('refresh_summary_timestamps() {\n', 1)[1].split('\n}\n', 1)[0]
        self.assertIn('marker_create update\nrefresh_summary_timestamps\nswitch_repo "$site/repo"', script)
        with tempfile.TemporaryDirectory() as temp:
            site = Path(temp)
            repo = site / 'repo'
            repo.mkdir()
            for name in ('summary', 'summary.sig', 'summary.idx'):
                (repo / name).write_bytes(b'signed fixture ' + name.encode())
            before = {p.name: (p.read_bytes(), p.stat().st_mtime_ns) for p in repo.iterdir()}
            subprocess.run(['bash', '-euc', 'site="$1"\n' + body, 'fixture', temp], check=True)
            for name, (content, mtime) in before.items():
                self.assertEqual((repo / name).read_bytes(), content)
                self.assertGreater((repo / name).stat().st_mtime_ns, mtime)

    def test_release_builds_cannot_be_cancelled_by_routine_pushes(self):
        workflow = (ROOT.parents[1] / '.github/workflows/build-artifacts.yml').read_text()
        self.assertIn('group: artifacts-${{ github.workflow }}-${{ inputs.release_tag || github.ref }}', workflow)
        self.assertIn("cancel-in-progress: ${{ inputs.release_tag == '' && !startsWith(github.ref, 'refs/tags/') }}", workflow)
