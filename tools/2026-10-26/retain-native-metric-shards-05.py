"""Retain exact successful metric archives and bounded original evidence bytes."""

from concurrent.futures import ThreadPoolExecutor
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
OUTPUT = BASE / '2026-10-26/native-metric-5ff52e0'
PYTHON = BASE / '2026-10-24/python-live-metrics/env-312/bin/python'
WRAPPER = BASE / '2026-10-20/pause-for-reboot/quux-oteleq-gh.py'
RUN = 40247112800
HEAD = '5ff52e0de07aaeb7f5395e35082a7dbc05b45266'
SUFFIXES = {'.json', '.protobuf', '.observation', '.c', '.cpp', '.h', '.hpp',
            '.toml', '.exit', '.py', '.tar', '.txt'}
ENV = dict(os.environ, XDG_CACHE_HOME=str(BASE / 'work/gh-cache'))


def digest(path: Path) -> str:
    with path.open('rb') as stream:
        return hashlib.file_digest(stream, 'sha256').hexdigest()


def api(endpoint: str) -> dict:
    result = subprocess.run([str(PYTHON), str(WRAPPER), 'api', endpoint],
                            env=ENV, capture_output=True, timeout=180)
    if result.returncode:
        raise RuntimeError(result.stderr.decode())
    return json.loads(result.stdout)


def retain(pair: str, artifacts: dict, jobs: dict) -> dict:
    """Require the original successful job before downloading or selecting bytes."""
    language, start = pair.split(':')
    assert language in ('c', 'cpp') and start in ('00', '01', '10', '11')
    job = jobs[f'native-metrics ({language}, {start})']
    assert job['head_sha'] == HEAD and job['run_attempt'] == 1
    assert (job['status'], job['conclusion']) == ('completed', 'success')
    name = f'native-metrics-{language}-{start}-{RUN}-1'
    artifact = artifacts[name]
    assert not artifact['expired'] and artifact['workflow_run']['head_sha'] == HEAD
    archive = OUTPUT / (name + '-' + str(artifact['id']) + '.zip')
    if not archive.exists():
        assert shutil.disk_usage(OUTPUT).free > artifact['size_in_bytes'] + 1024**3
        temporary = archive.with_name(archive.name + '.' + str(os.getpid()) + '.partial')
        with temporary.open('xb') as stream:
            result = subprocess.run([str(PYTHON), str(WRAPPER), 'api',
                f'repos/quuxio/oteleq/actions/artifacts/{artifact["id"]}/zip'],
                env=ENV, stdout=stream, stderr=subprocess.PIPE, timeout=600)
        if result.returncode:
            raise RuntimeError(result.stderr.decode())
        assert temporary.stat().st_size == artifact['size_in_bytes']
        assert 'sha256:' + digest(temporary) == artifact['digest']
        temporary.rename(archive)
    assert archive.stat().st_size == artifact['size_in_bytes']
    sha256 = digest(archive)
    assert 'sha256:' + sha256 == artifact['digest']
    selected = OUTPUT / (language + '-' + start + '-selected-04')
    index = OUTPUT / (language + '-' + start + '-selected-index-04.json')
    if index.exists():
        record = json.loads(index.read_text())
        assert record['archive_sha256'] == sha256
        assert record['language'] == language and record['start'] == start
        for member, value in record['files'].items():
            assert digest(selected / member) == value['sha256']
        return {key: value for key, value in record.items() if key != 'files'}
    assert not selected.exists(), 'partial selections require a new identity'
    with zipfile.ZipFile(archive) as bundle:
        entries = bundle.infolist()
        assert 0 < len(entries) <= 100000
        assert len({row.filename for row in entries}) == len(entries)
        for row in entries:
            path = PurePosixPath(row.filename)
            assert not path.is_absolute() and '..' not in path.parts
            assert row.filename == path.as_posix() and '\\' not in row.filename
            assert path.parts[0] in ('native-metric-evidence', 'native-metric-sdk')
            assert not stat.S_ISLNK(row.external_attr >> 16)
        wanted = [row for row in entries if not row.is_dir() and
                  (PurePosixPath(row.filename).suffix in SUFFIXES or
                   PurePosixPath(row.filename).name == 'observation')]
        total = sum(row.file_size for row in wanted)
        assert 0 < total <= 512 * 1024**2 and len(wanted) <= 50000
        assert shutil.disk_usage(OUTPUT).free > total + 1024**3
        selected.mkdir(mode=0o700)
        files = {}
        for row in wanted:
            path = selected / row.filename
            path.parent.mkdir(mode=0o700, parents=True, exist_ok=True)
            sha = hashlib.sha256()
            with bundle.open(row) as source, path.open('xb') as target:
                path.chmod(0o600)
                while data := source.read(1024**2):
                    sha.update(data)
                    target.write(data)
            assert path.stat().st_size == row.file_size
            files[row.filename] = {'sha256': sha.hexdigest(), 'bytes': row.file_size}
    record = {'start': start, 'language': language, 'archive': str(archive),
        'archive_sha256': sha256, 'artifact': artifact, 'successful_job': job['id'],
        'archive_members': len(entries), 'archive_directories': sum(row.is_dir() for row in entries),
        'selected_members': len(files), 'selected_bytes': total, 'root': str(selected),
        'files': files, 'scope': 'Original file bytes only. No executable runs; historical runner stat and kernel identities are not recertified. Empty ZIP directories are not invented.'}
    index.write_text(json.dumps(record, indent=2) + '\n')
    return {key: value for key, value in record.items() if key not in ('files', 'artifact')}


def main(pairs: list[str]) -> None:
    assert pairs and len(pairs) == len(set(pairs)) <= 8
    stamp = datetime.now(timezone.utc).strftime('%Y%m%dT%H%M%S%fZ')
    snapshot = OUTPUT / ('retention-observation-' + stamp + '.json')
    state = {'observed_at': stamp, 'run': api(f'repos/quuxio/oteleq/actions/runs/{RUN}')}
    assert state['run']['head_sha'] == HEAD and state['run']['run_attempt'] == 1
    state['jobs'] = api(f'repos/quuxio/oteleq/actions/runs/{RUN}/jobs?per_page=100')
    state['artifacts'] = api(f'repos/quuxio/oteleq/actions/runs/{RUN}/artifacts?per_page=100')
    snapshot.write_text(json.dumps(state, indent=2) + '\n')
    assert state['jobs']['total_count'] == len(state['jobs']['jobs']) == 8
    assert state['artifacts']['total_count'] == len(state['artifacts']['artifacts']) <= 8
    jobs = {row['name']: row for row in state['jobs']['jobs']}
    artifacts = {row['name']: row for row in state['artifacts']['artifacts']}
    assert len(jobs) == 8 and len(artifacts) == len(state['artifacts']['artifacts'])
    with ThreadPoolExecutor(max_workers=2) as pool:
        results = list(pool.map(lambda pair: retain(pair, artifacts, jobs), pairs))
    result = {'status': 'retained exact successful shard bytes', 'observed_at': stamp,
        'head': HEAD, 'snapshot': str(snapshot), 'shards': results,
        'free_bytes': shutil.disk_usage(OUTPUT).free, 'new_application_launches': 0}
    (OUTPUT / ('retention-result-' + stamp + '.json')).write_text(json.dumps(result, indent=2) + '\n')
    print(json.dumps(result, indent=2))


if __name__ == '__main__':
    main(sys.argv[1:])
