"""Independent receipt oracle for one declared native fixture call per process."""

import bisect
import hashlib
import json
import math
from pathlib import Path

BOUNDS = [1e-6, 1e-5, 1e-4, .001, .01, .1, 1.]
SCOPE = 'io.quux.otelc.native'
ROUTES = {'/v1/traces', '/v1/metrics'}
MAX_BYTES = 32 * 1024**2


def require(condition: bool, reason: str) -> None:
    if not condition:
        raise ValueError('native qualification: ' + reason)


def same(value, expected) -> None:
    """JSON wire values retain bool/int and missing-field distinctions."""
    require(json.dumps(value, sort_keys=True, allow_nan=False) == json.dumps(expected, sort_keys=True, allow_nan=False),
            'different literal evidence')


def attributes(rows) -> dict:
    values = {}
    for row in rows:
        require(row.key not in values and row.value.WhichOneof('value') == 'string_value', 'invalid OTLP attributes')
        values[row.key] = row.value.string_value
    return values


def groups(message, language: str, service: str, *, traces: bool):
    """Do not use producer summaries to choose a resource, scope or signal."""
    values = message.resource_spans if traces else message.resource_metrics
    require(bool(values), 'empty OTLP request')
    for resource in values:
        same(attributes(resource.resource.attributes), {'service.name': service, 'otelc.language': language,
             'telemetry.sdk.language': 'cpp', 'telemetry.sdk.name': 'opentelemetry', 'telemetry.sdk.version': '1.30.0'})
        require(not resource.schema_url and not resource.resource.dropped_attributes_count, 'dropped resource metadata')
        scopes = resource.scope_spans if traces else resource.scope_metrics
        require(bool(scopes), 'missing OTLP scope')
        for scope in scopes:
            require(scope.scope.name == SCOPE and not scope.scope.version and not scope.schema_url
                    and not scope.scope.attributes and not scope.scope.dropped_attributes_count, 'foreign OTLP scope')
            rows = scope.spans if traces else scope.metrics
            require(bool(rows), 'empty OTLP scope')
            yield from rows


def function_span(span, name: str, *, failed: bool = False) -> None:
    """Check one independently selected ordinary function root."""
    require(len(span.trace_id) == 16 and any(span.trace_id) and len(span.span_id) == 8 and any(span.span_id)
            and not span.parent_span_id and span.name == name and span.kind == 1 and span.flags & 1
            and type(failed) is bool and span.status.code == (2 if failed else 0) and not span.status.message
            and 0 < span.start_time_unix_nano <= span.end_time_unix_nano
            and not span.events and not span.links
            and not span.dropped_attributes_count and not span.dropped_events_count and not span.dropped_links_count,
            'fixture trace differs from the declared selected outcome')
    same(attributes(span.attributes), {'function': name, **({'error.type': 'exception'} if failed else {})})


def trace(message, language: str, service: str, name: str) -> int:
    count = 0
    for span in groups(message, language, service, traces=True):
        function_span(span, name)
        count += 1
    return count


def histogram(point) -> tuple:
    require(list(point.explicit_bounds) == BOUNDS and len(point.bucket_counts) == len(BOUNDS) + 1
            and point.count in (0, 1) and sum(point.bucket_counts) == point.count
            and point.HasField('sum') and math.isfinite(point.sum) and point.sum >= 0,
            'invalid single-call histogram')
    if point.count:
        require(point.HasField('min') and point.HasField('max') and point.min == point.sum == point.max,
                'single-call histogram extrema/sum differ')
        buckets = [0] * (len(BOUNDS) + 1)
        buckets[bisect.bisect_left(BOUNDS, point.sum)] = 1
        same(list(point.bucket_counts), buckets)
    else:
        require(point.sum == 0 and (not point.HasField('min') or point.min == 0)
                and (not point.HasField('max') or point.max == 0), 'nonempty zero-count histogram')
    return point.count, tuple(point.bucket_counts), point.sum


def function_metric(value, name: str, series: dict, *, failed: bool = False) -> int:
    """Retain every point from one declared function instrument."""
    count = 0
    expected = {'otelc.function.calls': ('sum', '{call}'), 'otelc.function.errors': ('sum', '{error}'),
                'otelc.function.duration': ('histogram', 's')}
    require(type(failed) is bool and value.name in expected, 'foreign metric instrument or outcome')
    kind, unit = expected[value.name]
    data = getattr(value, kind)
    require(value.WhichOneof('data') == kind and value.unit == unit
            and data.aggregation_temporality == 2 and bool(data.data_points), 'invalid metric type/unit/temporality')
    if kind == 'sum':
        require(data.is_monotonic, 'nonmonotonic function counter')
    for point in data.data_points:
        labels = {'function': name}
        if value.name.endswith('.errors'):
            labels['error.type'] = 'exception'
        same(attributes(point.attributes), labels)
        require(not point.flags and not point.exemplars and 0 < point.start_time_unix_nano <= point.time_unix_nano,
                'invalid metric flags/exemplars/time')
        if kind == 'histogram':
            sample = histogram(point)
        else:
            require(point.WhichOneof('value') == 'as_int' and point.as_int in (0, 1)
                    and (not value.name.endswith('.errors') or point.as_int <= int(failed)), 'invalid declared-call counter')
            sample = (point.as_int, (), 0)
        series.setdefault(value.name, []).append((point.start_time_unix_nano, point.time_unix_nano, *sample))
        count += 1
    return count


