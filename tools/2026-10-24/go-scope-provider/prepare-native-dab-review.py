"""Freeze the nine-file native gate delta for independent consumer review."""

import difflib
import hashlib
import json
from pathlib import Path
import tarfile

ROOT = Path('/Users/sclarke/github/oteleq-qualification/2026-10-24/native-gate-review-dab479f')
ROOT.mkdir()
producer = Path('/Users/sclarke/github/otelc-qualification/2026-10-24/native-exec-gate')
index = json.loads((producer / 'source-dab479f.json').read_text())
assert index['head'] == 'dab479f79cd005e3e4644b5058664fc2016353fd'
archive = Path(index['archive'])
assert hashlib.sha256(archive.read_bytes()).hexdigest() == index['archive_sha256'] == '95d4072978d77ca3a5b7ad728ac40bfe10d5d313071c43daa4d1d1e181eb9b03'
source = ROOT / 'source'
source.mkdir()
with tarfile.open(archive) as data:
    data.extractall(source, filter='data')
assert len(index['files']) == 441
assert all(hashlib.sha256((source / name).read_bytes()).hexdigest() == digest for name, digest in index['files'].items())
parent = json.loads(Path('/Users/sclarke/github/otelc-qualification/2026-10-24/native-sdk-budget/source-3568c8d.json').read_text())
before = Path('/Users/sclarke/github/oteleq-qualification/2026-10-24/native-launch-review-3568c8d/source')
assert all(hashlib.sha256((before / name).read_bytes()).hexdigest() == digest for name, digest in parent['files'].items())
names = sorted(name for name in set(index['files']) | set(parent['files']) if index['files'].get(name) != parent['files'].get(name))
assert len(names) == 9
with (ROOT / 'delta.diff').open('x') as output:
    for name in names:
        left = (before / name).read_text().splitlines(keepends=True) if name in parent['files'] else []
        right = (source / name).read_text().splitlines(keepends=True) if name in index['files'] else []
        output.writelines(difflib.unified_diff(left, right, fromfile='before/' + name, tofile='after/' + name))
(ROOT / 'source-index.json').write_text(json.dumps({**index, 'source': str(source), 'delta_files': names}, indent=2) + '\n')
print(json.dumps({'head': index['head'], 'files': 441, 'delta_files': names}, indent=2))
