"""Review the frozen two-file Python exception-label allocation correction."""
from __future__ import annotations

from concurrent.futures import ThreadPoolExecutor
import hashlib
import json
import os
from pathlib import Path
import re
import subprocess
import tarfile
import time


ROOT = Path('/Users/sclarke/github/oteleq-qualification')
SDK = Path('/Users/sclarke/github/otelc-qualification')
OUT = ROOT / '2026-10-26/sdk-python-label-5e110b8-review-02'
MANIFESTS = {
    'before': SDK / '2026-10-26/python-exception-name-encoding/source-final/source.json',
    'after': SDK / '2026-10-26/python-exception-label-bound/source-final/source.json',
}
MODULES = [
    'test_python_cancellation', 'test_python_exception_names',
    'test_python_monitor', 'test_python_monitor_failures',
    'test_python_frontend_components', 'test_python_lifetime_controls',
    'test_python_meter_bridge', 'test_python_health',
]


def digest(path: Path) -> str:
    """Hash a regular frozen file without changing it."""
    return hashlib.sha256(path.read_bytes()).hexdigest()


def check_source(manifest: dict) -> dict:
    """Recheck every original file fact and every archived source member."""
    source = Path(manifest['root'])
    for name, expected in manifest['source_facts'].items():
        path = source / name
        stat = path.lstat()
        actual = [digest(path), stat.st_dev, stat.st_ino, stat.st_mode,
                  stat.st_size, stat.st_mtime_ns, stat.st_ctime_ns]
        assert actual == expected, (name, 'source fact changed')
        assert [stat.st_uid, stat.st_gid, stat.st_nlink] == manifest['extra_facts'][name], name
    archive = Path(manifest['archive'])
    assert digest(archive) == manifest['archive_sha256']
    with tarfile.open(archive) as bundle:
        files = {member.name: member for member in bundle if member.isfile()}
        assert set(files) == set(manifest['source_facts'])
        for name, member in files.items():
            stream = bundle.extractfile(member)
            assert stream is not None
            assert hashlib.sha256(stream.read()).hexdigest() == manifest['source_facts'][name][0], name
    return {'files': len(files), 'archive_sha256': manifest['archive_sha256']}


def run(python_id: str, before: dict, after: dict) -> dict:
    """Reproduce the original failure, then run the final exact-head corpus."""
    python = ROOT / f'2026-10-24/python-live-metrics/env-{python_id}/bin/python'
    source = Path(after['root'])
    environment = os.environ.copy()
    environment['PYTHONDONTWRITEBYTECODE'] = '1'
    environment['PYTHONPATH'] = f"{before['root']}:{before['root']}/tests"
    control = '''import pathlib, sys, unittest
namespace = {'__name__': 'review_control', '__file__': str(pathlib.Path(sys.argv[2]) / 'tests/test_python_exception_names.py')}
exec(compile(pathlib.Path(sys.argv[1]).read_text(), sys.argv[1], 'exec'), namespace)
suite = unittest.TestSuite([namespace['ExceptionNameTests']('test_rejecting_a_large_name_does_not_allocate_its_encoded_copy')])
result = unittest.TextTestRunner(verbosity=2).run(suite)
sys.exit(not result.wasSuccessful())
'''
    prior = subprocess.run(
        [str(python), '-B', '-c', control,
         str(source / 'tests/test_python_exception_names.py'), before['root']],
        cwd=before['root'], env=environment, capture_output=True, text=True, timeout=60,
    )
    (OUT / f'{python_id}-before.log').write_text(prior.stdout + prior.stderr)
    peak = re.search(r'AssertionError: (\d+) not less than 16384', prior.stderr)
    assert prior.returncode == 1 and peak is not None, prior.stderr
    assert int(peak[1]) >= 1_000_000, prior.stderr
    assert 'FAILED (failures=1)' in prior.stderr and 'Ran 1 test' in prior.stderr
    environment['PYTHONPATH'] = f'{source}:{source}/tests'
    data = OUT / f'{python_id}.coverage'
    argv = [str(python), '-B', '-m', 'coverage', 'run',
            f'--data-file={data}', '--source=otelc.python_runtime',
            '-m', 'unittest', *MODULES, '-v']
    started = time.monotonic()
    result = subprocess.run(argv, cwd=source, env=environment,
                            capture_output=True, text=True, timeout=180)
    elapsed = time.monotonic() - started
    (OUT / f'{python_id}-after.log').write_text(result.stdout + result.stderr)
    assert result.returncode == 0, result.stderr[-6000:]
    assert re.search(r'Ran 45 tests', result.stderr), result.stderr[-300:]
    coverage_path = OUT / f'{python_id}-coverage.json'
    covered = subprocess.run(
        [str(python), '-B', '-m', 'coverage', 'json', f'--data-file={data}',
         '-o', str(coverage_path)],
        cwd=source, env=environment, capture_output=True, text=True, timeout=30,
    )
    assert covered.returncode == 0, covered.stderr
    coverage = json.loads(coverage_path.read_text())['totals']
    assert coverage['percent_covered'] >= 80
    return {'python': python_id, 'before_exit': prior.returncode,
            'before_peak_bytes': int(peak[1]), 'argv': argv,
            'exit_code': result.returncode, 'methods': 45,
            'seconds': elapsed, 'runtime_coverage': coverage}


