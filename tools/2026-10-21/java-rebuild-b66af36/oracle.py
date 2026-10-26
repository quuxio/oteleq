"""Independent fixed-value and telemetry checks for retained Java live captures."""
import base64
from collections import Counter
import json
import math
from pathlib import Path
import re
from google.protobuf.json_format import MessageToDict
from opentelemetry.proto.collector.metrics.v1.metrics_service_pb2 import ExportMetricsServiceRequest
from opentelemetry.proto.collector.trace.v1.trace_service_pb2 import ExportTraceServiceRequest

WORK = 'examples.BenchmarkApp$WorkItem'
LIFE = 'examples.BenchmarkApp$LifecycleWorkItem'
BOUNDS = [1e-6, 1e-5, .0001, .001, .01, .1, 1.0]


def attributes(rows: list) -> dict:
    values = {}
    for row in rows:
        assert row['key'] not in values
        value = row['value']
        assert len(value) == 1
        values[row['key']] = next(iter(value.values()))
    return values


def numbers(value: object) -> int:
    assert type(value) is str and value.isascii() and value.isdecimal()
    return int(value)


def label(point: dict) -> tuple:
    return tuple(sorted(attributes(point.get('attributes', [])).items()))


def check_history(rows: list) -> None:
    ordered = sorted(rows)
    for before, after in zip(ordered, ordered[1:]):
        assert before[1] <= after[1]


def decoded(folder: Path) -> tuple[list, dict]:
    spans, metrics = [], {}
    histories = {}
    expected_service = 'oteleq-independent-' + folder.name
    retained = json.loads((folder / 'decoded-otlp.json').read_text())
    manifest = json.loads((folder / 'http-capture.json').read_text())
    actual = []
    assert len(manifest['bodies']) <= 1024
    for index, record in enumerate(manifest['bodies']):
        assert record['file'] == f'otlp-{index}.protobuf'
        assert record['path'] in ('/v1/traces', '/v1/metrics')
        raw = (folder / record['file']).read_bytes()
        assert len(raw) <= 1024 * 1024
        message = ExportTraceServiceRequest() if record['path'] == '/v1/traces' else ExportMetricsServiceRequest()
        message.ParseFromString(raw)
        actual.append({'path': record['path'], 'message': MessageToDict(message, preserving_proto_field_name=True)})
    assert actual == retained
    for frame in actual:
        message = frame['message']
        for key in ('resource_spans', 'resource_metrics'):
            for resource in message.get(key, []):
                attrs = attributes(resource['resource']['attributes'])
                assert attrs['service.name'] == expected_service
                assert attrs['otelc.language'] == 'java'
                assert attrs['telemetry.sdk.version'] == '1.66.0'
                for scope in resource.get('scope_spans', []):
                    spans.extend(scope.get('spans', []))
                for scope in resource.get('scope_metrics', []):
                    for metric in scope.get('metrics', []):
                        if not metric['name'].startswith('otelc.'):
                            continue
                        kind = next(k for k in ('sum', 'histogram', 'gauge') if k in metric)
                        for point in metric[kind]['data_points']:
                            identity = metric['name'], label(point)
                            if kind in ('sum', 'histogram'):
                                value = numbers(point['as_int'] if kind == 'sum' else point['count'])
                                histories.setdefault(identity, []).append((numbers(point['time_unix_nano']), value))
                            prior = metrics.get(identity)
                            if prior is None or numbers(point['time_unix_nano']) >= numbers(prior[2]['time_unix_nano']):
                                metrics[identity] = (kind, metric, point)
    for history in histories.values():
        check_history(history)
    return spans, metrics


def counter(metrics: dict, name: str) -> dict:
    result = {}
    for (metric_name, labels), (kind, metric, point) in metrics.items():
        if metric_name != name:
            continue
        assert kind == 'sum' and metric['sum']['is_monotonic']
        assert metric['sum']['aggregation_temporality'] == 'AGGREGATION_TEMPORALITY_CUMULATIVE'
        result[labels] = numbers(point['as_int'])
    return result


