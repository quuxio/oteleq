"""Review fixed Rust preparation/supervision without native builds or launches."""
from concurrent.futures import ThreadPoolExecutor
import hashlib
import json
import os
from pathlib import Path
import re
import runpy
import subprocess

BASE = Path('/Users/sclarke/github/oteleq-qualification')
MANIFEST = Path('/Users/sclarke/github/otelc-qualification/2026-10-26/rust-prepared-constructor-section/source/source.json')
OUT = BASE / '2026-10-26/sdk-rust-prepared-9193-review'


def check(version: str, source: Path) -> dict:
    python = BASE / f'2026-10-24/python-live-metrics/env-{version}/bin/python'
    env = os.environ | {'PYTHONDONTWRITEBYTECODE': '1', 'PYTHONPATH': str(source) + ':' + str(source / 'tests')}
    data = OUT / (version + '.coverage')
    argv = [str(python), '-B', '-m', 'coverage', 'run', f'--data-file={data}',
            '--source=otelc.prepared_rust,otelc.rust_supervisor', '-m', 'unittest',
            'test_rust_prepared', 'test_rust_owned_build', 'test_rust_lifetimes', '-v']
    result = subprocess.run(argv, cwd=source, env=env, capture_output=True, text=True, timeout=120)
    (OUT / (version + '-tests.log')).write_text(result.stdout + result.stderr)
    assert result.returncode == 0, result.stderr[-5000:]
    count = re.search(r'Ran (\d+) tests', result.stderr)
    assert count and int(count[1]) == 53 and '\nOK\n' in result.stderr, result.stderr[-1500:]
    report = OUT / (version + '-coverage.json')
    subprocess.run([str(python), '-B', '-m', 'coverage', 'json', f'--data-file={data}', '-o', str(report)],
                   cwd=source, env=env, capture_output=True, timeout=30, check=True)
    files = json.loads(report.read_text())['files']
    floors = {name: item['summary'] for name, item in files.items()}
    assert len(floors) == 2 and all(item['percent_covered'] >= 80 for item in floors.values())
    return {'python': version, 'argv': argv, 'test_methods': int(count[1]), 'module_coverage': floors}


def main() -> None:
    OUT.mkdir(exist_ok=False)
    manifest = json.loads(MANIFEST.read_text())
    assert manifest['head'] == '9193bf18abae6df589db2821097b09c6af2292ca'
    source = Path(manifest['root'])
    checker = runpy.run_path(str(BASE / '2026-10-26/review-python-label-bound.py'))['check_source']
    before = checker(manifest)
    with ThreadPoolExecutor(max_workers=2) as pool:
        results = list(pool.map(lambda version: check(version, source), ('312', '314')))
    after = checker(manifest)
    assert before == after
    result = {'status': 'source and bounded literal API review clear; actual execution qualification separate',
        'head': manifest['head'], 'source_preservation': after, 'tests': results, 'findings': [],
        'manual_review': [
            'Read full fixed preparation, supervisor, shared launch callback and host-release/cleanup paths; argv and image are derived from verified original build, never stored command metadata.',
            'Closed exact-type request/plan/prepared/start/release/final records keep bool/int/float identities separate. Producer and interpreter identities are rechecked; runtime output refuses physical source/compiler/SDK/owned-build overlap.',
            'Supervisor and waiting child have distinct private sessions/groups. Literal stale release, parent, timeout, early exit, signal, signed exit, bad health and cleanup controls remain incomplete rather than false success.',
            'Actual image has not executed at waiting_exec. SDK explicitly records exec_verified=false; independent consumer kernel/image observations and downstream decoded receipt remain separate obligations.',
            'Read genuine constructor/literal argv, four same-process control states, drop-profile and public CLI test cases and workflow capture wiring. Those cases are not run in this local review; their control acknowledgements and final health do not alone prove exact downstream receipt or zero loss.',
        ], 'compiler_builds': 0, 'sdk_builds': 0, 'application_launches': 0,
        'limits': 'Exact current SDK candidate source and literal metadata/API checks. Hosted runtime/transport/coverage artefacts, required protected CI, all Rust/Cargo/async and shipping qualification remain separate.'}
    path = OUT / 'review.json'; path.write_text(json.dumps(result, indent=2) + '\n')
    print(json.dumps({'path': str(path), 'sha256': hashlib.sha256(path.read_bytes()).hexdigest(),
                      'status': result['status'], 'methods_per_python': [item['test_methods'] for item in results]}))


if __name__ == '__main__':
    main()