def metric(message, language: str, service: str, name: str, series: dict) -> int:
    return sum(function_metric(value, name, series) for value in groups(message, language, service, traces=False))


def totals(series: dict, *, failed: bool = False) -> None:
    """Keep every cumulative point; one observed call cannot reset or multiply."""
    required = {'otelc.function.calls', 'otelc.function.duration'} | ({'otelc.function.errors'} if failed else set())
    require(type(failed) is bool and required <= set(series), 'missing function measurements')
    for name, rows in series.items():
        rows.sort()
        require(len({row[0] for row in rows}) == 1 and len({row[1] for row in rows}) == len(rows)
                and all(first[2] <= second[2] for first, second in zip(rows, rows[1:])), 'reset/duplicate cumulative sample')
        require(rows[-1][2] == (int(failed) if name.endswith('.errors') else 1), 'wrong final function total')
        if name.endswith('.duration'):
            populated = [row[3:] for row in rows if row[2]]
            require(all(row == populated[0] for row in populated), 'one-call histogram changed after measurement')


def response(value: dict, bodies: list) -> None:
    same({key: value[key] for key in ('schema_version', 'scope', 'clock', 'unrecorded_events')},
         {'schema_version': 1, 'scope': 'server response headers; client acknowledgement is not observed',
          'clock': 'monotonic_ns', 'unrecorded_events': 0})
    events = value['events']
    require(len(events) == len(bodies) and all(type(row['body_index']) is int for row in events)
            and sorted(row['body_index'] for row in events) == list(range(len(bodies))),
            'incomplete HTTP response denominator')
    for row in events:
        same(row['status'], 200); same(row['headers_write_failed'], False)
        same(row['path'], bodies[row['body_index']][0])
        times = [row[key] for key in ('request_started_ns', 'body_received_ns', 'response_started_ns',
                                      'headers_written_ns', 'handler_finished_ns')]
        require(all(type(value) is int and value > 0 for value in times) and times == sorted(times),
                'invalid HTTP response clock')


def payloads(folder: Path, read) -> list[tuple[str, bytes]]:
    """Only bounded fixed capture filenames may supply the complete HTTP payload set."""
    manifest = read(folder / 'http-capture.json')
    same(sorted(manifest), ['bodies', 'errors']); same(manifest['errors'], [])
    bodies = []
    total = 0
    require(len(manifest['bodies']) <= 4096, 'HTTP request budget exceeded')
    for index, row in enumerate(manifest['bodies']):
        same(sorted(row), ['file', 'path'])
        require(row['path'] in ROUTES and row['file'] == 'otlp-' + str(index) + '.protobuf', 'foreign transport payload')
        path = folder / row['file']
        require(path.is_file() and not path.is_symlink(), 'invalid protobuf file')
        size = path.stat().st_size
        require(0 < size <= MAX_BYTES - total, 'protobuf capture budget exceeded')
        with path.open('rb') as stream:
            raw = stream.read(MAX_BYTES - total + 1)
        require(len(raw) == size and len(raw) <= MAX_BYTES - total, 'protobuf changed or exceeded capture budget')
        bodies.append((row['path'], raw))
        total += len(raw)
    same(sorted(path.name for path in folder.glob('otlp-*.protobuf')), sorted(row['file'] for row in manifest['bodies']))
    response(read(folder / 'http-responses.json'), bodies)
    return bodies


def receipt(folder: Path, read, language: str, service: str, name: str, *, plain: bool) -> tuple[dict | None, int, int, int]:
    """Decode original protobuf and bind each retained successful server response."""
    bodies = payloads(folder, read)
    if plain:
        require(not bodies, 'plain fixture emitted telemetry')
        return None, 0, 0, 0
    from opentelemetry.proto.collector.metrics.v1.metrics_service_pb2 import ExportMetricsServiceRequest
    from opentelemetry.proto.collector.trace.v1.trace_service_pb2 import ExportTraceServiceRequest
    from google.protobuf.message import DecodeError
    spans = points = traces = metrics = 0
    series = {}; raw_digest = hashlib.sha256()
    for route, body in bodies:
        raw_digest.update(len(route).to_bytes(8, 'big') + route.encode() + len(body).to_bytes(8, 'big') + body)
        try:
            if route == '/v1/traces':
                spans += trace(ExportTraceServiceRequest.FromString(body), language, service, name); traces += 1
            else:
                points += metric(ExportMetricsServiceRequest.FromString(body), language, service, name, series); metrics += 1
        except DecodeError as error:
            raise ValueError('native qualification: malformed protobuf') from error
    require(spans == 1, 'missing or additional selected trace'); totals(series)
    witness = {'decoder': 'opentelemetry-proto native traces/metrics with independent owned health1',
               'raw_otlp_sha256': raw_digest.hexdigest(), 'functions': {name: 1}, 'spans': 1,
               'losses': {'function_lost': 0, 'metadata_errors': 0, 'queue_dropped': 0, 'diagnostic_dropped': 0}, 'pending': 0}
    return witness, points, traces, metrics
