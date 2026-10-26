"""Bounded independent retained benchmark source and record review."""
from concurrent.futures import ThreadPoolExecutor
import hashlib
import importlib.util
import json
import os
from pathlib import Path
import re
import subprocess

BASE = Path('/Users/sclarke/github/oteleq-qualification')
DAY = BASE / '2026-10-26'
SDK = Path('/Users/sclarke/github/otelc-qualification')
OUT = DAY / 'sdk-go-retained-e6-review-02'
SOURCE = SDK / 'work/go-retained-workload-selection'
MODULES = ('test_go_benchmark_receipt', 'test_go_benchmark_downstream', 'test_qualify_go_benchmark')
COVERED = ('ci.go_benchmark_receipt', 'ci.go_benchmark_downstream', 'ci.qualify_go_benchmark')

def check(version):
    python = BASE / f'2026-10-24/python-live-metrics/env-{version}/bin/python'
    env = os.environ | {'PYTHONDONTWRITEBYTECODE':'1', 'PYTHONPATH': str(SOURCE) + ':' + str(SOURCE/'tests')}
    data = OUT / f'{version}.coverage'
    argv = [str(python), '-B', '-m', 'coverage', 'run', f'--data-file={data}', '--source='+','.join(COVERED), '-m','unittest',*MODULES,'-v']
    result = subprocess.run(argv,cwd=SOURCE,env=env,capture_output=True,text=True,timeout=90)
    (OUT/f'{version}.log').write_text(result.stdout+result.stderr)
    count = re.search(r'Ran (\d+) tests',result.stderr)
    assert result.returncode == 0 and count and int(count[1]) == 30,result.stderr[-4000:]
    report = OUT/f'{version}-coverage.json'
    subprocess.run([str(python),'-B','-m','coverage','json',f'--data-file={data}','-o',str(report)],cwd=SOURCE,env=env,check=True,capture_output=True,timeout=20)
    files = json.loads(report.read_text())['files']
    measured = {name: value['summary']['percent_covered'] for name,value in files.items()}
    assert len(measured) == 3 and min(measured.values()) >= 80,measured
    return {'python':version,'methods':int(count[1]),'coverage':measured,'argv':argv}


def original_rejection():
    """Use the unchanged genuine green-but-uninstrumented artifact as a control."""
    import sys
    import zipfile
    sys.path[:0] = [str(SOURCE), str(SOURCE/'tests')]
    from ci import go_benchmark_receipt as receipt
    archive=SDK/'2026-10-26/go-retained-hosted-79e-cc190/original.zip'
    raw=archive.read_bytes()
    expected='973571f9712e19a2f307fcd3e9037c5bab1246fcdecc67d20ae5309a2e8e93b1'
    assert hashlib.sha256(raw).hexdigest()==expected
    failures={}
    with zipfile.ZipFile(archive) as bundle:
        assert len(bundle.infolist())==84 and bundle.testzip() is None
        built={'receipt':json.loads(bundle.read('go-build.json'))}
        config=json.loads(bundle.read('instrumented-config.json'))
        health=json.loads(bundle.read('instrumented-health.json'))
        report=json.loads(bundle.read('report.json'))
        captured=json.loads(bundle.read('wire/forward-capture.json'))
        assert config['functions']==[] and health['probe_accounting']['function_started']=='0'
        controls={
            'selection':lambda:receipt.workload_selection(built),
            'raw_function_telemetry':lambda:receipt.workload_telemetry(captured,lambda name:bundle.read('wire/'+name),service=report['config']['resource']['service_name'],function='io.quux.otelc.examples/go.workload',calls=2*report['config']['benchmark']['samples']*report['iterations']),
        }
        for label,operation in controls.items():
            try:operation()
            except ValueError as error:failures[label]=str(error)
            else:raise AssertionError('original uninstrumented run was accepted: '+label)
    assert hashlib.sha256(archive.read_bytes()).hexdigest()==expected
    return {'original_zip_sha256':expected,'members_crc_checked':84,'actual_workflow_success_is_unqualified':True,'refusals':failures,'new_application_launches':0}

if __name__ == '__main__':
    OUT.mkdir()
    spec=importlib.util.spec_from_file_location('guard',DAY/'review-python-label-bound.py')
    guard=importlib.util.module_from_spec(spec);spec.loader.exec_module(guard)
    manifest=json.loads((SDK/'2026-10-26/go-retained-workload-selection/source/source.json').read_text())
    assert manifest['head']=='e6be2448c989cc6f4f78f99f8032f7a66bc98175'
    held=guard.check_source(manifest)
    names=subprocess.check_output(['git','diff','--name-only','79e30602d21d34c83c694e0ffea218a147baceb3',manifest['head']],cwd=SOURCE,text=True).splitlines()
    expected={'README.md','ci/go_benchmark_receipt.py','ci/qualify_go_benchmark.py','docs/go-retained-benchmark.md','examples/benchmark-metrics.toml','tests/test_go_benchmark_receipt.py','tests/test_qualify_go_benchmark.py'}
    assert set(names)==expected,names
    with ThreadPoolExecutor(max_workers=2) as pool: checks=list(pool.map(check,('312','314')))
    subprocess.run(['git','diff','--check','79e30602d21d34c83c694e0ffea218a147baceb3',manifest['head']],cwd=SOURCE,check=True)
    rejection=original_rejection()
    assert guard.check_source(manifest)==held
    result={'status':'pass for combined retained benchmark source and bounded record/transport controls','head':manifest['head'],'source_preservation':held,'changed_files':names,'original_actual_rejection':rejection,'checks':checks,'sdk_builds':0,'compiler_builds':0,'target_application_launches':0,'reviewed_boundaries':['all seven successor files against reviewed retained benchmark parent','original physical source facts and no-follow reads','literal loopback HTTP with environment proxies bypassed and redirects refused','fixed original stock/woven command roles and five-mode response/raw/resource joins','closed current-run Prometheus counts and provisioned Grafana mean expression/data source joins','capture drain and primary-error cleanup ordering','retained build images/private source records excluding disposable compiler caches and live control authentication files','manual-only actual hosted qualification with pinned external capture revision'],'scope':'Controlled Python fixtures and record/refusal methods only. Real SDK/compiler/application/Collector/Grafana execution and raw retained artifact audit remain required.'}
    (OUT/'review.json').write_text(json.dumps(result,indent=2)+'\n')
    print(json.dumps({'head':manifest['head'],'source':held,'methods_each_python':30,'record_sha256':hashlib.sha256((OUT/'review.json').read_bytes()).hexdigest()}))
