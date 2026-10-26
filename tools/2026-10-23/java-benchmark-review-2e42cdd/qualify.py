"""Retain actual Java resource windows and independently audit received metrics."""

import copy
import gzip
import hashlib
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
import json
import math
import os
from pathlib import Path
import sys
import threading

ROOT = Path(__file__).resolve().parent
SOURCE = ROOT / 'source-2e42cdd'
sys.path.insert(0, str(SOURCE))
os.chdir(SOURCE)
from otelc import benchmark
from otelc.config import Policy
from opentelemetry.proto.collector.metrics.v1.metrics_service_pb2 import ExportMetricsServiceRequest

OUTPUT = ROOT / 'actual'
OUTPUT.mkdir()
raw = OUTPUT / 'otlp'
raw.mkdir()
received = []
receipt_lock = threading.Lock()


class Handler(BaseHTTPRequestHandler):
    def do_POST(self):
        assert self.path in ('/v1/metrics', '/v1/traces')
        assert self.headers.get('Transfer-Encoding') is None
        size = int(self.headers['Content-Length'])
        assert 0 < size < 16 * 1024 * 1024
        body = self.rfile.read(size)
        assert len(body) == size
        if self.headers.get('Content-Encoding') == 'gzip':
            body = gzip.decompress(body)
        with receipt_lock:
            number = len(received)
            path = raw / f'{number:03d}.bin'
            path.write_bytes(body)
            received.append({'route': self.path, 'file': path.name,
                             'sha256': hashlib.sha256(body).hexdigest()})
        self.send_response(200)
        self.send_header('Content-Type', 'application/x-protobuf')
        self.send_header('Content-Length', '0')
        self.end_headers()

    def log_message(self, *_):
        pass


server = ThreadingHTTPServer(('127.0.0.1', 0), Handler)
worker = threading.Thread(target=server.serve_forever, daemon=True)
worker.start()
data = copy.deepcopy(Policy.load(Path('examples/otelc.toml')).data)
data['benchmark'].update(iterations=10, samples=2, warmup=1)
data['export']['endpoint'] = f'http://127.0.0.1:{server.server_port}'
try:
    report = benchmark.run(Policy.parse(data), OUTPUT / 'run', comparison_id='independent-java-resources-2e42cdd')
finally:
    server.shutdown()
    server.server_close()
    worker.join(2)
(raw / 'index.json').write_text(json.dumps(received, indent=2) + '\n')
assert report['schema_version'] == 2 and report['sdk_pid'] is None
assert report['expected_checksum'] == 41284864
rows = [json.loads(line) for line in (OUTPUT / 'run/raw.jsonl').read_text().splitlines()]
responses = [json.loads(line) for line in (OUTPUT / 'run/responses.jsonl').read_text().splitlines()]
assert len(rows) == len(responses) == len(report['process_samples']) == 10
assert {row['mode'] for row in rows} == {'plain', 'both_off', 'collection_only', 'emission_only', 'both_on'}
expected = {}
for row, response in zip(rows, responses):
    mode = row['mode']
    pid = report['pids']['plain' if mode == 'plain' else 'instrumented']
    assert row['pid'] == response['pid'] == pid
    assert row['checksum'] == response['response']['checksum'] == 41284864
    assert set(row['process_usage']) == {'application'}
    usage = row['process_usage']['application']
    before, after = usage['before'], usage['after']
    assert before['pid'] == after['pid'] == pid
    assert usage['cpu_ns'] == after['cpu_ns'] - before['cpu_ns'] >= 0
    assert usage['rss_bytes'] == max(before['rss_bytes'], after['rss_bytes']) > 0
    assert before['observed_at_unix_ns'] <= after['observed_at_unix_ns']
    for metric, value in [('otelc.benchmark.process.cpu.duration', usage['cpu_ns'] / 10 / 1_000_000_000),
                          ('otelc.benchmark.process.rss', usage['rss_bytes'])]:
        expected.setdefault((metric, mode), []).append(value)
observed = {}
for item in received:
    if item['route'] != '/v1/metrics':
        continue
    message = ExportMetricsServiceRequest.FromString((raw / item['file']).read_bytes())
    for resource in message.resource_metrics:
        for scope in resource.scope_metrics:
            for metric in scope.metrics:
                if not metric.name.startswith('otelc.benchmark.process.'):
                    continue
                assert metric.WhichOneof('data') == 'histogram'
                for point in metric.histogram.data_points:
                    attrs = {entry.key: getattr(entry.value, entry.value.WhichOneof('value')) for entry in point.attributes}
                    assert attrs['role'] == 'application' and attrs['window'] == 'batch_and_sdk_flush'
                    assert attrs['language'] == 'java' and attrs['comparison_id'] == report['comparison_id']
                    key = metric.name, attrs['mode']
                    assert key not in observed
                    values = expected[key]
                    assert point.count == len(values) == 2
                    assert math.isclose(point.sum, sum(values), rel_tol=1e-12, abs_tol=1e-12)
                    observed[key] = {'count': point.count, 'sum': point.sum, 'expected_sum': sum(values)}
assert set(observed) == set(expected) and len(observed) == 10
metadata = json.loads(Path('/Users/sclarke/github/otelc-qualification/2026-10-23/java-benchmark-resources/source-2e42cdd.json').read_text())
assert all(hashlib.sha256((SOURCE / name).read_bytes()).hexdigest() == sha for name, sha in metadata['files'].items())
proof = {'head': metadata['head'], 'actual_jvm_pids': report['pids'],
         'actual_launches': 2, 'samples': 10, 'independent_checksum': 41284864,
         'resource_histograms': [{'metric': key[0], 'mode': key[1], **value} for key, value in sorted(observed.items())],
         'raw_receipts': received, 'source_files_preserved': len(metadata['files']),
         'scope': 'functional resource-accounting and export check; no performance claim or Grafana visual check'}
(ROOT / 'resource-proof.json').write_text(json.dumps(proof, indent=2) + '\n')
print(json.dumps({'actual_launches': 2, 'samples': 10, 'matched_histograms': len(observed),
                  'proof_sha256': hashlib.sha256((ROOT / 'resource-proof.json').read_bytes()).hexdigest()}))
