"""Probe retained Rust receipt oracles using literal protobufs only."""
from concurrent.futures import ThreadPoolExecutor
import hashlib
import json
import os
from pathlib import Path
import runpy
import subprocess

BASE = Path('/Users/sclarke/github/oteleq-qualification')
OUT = BASE / '2026-10-26/sdk-rust-receipts-910-probes'
MANIFEST = Path('/Users/sclarke/github/otelc-qualification/2026-10-26/rust-prepared-telemetry-receipts/source/source.json')
PROBE = '''import json
from test_rust_telemetry import RustTelemetryTests
results=[]
for changed in ('nonfinite-duration-sum','negative-duration-extrema','wrong-function-admissions','delta-nonmonotonic-calls'):
 fixture=RustTelemetryTests('test_actual_point_units_are_separate_from_empty_api_batch_counts');fixture.setUp()
 if changed=='nonfinite-duration-sum': fixture.metric_scope.metrics[1].histogram.data_points[0].sum=float('nan')
 elif changed=='negative-duration-extrema':
  point=fixture.metric_scope.metrics[1].histogram.data_points[0];point.min=-2;point.max=-1;point.sum=-3
 elif changed=='wrong-function-admissions': fixture.health['function_accounting'].update(started='3',ended='3')
 else:
  metric=fixture.metric_scope.metrics[0];metric.sum.aggregation_temporality=1;metric.sum.is_monotonic=False
 try:
  result=fixture.verify();results.append({'change':changed,'accepted':True,'receipt':result})
 except ValueError as error: results.append({'change':changed,'accepted':False,'error':str(error)})
print(json.dumps(results))
'''


def check(version: str, source: Path) -> dict:
    python = BASE / f'2026-10-24/python-live-metrics/env-{version}/bin/python'
    env = os.environ | {'PYTHONDONTWRITEBYTECODE': '1', 'PYTHONPATH': str(source) + ':' + str(source / 'tests')}
    argv = [str(python), '-B', '-m', 'unittest', 'test_rust_telemetry', 'test_rust_capture_records', '-v']
    result = subprocess.run(argv, cwd=source, env=env, capture_output=True, text=True, timeout=120)
    (OUT / (version + '-maintained.log')).write_text(result.stdout + result.stderr)
    assert result.returncode == 0 and 'Ran 12 tests' in result.stderr, result.stderr[-2000:]
    probe = subprocess.run([str(python), '-B', '-c', PROBE], cwd=source, env=env,
                           capture_output=True, text=True, timeout=60)
    (OUT / (version + '-probes.log')).write_text(probe.stdout + probe.stderr)
    assert probe.returncode == 0, probe.stderr
    cases = json.loads(probe.stdout)
    assert len(cases) == 4 and all(row['accepted'] for row in cases)
    return {'python': version, 'maintained_methods': 12, 'probes': cases}


def main() -> None:
    OUT.mkdir(exist_ok=False)
    manifest = json.loads(MANIFEST.read_text())
    assert manifest['head'] == '910a28e62f941f3c39c80f5ceef43d547e708a3e'
    source = Path(manifest['root'])
    checker = runpy.run_path(str(BASE / '2026-10-26/review-python-label-bound.py'))['check_source']
    before = checker(manifest)
    with ThreadPoolExecutor(max_workers=2) as pool:
        tests = list(pool.map(lambda version: check(version, source), ('312', '314')))
    after = checker(manifest); assert before == after
    result = {'status': 'changes required in new fixture receipt verifier', 'head': manifest['head'],
        'source_preservation': after, 'tests': tests,
        'findings': [
            {'priority': 1, 'file': 'ci/rust_telemetry.py', 'functions': ['verify', 'lifetime_metrics'],
             'issue': 'Duration histograms check only counts/bucket denominators and bounds; nonfinite sums and negative/impossible duration extrema are accepted. Validate finite nonnegative sums/extrema, presence, populated bucket/extrema consistency and cumulative state for both function/lifetime series.'},
            {'priority': 2, 'file': 'ci/rust_telemetry.py', 'functions': ['verify'],
             'issue': 'Final function started/ended accounting is only internally balanced and is never joined to the declared exact root denominator. Three clean admissions with only two received/declared roots pass the current sample_ratio=1 fixture. Require declared function and lifetime totals to match final engine admission/completion counters.'},
        ], 'compiler_builds': 0, 'sdk_builds': 0, 'application_launches': 0,
        'scope': 'Bounded literal protobuf/counter acceptance probes and existing loopback capture tests. No new runtime/provider admission. Existing productAPI9193 review remains separate.'}
    p=OUT/'review.json';p.write_text(json.dumps(result,indent=2)+'\n')
    print(json.dumps({'record':str(p),'sha256':hashlib.sha256(p.read_bytes()).hexdigest(), 'status':result['status']}))


if __name__ == '__main__':
    main()
