"""Review the six-file diagnostic-only native benchmark capture change."""
from __future__ import annotations

from concurrent.futures import ThreadPoolExecutor
import importlib.util
import json
import os
from pathlib import Path
import re
import subprocess
import time


BASE = Path('/Users/sclarke/github/oteleq-qualification')
SDK = Path('/Users/sclarke/github/otelc-qualification')
SOURCE = SDK / 'work/native-benchmark-failure-capture'
OUT = BASE / '2026-10-26/sdk-native-capture-9c7e4ad-review'
OUT.mkdir(mode=0o700)
spec = importlib.util.spec_from_file_location('source_guard', BASE / '2026-10-26/review-python-label-bound.py')
assert spec is not None and spec.loader is not None
guard = importlib.util.module_from_spec(spec)
spec.loader.exec_module(guard)
manifest = json.loads((SDK / '2026-10-26/native-benchmark-failure-capture/source-final/source.json').read_text())
assert manifest['head'] == '9c7e4ada9b4646626291d37118ca5fbb935abc9d'
held_before = guard.check_source(manifest)
changed = subprocess.check_output(['git', 'diff', '--name-only',
    '78572588bd86aca6ecd3ac27d490074f4b0031fe', manifest['head']], cwd=SOURCE, text=True).splitlines()
assert set(changed) == {'.github/workflows/ci.yml', '.github/workflows/native-benchmarks.yml',
                        'docs/native-benchmarks.md', 'tests/test_capture_records.py',
                        'tests/test_java_integration.py', 'tests/test_native_benchmark.py'}
subprocess.run(['git', 'diff', '--check', manifest['base'], manifest['head']], cwd=SOURCE, check=True)


def controls(version: str) -> dict:
    """Run only explicit bounded classes and two extra real HTTP capture controls."""
    python = BASE / f'2026-10-24/python-live-metrics/env-{version}/bin/python'
    environment = dict(os.environ, PYTHONDONTWRITEBYTECODE='1', PYTHONPATH=f'{SOURCE}:{SOURCE}/tests')
    names = ['test_capture_records.CaptureRecordTests',
             'test_capture_records.BenchmarkFailureCaptureTests',
             'test_native_benchmark.NativeBenchmarkAccountingTests',
             'test_benchmark_failures', 'test_native_launch_gate.NativeLaunchGateTests']
    started = time.monotonic()
    result = subprocess.run([str(python), '-B', '-m', 'unittest', *names, '-v'],
        cwd=SOURCE, env=environment, capture_output=True, text=True, timeout=60)
    (OUT / f'{version}-controls.log').write_text(result.stdout + result.stderr)
    assert result.returncode == 0 and re.search(r'Ran 22 tests', result.stderr), result.stderr[-5000:]
    assert 'skipped=' not in result.stderr
    extra = r'''import gzip, hashlib, http.client, json, pathlib, tempfile
from unittest.mock import patch
from test_java_integration import Capture
with tempfile.TemporaryDirectory() as directory:
 root=pathlib.Path(directory)
 captured=[]
 for malformed in (False,True):
  output=root/('malformed' if malformed else 'chunked')
  capture=Capture(output)
  body=b'\xff' if malformed else gzip.compress(b'',mtime=0)
  try:
   with patch.object(capture.server,'handle_error') as server_errors:
    connection=http.client.HTTPConnection('127.0.0.1',capture.server.server_port,timeout=3)
    try:
     if malformed:
      connection.request('POST','/v1/metrics',body=body)
     else:
      connection.request('POST','/v1/metrics',body=iter([body[:7],body[7:]]),
                         headers={'Content-Encoding':'gzip'},encode_chunked=True)
     try:
      response=connection.getresponse()
      assert not malformed and response.status==200
      response.read()
     except http.client.RemoteDisconnected:
      assert malformed
    finally:
     connection.close()
    assert server_errors.call_count==int(malformed)
   paths=list(output.glob('otlp-*.json'))
   assert len(paths)==1
   value=json.loads(paths[0].read_text())
   assert paths[0].with_suffix('.http-body').read_bytes()==body
   assert value['body_bytes']==len(body)
   assert value['body_sha256']==hashlib.sha256(body).hexdigest()
   assert len(capture.metrics)==int(not malformed)
   captured.append({'malformed':malformed,'raw_entity_retained':True,'decoded_metrics':len(capture.metrics)})
  finally:
   capture.close()
 print(json.dumps(captured))
'''
    probe = subprocess.run([str(python), '-B', '-c', extra], cwd=SOURCE, env=environment,
                            capture_output=True, text=True, timeout=30)
    (OUT / f'{version}-extra-http.log').write_text(probe.stdout + probe.stderr)
    assert probe.returncode == 0, probe.stderr
    return {'python': version, 'maintained_methods': 22, 'exit_code': 0,
            'seconds': time.monotonic() - started, 'extra_http_controls': json.loads(probe.stdout)}


