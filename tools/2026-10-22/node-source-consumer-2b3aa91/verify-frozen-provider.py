"""Recheck the provisional immutable provider without changing its contents."""

import hashlib
import json
import os
from pathlib import Path
import stat
import sys

HANDOFF = Path('/Users/sclarke/github/otelc-qualification/2026-10-22/node-provider-2b3aa91/handoff.json')
INDEX_SHA256 = '160381f80673586e966fbf916ee9ac51f9c33cd9d84b5a26e4e879e32ceb4e69'
HEAD = '2b3aa9172e8ee8676fcd890eeaae6386bd13495e'


def digest(path: Path) -> str:
    """Read a regular file with a bounded buffer and stable file identity."""
    before = path.stat()
    assert stat.S_ISREG(before.st_mode), path
    value = hashlib.sha256()
    with path.open('rb') as stream:
        for chunk in iter(lambda: stream.read(1024 * 1024), b''):
            value.update(chunk)
    after = path.stat()
    fields = ('st_mode', 'st_size', 'st_ino', 'st_dev', 'st_mtime_ns', 'st_ctime_ns')
    assert all(getattr(before, name) == getattr(after, name) for name in fields), path
    return value.hexdigest()


def fail_walk(error: OSError) -> None:
    """An unreadable subtree cannot produce a successful partial verification."""
    raise error


def verify() -> dict:
    """Check exact entry membership, bytes, links, modes and external tools."""
    handoff = json.loads(HANDOFF.read_text())
    assert handoff['head'] == HEAD
    index_path = Path(handoff['provider_index'])
    assert digest(index_path) == INDEX_SHA256 == handoff['provider_index_sha256']
    index = json.loads(index_path.read_text())
    root = Path(handoff['provider'])
    assert index['source_commit'] == HEAD and index['root'] == str(root)
    rows = {row['path']: row for row in index['entries']}
    assert len(rows) == len(index['entries']) == handoff['entries'] == 8297
    actual, directory_count = set(), 0
    for directory, directories, files in os.walk(root, onerror=fail_walk):
        parent = Path(directory)
        metadata = parent.lstat()
        assert stat.S_ISDIR(metadata.st_mode) and not metadata.st_mode & 0o222, parent
        directory_count += 1
        for name in directories + files:
            path = parent / name
            metadata = path.lstat()
            if stat.S_ISDIR(metadata.st_mode):
                continue
            relative = path.relative_to(root).as_posix()
            actual.add(relative)
            expected = rows[relative]
            if stat.S_ISLNK(metadata.st_mode):
                assert expected == {'kind': 'symlink', 'path': relative, 'target': os.readlink(path)}, path
            else:
                assert stat.S_ISREG(metadata.st_mode), path
                assert not metadata.st_mode & 0o222, path
                assert expected == {'kind': 'file', 'path': relative, 'size': metadata.st_size,
                                    'mode': stat.S_IMODE(metadata.st_mode), 'sha256': digest(path)}, path
    assert actual == set(rows), sorted(set(rows) ^ actual)
    for tool in handoff['node_tools']:
        assert digest(Path(tool['node'])) == tool['sha256'], tool['node']
    assert digest(Path(handoff['python_tool']['path'])) == handoff['python_tool']['sha256']
    assert (root / '.venv/bin/python').resolve() == Path(handoff['python_tool']['path']).resolve()
    for name in ('public_plan', 'common_defaults'):
        assert digest(Path(handoff[name])) == handoff[name + '_sha256']
    return {'head': HEAD, 'index_sha256': INDEX_SHA256, 'entries': len(actual),
            'links': sum(row['kind'] == 'symlink' for row in rows.values()),
            'read_only_directories_including_root': directory_count,
            'external_tools': len(handoff['node_tools']) + 1,
            'scope': 'read-only development preservation; not provider admission', 'accepted': False}


if __name__ == '__main__':
    result = verify()
    Path(sys.argv[1]).write_text(json.dumps(result, indent=2) + '\n')
    print(json.dumps(result))
