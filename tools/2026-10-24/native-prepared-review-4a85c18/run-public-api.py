"""Exercise the unmodified held native API with independent OS and OTLP checks."""

from datetime import datetime, timezone
import hashlib
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
import json
import math
import os
from pathlib import Path
import select
import signal
import stat
import subprocess
import sys
import threading
import time
from unittest.mock import patch

ROOT = Path(__file__).resolve().parent
SOURCE = Path('/Users/sclarke/github/otelc-qualification/work/native-prepared')
SDK = SOURCE / 'build/prepared-sdk'
INDEX = json.loads((ROOT / 'source-index.json').read_text())
DEST = ROOT / 'public-api-01'
DEST.mkdir(mode=0o700)
sys.dont_write_bytecode = True


def write(path, value):
    path.write_text(json.dumps(value, indent=2) + '\n')


def facts(path):
    value = path.stat()
    return [hashlib.sha256(path.read_bytes()).hexdigest(), value.st_dev, value.st_ino, value.st_mode,
            value.st_uid, value.st_gid, value.st_size, value.st_mtime_ns, value.st_ctime_ns]


def inputs():
    return {'source': {name: facts(SOURCE / name) for name in INDEX['files']},
            'sdk': {name: facts(SDK / name) for name in ('native-sdk-build.json', 'libotelc_native_runtime.dylib')}}


before = inputs()
assert all(before['source'][name][0] == digest for name, digest in INDEX['files'].items())
assert before['sdk']['native-sdk-build.json'][0] == 'e7b594bbc6a9a46e825a4d279131f2de94b3d9692e0bf9b9d00d114507e6cbde'
assert before['sdk']['libotelc_native_runtime.dylib'][0] == 'c8d493fa8746b4852f02151a87c3d822f8e91eb5b946a0f12b476fced0dc0e8a'
write(DEST / 'inputs-before.json', before)
sys.path.insert(0, str(SOURCE))
from otelc import control, native_build, prepared_native as prepared
from otelc.config import Policy
from opentelemetry.proto.collector.metrics.v1.metrics_service_pb2 import ExportMetricsServiceRequest
from opentelemetry.proto.collector.trace.v1.trace_service_pb2 import ExportTraceServiceRequest


class Capture:
    def __init__(self, folder):
        self.folder, self.bodies = folder, []
        folder.mkdir()
        owner = self
        class Handler(BaseHTTPRequestHandler):
            def do_POST(self):
                size = int(self.headers['Content-Length'])
                assert 0 < size <= 32 * 1024 * 1024 and self.path in ('/v1/traces', '/v1/metrics')
                raw = self.rfile.read(size)
                assert len(raw) == size and not self.headers.get('Content-Encoding')
                name = str(len(owner.bodies)) + '.pb'
                (folder / name).write_bytes(raw)
                owner.bodies.append((self.path, raw))
                self.send_response(200)
                self.send_header('Content-Type', 'application/x-protobuf')
                self.send_header('Content-Length', '0')
                self.end_headers()
            def log_message(self, *args):
                pass
        self.server = ThreadingHTTPServer(('127.0.0.1', 0), Handler)
        self.thread = threading.Thread(target=self.server.serve_forever, daemon=True)
        self.thread.start()

    def close(self):
        self.server.shutdown()
        self.server.server_close()
        self.thread.join(2)
        write(self.folder / 'bodies.json', [{'path': path, 'file': str(index) + '.pb',
              'sha256': hashlib.sha256(raw).hexdigest()} for index, (path, raw) in enumerate(self.bodies)])


APP = r'''#include <cstdio>
#include <cstdlib>
#include <stdexcept>
#include <unistd.h>
__attribute__((noinline)) int workload(int x){if(x<0)throw std::runtime_error("original");return x+7;}
struct Item{Item(){const char*p=std::getenv("CTOR_MARKER");if(p){FILE*f=std::fopen(p,"w");if(f){std::fputs("ctor\n",f);std::fclose(f);}}workload(1);}};Item item;
int main(int argc,char**argv){std::printf("ready %ld %s\n",(long)getpid(),argc>1?argv[1]:"none");std::fflush(stdout);int x;while(std::scanf("%d",&x)==1){if(x==99)return 23;try{std::printf("%d\n",workload(x));}catch(const std::exception&e){std::printf("%s\n",e.what());}std::fflush(stdout);}return 0;}
'''
application = DEST / 'application'
application.mkdir()
(application / 'main.cpp').write_text(APP)
application_before = facts(application / 'main.cpp')
base_policy = {'schema_version': 3, 'languages': ['c', 'cpp'], 'resource': {'service_name': 'native-api-review'},
    'sources': {'include': ['**']}, 'functions': {'include': ['workload*']},
    'metrics': {'collection': False, 'emission': False}, 'traces': {'enabled': True, 'sample_ratio': 1.0},
    'export': {'endpoint': 'http://127.0.0.1:1', 'interval_ms': 60000, 'timeout_ms': 1000, 'shutdown_timeout_ms': 5000}}