def histogram(metrics: dict, name: str) -> dict:
    result = {}
    for (metric_name, labels), (kind, metric, point) in metrics.items():
        if metric_name != name:
            continue
        assert kind == 'histogram' and metric['unit'] == 's'
        assert metric['histogram']['aggregation_temporality'] == 'AGGREGATION_TEMPORALITY_CUMULATIVE'
        count = numbers(point['count'])
        assert point['explicit_bounds'] == BOUNDS
        assert len(point['bucket_counts']) == len(BOUNDS) + 1
        assert sum(numbers(x) for x in point['bucket_counts']) == count
        for key in ('sum', 'min', 'max'):
            assert math.isfinite(point[key]) and point[key] >= 0
        assert point['min'] <= point['max']
        assert point['min'] * count - 1e-9 <= point['sum'] <= point['max'] * count + 1e-9
        result[labels] = count
    return result


def cells(values: dict[tuple[str, str], int]) -> dict:
    return {tuple(sorted({'type': type_name, 'boundary': boundary}.items())): count
            for (type_name, boundary), count in values.items()}


def check_metrics(metrics: dict, rounds: int) -> None:
    assert counter(metrics, 'otelc.function.calls') == {(('function', 'workload'),): 11 * rounds}
    assert histogram(metrics, 'otelc.function.duration') == {(('function', 'workload'),): 11 * rounds}
    admitted = cells({(WORK, 'resource'): 10 * rounds, (WORK, 'observed_gc'): 10 * rounds,
                      (LIFE, 'resource'): 2 * rounds, (LIFE, 'observed_gc'): 2 * rounds})
    completed = cells({(WORK, 'resource'): 10 * rounds, (WORK, 'observed_gc'): 10 * rounds,
                       (LIFE, 'resource'): rounds, (LIFE, 'observed_gc'): 2 * rounds})
    assert counter(metrics, 'otelc.lifetime.admitted') == admitted
    assert counter(metrics, 'otelc.lifetime.completed') == completed
    assert histogram(metrics, 'otelc.lifetime.duration') == completed
    assert counter(metrics, 'otelc.lifetime.incomplete') == cells({(LIFE, 'resource'): rounds})
    assert not any(counter(metrics, 'otelc.lifetime.lost').values())
    gauges = {labels: numbers(point['as_int']) for (name, labels), (kind, _, point) in metrics.items()
              if name == 'otelc.lifetime.live' and kind == 'gauge'}
    assert gauges == cells({('all', 'resource'): 0, ('all', 'observed_gc'): 0})


def identity(span: dict) -> tuple:
    for name, length in (('trace_id', 16), ('span_id', 8)):
        raw = base64.b64decode(span[name], validate=True)
        assert len(raw) == length and any(raw)
    assert not span.get('parent_span_id')
    assert numbers(span['start_time_unix_nano']) > 0
    assert numbers(span['end_time_unix_nano']) >= numbers(span['start_time_unix_nano'])
    return span['trace_id'], span['span_id']