def main() -> None:
    """Record a bounded review, preserving both immutable revisions."""
    OUT.mkdir(exist_ok=False)
    manifests = {name: json.loads(path.read_text()) for name, path in MANIFESTS.items()}
    before, after = manifests['before'], manifests['after']
    assert after['head'] == '5e110b834cd34233cea8342765951d41207e8ea0'
    assert after['base'] == before['head'] == '7f4df220b9559de058dbc23cf7934b915b20fe78'
    held_before = {name: check_source(data) for name, data in manifests.items()}
    source = Path(after['root'])
    changed = subprocess.check_output(
        ['git', 'diff', '--name-only', before['head'], after['head']], cwd=source,
        text=True,
    ).splitlines()
    assert set(changed) == {'otelc/python_runtime.py', 'tests/test_python_exception_names.py'}
    original = (Path(before['root']) / 'otelc/python_runtime.py').read_text()
    expected = original.replace('if type(name) is not str:',
                                'if type(name) is not str or len(name) > 1024:', 1)
    assert expected != original
    assert (source / 'otelc/python_runtime.py').read_text() == expected
    subprocess.run(['git', 'diff', '--check', before['head'], after['head']],
                   cwd=source, check=True)
    with ThreadPoolExecutor(max_workers=2) as pool:
        checks = list(pool.map(lambda version: run(version, before, after), ('312', '314')))
    held_after = {name: check_source(data) for name, data in manifests.items()}
    assert held_before == held_after
    record = {
        'status': 'clear for the exact two-file bounded-allocation successor',
        'head': after['head'], 'base': before['head'], 'changed': changed,
        'source_preservation': held_after, 'checks': checks, 'findings': [],
        'manual_review': [
            'Only the existing exact-str guard changes in production; UTF-8 byte limits and surrogate fallback remain unchanged.',
            'UTF-8 has at least one byte per code point, so rejecting more than1024 code points preserves every previous label result and bounds subsequent encoding.',
            'The isolated maintained regression allocates the application name before tracing; it fails on an original encoded copy of at least1,000,000 bytes on each interpreter and passes under a16KiB ceiling on the successor.',
            'Existing cancellation, exception identity, hostile hooks and three-signal actual public CLI controls run unchanged on both interpreters.',
        ],
        'sdk_builds': 0, 'compiler_builds': 0,
        'limits': 'Exact two-file source/test review; no arbitrary application, shipping or whole-language performance admission. Current-head protected CI remains separate.',
    }
    (OUT / 'review.json').write_text(json.dumps(record, indent=2) + '\n')
    print(json.dumps(record, indent=2))


if __name__ == '__main__':
    main()
