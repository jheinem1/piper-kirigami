#!/usr/bin/env python3
"""Create downstream pins only from an installed-runtime-tested CI bundle."""
import hashlib
import json
from pathlib import Path
import re
import sys

APP = 'io.github.jheinem1.PiperKirigami'


def prepare(directory, tag):
    directory = Path(directory)
    info = json.loads((directory / 'build-info.json').read_text())
    if not re.fullmatch(r'v[0-9]+\.[0-9]+\.[0-9]+', tag) or tag != 'v' + info['version']:
        raise ValueError('Release tag must match the packaged project version')
    source = info['commit']
    commit = (directory / 'flatpak-app-commit.txt').read_text().strip()
    if not re.fullmatch(r'[0-9a-f]{40}', source) or not re.fullmatch(r'[0-9a-f]{64}', commit):
        raise ValueError('Missing immutable source or installed app commit')
    if (info['app_id'], info['arch'], info['branch']) != (APP, 'x86_64', 'development'):
        raise ValueError('Unexpected Flatpak identity')
    # These outputs exist only after the installed Platform runtime checks pass.
    json.loads((directory / 'runtime-check.json').read_text())
    for name in ('installed-smoke.png', 'installed-permissions.ini'):
        if not (directory / name).stat().st_size:
            raise ValueError('Empty installed-runtime evidence: ' + name)
    bundle = directory / f'{APP}-x86_64-development.flatpak'
    release = dict(app_id=APP, tag=tag, sha256=hashlib.sha256(bundle.read_bytes()).hexdigest(),
                   flatpak_commit=commit, source_commit=source)
    (directory / 'release.json').write_text(json.dumps(release, indent=2) + '\n')
    checksum = hashlib.sha256((directory / 'release.json').read_bytes()).hexdigest()
    with (directory / 'SHA256SUMS').open('a') as output:
        output.write(f'{checksum}  release.json\n')
    return release


if __name__ == '__main__':
    prepare(*sys.argv[1:])