def check_spans(spans: list, phases: list) -> None:
    assert len({identity(span) for span in spans}) == len(spans) == 204
    functions = [span for span in spans if span['name'] == 'BenchmarkApp.workload']
    assert len(functions) == 66
    by_identity = {identity(span): span for span in functions}
    successful, failed = set(), set()
    for span in functions:
        attrs = attributes(span['attributes'])
        assert attrs['code.function'] == 'workload' and attrs['code.namespace'] == 'examples.BenchmarkApp'
        errors = [event for event in span.get('events', []) if event['name'] == 'exception']
        if errors:
            assert len(errors) == 1 and span['status']['code'] == 'STATUS_CODE_ERROR'
            error = attributes(errors[0]['attributes'])
            assert error['exception.type'] == 'java.lang.IllegalArgumentException' and error['exception.message'] == 'negative seed'
            failed.add(identity(span))
        else:
            assert span.get('status', {}).get('code') in (None, 'STATUS_CODE_UNSET')
            successful.add(identity(span))
    assert len(failed) == 6 and len(successful) == 60
    counts, linked = Counter(), {}
    for span in spans:
        if identity(span) in by_identity:
            continue
        attrs = attributes(span['attributes'])
        type_name, boundary = attrs['type'], attrs['boundary']
        assert type_name in (WORK, LIFE) and boundary in ('resource', 'observed_gc')
        assert span['name'] == type_name + ' lifetime'
        assert span.get('status', {}).get('code') in (None, 'STATUS_CODE_UNSET')
        counts[type_name, boundary] += 1
        links = span.get('links', [])
        if type_name == WORK:
            assert len(links) == 1
            creation = links[0]['trace_id'], links[0]['span_id']
            assert creation in successful and creation not in failed
            assert span['trace_id'] != creation[0]
            linked.setdefault(creation, {})[boundary] = span
        else:
            assert not links
    assert counts == Counter({(WORK, 'resource'): 60, (WORK, 'observed_gc'): 60,
                              (LIFE, 'resource'): 6, (LIFE, 'observed_gc'): 12})
    assert set(linked) == successful
    for pair in linked.values():
        assert set(pair) == {'resource', 'observed_gc'}
        resource, gc = pair['resource'], pair['observed_gc']
        assert resource['start_time_unix_nano'] == gc['start_time_unix_nano']
        assert numbers(gc['end_time_unix_nano']) >= numbers(resource['end_time_unix_nano'])
    for phase in phases:
        current = [s for s in spans if phase['start_ns'] <= numbers(s['start_time_unix_nano']) <= phase['end_ns']]
        assert len(current) == 34
        assert sum(s['name'] == 'BenchmarkApp.workload' for s in current) == 11


def check_outputs(phases: list) -> None:
    for phase in phases:
        result, error, lifecycle, gc = phase['outputs']
        assert set(result) == {'checksum', 'calls', 'elapsed_ns'}
        assert type(result['checksum']) is int and result['checksum'] == 41284864
        assert type(result['calls']) is int and result['calls'] == 10
        assert type(result['elapsed_ns']) is int and result['elapsed_ns'] >= 0
        assert error == {'exception': 'IllegalArgumentException', 'message': 'negative seed'}
        assert lifecycle == {'construction_failed': True, 'close_failed': True} and all(type(x) is bool for x in lifecycle.values())
        assert gc == {'gc_requested': True} and type(gc['gc_requested']) is bool


