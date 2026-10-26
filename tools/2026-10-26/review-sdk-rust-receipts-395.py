"""Review the isolated duration/cumulative/engine-accounting correction."""
from concurrent.futures import ThreadPoolExecutor
import hashlib
import json
import os
from pathlib import Path
import runpy
import subprocess

BASE = Path('/Users/sclarke/github/oteleq-qualification')
MANIFEST = Path('/Users/sclarke/github/otelc-qualification/2026-10-26/rust-receipt-duration-accounting/source/source.json')
OUT = BASE / '2026-10-26/sdk-rust-receipts-395-review'
MODULES = ('test_rust_prepared', 'test_rust_owned_build', 'test_rust_lifetimes',
           'test_rust_telemetry', 'test_rust_capture_records', 'test_rust_histogram_observation')


def check(version: str, source: Path, probe: str) -> dict:
    python = BASE / f'2026-10-24/python-live-metrics/env-{version}/bin/python'
    env = os.environ | {'PYTHONDONTWRITEBYTECODE': '1', 'PYTHONPATH': str(source) + ':' + str(source / 'tests')}
    data = OUT / (version + '.coverage')
    argv = [str(python), '-B', '-m', 'coverage', 'run', f'--data-file={data}',
            '--source=ci.rust_telemetry,ci.histogram_observation,otelc.prepared_rust,otelc.rust_supervisor',
            '-m', 'unittest', *MODULES, '-v']
    result = subprocess.run(argv, cwd=source, env=env, capture_output=True, text=True, timeout=180)
    (OUT / (version + '-tests.log')).write_text(result.stdout + result.stderr)
    assert result.returncode == 0 and 'Ran 74 tests' in result.stderr and '\nOK\n' in result.stderr, result.stderr[-5000:]
    report = OUT / (version + '-coverage.json')
    subprocess.run([str(python), '-B', '-m', 'coverage', 'json', f'--data-file={data}', '-o', str(report)],
                   cwd=source, env=env, capture_output=True, timeout=30, check=True)
    files = json.loads(report.read_text())['files'];floors = {name: item['summary'] for name,item in files.items()}
    assert len(floors) == 4 and all(item['percent_covered'] >= 80 for item in floors.values())
    result = subprocess.run([str(python), '-B', '-c', probe], cwd=source, env=env,
                            capture_output=True, text=True, timeout=60)
    (OUT / (version + '-original-probes.log')).write_text(result.stdout + result.stderr)
    assert result.returncode == 0, result.stderr
    cases = json.loads(result.stdout);assert len(cases) == 4 and all(not case['accepted'] for case in cases)
    return {'python': version, 'methods': 74, 'module_coverage': floors, 'original_910_probes': cases}


def main() -> None:
    OUT.mkdir(exist_ok=False)
    manifest = json.loads(MANIFEST.read_text());source = Path(manifest['root'])
    assert manifest['head'] == '395db0337a15edb07aab42625df14105c001764b'
    checker = runpy.run_path(str(BASE / '2026-10-26/review-python-label-bound.py'))['check_source']
    before = checker(manifest)
    donor = BASE / 'work/oteleq-rust-owned-provider/adapters/generation/histogram_observation.py'
    copied = source / 'ci/histogram_observation.py'
    assert donor.read_bytes() == copied.read_bytes()
    probe = runpy.run_path(str(BASE / '2026-10-26/probe-sdk-rust-receipts-910.py'))['PROBE']
    with ThreadPoolExecutor(max_workers=2) as pool:
        tests = list(pool.map(lambda version: check(version, source, probe), ('312', '314')))
    after = checker(manifest);assert before == after
    changes = subprocess.check_output(['git','diff','--name-only','910a28e62f941f3c39c80f5ceef43d547e708a3e',manifest['head']],cwd=source,text=True).splitlines()
    assert set(changes) == {'Makefile','ci/histogram_observation.py','ci/rust_telemetry.py',
        'docs/rust-prepared.md','tests/test_rust_histogram_observation.py','tests/test_rust_telemetry.py'}
    subprocess.run(['git','diff','--check','910a28e62f941f3c39c80f5ceef43d547e708a3e',manifest['head']],cwd=source,check=True)
    result = {'status':'clear for exact test-only receipt correction and maintained bounded controls',
        'head':manifest['head'],'base':manifest['base'],'changed':changes,'source_preservation':after,
        'tests':tests,'findings':[],'histogram_model_sha256':hashlib.sha256(copied.read_bytes()).hexdigest(),
        'manual_review':[
            'Exact SDK-owned test-only histogram model copy matches reviewed da94 consumer bytes; SDK runtime has no oteleq checkout/package import.',
            'Finite nonnegative present sum/extrema and complete bucket denominators precede exact rational feasibility and binary64 summation bounds, including subnormal/large-value seeded concrete prefixes.',
            'Counter/histogram cumulative temporality, monotonicity, fixed start, positive observation times, identical same-time state and newly added bucket/range/sum consistency are independently checked; gauge time stays separate.',
            'Exact declared selected roots join final function admissions/completions/registration. Declared positive lifetime types/counts join final drop admissions/completions/type denominator. Actual point/spans units remain separate from HTTP/API batch counts.',
            'All four independently reproduced original910acceptance probes now refuse on both real interpreters; original source/API/prepared/supervisor behaviour remains separately covered.',
        ],'compiler_builds':0,'sdk_builds':0,'application_launches':0,
        'limits':'Declared positive synchronous/drop fixtures only. Current-head genuine wire capture/runtime/coverage and required protected CI remain separate; original26e decoded replay does not qualify a new execution or original HTTP transport. General zero/async/Cargo/caller and shipping admission remain open.'}
    p=OUT/'review.json';p.write_text(json.dumps(result,indent=2)+'\n');print(json.dumps({'record':str(p),'sha256':hashlib.sha256(p.read_bytes()).hexdigest(),'status':result['status']}))


if __name__ == '__main__':
    main()
