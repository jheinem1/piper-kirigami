"""Refuse publishing an older app version over a newer public repository."""
import json
import re
import sys


def version(tag):
    match = re.fullmatch(r'v([0-9]+)\.([0-9]+)\.([0-9]+)', tag)
    if not match:
        raise ValueError('Expected vX.Y.Z release tag')
    return tuple(map(int, match.groups()))


def check(tag, releases):
    target = version(tag)
    for release in releases:
        if release.get('draft'):
            continue
        other = release['tag_name']
        if re.fullmatch(r'v[0-9]+\.[0-9]+\.[0-9]+', other) and version(other) > target:
            raise ValueError('A newer release already exists; refuse repository downgrade')


if __name__ == '__main__':
    check(sys.argv[1], json.load(sys.stdin))
