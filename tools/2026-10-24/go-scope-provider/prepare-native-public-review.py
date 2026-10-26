"""Freeze the native public protocol candidate without mutating the SDK tree."""

import difflib
import hashlib
import json
from pathlib import Path
import tarfile

ROOT = Path('/Users/sclarke/github/oteleq-qualification/2026-10-24/native-prepared-review-3c8269e')
ROOT.mkdir()
producer = Path('/Users/sclarke/github/otelc-qualification/2026-10-24/native-prepared')
index = json.loads((producer / 'source-3c8269e.json').read_text())
assert index['head'] == '3c8269eb62224c4f0bdd69ea3e7b63a19354b841'
archive = Path(index['archive'])
assert hashlib.sha256(archive.read_bytes()).hexdigest() == index['archive_sha256'] == '49016cc60f127d1f752863929dfdf70615800bc421deeeee46d6335db0c23ae1'
source = ROOT / 'source'
source.mkdir()
with tarfile.open(archive) as data:
    data.extractall(source, filter='data')
assert len(index['files']) == 446
assert all(hashlib.sha256((source / name).read_bytes()).hexdigest() == digest for name, digest in index['files'].items())
parent = json.loads((ROOT.parent / 'native-gate-review-dab479f/source-index.json').read_text())
before = Path(parent['source'])
assert all(hashlib.sha256((before / name).read_bytes()).hexdigest() == digest for name, digest in parent['files'].items())
names = sorted(name for name in set(index['files']) | set(parent['files']) if index['files'].get(name) != parent['files'].get(name))
assert len(names) == 11
with (ROOT / 'delta.diff').open('x') as output:
    for name in names:
        left = (before / name).read_text().splitlines(keepends=True) if name in parent['files'] else []
        right = (source / name).read_text().splitlines(keepends=True) if name in index['files'] else []
        output.writelines(difflib.unified_diff(left, right, fromfile='before/' + name, tofile='after/' + name))
(ROOT / 'source-index.json').write_text(json.dumps({**index, 'source': str(source), 'delta_files': names}, indent=2) + '\n')
print(json.dumps({'head': index['head'], 'files': 446, 'delta_files': names}, indent=2))
