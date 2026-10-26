"""Retain successful d1b1a0e lifetime shards without executing archived code."""
from __future__ import annotations

from datetime import datetime, timezone
import hashlib
import json
import os
from pathlib import Path, PurePosixPath
import shutil
import stat
import subprocess
import sys
import zipfile


BASE = Path('/Users/sclarke/github/oteleq-qualification')
OUT = BASE / '2026-10-26/native-lifetime-d1b1a0e'
PYTHON = BASE / '2026-10-24/python-live-metrics/env-312/bin/python'
WRAPPER = BASE / '2026-10-20/pause-for-reboot/quux-oteleq-gh.py'
RUN = 40246431600
HEAD = 'd1b1a0ef8fa2ae1fb38cc5e7a69d18d53cb45805'
CASES = {'c-completed', 'cpp-completed', 'c-state', 'c-zero', 'cpp-zero',
         'c-censored', 'cpp-censored', 'cpp-unwind',
         'cpp-throwing-destructor', 'cpp-target-error'}
SUFFIXES = {'.json', '.protobuf', '.observation', '.c', '.cpp', '.h', '.hpp',
            '.toml', '.exit', '.py', '.tar', '.txt'}
ENV = dict(os.environ, XDG_CACHE_HOME=str(BASE / 'work/gh-cache'))


def digest(path: Path) -> str:
    """Hash a complete archive or retained byte copy."""
    with path.open('rb') as stream:
        return hashlib.file_digest(stream, 'sha256').hexdigest()


def api(endpoint: str) -> dict:
    """Use the existing account-verifying wrapper for every GitHub request."""
    result = subprocess.run([str(PYTHON), str(WRAPPER), 'api', endpoint],
                            env=ENV, capture_output=True, timeout=180, check=True)
    return json.loads(result.stdout)


def retain(name: str) -> dict:
    """Authenticate the exact successful job, archive and bounded selection."""
    assert name in CASES
    OUT.mkdir(mode=0o700, exist_ok=True)
    stamp = datetime.now(timezone.utc).strftime('%Y%m%dT%H%M%S%fZ')
    state = {
        'observed_at': stamp,
        'run': api(f'repos/quuxio/oteleq/actions/runs/{RUN}'),
        'jobs': api(f'repos/quuxio/oteleq/actions/runs/{RUN}/jobs?per_page=100'),
        'artifacts': api(f'repos/quuxio/oteleq/actions/runs/{RUN}/artifacts?per_page=100'),
    }
    (OUT / f'{name}-github-{stamp}.json').write_text(json.dumps(state, indent=2) + '\n')
    assert state['run']['head_sha'] == HEAD and state['run']['run_attempt'] == 1
    assert state['jobs']['total_count'] == len(state['jobs']['jobs']) == 10
    assert state['artifacts']['total_count'] == len(state['artifacts']['artifacts']) <= 10
    job, = [row for row in state['jobs']['jobs'] if row['name'] == f'native-lifetimes ({name})']
    assert job['head_sha'] == HEAD and job['run_attempt'] == 1
    assert (job['status'], job['conclusion']) == ('completed', 'success')
    artifact, = [row for row in state['artifacts']['artifacts']
                if row['name'] == f'native-lifetimes-{name}-{RUN}-1']
    assert not artifact['expired'] and artifact['workflow_run']['head_sha'] == HEAD
    archive = OUT / f'{name}-{artifact["id"]}.zip'
    expected = artifact['digest']
    if not archive.exists():
        assert shutil.disk_usage(OUT).free > artifact['size_in_bytes'] + 1024**3
        temporary = archive.with_suffix('.partial')
        with temporary.open('xb') as stream:
            subprocess.run([str(PYTHON), str(WRAPPER), 'api',
                f'repos/quuxio/oteleq/actions/artifacts/{artifact["id"]}/zip'],
                env=ENV, stdout=stream, stderr=subprocess.PIPE, timeout=300, check=True)
        assert temporary.stat().st_size == artifact['size_in_bytes']
        assert 'sha256:' + digest(temporary) == expected
        temporary.rename(archive)
    assert archive.stat().st_size == artifact['size_in_bytes']
    assert 'sha256:' + digest(archive) == expected
    selected = OUT / (name + '-selected-01')
    index = OUT / (name + '-selected-index-01.json')
    if index.exists():
        result = json.loads(index.read_text())
        assert result['archive_sha256'] == expected.removeprefix('sha256:')
        for member, fact in result['files'].items():
            assert (selected / member).stat().st_size == fact['bytes']
            assert digest(selected / member) == fact['sha256']
        return result
    assert not selected.exists(), 'preserve partial selections under their original identity'
    with zipfile.ZipFile(archive) as bundle:
        entries = bundle.infolist()
        assert 0 < len(entries) <= 100000
        assert len({row.filename for row in entries}) == len(entries)
        for row in entries:
            path = PurePosixPath(row.filename)
            assert not path.is_absolute() and '..' not in path.parts
            assert row.filename.rstrip('/') == path.as_posix() and '\\' not in row.filename
            assert path.parts[0] in ('native-lifetime-evidence', 'native-lifetime-sdk')
            assert not stat.S_ISLNK(row.external_attr >> 16) and not row.flag_bits & 1
        wanted = [row for row in entries if not row.is_dir() and
                  (PurePosixPath(row.filename).suffix in SUFFIXES or
                   PurePosixPath(row.filename).name == 'observation')]
        total = sum(row.file_size for row in wanted)
        assert 0 < total <= 512 * 1024**2 and len(wanted) <= 50000
        assert all(row.file_size <= 64 * 1024**2 for row in wanted)
        assert shutil.disk_usage(OUT).free > total + 1024**3
        selected.mkdir(mode=0o700)
        files = {}
        for row in wanted:
            path = selected / row.filename
            path.parent.mkdir(mode=0o700, parents=True, exist_ok=True)
            sha = hashlib.sha256()
            with bundle.open(row) as source, path.open('xb') as target:
                path.chmod(0o600)
                while block := source.read(1024**2):
                    sha.update(block)
                    target.write(block)
            assert path.stat().st_size == row.file_size
            files[row.filename] = {'sha256': sha.hexdigest(), 'bytes': row.file_size}
    result = {
        'case': name, 'head': HEAD, 'run': RUN, 'successful_job': job['id'],
        'archive': str(archive), 'archive_sha256': expected.removeprefix('sha256:'),
        'artifact': artifact, 'archive_members': len(entries),
        'archive_directories': sum(row.is_dir() for row in entries),
        'selected_members': len(files), 'selected_bytes': total,
        'root': str(selected), 'files': files,
        'scope': 'Original archive bytes and selected byte copies only; no archived executable runs or historical kernel/stat identity recertification. Empty directories are not invented.',
    }
    index.write_text(json.dumps(result, indent=2) + '\n')
    return result


if __name__ == '__main__':
    assert len(sys.argv) == 2
    result = retain(sys.argv[1])
    print(json.dumps({key: value for key, value in result.items()
                      if key not in ('files', 'artifact')}, indent=2))
