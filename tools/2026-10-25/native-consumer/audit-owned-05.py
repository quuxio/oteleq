"""Correct a retained-only API-batch versus HTTP-request audit; start no processes."""
import hashlib
import json
from pathlib import Path
import time

from opentelemetry.proto.collector.metrics.v1.metrics_service_pb2 import ExportMetricsServiceRequest
from opentelemetry.proto.collector.trace.v1.trace_service_pb2 import ExportTraceServiceRequest

BASE = Path(__file__).resolve().parent
ROOT = BASE / 'owned-probe-05'
AUDIT = BASE / 'owned-probe-05-audit-01'; AUDIT.mkdir(mode=0o700)


def facts(path):
    info = path.stat()
    return [hashlib.sha256(path.read_bytes()).hexdigest(), info.st_dev, info.st_ino, info.st_mode,
            info.st_size, info.st_mtime_ns, info.st_ctime_ns]


def evidence():
    return {str(path): facts(path) for path in ROOT.rglob('*') if path.is_file()}


before = evidence(); (AUDIT / 'evidence-before.json').write_text(json.dumps(before, indent=2) + '\n')
started = time.monotonic()
results = []
for plain in (True, False):
    label = 'plain' if plain else 'woven'
    runtime = ROOT / ('runtime-' + label)
    output = ROOT / ('execution-' + label)
    def read(path):
        return json.loads(path.read_bytes())
    start = read(runtime / 'oteleq-native-start.json')
    final = read(runtime / 'native-execution.json')
    host = read(runtime / 'oteleq-native-finish.json')
    pid = start['application']['pid']; supervisor = start['supervisor']['pid']
    assert start['application'] == {'pid': pid, 'parent_pid': supervisor, 'process_group': pid, 'session': pid}
    assert start['supervisor']['process_group'] == start['supervisor']['session'] == supervisor
    assert final['process_exit_code'] == final['supervisor_exit_code'] == 0 and final['failures'] == {}
    assert final['released'] is True and final['inputs_rechecked'] is True and final['exec_verified'] is False
    assert final['application']['pid'] == host['application_pid'] == pid
    assert host['sdk_pid'] == (None if plain else pid)
    assert (ROOT / (label + '.constructor')).read_bytes() == b'constructor\n'
    assert (output / 'stdout').read_bytes() == (str(pid) + '|literal space|--literal|$literal|17|input $data\n').encode()
    assert (output / 'stderr').read_bytes() == b''
    capture = read(output / 'http-capture.json'); assert capture['errors'] == []
    spans, points, batches, totals = [], 0, {'/v1/traces': 0, '/v1/metrics': 0}, {}
    for item in capture['bodies']:
        route = item['path']; batches[route] += 1
        raw = (output / item['file']).read_bytes()
        if route == '/v1/traces':
            document = ExportTraceServiceRequest.FromString(raw)
            for resource in document.resource_spans:
                for scope in resource.scope_spans:
                    assert scope.scope.name == 'io.quux.otelc.native'
                    spans.extend(scope.spans)
        else:
            document = ExportMetricsServiceRequest.FromString(raw)
            for resource in document.resource_metrics:
                for scope in resource.scope_metrics:
                    assert scope.scope.name == 'io.quux.otelc.native'
                    for metric in scope.metrics:
                        kind = metric.WhichOneof('data')
                        assert metric.name in ('otelc.function.calls', 'otelc.function.duration')
                        assert kind == ('histogram' if metric.name.endswith('duration') else 'sum')
                        for point in getattr(metric, kind).data_points:
                            points += 1
                            assert {row.key: row.value.string_value for row in point.attributes} == {'function': 'main.cpp::workload(int)'}
                            assert 0 < point.start_time_unix_nano <= point.time_unix_nano and point.flags == 0
                            number = point.count if kind == 'histogram' else point.as_int
                            if kind == 'histogram':
                                assert list(point.explicit_bounds) == [1e-6, 1e-5, .0001, .001, .01, .1, 1.]
                                assert sum(point.bucket_counts) == point.count and point.sum >= 0
                            totals[metric.name] = max(number, totals.get(metric.name, 0))
    if plain:
        assert capture['bodies'] == [] and final['sdk_health'] is None
    else:
        health = read(runtime / 'app/health.json'); assert health == final['sdk_health']
        assert health['pid'] == pid and health['phase'] == 'final'
        assert health['lifecycle'] == {'flush': 'succeeded', 'shutdown': 'succeeded'}
        assert health['function_accounting'] == {'registered': '1', 'started': '2', 'ended': '2', 'active': '0',
            'lost': '0', 'invalid': '0', 'metadata_errors': '0', 'closed': True}
        assert len(spans) == 2 and len({(span.trace_id, span.span_id) for span in spans}) == 2
        assert all(span.name == 'main.cpp::workload(int)' and not span.parent_span_id
                   and any(span.trace_id) and any(span.span_id) and 0 < span.start_time_unix_nano <= span.end_time_unix_nano for span in spans)
        assert totals == {'otelc.function.calls': 2, 'otelc.function.duration': 2}
        for category, units in (('trace_exports', len(spans)), ('metric_exports', points)):
            exports = health[category]
            assert exports['batches_started'] == exports['batches_succeeded']
            assert exports['units_started'] == exports['units_succeeded'] == str(units)
            assert all(exports[name] == '0' for name in ('batches_failed', 'batches_pending', 'units_failed'))
        # The official metric exporter can accept an empty API batch and send
        # no HTTP request. Points are comparable; these batch counts are not.
        assert int(health['trace_exports']['batches_succeeded']) == batches['/v1/traces']
    results.append({'plain': plain, 'pid': pid, 'spans': len(spans), 'points': points,
                    'requests': batches, 'typed_metric_totals': totals})
after = evidence(); assert before == after
(AUDIT / 'evidence-after.json').write_text(json.dumps(after, indent=2) + '\n')
result = {'status': 'passed', 'actual_new_application_launches': 0, 'original_applications': 2,
          'original_failed_audit_preserved': True, 'results': results, 'evidence_files': len(before),
          'evidence_bytes_and_facts_preserved': True, 'seconds': round(time.monotonic() - started, 3),
          'scope': 'dirty development native consumer component; no generated/native language admission'}
(AUDIT / 'result.json').write_text(json.dumps(result, indent=2) + '\n')
print(json.dumps(result, indent=2))
