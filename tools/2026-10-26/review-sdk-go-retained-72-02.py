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
OUT = DAY / 'sdk-go-retained-72-review-02'
SOURCE = SDK / 'work/go-retained-policy-identities'
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
    assert result.returncode == 0 and count and int(count[1]) == 31,result.stderr[-4000:]
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


def actual_policy_and_workload():
    """Read original failed e6 observations without inventing absent build products."""
    import sys
    import zipfile
    sys.path[:0]=[str(SOURCE),str(SOURCE/'tests')]
    from ci import go_benchmark_receipt as receipt
    archive=SDK/'2026-10-26/go-retained-hosted-e6-cc190/original.zip'
    expected='1ed0744438bf752651ebd3a630992aff05849a1ec2c14ad0dd25015e5fb8e2aa'
    assert hashlib.sha256(archive.read_bytes()).hexdigest()==expected
    witness=json.loads((SOURCE/'tests/fixtures/go-benchmark-policy-identities.json').read_text())
    with zipfile.ZipFile(archive) as bundle:
        assert len(bundle.infolist())==200 and bundle.testzip() is None
        report=json.loads(bundle.read('report.json'))
        config=json.loads(bundle.read('instrumented-config.json'))
        health=json.loads(bundle.read('instrumented-health.json'))
        captured=json.loads(bundle.read('wire/forward-capture.json'))
        assert witness['origin']['zip_sha256']==expected and receipt.same(witness['policy'],report['config'])
        policy=json.dumps(report['config'],sort_keys=True,allow_nan=False).encode()
        runtime_hash=hashlib.sha256(policy).hexdigest()
        report_hash=hashlib.sha256(policy+b'\n').hexdigest()
        assert runtime_hash!=report_hash
        assert config['policy_sha256']==health['policy_sha256']==witness['runtime_policy_sha256']==runtime_hash
        assert report['config_sha256']==witness['report_config_sha256']==report_hash
        count=1+(report['config']['benchmark']['warmup']+4*report['config']['benchmark']['samples'])*report['iterations']
        collected=2*report['config']['benchmark']['samples']*report['iterations']
        probes=health['probe_accounting']
        assert probes['function_started']==probes['function_ended']==str(count) and probes['closed'] is True
        assert all(probes[k]=='0' for k in ('function_active','function_lost','unwind_unknown'))
        assert config['functions']==['io.quux.otelc.examples/go.workload']
        telemetry=receipt.workload_telemetry(captured,lambda name:bundle.read('wire/'+name),service=report['config']['resource']['service_name'],function=config['functions'][0],calls=collected)
        products_present=all(name in bundle.namelist() for name in ('go-build.json','plain-image.gz','instrumented-image.gz'))
    assert hashlib.sha256(archive.read_bytes()).hexdigest()==expected
    return {'original_run':40294616050,'original_zip_sha256':expected,'members_crc_checked':200,'actual_invocations':count,'collected_calls':collected,'actual_raw_telemetry':telemetry,'fixture_policy_and_two_hashes_match_original':True,'complete_build_and_images_retained':products_present,'status':'Original run remains failed; positive retained policy/probe/raw telemetry observations only. Missing build/images are not reconstructed; no downstream or full qualification claim.'}

if __name__ == '__main__':
    OUT.mkdir()
    spec=importlib.util.spec_from_file_location('guard',DAY/'review-python-label-bound.py')
    guard=importlib.util.module_from_spec(spec);spec.loader.exec_module(guard)
    manifest=json.loads((SDK/'2026-10-26/go-retained-policy-identities/source/source.json').read_text())
    assert manifest['head']=='72ee497df22ab77dbcd6b598dec24bd97938ee96'
    held=guard.check_source(manifest)
    names=subprocess.check_output(['git','diff','--name-only','e6be2448c989cc6f4f78f99f8032f7a66bc98175',manifest['head']],cwd=SOURCE,text=True).splitlines()
    expected={'.github/workflows/go-benchmark-retained.yml','ci/go_benchmark_receipt.py','docs/go-retained-benchmark.md','tests/fixtures/go-benchmark-policy-identities.json','tests/test_go_benchmark_receipt.py'}
    assert set(names)==expected,names
    with ThreadPoolExecutor(max_workers=2) as pool: checks=list(pool.map(check,('312','314')))
    subprocess.run(['git','diff','--check','e6be2448c989cc6f4f78f99f8032f7a66bc98175',manifest['head']],cwd=SOURCE,check=True)
    rejection=original_rejection()
    actual=actual_policy_and_workload()
    assert guard.check_source(manifest)==held
    result={'status':'pass for combined retained benchmark source and bounded record/transport controls','head':manifest['head'],'source_preservation':held,'changed_files':names,'original_actual_rejection':rejection,'actual_policy_and_workload':actual,'checks':checks,'sdk_builds':0,'compiler_builds':0,'target_application_launches':0,'reviewed_boundaries':['all five policy identity correction files against reviewed workload parent','original physical source facts and no-follow reads','literal loopback HTTP with environment proxies bypassed and redirects refused','fixed original stock/woven command roles and five-mode response/raw/resource joins','closed current-run Prometheus counts and provisioned Grafana mean expression/data source joins','capture drain and primary-error cleanup ordering','retained build images/private source records excluding disposable compiler caches and live control authentication files','manual-only actual hosted qualification with pinned external capture revision'],'scope':'Controlled Python fixtures and record/refusal methods only. Real SDK/compiler/application/Collector/Grafana execution and raw retained artifact audit remain required.'}
    (OUT/'review.json').write_text(json.dumps(result,indent=2)+'\n')
    print(json.dumps({'head':manifest['head'],'source':held,'methods_each_python':31,'record_sha256':hashlib.sha256((OUT/'review.json').read_bytes()).hexdigest()}))