with ThreadPoolExecutor(max_workers=2) as pool:
    checks = list(pool.map(controls, ('312', '314')))

node = '/opt/homebrew/Cellar/node@24/24.21.0_2/bin/node'
modules = BASE / 'work/oteleq-native-generated/ci/markdownlint/node_modules'
code = """const fs=require('fs'),yaml=require('js-yaml');
const documents=process.argv.slice(1).map(path=>({path,value:yaml.load(fs.readFileSync(path,'utf8'))}));
process.stdout.write(JSON.stringify(documents));"""
files = [SOURCE / '.github/workflows/ci.yml', SOURCE / '.github/workflows/native-benchmarks.yml']
loaded = subprocess.run([node, '-e', code, *map(str, files)],
    env=dict(os.environ, NODE_PATH=str(modules)), capture_output=True, text=True, check=True)
documents = json.loads(loaded.stdout)
scripts = []
for document in documents:
    value = document['value']
    assert value['permissions'] == {'contents': 'read'}
    for job in value['jobs'].values():
        for step in job.get('steps', []):
            if 'run' in step:
                script = step['run']
                subprocess.run(['bash', '-n'], input=script, text=True, capture_output=True, check=True)
                scripts.append(script)
            if step.get('name') in ('Retain native benchmark failure diagnostics',
                                    'Retain compact benchmark diagnostics even on failure'):
                assert step['if'] == 'always()'
                paths = step['with']['path'].splitlines()
                assert not any('plan.json' in path or 'control.json' in path for path in paths)
                assert any(path.endswith('/compiled/plain') for path in paths)
                assert any(path.endswith('/compiled/instrumented') for path in paths)
focus = documents[1]['value']
assert focus['jobs']['native-benchmarks']['defaults']['run']['shell'] == 'bash'
assert focus['jobs']['native-benchmarks']['strategy']['matrix']['os'] == ['ubuntu-24.04', 'macos-26']
subprocess.run([node, str(modules / 'markdownlint-cli/markdownlint.js'), '--config',
               str(SOURCE / '.markdownlint.json'), str(SOURCE / 'docs/native-benchmarks.md')],
              capture_output=True, text=True, check=True)
held_after = guard.check_source(manifest)
assert held_after == held_before
record = {
    'status': 'clear for the exact six-file test/diagnostic/workflow change',
    'head': manifest['head'], 'base': manifest['base'], 'changed': changed,
    'source_preservation': held_after, 'checks': checks,
    'bash_scripts_parsed': len(scripts), 'yaml_and_markdown': 'pass', 'findings': [],
    'manual_review': [
        'All production/runtime/examples remain exact reviewed785; recording is opt-in and existing deadlines, acceptance rules and error precedence are unchanged.',
        'The receiver records exact HTTP entity bytes after transfer framing and before content/protobuf decoding, with bounded locked counters, fixed exclusive filenames, hashes and private modes. It does not record headers or claim response acknowledgement.',
        'Failed flush diagnostics query health through the original unpatched function and re-raise the same failure; health/write errors cannot replace it. The existing workload stops at the first failed flush.',
        'Explicit module import avoids exposing the native integration TestCase to unit discovery. A maintained8GiB guard rejects before any native SDK setup.',
        'Both hosted platforms retain compact allowlisted bytes and actual test images on failure; descriptor/plan files are omitted. Explicit Bash keeps the tee pipeline failure visible.',
    ],
    'sdk_builds': 0, 'compiler_builds': 0, 'native_application_launches': 0,
    'limits': 'Diagnostic capture review only. Original macOS benchmark flush failure remains unresolved; exact-head protected/native runs and diagnosis are still required. Extra HTTP controls are synthetic receiver requests, not application or SDK qualification.',
}
(OUT / 'controller.py').write_bytes(Path(__file__).read_bytes())
(OUT / 'review.json').write_text(json.dumps(record, indent=2) + '\n')
print(json.dumps({'status': record['status'], 'source': held_after,
                  'methods_per_python': [r['maintained_methods'] for r in checks],
                  'bash_scripts_parsed': len(scripts)}, indent=2))