build = DEST / 'build'
state = {'status': 'running', 'head': INDEX['head'], 'started': datetime.now(timezone.utc).isoformat(), 'applications': []}
write(DEST / 'status.json', state)


def line(process):
    assert select.select([process.stdout], [], [], 15)[0], 'application output timed out'
    value = process.stdout.readline()
    assert value, 'application output ended'
    return value


def wait_ready(runtime, process):
    deadline = time.monotonic() + 15
    while True:
        assert process.poll() is None and time.monotonic() < deadline, 'supervisor ended or readiness expired'
        try:
            return prepared.files.read(runtime / 'native-application-start.json')[0]
        except (FileNotFoundError, prepared.files.PublicationPending):
            time.sleep(.005)


def kernel(pid):
    assert type(pid) is int and pid > 1
    raw = subprocess.check_output(['/bin/ps', '-p', str(pid), '-o', 'ppid='], timeout=5)
    return {'pid': pid, 'parent_pid': int(raw.strip()), 'process_group': os.getpgid(pid), 'session': os.getsid(pid)}


def decode(capture, function, spans_expected, calls_expected):
    spans, counts, metrics = [], {}, []
    for route, raw in capture.bodies:
        if route == '/v1/traces':
            request = ExportTraceServiceRequest.FromString(raw)
            for resource in request.resource_spans:
                assert any(item.key == 'service.name' and item.value.string_value == 'native-api-review' for item in resource.resource.attributes)
                for scope in resource.scope_spans:
                    assert scope.scope.name == 'io.quux.otelc.native'
                    spans.extend(scope.spans)
        else:
            request = ExportMetricsServiceRequest.FromString(raw)
            for resource in request.resource_metrics:
                for scope in resource.scope_metrics:
                    assert scope.scope.name == 'io.quux.otelc.native'
                    metrics.extend(scope.metrics)
    assert len(spans) == spans_expected and all(span.name == function and not span.parent_span_id for span in spans)
    assert len({(span.trace_id, span.span_id) for span in spans}) == spans_expected
    for span in spans:
        assert len(span.trace_id) == 16 and any(span.trace_id) and len(span.span_id) == 8 and any(span.span_id)
        assert 0 < span.start_time_unix_nano <= span.end_time_unix_nano
    for metric in metrics:
        kind = metric.WhichOneof('data')
        assert metric.name in ('otelc.function.calls', 'otelc.function.errors', 'otelc.function.duration')
        assert kind == ('histogram' if metric.name.endswith('duration') else 'sum')
        for point in getattr(metric, kind).data_points:
            attrs = {item.key: item.value.string_value for item in point.attributes}
            assert attrs.get('function') == function
            count = point.count if kind == 'histogram' else point.as_int
            counts[metric.name] = max(counts.get(metric.name, 0), count)
            if kind == 'histogram':
                assert sum(point.bucket_counts) == point.count and math.isfinite(point.sum) and point.sum >= 0
    if calls_expected:
        assert counts.get('otelc.function.calls') == calls_expected
        assert counts.get('otelc.function.duration') == calls_expected
        assert counts.get('otelc.function.errors') == 1
    return {'spans': len(spans), 'metric_counts': counts}


