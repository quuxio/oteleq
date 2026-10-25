"""Join native owned completion to independently decoded function traces and metrics."""

from collections import Counter
import hashlib
import json
import math
from pathlib import Path

import native_execution
from native_protocol import require
import otelc_capture as capture

SCOPE = 'io.quux.otelc.native'
SDK_VERSION = '1.30.0'
CALLS, ERRORS, DURATION = ('otelc.function.' + name for name in ('calls', 'errors', 'duration'))
MAX_SPANS, MAX_POINTS, MAX_BYTES = 16384, 65536, 32 * 1024 * 1024
WITNESS_FIELDS = ('decoder', 'raw_otlp_sha256', 'functions', 'spans', 'losses', 'pending')


def attributes(rows) -> dict:
    """Duplicate, non-string and missing labels cannot hide another identity."""
    result = {}
    for row in rows:
        require(row.key not in result and row.value.WhichOneof('value') == 'string_value',
                'invalid native OTLP attributes')
        result[row.key] = row.value.string_value
    return result


def resource(group, language: str, service: str) -> None:
    """The native SDK is C++ even when the instrumented application language is C."""
    require(not group.schema_url and group.resource.dropped_attributes_count == 0
            and attributes(group.resource.attributes) == {'service.name': service,
                'telemetry.sdk.language': 'cpp', 'telemetry.sdk.name': 'opentelemetry',
                'telemetry.sdk.version': SDK_VERSION, 'otelc.language': language},
            'native OTLP resource differs from the selected service or SDK')


def scope(value) -> None:
    """Require the fixed native scope without dropped or foreign metadata."""
    require(value.scope.name == SCOPE and not value.scope.version and not value.schema_url
            and not value.scope.attributes and value.scope.dropped_attributes_count == 0,
            'unexpected native instrumentation scope')


def decode(decoder, body: bytes):
    """Malformed protobuf is a qualification failure, never absent telemetry."""
    from google.protobuf.message import DecodeError
    try:
        return decoder.FromString(body)
    except DecodeError as error:
        raise ValueError('native prepared provider: invalid OTLP protobuf') from error


def traces(bodies: list, language: str, service: str, roots: tuple[str, ...]) -> tuple[dict, Counter, int]:
    """Bind complete serial selected call trees, including recursive child calls."""
    from opentelemetry.proto.collector.trace.v1.trace_service_pb2 import ExportTraceServiceRequest
    spans, nodes, errors = {}, {}, Counter()
    selected = set(roots)
    for route, body in bodies:
        if route != '/v1/traces':
            continue
        message = decode(ExportTraceServiceRequest, body)
        require(bool(message.resource_spans), 'empty native trace request')
        for group in message.resource_spans:
            resource(group, language, service)
            require(bool(group.scope_spans), 'missing native trace scope')
            for instrumentation in group.scope_spans:
                scope(instrumentation)
                require(bool(instrumentation.spans), 'empty native trace scope')
                for span in instrumentation.spans:
                    key = capture.span_identity(span)
                    labels = {'function': span.name}
                    if span.status.code == 2:
                        labels['error.type'] = 'exception'; errors[span.name] += 1
                    require(key not in spans and len(spans) < MAX_SPANS and span.name in selected
                            and span.kind == 1 and span.status.code in (0, 2) and not span.status.message
                            and span.flags & 1 and attributes(span.attributes) == labels
                            and not span.events and not span.links
                            and span.dropped_attributes_count == span.dropped_events_count == span.dropped_links_count == 0,
                            'invalid, dropped, excessive or unbound native function span')
                    spans[key] = span
                    nodes[key] = (span.trace_id, span.parent_span_id) if span.parent_span_id else None
    capture.trace_roots(nodes)
    ordered = sorted((span for span in spans.values() if not span.parent_span_id), key=lambda span: span.start_time_unix_nano)
    require(tuple(span.name for span in ordered) == roots
            and all(first.end_time_unix_nano <= second.start_time_unix_nano for first, second in zip(ordered, ordered[1:])),
            'native invocation roots differ from the declared serial calls')
    for key, parent in nodes.items():
        if parent is not None:
            child, owner = spans[key], spans[parent]
            require(owner.start_time_unix_nano <= child.start_time_unix_nano
                    <= child.end_time_unix_nano <= owner.end_time_unix_nano,
                    'native selected child lies outside its parent')
    return dict(Counter(span.name for span in spans.values())), errors, len(spans)


def point(metric, value, names: set[str], bounds: list) -> tuple:
    """Check labels, scalar representation and complete histogram accounting."""
    labels = attributes(value.attributes)
    function = labels.get('function')
    expected = {'function': function}
    if metric.name == ERRORS:
        expected['error.type'] = 'exception'
    require(function in names and labels == expected and value.flags == 0
            and 0 < value.start_time_unix_nano <= value.time_unix_nano,
            'invalid native metric labels or timestamps')
    if metric.name == DURATION:
        require(list(value.explicit_bounds) == bounds and len(value.bucket_counts) == len(bounds) + 1
                and sum(value.bucket_counts) == value.count and value.HasField('sum')
                and math.isfinite(value.sum) and value.sum >= 0 and not value.exemplars,
                'invalid native duration histogram')
        if value.count:
            require(value.HasField('min') and value.HasField('max')
                    and math.isfinite(value.min) and math.isfinite(value.max)
                    and 0 <= value.min <= value.max, 'missing native histogram extrema')
        number = value.count
    else:
        require(metric.sum.is_monotonic and value.WhichOneof('value') == 'as_int'
                and value.as_int >= 0 and not value.exemplars, 'invalid native cumulative counter')
        number = value.as_int
    return (metric.name, function), (value.start_time_unix_nano, value.time_unix_nano, number)


