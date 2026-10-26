"""Check all six recorded Node/compiler profiles with the fixed supervisor."""

import hashlib
import json
from pathlib import Path
import sys

SOURCE = Path('/Users/sclarke/github/oteleq-qualification/work/oteleq-node-source-provider')
PROOF = Path(__file__).resolve().parent
sys.path[:0] = [str(SOURCE / 'adapters/generation'), str(SOURCE / 'examples')]
import generation
import node_source
import otelc_capture as capture
from opentelemetry.proto.collector.trace.v1.trace_service_pb2 import ExportTraceServiceRequest

HANDOFF = json.loads(Path('/Users/sclarke/github/otelc-qualification/2026-10-22/node-provider-2b3aa91/handoff.json').read_text())
ROOT = Path(HANDOFF['provider'])
DESTINATION = PROOF / 'supervisor-six-profile-matrix'
BOOTSTRAP = "import runpy,sys;sys.path[:0]=sys.argv[1:3];script=sys.argv[3];sys.argv=sys.argv[3:];runpy.run_path(script,run_name='__main__')"


def digest(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()


def run_profile(tool, language, compiler, suffix):
    name = tool['version'].split('.')[0] + '-' + language + '-' + compiler
    folder = DESTINATION / name
    folder.mkdir(mode=0o700)
    rows = []
    for plain in (True, False):
        attempt = folder / ('plain' if plain else 'instrumented')
        attempt.mkdir(mode=0o700)
        project = attempt / 'project'
        project.mkdir(mode=0o700)
        entry = project / ('app.' + suffix)
        annotation = ':number' if language == 'typescript' else ''
        text = 'let total=10; function add(value' + annotation + ')' + annotation + '{total+=value;return total;} const before=total; const result=add(7); console.log(JSON.stringify({before,result,after:total}));\n'
        entry.write_text(text)
        service = 'oteleq-node-matrix-' + name
        selected = {'language': language, 'node_backend': node_source.SOURCE,
                    'path': entry.name, 'otelc_function': 'app.add'}
        with capture.receiver(allow_chunked=True, response_path=attempt / 'http-responses.json') as (endpoint, bodies, errors):
            config = attempt / 'policy.toml'
            config.write_text(node_source.policy(selected, endpoint, service))
            request = {'schema_version': 1, 'provider': str(ROOT), 'project': str(project),
                       'entry': str(entry), 'runtime': str(attempt / 'node-runtime'), 'policy': str(config),
                       'node': tool['node'], 'language': language, 'compiler': compiler,
                       'plain': plain, 'gc_fixture': False, 'timeout_ms': 60000}
            request_path = attempt / 'node-source-request.json'
            request_path.write_text(json.dumps(request, indent=2) + '\n')
            argv = [sys.executable, '-I', '-B', '-c', BOOTSTRAP, str(SOURCE / 'adapters/generation'),
                    str(SOURCE / 'examples'), str(SOURCE / 'adapters/generation/node_source_worker.py'), str(request_path)]
            environment = capture.environment(project, {'javascript': Path(tool['node'])}, service, ROOT)
            environment['TMPDIR'] = str(attempt)
            result = generation.execute(argv, project, environment, attempt, timeout=60, record_process=True)
        capture.retain_http(attempt, bodies, errors)
        assert result.returncode == 0, (name, plain, result.returncode, result.stderr.decode())
        assert result.stdout == b'{"before":10,"result":17,"after":17}\n' and not result.stderr
        assert entry.read_text() == text and not errors
        completed = json.loads((attempt / 'node-source-completion.json').read_text())
        assert completed['application_returncode'] == 0 and completed['inputs_verified'] is True
        spans = [span for path, body in bodies if path == capture.TRACE_PATH
                 for resource in ExportTraceServiceRequest.FromString(body).resource_spans
                 for scope in resource.scope_spans for span in scope.spans]
        if plain:
            assert not bodies and completed['sdk_pid'] is None and completed['sdk_exited'] is None
        else:
            assert completed['phase'] == 'closed' and completed['sdk_exited'] is True
            assert len(spans) == 1 and spans[0].name == 'app.add' and not spans[0].parent_span_id
            report = json.loads((attempt / 'node-runtime/node-status.json').read_text())
            assert report['pid'] == completed['application_pid']
            assert report['function_completions'] == 1 and report['native_callback_failures'] == 0
            assert all(type(value) is int and value == 0 for value in report['runtime_losses'].values())
            assert report['span_accounting']['received'] == report['span_accounting']['sdk_exported'] == 1
            assert report['span_accounting']['queue_dropped'] == report['span_accounting']['queue_pending'] == 0
        row = {'plain': plain, 'application_pid': completed['application_pid'], 'sdk_pid': completed['sdk_pid'],
               'decoded_spans': len(spans), 'http_requests': len(bodies), 'exit_code': result.returncode}
        rows.append(row)
        (folder / ('verified-' + ('plain' if plain else 'instrumented') + '.json')).write_text(json.dumps(row, indent=2) + '\n')
    return {'name': name, 'rows': rows}


if __name__ == '__main__':
    assert Path(sys.executable).resolve() == Path(HANDOFF['python_tool']['path']).resolve()
    assert digest(Path(sys.executable)) == HANDOFF['python_tool']['sha256']
    DESTINATION.mkdir(mode=0o700)
    components = {name: digest(SOURCE / name) for name in ('examples/otelc_capture.py',
        'adapters/generation/generation.py', 'adapters/generation/node_source.py', 'adapters/generation/node_source_worker.py')}
    (DESTINATION / 'source-before.json').write_text(json.dumps(components, indent=2) + '\n')
    results = []
    for tool in HANDOFF['node_tools']:
        assert digest(Path(tool['node'])) == tool['sha256']
        for language, compiler, suffix in [('javascript', 'native', 'cjs'), ('typescript', 'native', 'cts'), ('typescript', 'api', 'mts')]:
            results.append(run_profile(tool, language, compiler, suffix))
            assert components == {name: digest(SOURCE / name) for name in components}
    receipt = {'provider_head': HANDOFF['head'], 'consumer_base': '891de0f', 'components': components,
               'profiles': results, 'application_launches': 12, 'python_sha256': digest(Path(sys.executable)),
               'scope': 'six-profile supervisor/transport prototype; not generated-suite or provider admission', 'accepted': False}
    (DESTINATION / 'receipt.json').write_text(json.dumps(receipt, indent=2) + '\n')
    print(json.dumps({'profiles': len(results), 'application_launches': 12, 'accepted': False}))