def exercise(name, *, plain, outcome='normal'):
    folder = DEST / name
    folder.mkdir()
    capture = Capture(folder / 'otlp')
    data = json.loads(json.dumps(base_policy))
    data['export']['endpoint'] = 'http://127.0.0.1:' + str(capture.server.server_port)
    policy = Policy.parse(data)
    runtime, marker = folder / 'runtime', folder / 'constructor.marker'
    with patch.object(subprocess, 'Popen', side_effect=AssertionError('preparation launched a process')):
        prepared.prepare(policy, runtime, build_directory=build, arguments=('literal $value; *',), plain=plain,
                         wait_ms=2000 if outcome == 'timeout' else 30000)
        command = prepared.command(runtime)
    assert command == [sys.executable, '-I', '-S', str(SOURCE / 'otelc/native_supervisor.py'), str(runtime)]
    process = subprocess.Popen(command, env={**os.environ, 'PATH': '/no-tools', 'CTOR_MARKER': str(marker)},
        stdin=subprocess.PIPE, stdout=subprocess.PIPE, stderr=subprocess.PIPE, start_new_session=True, bufsize=0)
    app = None
    try:
        app = wait_ready(runtime, process)
        assert kernel(process.pid) == {'pid': process.pid, 'parent_pid': os.getpid(), 'process_group': process.pid, 'session': process.pid}
        assert kernel(app['pid']) == {key: app[key] for key in ('pid', 'parent_pid', 'process_group', 'session')}
        assert app['parent_pid'] == process.pid and app['pid'] != process.pid
        assert not marker.exists() and not (runtime / 'app/control.json').exists()
        assert not select.select([process.stdout], [], [], 0)[0]
        write(folder / 'observed-kernel.json', {'supervisor': kernel(process.pid), 'application': kernel(app['pid'])})
        if outcome == 'wrong-release':
            prepared.files.write(runtime / 'native-host-release.json', {'schema_version': 1, 'pid': app['pid'] + 1})
        elif outcome == 'interrupt':
            process.send_signal(signal.SIGTERM)
        elif outcome != 'timeout':
            prepared.release(runtime, pid=app['pid'], supervisor_pid=process.pid)
            assert line(process) == f'ready {app["pid"]} literal $value; *\n'.encode()
            assert marker.read_text() == 'ctor\n'
            if outcome == 'kill':
                os.kill(app['pid'], signal.SIGKILL)
            elif outcome == 'nonzero':
                process.stdin.write(b'99\n'); process.stdin.flush()
            else:
                endpoint = runtime / 'app/control.json'
                if not plain:
                    control.wait_ready(endpoint, app['pid'])
                transitions = []
                for index, flags in enumerate(((False, False), (False, True), (True, False), (True, True))):
                    if not plain:
                        before_status = control.request(endpoint, 'status')
                        selected = control.request(endpoint, 'collection ' + ('on' if flags[0] else 'off'))
                        assert selected['collection'] is flags[0] and selected['emission'] is before_status['emission']
                        selected = control.request(endpoint, 'emission ' + ('on' if flags[1] else 'off'))
                        assert selected['collection'] is flags[0] and selected['emission'] is flags[1]
                        assert selected['pid'] == app['pid']
                    cursor = len(capture.bodies)
                    process.stdin.write(b'-1\n' if index == 2 else b'10\n'); process.stdin.flush()
                    assert line(process) == (b'original\n' if index == 2 else b'17\n')
                    if not plain:
                        control.request(endpoint, 'flush')
                        if not all(flags):
                            assert not any(route == '/v1/metrics' for route, _ in capture.bodies[cursor:])
                        transitions.append({'flags': flags, 'status': selected, 'health': control.request(endpoint, 'health')})
                write(folder / 'transitions.json', transitions)
        process.stdin.close(); process.stdin = None
        code = process.wait(timeout=15)
        out, err = process.communicate(timeout=5)
        assert out == err == b''
        expected = {'normal': 0, 'wrong-release': 1, 'timeout': 1, 'interrupt': 128 + signal.SIGTERM,
                    'nonzero': 23, 'kill': 128 + signal.SIGKILL}[outcome]
        assert code == expected, (name, code, expected)
        final = prepared.execution(runtime, supervisor_pid=process.pid, parent_pid=os.getpid(), returncode=code)
        assert final['exec_verified'] is final['source_complete'] is False
        released = outcome in ('normal', 'nonzero', 'kill')
        assert final['released'] is released and marker.exists() is released
        if outcome in ('normal', 'nonzero'):
            assert not final['failures'] and final['inputs_rechecked']
        if plain:
            assert final['sdk_health'] is None and not capture.bodies
        elif outcome == 'kill':
            assert final['sdk_health'] is None and final['process_exit_code'] == -signal.SIGKILL
            assert final['failures'] and not final['inputs_rechecked']
        else:
            assert final['sdk_health']['lifecycle'] == {'flush': 'succeeded', 'shutdown': 'succeeded'}
            assert final['sdk_health']['function_accounting']['ended'] == '5'
            final['independent_receipt'] = decode(capture, 'main.cpp::workload(int)', 5, 2)
        write(folder / 'checked-final.json', final)
        state['applications'].append({'case': name, 'pid': app['pid'], 'supervisor_pid': process.pid, 'exit': code})
        write(DEST / 'status.json', state)
        try:
            os.kill(app['pid'], 0)
        except ProcessLookupError:
            pass
        else:
            raise AssertionError('application was not reaped')
    finally:
        if process.poll() is None:
            process.terminate()
            try:
                process.wait(timeout=5)
            except subprocess.TimeoutExpired:
                if app is not None and os.getpgid(app['pid']) == app['pid']:
                    os.killpg(app['pid'], signal.SIGKILL)
                process.kill(); process.wait(timeout=3)
        process.communicate(timeout=5)
        capture.close()


started = time.monotonic()
try:
    native_build.build(Policy.parse(base_policy), 'cpp', application, [Path('main.cpp')], build, sdk_directory=SDK)
    for name, plain, outcome in (('plain', True, 'normal'), ('woven', False, 'normal'),
            ('wrong-release', True, 'wrong-release'), ('timeout', True, 'timeout'),
            ('interrupted', True, 'interrupt'), ('nonzero', True, 'nonzero'), ('killed', False, 'kill')):
        exercise(name, plain=plain, outcome=outcome)
    assert facts(application / 'main.cpp') == application_before
    state['status'] = 'passed'
except Exception as error:
    state.update(status='failed', error=repr(error))
finally:
    after = inputs()
    write(DEST / 'inputs-after.json', after)
    state.update(source_preserved=before['source'] == after['source'], sdk_preserved=before['sdk'] == after['sdk'],
                 seconds=round(time.monotonic() - started, 3), finished=datetime.now(timezone.utc).isoformat())
    if before != after:
        state['status'] = 'failed'
    write(DEST / 'status.json', state)
    print(json.dumps(state, indent=2), flush=True)
    raise SystemExit(0 if state['status'] == 'passed' else 1)