def check_case(folder: Path) -> dict:
    phases = json.loads((folder / 'phases.json').read_text())
    check_outputs(phases)
    assert [json.loads(line) for line in (folder / 'stdout').read_text().splitlines()] == [
        row for phase in phases for row in phase['outputs']]
    spans, metrics = decoded(folder)
    http = json.loads((folder / 'http-capture.json').read_text())
    assert not http['errors'] and http['requests'] == len(http['bodies'])
    if folder.name == 'baseline':
        assert not spans and not metrics and not http['bodies'] and len(phases) == 6
        assert not (folder / 'stderr').read_bytes()
        return {'name': folder.name, 'phases': 6, 'spans': 0}
    patterns = [r'Control socket: /tmp/otelc-[^/\s]+/control.sock',
                r'OpenJDK 64-Bit Server VM warning: Sharing is only supported for boot loader classes because bootstrap classpath has been appended',
                r'\[otel\.javaagent [^\]]+\] \[main\] INFO io\.opentelemetry\.javaagent\.tooling\.VersionLogger - opentelemetry-javaagent - version: 2\.32\.0']
    if folder.name == 'excluded':
        patterns.append(r'\[otel\.javaagent [^\]]+\] \[main\] WARN io\.opentelemetry\.javaagent\.extension\.instrumentation\.InstrumentationModule - Helper classes and resources wont be injected if no types are instrumented: \{0\}')
    diagnostics = (folder / 'stderr').read_text().splitlines()
    assert len(diagnostics) == len(patterns)
    assert all(sum(re.fullmatch(pattern, line) is not None for line in diagnostics) == 1 for pattern in patterns)
    process = json.loads((folder / 'process.json').read_text())
    frozen = json.loads((folder / 'build-identity.json').read_text())
    expected_products = json.loads((Path(__file__).resolve().parent / 'prepared-products.json').read_text())
    assert len(frozen) == 3
    for name, record in frozen.items():
        assert record['sha256'] == expected_products['build/examples/java/' + name]
    socket = json.loads((folder / 'socket-identity.json').read_text())
    assert socket['mode'] == 0o600 and socket['parent_mode'] == 0o700
    for phase in phases:
        assert phase['process'] == process and phase['build'] == frozen and phase['socket'] == socket
        status = phase['status']
        assert type(phase['collection']) is bool and type(phase['emission']) is bool
        assert type(status['collection']) is bool and type(status['emission']) is bool
        assert type(status['pid']) is int and status['pid'] > 0
        assert type(status['completed']) is int and type(phase['completed']) is int
        assert type(status['schema_version']) is int and status['schema_version'] == 1
        assert type(status['effective_emission_off']) is bool
        assert type(status['in_flight_exports']) is int and status['in_flight_exports'] >= 0
        assert status['pid'] == process['application_pid']
        assert status['collection'] is phase['collection'] and status['emission'] is phase['emission']
        assert status['completed'] == phase['completed']
        assert (type(status['lifetime_lost']) is int and status['lifetime_lost'] == 0
                or folder.name == 'excluded' and status['lifetime_lost'] is None)
        if not phase['emission']:
            assert status['effective_emission_off'] and status['in_flight_exports'] == 0
            window = http['bodies'][phase['body_index']:phase['end_body_index']]
            assert not any(row['path'] == '/v1/metrics' for row in window)
    if folder.name == 'live':
        assert [(p['collection'], p['emission'], p['completed']) for p in phases] == [
            (False, False, 0), (True, False, 11), (True, True, 22),
            (False, True, 22), (False, False, 22), (True, True, 33)]
        check_metrics(metrics, 3)
        check_spans(spans, phases)
        snapshots = json.loads((folder / 'decoded-otlp.json').read_text())
        for phase in phases:
            points = [point for frame in snapshots[phase['body_index']:phase['end_body_index']]
                      for resource in frame['message'].get('resource_metrics', [])
                      for scope in resource.get('scope_metrics', []) for metric in scope.get('metrics', [])
                      if metric['name'] == 'otelc.function.calls' for point in metric['sum']['data_points']]
            if phase['collection'] and phase['emission']:
                assert points and numbers(max(points, key=lambda p: numbers(p['time_unix_nano']))['as_int']) == phase['completed']
            assert all(numbers(point['as_int']) <= phase['completed'] for point in points)
    elif folder.name == 'unsampled':
        assert not spans and phases[0]['completed'] == 11
        check_metrics(metrics, 1)
    else:
        assert folder.name == 'excluded' and not spans and not metrics and phases[0]['completed'] == 0
    return {'name': folder.name, 'phases': len(phases), 'spans': len(spans), 'application_pid': process['application_pid']}


def main() -> None:
    import sys
    if sys.flags.optimize:
        raise ValueError('Oracle requires assertions')
    root = Path(__file__).resolve().parent / 'live-v3'
    results = [check_case(root / name) for name in ('baseline', 'live', 'unsampled', 'excluded')]
    (root / 'oracle.json').write_text(json.dumps({'results': results, 'claim': 'equivalence over these tests and observations',
        'scope': 'Fixed Java example, six same-PID metric states, functional outputs and independently expected telemetry. Timing values retained separately.'}, indent=2) + '\n')
    print(json.dumps(results, indent=2))


if __name__ == '__main__':
    main()
