"""Independently verify the frozen source5 bundle and its external tools."""
import hashlib
import io
import json
import os
from pathlib import Path
import stat
import subprocess
import sys
import tarfile

BASE = Path('/Users/sclarke/github/otelc-qualification/2026-10-22/node-provider-0f05020')
ROOT = BASE / 'provider'
HEAD = '0f05020bae4553d500cd2e523429dfc006ef478d'
INDEX = 'c490a60d92dfe01c8ef7b5c00bc75bd81d8f4b06abe77332a29c33fc22a5f2cd'
TOOLS = {
 '/opt/homebrew/Cellar/node@24/24.21.0_2/bin/node': '798d7f9c0d38051608d11ba87a12fbb01e92bfa457cd77ec612b5bad2a73a05e',
 '/opt/homebrew/Cellar/node/26.11.0_1/bin/node': '849e5785bd5b3ac68516f105d617c4a7ddcc3de1d7a89ba696d5dab271ab0164',
 '/opt/homebrew/Cellar/python@3.14/3.14.8_1/Frameworks/Python.framework/Versions/3.14/bin/python3.14': '1860df605473e659fb393abbec47ef75a187b07777c0acf4322b9a1a1f057a08'
}


def digest(path):
    before = path.stat()
    assert stat.S_ISREG(before.st_mode), path
    with path.open('rb') as stream:
        value = hashlib.file_digest(stream, 'sha256').hexdigest()
    after = path.stat()
    assert all(getattr(before, field) == getattr(after, field) for field in
               ('st_mode', 'st_size', 'st_dev', 'st_ino', 'st_mtime_ns', 'st_ctime_ns')), path
    return value


def fail(error):
    raise error


assert digest(BASE / 'provider-index.json') == INDEX
index = json.loads((BASE / 'provider-index.json').read_bytes())
assert index['root'] == str(ROOT) and index['source_commit'] == HEAD and index['schema_version'] == 1
rows = {row['path']: row for row in index['entries']}
assert len(rows) == len(index['entries']) == 8284
actual, directories = set(), 0
for directory, children, files in os.walk(ROOT, onerror=fail):
    parent = Path(directory)
    assert stat.S_ISDIR(parent.lstat().st_mode) and not parent.lstat().st_mode & 0o222, parent
    directories += 1
    for name in children + files:
        path = parent / name
        metadata = path.lstat()
        if stat.S_ISDIR(metadata.st_mode):
            continue
        relative = path.relative_to(ROOT).as_posix()
        actual.add(relative)
        if stat.S_ISLNK(metadata.st_mode):
            assert rows[relative] == {'kind': 'symlink', 'path': relative, 'target': os.readlink(path)}, path
        else:
            assert stat.S_ISREG(metadata.st_mode) and not metadata.st_mode & 0o222, path
            assert rows[relative] == {'kind': 'file', 'path': relative, 'mode': stat.S_IMODE(metadata.st_mode),
                                      'size': metadata.st_size, 'sha256': digest(path)}, path
assert actual == set(rows), sorted(actual ^ set(rows))
for filename, expected in TOOLS.items():
    assert digest(Path(filename)) == expected, filename
assert (ROOT / '.venv/bin/python').resolve() == Path(next(name for name in TOOLS if 'python' in name)).resolve()
archive = subprocess.check_output(['git', '-C', '/Users/sclarke/github/otelc', 'archive', '--format=tar', HEAD])
assert hashlib.sha256(archive).hexdigest() == digest(BASE / 'source.tar') == 'ba808e34ec0074d1ae3a9a190e2004cf7276d62709b76c1037252da125d5a418'
source_files = 0
with tarfile.open(fileobj=io.BytesIO(archive)) as source:
    for member in source:
        if member.isfile():
            assert (ROOT / member.name).read_bytes() == source.extractfile(member).read(), member.name
            source_files += 1
result = {'source_commit': HEAD, 'index_sha256': INDEX, 'entries': len(actual), 'source_files': source_files,
          'read_only_directories': directories, 'links': sum(row['kind'] == 'symlink' for row in rows.values()),
          'external_tools': TOOLS, 'scope': 'Byte preservation before the four-startup-state c9 verifier /88ca runtime matrix; no startup admission is established by this check',
          'live_controls_admitted': False}
Path(sys.argv[1]).write_text(json.dumps(result, indent=2) + '\n')
print(json.dumps(result))
