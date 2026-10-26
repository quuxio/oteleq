"""Independently build C through the public CLI and launch with no compiler PATH."""

import hashlib
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
import json
import os
from pathlib import Path
import subprocess
import sys
import threading
import time

ROOT = Path(__file__).resolve().parent
SOURCE = Path('/Users/sclarke/github/otelc-qualification/work/native-prepared')
SDK = SOURCE / 'build/prepared-sdk'
DEST = ROOT / 'c-public-cli-01'
DEST.mkdir(mode=0o700)
index = json.loads((ROOT / 'source-index.json').read_text())

def facts(path):
    value = path.stat()
    return [hashlib.sha256(path.read_bytes()).hexdigest(), value.st_dev, value.st_ino, value.st_mode,
            value.st_uid, value.st_gid, value.st_size, value.st_mtime_ns, value.st_ctime_ns]

def inputs():
    return {'source': {name: facts(SOURCE / name) for name in index['files']},
            'sdk': {name: facts(SDK / name) for name in ('native-sdk-build.json', 'libotelc_native_runtime.dylib')}}

def write(path, value):
    path.write_text(json.dumps(value, indent=2) + '\n')

before = inputs()
assert all(before['source'][name][0] == digest for name, digest in index['files'].items())
write(DEST / 'inputs-before.json', before)
captures = []
class Handler(BaseHTTPRequestHandler):
    def do_POST(self):
        size = int(self.headers['Content-Length'])
        assert 0 < size <= 32 * 1024 * 1024 and self.path in ('/v1/traces', '/v1/metrics')
        raw = self.rfile.read(size)
        assert len(raw) == size
        (DEST / (str(len(captures)) + '.pb')).write_bytes(raw)
        captures.append((self.path, raw))
        self.send_response(200)
        self.send_header('Content-Type', 'application/x-protobuf')
        self.send_header('Content-Length', '0')
        self.end_headers()
    def log_message(self, *args):
        pass

server = ThreadingHTTPServer(('127.0.0.1', 0), Handler)
worker = threading.Thread(target=server.serve_forever, daemon=True)
worker.start()
application = DEST / 'application'
application.mkdir()
source = application / 'main.c'
source.write_text('__attribute__((noinline)) int workload(int x){return x+7;}\nint main(void){return workload(10)==17?0:1;}\n')
source_before = facts(source)
policy = DEST / 'policy.toml'
policy.write_text('schema_version=3\nlanguages=["c","cpp"]\n[resource]\nservice_name="native-c-review"\n'
    '[sources]\ninclude=["**"]\n[functions]\ninclude=["workload*"]\n'
    '[metrics]\ncollection=false\nemission=false\n[traces]\nenabled=true\nsample_ratio=1.0\n'
    '[export]\nendpoint="http://127.0.0.1:' + str(server.server_port) + '"\ninterval_ms=60000\ntimeout_ms=1000\nshutdown_timeout_ms=5000\n')
environment = {key: value for key, value in os.environ.items() if not key.startswith(('OTEL', 'OTELEQ', 'GH_', 'GITHUB_', 'AWS_', 'SONAR_'))}
environment.update(OTELC_PYTHON=sys.executable, PYTHONDONTWRITEBYTECODE='1', LLVM_CONFIG='/opt/homebrew/opt/llvm@22/bin/llvm-config')
cli = [str(SOURCE / 'bin/quux-otelc')]

def execute(label, arguments, *, no_tools=False):
    command = [*cli, *map(str, arguments)]
    write(DEST / (label + '.command.json'), command)
    selected = environment | ({'PATH': '/no-tools'} if no_tools else {})
    result = subprocess.run(command, env=selected, capture_output=True, timeout=180)
    (DEST / (label + '.stdout')).write_bytes(result.stdout)
    (DEST / (label + '.stderr')).write_bytes(result.stderr)
    assert result.returncode == 0, (label, result.returncode, result.stderr)
    return result.stdout

started = time.monotonic()
state = {'status': 'running', 'head': index['head'], 'applications': 0}
write(DEST / 'status.json', state)
try:
    descriptor = json.loads(execute('protocols', ['--config', '/no-config', 'native-protocols'], no_tools=True))
    assert descriptor == {'schema_version': 1, 'kind': 'otelc.native.protocols', 'profile': 'native-owned-v1',
        'build': 2, 'request': 1, 'plan': 1, 'prepared': 1, 'command': 1, 'execution': 1,
        'host_release': 1, 'gate': 1, 'embedded_sdk': True, 'source_complete': False}
    built = json.loads(execute('build', ['--config', policy, 'native-build', '--language', 'c', '--root', application,
        '--source', 'main.c', '--output', DEST / 'build', '--sdk-build', SDK]))
    assert built['schema_version'] == 2 and built['profile'] == 'native-owned-v1'
    for plain in (True, False):
        runtime = DEST / ('plain' if plain else 'woven')
        output = execute(runtime.name, ['--config', policy, 'native-run', '--build', DEST / 'build', '--runtime', runtime,
                                       *(['--plain'] if plain else [])], no_tools=True)
        assert output == b''
        final = json.loads((runtime / 'native-execution.json').read_text())
        assert final['process_exit_code'] == final['supervisor_exit_code'] == 0
        assert final['released'] is final['inputs_rechecked'] is True and final['failures'] == {}
        assert final['exec_verified'] is final['source_complete'] is False
        if plain:
            assert final['sdk_health'] is None and captures == []
        else:
            assert final['sdk_health']['language'] == 'c' and final['sdk_health']['function_accounting']['ended'] == '1'
        state['applications'] += 1
    from opentelemetry.proto.collector.trace.v1.trace_service_pb2 import ExportTraceServiceRequest
    spans = []
    for route, raw in captures:
        assert route == '/v1/traces'
        request = ExportTraceServiceRequest.FromString(raw)
        spans.extend(span for resource in request.resource_spans for scope in resource.scope_spans for span in scope.spans)
    assert len(spans) == 1 and spans[0].name == 'main.c::workload' and not spans[0].parent_span_id
    assert facts(source) == source_before
    state.update(status='passed', received_spans=len(spans), compiler_free_launch=True)
except Exception as error:
    state.update(status='failed', error=repr(error))
finally:
    server.shutdown(); server.server_close(); worker.join(2)
    after = inputs()
    write(DEST / 'inputs-after.json', after)
    state.update(source_preserved=before['source'] == after['source'], sdk_preserved=before['sdk'] == after['sdk'],
                 seconds=round(time.monotonic() - started, 3))
    if before != after:
        state['status'] = 'failed'
    write(DEST / 'status.json', state)
    print(json.dumps(state, indent=2), flush=True)
    raise SystemExit(0 if state['status'] == 'passed' else 1)
