"""Exercise one real paired application before extending the new consumer path."""

import hashlib
import json
import os
from pathlib import Path
import sys

SOURCE = Path('/Users/sclarke/github/oteleq-qualification/work/oteleq-node-source-provider')
PROOF = Path(__file__).resolve().parent
sys.path[:0] = [str(SOURCE / 'adapters/generation'), str(SOURCE / 'examples')]
import generation
import node_source
import otelc_capture as capture
from opentelemetry.proto.collector.trace.v1.trace_service_pb2 import ExportTraceServiceRequest

handoff = json.loads(Path('/Users/sclarke/github/otelc-qualification/2026-10-22/node-provider-2b3aa91/handoff.json').read_text())
root = Path(handoff['provider'])
node = Path(handoff['node_tools'][0]['node'])
folder = PROOF / 'prototype-supervisor-chunked'
folder.mkdir(mode=0o700)
worker = SOURCE / 'adapters/generation/node_source_worker.py'
components = {name: hashlib.sha256((SOURCE / 'adapters/generation' / name).read_bytes()).hexdigest()
              for name in ('node_source.py', 'node_source_worker.py')}
bootstrap = "import runpy,sys;sys.path[:0]=sys.argv[1:3];script=sys.argv[3];sys.argv=sys.argv[3:];runpy.run_path(script,run_name='__main__')"
components['capture.py'] = hashlib.sha256((SOURCE / 'examples/otelc_capture.py').read_bytes()).hexdigest()
(folder / 'source-before.json').write_text(json.dumps(components, indent=2)+'\n')
results = []
for plain in (True, False):
    attempt = folder / ('plain' if plain else 'instrumented')
    attempt.mkdir(mode=0o700)
    project = attempt / 'project'
    project.mkdir(mode=0o700)
    entry = project / 'app.cjs'
    application = "let total=10; function add(value){total+=value;return total;} const before=total; const result=add(7); console.log(JSON.stringify({before,result,after:total}));\n"
    entry.write_text(application)
    service = 'oteleq-node-source-prototype'
    selected = {'language': 'javascript', 'node_backend': node_source.SOURCE,
                'path': 'app.cjs', 'otelc_function': 'app.add'}
    with capture.receiver(allow_chunked=True, response_path=attempt / 'http-responses.json') as (endpoint, bodies, errors):
        config = attempt / 'policy.toml'
        config.write_text(node_source.policy(selected, endpoint, service))
        request = {'schema_version': 1, 'provider': str(root), 'project': str(project),
                   'entry': str(entry), 'runtime': str(attempt / 'node-runtime'), 'policy': str(config),
                   'node': str(node), 'language': 'javascript', 'compiler': 'native',
                   'plain': plain, 'gc_fixture': False, 'timeout_ms': 60000}
        request_path = attempt / 'node-source-request.json'
        request_path.write_text(json.dumps(request, indent=2) + '\n')
        command = [sys.executable, '-I', '-B', '-c', bootstrap, str(SOURCE / 'adapters/generation'),
                   str(SOURCE / 'examples'), str(worker), str(request_path)]
        environment = capture.environment(project, {'javascript': node}, service, root)
        environment['TMPDIR'] = str(attempt)
        result = generation.execute(command, project, environment, attempt, timeout=60, record_process=True)
    capture.retain_http(attempt, bodies, errors)
    assert result.returncode == 0, (result.returncode, result.stderr.decode())
    assert result.stdout == b'{"before":10,"result":17,"after":17}\n' and not result.stderr
    assert entry.read_text() == application
    assert not errors, errors
    completion = json.loads((attempt / 'node-source-completion.json').read_text())
    assert completion['application_returncode'] == 0 and completion['inputs_verified'] is True
    spans = [span for path, body in bodies if path == capture.TRACE_PATH
             for resource in ExportTraceServiceRequest.FromString(body).resource_spans
             for scope in resource.scope_spans for span in scope.spans]
    if plain:
        assert not bodies and completion['sdk_pid'] is None and completion['sdk_exited'] is None
    else:
        assert completion['phase'] == 'closed' and completion['sdk_exited'] is True
        assert len(spans) == 1 and spans[0].name == 'app.add' and not spans[0].parent_span_id
        report = json.loads((attempt / 'node-runtime/node-status.json').read_text())
        assert report['pid'] == completion['application_pid']
        assert report['function_completions'] == 1 and report['native_callback_failures'] == 0
        assert all(value == 0 for value in report['runtime_losses'].values())
        assert report['span_accounting']['received'] == report['span_accounting']['sdk_exported'] == 1
        assert report['span_accounting']['queue_dropped'] == report['span_accounting']['queue_pending'] == 0
    results.append({'plain': plain, 'application_pid': completion['application_pid'],
                    'sdk_pid': completion['sdk_pid'], 'exit_code': result.returncode,
                    'decoded_spans': len(spans), 'http_requests': len(bodies)})
    assert components == {name: hashlib.sha256((SOURCE / 'adapters/generation' / name).read_bytes()).hexdigest()
                          for name in ('node_source.py','node_source_worker.py')} | {'capture.py': hashlib.sha256((SOURCE / 'examples/otelc_capture.py').read_bytes()).hexdigest()}
receipt = {'provider_head': handoff['head'], 'components': components, 'application_launches': 2,
           'results': results, 'scope': 'explicit chunked transport supervisor prototype; no generated-suite/provider admission',
           'accepted': False}
(folder / 'receipt.json').write_text(json.dumps(receipt, indent=2) + '\n')
print(json.dumps(receipt))
