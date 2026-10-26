"""Independently check the frozen internal Java example and live metric states."""
import hashlib
import json
import os
from pathlib import Path
import re
import shutil
import socket
import stat
import subprocess
import sys
import threading
import time

sys.path.insert(0, '/Users/sclarke/github/oteleq/examples')
import otelc_capture as capture
from google.protobuf.json_format import MessageToDict
from opentelemetry.proto.collector.metrics.v1.metrics_service_pb2 import ExportMetricsServiceRequest
from opentelemetry.proto.collector.trace.v1.trace_service_pb2 import ExportTraceServiceRequest
from java_process import App

ROOT = Path(__file__).resolve().parent
PROVIDER = ROOT / 'prepared-provider'
PHASES = [('startup_off', None, False, False),
          ('collection_only', 'collection on', True, False),
          ('both_on', 'emission on', True, True),
          ('emission_only', 'collection off', False, True),
          ('combined_off', 'off', False, False),
          ('combined_on', 'on', True, True)]


def write(path: Path, value: object) -> None:
    path.write_text(json.dumps(value, indent=2) + '\n')


def digest(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def products() -> dict:
    classes = PROVIDER / 'build/examples/java'
    return {p.relative_to(classes).as_posix(): {'sha256': digest(p), 'mtime_ns': p.stat().st_mtime_ns,
            'inode': p.stat().st_ino} for p in classes.rglob('*.class')}


def control_path(app: App) -> Path:
    deadline = time.monotonic() + 25
    while time.monotonic() < deadline:
        line = app.receive(app.diagnostics)
        if line.startswith('Control socket: '):
            path = Path(line.removeprefix('Control socket: ').strip())
            while not path.exists() and time.monotonic() < deadline:
                time.sleep(.02)
            mode = path.lstat()
            assert stat.S_ISSOCK(mode.st_mode) and mode.st_uid == os.getuid() and mode.st_mode & 0o077 == 0
            assert path.parent.stat().st_mode & 0o077 == 0
            return path
    raise TimeoutError('Control socket unavailable')


def raw_status(path: Path) -> dict:
    with socket.socket(socket.AF_UNIX) as client:
        client.settimeout(3)
        client.connect(str(path))
        client.sendall(b'status\n')
        data = bytearray()
        while not data.endswith(b'\n'):
            piece = client.recv(1024)
            assert piece and len(data) + len(piece) <= 4096
            data.extend(piece)
    return capture.strict_json(data)


def check_status(value: dict, *, collection: bool, emission: bool,
                 completed: int, require_lifetime: bool) -> None:
    assert set(value) == {'schema_version', 'pid', 'collection', 'emission', 'in_flight_exports',
                          'effective_emission_off', 'completed', 'lifetime_lost'}
    for key in ('schema_version', 'pid', 'in_flight_exports', 'completed'):
        assert type(value[key]) is int and value[key] >= 0
    assert value['schema_version'] == 1 and value['pid'] > 0
    assert type(value['collection']) is bool and value['collection'] == collection
    assert type(value['emission']) is bool and value['emission'] == emission
    assert value['completed'] == completed
    assert type(value['effective_emission_off']) is bool
    assert value['effective_emission_off'] == (not emission and value['in_flight_exports'] == 0)
    if require_lifetime:
        assert type(value['lifetime_lost']) is int and value['lifetime_lost'] == 0
    else:
        assert value['lifetime_lost'] is None or type(value['lifetime_lost']) is int and value['lifetime_lost'] == 0


def process_identity(app: App, pid: int) -> dict:
    parent = int(subprocess.check_output(['/bin/ps', '-p', str(pid), '-o', 'ppid='], text=True))
    command = subprocess.check_output(['/bin/ps', '-ww', '-p', str(pid), '-o', 'command='], text=True).strip()
    assert pid == app.process.pid or parent == app.process.pid
    assert str(PROVIDER / 'build/examples/java') in command and command.endswith('examples.BenchmarkApp')
    assert '/java ' in command and '-javaagent:' in command
    return {'application_pid': pid, 'launcher_pid': app.process.pid, 'parent_pid': parent, 'command': command}


def exchange(app: App) -> list[dict]:
    result = app.exchange('10')
    assert set(result) == {'checksum', 'calls', 'elapsed_ns'}
    assert type(result['checksum']) is int and result['checksum'] == 41284864
    assert type(result['calls']) is int and result['calls'] == 10
    assert type(result['elapsed_ns']) is int and result['elapsed_ns'] >= 0
    thrown = app.exchange('throw')
    assert thrown == {'exception': 'IllegalArgumentException', 'message': 'negative seed'}
    life = app.exchange('lifecycle')
    assert life == {'construction_failed': True, 'close_failed': True} and all(type(v) is bool for v in life.values())
    gc = app.exchange('gc')
    assert gc == {'gc_requested': True} and type(gc['gc_requested']) is bool
    return [result, thrown, life, gc]


def frames(server: capture.CaptureServer) -> list[dict]:
    rows = []
    for path, body in tuple(server.bodies):
        message = ExportTraceServiceRequest() if path == '/v1/traces' else ExportMetricsServiceRequest()
        message.ParseFromString(body)
        rows.append({'path': path, 'message': MessageToDict(message, preserving_proto_field_name=True)})
    return rows


def app_spans(server: capture.CaptureServer) -> list[dict]:
    return [span for frame in frames(server) if frame['path'] == '/v1/traces'
            for resource in frame['message'].get('resource_spans', [])
            for scope in resource.get('scope_spans', []) for span in scope.get('spans', [])]


def policy(folder: Path, server: capture.CaptureServer, name: str, *, sample_zero=False, excluded=False) -> Path:
    text = (PROVIDER / 'examples/otelc.toml').read_text()
    text = text.replace('http://127.0.0.1:4320', f'http://127.0.0.1:{server.server_port}')
    text = text.replace('otelc-examples', 'oteleq-independent-' + name)
    text = text.replace('sample_ratio = 0.01', 'sample_ratio = ' + ('0.0' if sample_zero else '1.0'))
    text = text.replace('interval_ms = 1000', 'interval_ms = 100')
    if not sample_zero and not excluded:
        text = text.replace('collection = true', 'collection = false').replace('emission = true', 'emission = false')
    if excluded:
        text = text.replace('exclude = ["**/generated/**"]', 'exclude = ["**"]')
    path = folder / 'policy.toml'
    path.write_text(text)
    return path


def command(app: App, path: Path, operation: str, collection: bool, emission: bool, completed: int) -> dict:
    value = app.cli(['metrics', '--socket', str(path), *operation.split()])
    check_status(value, collection=collection, emission=emission, completed=completed, require_lifetime=False)
    independent = raw_status(path)
    for key in ('pid', 'collection', 'emission', 'completed', 'lifetime_lost'):
        assert value[key] == independent[key]
    if not emission:
        deadline = time.monotonic() + 5
        while not independent['effective_emission_off'] and time.monotonic() < deadline:
            time.sleep(.02)
            independent = raw_status(path)
        assert independent['effective_emission_off']
    return independent


def run_case(root: Path, kind: str) -> None:
    folder = root / kind
    folder.mkdir()
    server = capture.CaptureServer(max_requests=1024)
    serving = threading.Thread(target=server.serve_forever, daemon=True)
    serving.start()
    path = policy(folder, server, kind, sample_zero=kind == 'unsampled', excluded=kind == 'excluded')
    app = App(folder, PROVIDER, path, plain=kind == 'baseline')
    records, completed = [], 0
    try:
        if kind != 'baseline':
            control = control_path(app)
            initial = raw_status(control)
            identity = process_identity(app, initial['pid'])
            write(folder / 'process.json', identity)
            for name in ('agent.properties', 'plan.properties'):
                shutil.copy2(control.parent / name, folder / name)
            frozen = products()
        phases = PHASES if kind in ('baseline', 'live') else [(kind, None, True, True)]
        for index, (name, operation, collecting, emitting) in enumerate(phases):
            before = time.time_ns()
            status, body_index = None, len(server.bodies)
            if kind != 'baseline':
                status = command(app, control, operation or 'status', collecting, emitting, completed)
                assert process_identity(app, status['pid']) == identity and products() == frozen
                body_index = len(server.bodies)
            outputs = exchange(app)
            if kind != 'baseline':
                completed += 11 if collecting and kind != 'excluded' else 0
                status = command(app, control, 'flush', collecting, emitting, completed)
                check_status(status, collection=collecting, emission=emitting, completed=completed,
                             require_lifetime=kind != 'excluded')
                expected_spans = 34 * (index + 1) if kind == 'live' else 0
                deadline = time.monotonic() + (8 if expected_spans else 1)
                while time.monotonic() < deadline and (len(app_spans(server)) < expected_spans or not expected_spans):
                    time.sleep(.05)
                assert len(app_spans(server)) == expected_spans
                if not emitting:
                    assert not any(route == '/v1/metrics' for route, _ in server.bodies[body_index:])
                assert products() == frozen and process_identity(app, status['pid']) == identity
            records.append({'name': name, 'collection': collecting, 'emission': emitting,
                            'start_ns': before, 'end_ns': time.time_ns(), 'outputs': outputs,
                            'completed': completed, 'status': status, 'body_index': body_index})
            write(folder / 'phases.json', records)
        app.close()
        assert len(app.stdout) == 4 * len(phases)
        if kind == 'baseline':
            assert not server.bodies and not app.stderr
        if kind in ('unsampled', 'excluded'):
            assert not app_spans(server)
        server.require_complete()
    finally:
        app.stop()
        server.shutdown()
        server.server_close()
        serving.join(timeout=2)
        capture.retain_http(folder, server.bodies, server.errors, server.requests)
        write(folder / 'decoded-otlp.json', frames(server))
        write(folder / 'phases.json', records)


def main() -> None:
    if sys.flags.optimize:
        raise ValueError('Qualification requires assertions')
    root = ROOT / 'live-v1'
    root.mkdir(mode=0o700)
    for kind in ('baseline', 'live', 'unsampled', 'excluded'):
        run_case(root, kind)
    write(root / 'capture-complete.json', {'scope': 'Capture completed; full offline metric/span oracle pending',
        'cases': ['baseline', 'live', 'unsampled', 'excluded'], 'same_pid_states': 6})


if __name__ == '__main__':
    main()
