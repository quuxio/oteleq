"""Review the isolated public-module generated-caller fixture and capture wiring."""
from concurrent.futures import ThreadPoolExecutor
import hashlib
import json
import os
from pathlib import Path
import runpy
import subprocess

BASE = Path('/Users/sclarke/github/oteleq-qualification')
MANIFEST = Path('/Users/sclarke/github/otelc-qualification/2026-10-26/rust-generated-callers/source/source.json')
OUT = BASE / '2026-10-26/sdk-rust-callers-cf8-review'
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
    assert manifest['head'] == 'cf8fdb766b5683bd079548f72bdedade985987b6'
    checker = runpy.run_path(str(BASE / '2026-10-26/review-python-label-bound.py'))['check_source']
    before = checker(manifest)
    donor = BASE / 'work/oteleq-rust-owned-provider/adapters/generation/histogram_observation.py'
    copied = source / 'ci/histogram_observation.py'
    assert donor.read_bytes() == copied.read_bytes()
    probe = runpy.run_path(str(BASE / '2026-10-26/probe-sdk-rust-receipts-910.py'))['PROBE']
    with ThreadPoolExecutor(max_workers=2) as pool:
        tests = list(pool.map(lambda version: check(version, source, probe), ('312', '314')))
    after = checker(manifest);assert before == after
    changes = subprocess.check_output(['git','diff','--name-only','395db0337a15edb07aab42625df14105c001764b',manifest['head']],cwd=source,text=True).splitlines()
    assert set(changes) == {'.github/workflows/rust-runtime.yml','README.md','ci/rust_prepared_cases.py','docs/rust-prepared.md'}
    import ast
    original = subprocess.check_output(['git','show','395db0337a15edb07aab42625df14105c001764b:ci/rust_prepared_cases.py'],cwd=source,text=True)
    prior = ast.parse(original); current = ast.parse((source/'ci/rust_prepared_cases.py').read_text())
    cls = next(node for node in current.body if isinstance(node,ast.ClassDef) and node.name=='RustPreparedCases')
    added = [node for node in cls.body if isinstance(node,ast.FunctionDef) and node.name=='test_prepared_real_generated_caller_keeps_original_module_and_excludes_helpers']
    assert len(added)==1
    cls.body.remove(added[0])
    assert ast.dump(prior,include_attributes=False)==ast.dump(current,include_attributes=False)
    subprocess.run(['git','diff','--check','395db0337a15edb07aab42625df14105c001764b',manifest['head']],cwd=source,check=True)
    result = {'status':'clear for exact public-module caller fixture source and capture wiring',
        'head':manifest['head'],'base':manifest['base'],'changed':changes,'source_preservation':after,
        'tests':tests,'findings':[],'histogram_model_sha256':hashlib.sha256(copied.read_bytes()).hexdigest(),
        'manual_review':[
            'Exactly one genuine test method is added; removing its AST leaves the entire previous fixture module identical. No SDK runtime/compiler/prepared API file changes.',
            'Original/application.rs and generated drivers/main.rs have distinct caller-held physical identities before SDK compilation. Ordinary path-module loading preserves the original file; generated helpers are excluded by common source/function selectors.',
            'The maintained test requires the complete two-file dependency catalogue, exact selected original::workload, unchanged original/generated facts after build/execution, literal arguments/output, SDK-free baseline and exact instrumented single-call receipt joined to final engine units.',
            'Workflow capture patterns add original/generated source files, fixed caller build requests/inventories and owned gate records/image. Existing public prepared/raw transport assertions and all bounded receipt/API controls remain intact.',
            'This is a public-module caller fixture under existing source-build1/2, not support for private/receiver/factory access, independent oteleq compiler discovery or generated workflow admission.',
        ],'compiler_builds':0,'sdk_builds':0,'application_launches':0,
        'limits':'No genuine SDK/compiler/application build or launch performed locally. Current-head hosted caller runtime/capture and protected CI remain required. Source/AST/bounded controls do not establish independent caller compiler discovery, private/receiver support, oteleq generated admission, full closure or shipping equivalence.'}
    p=OUT/'review.json';p.write_text(json.dumps(result,indent=2)+'\n');print(json.dumps({'record':str(p),'sha256':hashlib.sha256(p.read_bytes()).hexdigest(),'status':result['status']}))


if __name__ == '__main__':
    main()
