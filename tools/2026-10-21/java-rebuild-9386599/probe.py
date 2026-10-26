"""Inspect the frozen Java example through its public CLI and actual OTLP."""
import hashlib
import json
import os
from pathlib import Path
import queue
import shutil
import signal
import subprocess
import sys
import threading
import time

sys.path.insert(0, '/Users/sclarke/github/oteleq/examples')
import otelc_capture as capture
from google.protobuf.json_format import MessageToDict
from opentelemetry.proto.collector.metrics.v1.metrics_service_pb2 import ExportMetricsServiceRequest
from opentelemetry.proto.collector.trace.v1.trace_service_pb2 import ExportTraceServiceRequest

ROOT = Path(__file__).resolve().parent
PROVIDER = ROOT / 'prepared-provider'
PYTHON = sys.executable


def write(path, data):
    path.write_text(json.dumps(data, indent=2) + '\n')


def digest(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()


class App:
    def __init__(self, folder, policy, plain):
        self.folder, self.stdout, self.stderr = folder, [], []
        self.lines, self.diagnostics = queue.Queue(), queue.Queue()
        self.env = {k: v for k, v in os.environ.items() if not k.startswith('OTEL_')
                    and k not in ('JAVA_TOOL_OPTIONS', '_JAVA_OPTIONS', 'JDK_JAVA_OPTIONS')}
        self.env.update(PYTHONDONTWRITEBYTECODE='1', PYTHONPATH=str(PROVIDER),
                        JAVA_HOME='/opt/homebrew/opt/openjdk@21')
        command = [PYTHON, '-m', 'otelc', '--config', str(policy), 'example', 'java']
        if plain:
            command.append('--plain')
        write(folder / 'command.json', command)
        self.process = subprocess.Popen(command, cwd=PROVIDER, env=self.env,
            stdin=subprocess.PIPE, stdout=subprocess.PIPE, stderr=subprocess.PIPE,
            text=True, bufsize=1, start_new_session=True)
        self.readers = []
        for stream, rows, channel in ((self.process.stdout, self.stdout, self.lines),
                                      (self.process.stderr, self.stderr, self.diagnostics)):
            reader = threading.Thread(target=self.read, args=(stream, rows, channel), daemon=True)
            reader.start()
            self.readers.append(reader)

    @staticmethod
    def read(stream, rows, channel):
        for line in stream:
            rows.append(line)
            channel.put(line)

    def exchange(self, line):
        self.process.stdin.write(line + '\n')
        self.process.stdin.flush()
        return capture.strict_json(self.lines.get(timeout=25))

    def control_socket(self):
        deadline = time.monotonic() + 25
        while time.monotonic() < deadline:
            line = self.diagnostics.get(timeout=25)
            if line.startswith('Control socket: '):
                path = Path(line.removeprefix('Control socket: ').strip())
                while not path.exists() and time.monotonic() < deadline:
                    time.sleep(.02)
                return path
        raise TimeoutError('No control socket')

    def control(self, path, command):
        result = subprocess.run([PYTHON, '-m', 'otelc', 'metrics', '--socket', str(path),
                                 *command.split()], cwd=PROVIDER, env=self.env,
                                capture_output=True, text=True, timeout=8, check=True)
        assert not result.stderr, result.stderr
        return capture.strict_json(result.stdout)

    def close(self):
        if self.process.poll() is None:
            self.process.stdin.write('quit\n')
            self.process.stdin.flush()
        assert self.process.wait(timeout=20) == 0
        for reader in self.readers:
            reader.join(timeout=2)
        (self.folder / 'stdout').write_text(''.join(self.stdout))
        (self.folder / 'stderr').write_text(''.join(self.stderr))

    def stop(self):
        if self.process.poll() is None:
            os.killpg(self.process.pid, signal.SIGTERM)
            self.process.wait(timeout=10)
        (self.folder / 'stdout').write_text(''.join(self.stdout))
        (self.folder / 'stderr').write_text(''.join(self.stderr))


def main():
    folder = ROOT / 'smoke'
    folder.mkdir(mode=0o700)
    server = capture.CaptureServer(max_requests=512)
    serving = threading.Thread(target=server.serve_forever, daemon=True)
    serving.start()
    policy = folder / 'policy.toml'
    text = (PROVIDER / 'examples/otelc.toml').read_text()
    text = text.replace('http://127.0.0.1:4320', f'http://127.0.0.1:{server.server_port}')
    text = text.replace('otelc-examples', 'oteleq-independent-java').replace('sample_ratio = 0.01', 'sample_ratio = 1.0')
    text = text.replace('interval_ms = 1000', 'interval_ms = 100')
    policy.write_text(text)
    try:
        for plain in (True, False):
            lane = folder / ('baseline' if plain else 'instrumented')
            lane.mkdir()
            app = App(lane, policy, plain)
            try:
                if not plain:
                    socket = app.control_socket()
                    status = app.control(socket, 'status')
                    write(lane / 'initial-status.json', status)
                    for name in ('agent.properties', 'plan.properties'):
                        shutil.copy2(socket.parent / name, lane / name)
                result = app.exchange('10')
                assert result['checksum'] == 41284864 and result['calls'] == 10
                assert type(result['elapsed_ns']) is int and result['elapsed_ns'] >= 0
                assert set(result) == {'checksum', 'calls', 'elapsed_ns'}
                assert app.exchange('throw') == {'exception': 'IllegalArgumentException', 'message': 'negative seed'}
                assert app.exchange('lifecycle') == {'construction_failed': True, 'close_failed': True}
                assert app.exchange('gc') == {'gc_requested': True}
                time.sleep(1)
                if not plain:
                    write(lane / 'final-status.json', app.control(socket, 'flush'))
                app.close()
            finally:
                app.stop()
            if plain:
                assert not server.bodies and not app.stderr
        server.require_complete()
    finally:
        server.shutdown()
        server.server_close()
        serving.join(timeout=2)
        capture.retain_http(folder, server.bodies, server.errors, server.requests)
    decoded = []
    for path, body in server.bodies:
        message = ExportTraceServiceRequest() if path == '/v1/traces' else ExportMetricsServiceRequest()
        message.ParseFromString(body)
        decoded.append({'path': path, 'message': MessageToDict(message, preserving_proto_field_name=True)})
    write(folder / 'decoded-otlp.json', decoded)
    manifest = json.loads((ROOT / 'source-manifest.json').read_text())['files_sha256']
    for name, expected in manifest.items():
        assert digest(PROVIDER / name) == expected and digest(ROOT / 'provider' / name) == expected, name
    for name, expected in json.loads((ROOT / 'prepared-products.json').read_text()).items():
        assert digest(PROVIDER / name) == expected, name
    write(folder / 'preliminary.json', {'functional_outputs_match': True, 'source_files_preserved': len(manifest),
        'http_requests': server.requests, 'scope': 'Preliminary transport/functional probe; metric/lifetime and live-state oracles pending.'})
    print(json.dumps({'http_requests': server.requests, 'functional_outputs_match': True}))


if __name__ == '__main__':
    main()
