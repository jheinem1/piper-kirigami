"""Write Flatpak trust/bootstrap descriptors for the signed repository."""
import base64
import json
from pathlib import Path
import sys


def write(config, key, output):
    c = json.loads(Path(config).read_text())
    encoded = base64.b64encode(Path(key).read_bytes()).decode()
    output = Path(output)
    common = f'Url={c["url"]}\nGPGKey={encoded}\n'
    (output / 'piper-kirigami.flatpakrepo').write_text(
        '[Flatpak Repo]\nTitle=Piper Kirigami\nDefaultBranch=development\n' + common)
    (output / 'piper-kirigami.flatpakref').write_text(
        '[Flatpak Ref]\nName=io.github.jheinem1.PiperKirigami\nBranch=development\n'
        'IsRuntime=false\nTitle=Piper Kirigami\nSuggestRemoteName=piper-kirigami\n'
        'RuntimeRepo=https://dl.flathub.org/repo/flathub.flatpakrepo\n' + common)


if __name__ == '__main__':
    write(*sys.argv[1:])