def metrics(bodies: list, language: str, service: str, names: dict, errors: Counter,
            bounds: list, enabled: bool) -> int:
    """Retain all cumulative samples and join their final totals to actual spans."""
    from opentelemetry.proto.collector.metrics.v1.metrics_service_pb2 import ExportMetricsServiceRequest
    series, points = {}, 0
    kinds = {CALLS: ('sum', '{call}'), ERRORS: ('sum', '{error}'), DURATION: ('histogram', 's')}
    for route, body in bodies:
        if route != '/v1/metrics':
            continue
        message = decode(ExportMetricsServiceRequest, body)
        require(bool(message.resource_metrics), 'empty native metric request')
        for group in message.resource_metrics:
            resource(group, language, service)
            require(bool(group.scope_metrics), 'missing native metric scope')
            for instrumentation in group.scope_metrics:
                scope(instrumentation)
                require(bool(instrumentation.metrics), 'empty native metric scope')
                for metric in instrumentation.metrics:
                    require(metric.name in kinds, 'unexpected native metric instrument')
                    kind, unit = kinds[metric.name]
                    data = getattr(metric, kind)
                    require(metric.WhichOneof('data') == kind and metric.unit == unit
                            and data.aggregation_temporality == 2 and bool(data.data_points),
                            'invalid native metric kind, unit or temporality')
                    for value in data.data_points:
                        points += 1
                        require(points <= MAX_POINTS, 'native metric point budget exceeded')
                        key, sample = point(metric, value, set(names), bounds)
                        series.setdefault(key, []).append(sample)
    totals = {}
    for key, samples in series.items():
        samples.sort()
        require(len({row[0] for row in samples}) == 1 and len({row[1] for row in samples}) == len(samples)
                and all(first[2] <= second[2] for first, second in zip(samples, samples[1:])),
                'reset, duplicate or decreasing native cumulative samples')
        totals[key] = samples[-1][2]
    if enabled:
        wanted = {(metric, name): number for name, number in names.items() for metric in (CALLS, DURATION)}
        wanted.update({(ERRORS, name): number for name, number in errors.items()})
        require({key: value for key, value in totals.items() if key[0] != ERRORS or value} == wanted,
                'native metric totals differ from completed selected traces')
    else:
        require(not points, 'native disabled startup emitted measurements')
    return points


def witness(completed: native_execution.Execution, bodies: list, service: str,
            roots: tuple[str, ...], *, folder: Path | None = None) -> dict | None:
    """Assess fixed-state calls; live toggles require their separate checkpoint profile."""
    require(type(completed) is native_execution.Execution and type(roots) is tuple and 1 <= len(roots) <= 64
            and all(type(name) is str and 0 < len(name) <= 4096 for name in roots), 'invalid native receipt intent')
    completed.verify()
    launch = completed.started.launch
    if launch.intent.plain:
        require(not bodies and completed.health is None, 'plain native worker emitted SDK evidence')
        return None
    policy = launch.intent.policy()
    require(policy['traces']['enabled'] is True and type(policy['traces']['sample_ratio']) in (int, float)
            and policy['traces']['sample_ratio'] == 1.0,
            'native qualification requires complete selected traces')
    require(type(bodies) is list and len(bodies) <= 4096
            and all(type(row) is tuple and len(row) == 2 and row[0] in ('/v1/traces', '/v1/metrics')
                    and type(row[1]) is bytes and bool(row[1]) for row in bodies)
            and sum(len(raw) for _, raw in bodies) <= MAX_BYTES, 'invalid native telemetry route or capture budget')
    language = launch.intent.build.intent.language
    names, errors, spans = traces(bodies, language, service, roots)
    points = metrics(bodies, language, service, names, errors,
                     policy['metrics']['histogram_boundaries_seconds'],
                     policy['metrics']['collection'] and policy['metrics']['emission'])
    health = completed.health.value()
    require(all(health['controls'][key] is policy['metrics'][key] for key in ('collection', 'emission')),
            'native fixed-state controls changed during execution')
    require(health['function_accounting']['registered'] == str(len(names))
            and health['function_accounting']['started'] == str(spans)
            and health['span_accounting']['sampled_started'] == str(spans)
            and health['trace_exports']['units_succeeded'] == str(spans)
            and health['metric_exports']['units_succeeded'] == str(points),
            'native final SDK unit counters differ from direct receipt')
    raw = hashlib.sha256()
    for route, body in bodies:
        raw.update(len(route).to_bytes(8, 'big') + route.encode() + len(body).to_bytes(8, 'big') + body)
    result = {'decoder': 'opentelemetry-proto native traces/metrics with independent owned health1',
              'raw_otlp_sha256': raw.hexdigest(), 'functions': names, 'spans': spans,
              'losses': {'function_lost': 0, 'metadata_errors': 0, 'queue_dropped': 0, 'diagnostic_dropped': 0},
              'pending': 0, 'sdk_pid': completed.started.owner.application_pid,
              'received': {'spans': spans, 'metric_points': points,
                  'trace_requests': sum(route == '/v1/traces' for route, _ in bodies),
                  'metric_requests': sum(route == '/v1/metrics' for route, _ in bodies)}, 'health': health}
    completed.verify()
    if folder is not None:
        (folder / 'native-verified-telemetry.json').write_text(json.dumps(result, indent=2, allow_nan=False) + '\n')
    return {name: result[name] for name in WITNESS_FIELDS}
