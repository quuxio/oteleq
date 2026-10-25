"""Independent raw oracle for the declared one-call native lifetime corpus.

Only the explicit zero/completed/censored/C++ exception fixtures are admitted.
Other object counts, escaping errors, startup and live schedules stay separate.
No SDK or consumer receipt renderer supplies expected telemetry values.
"""

import hashlib
from pathlib import Path

from google.protobuf.message import DecodeError
from opentelemetry.proto.collector.metrics.v1.metrics_service_pb2 import ExportMetricsServiceRequest
from opentelemetry.proto.collector.trace.v1.trace_service_pb2 import ExportTraceServiceRequest

import native_prepared_otlp as common
import native_lifetime_cases as cases
from native_prepared_otlp import require, same

INSTRUMENTS = {'otelc.lifetime.admitted': ('sum', '{object}'),
               'otelc.lifetime.completed': ('sum', '{object}'),
               'otelc.lifetime.incomplete': ('sum', '{object}'),
               'otelc.lifetime.duration': ('histogram', 's'),
               'otelc.lifetime.live': ('gauge', '{object}')}


def attributes(rows) -> dict:
    """Lifetime completion is an OTLP boolean, never a string or integer."""
    result = {}
    for row in rows:
        kind = row.value.WhichOneof('value')
        require(row.key not in result and kind in ('string_value', 'bool_value'), 'invalid lifetime attribute')
        result[row.key] = getattr(row.value, kind)
    return result


def observation(values: list, language: str, function: str, *, mode: str = 'completed') -> dict | None:
    """Zero or one lifetime must retain its declared creation and end boundaries."""
    expected = cases.expected(language, mode)
    require(len(values) == expected['spans'], 'wrong declared function/lifetime span denominator')
    roots = [span for span in values if span.name == function]
    require(len(roots) == 1, 'selected function root absent or duplicated')
    root, = roots
    common.function_span(root, function)
    require(not root.trace_state, 'foreign selected function trace state')
    if not expected['admitted']:
        return None
    lifetime, = [span for span in values if span is not root]
    declared, = expected['observations']
    boundary = expected['boundary']
    labels = {'type': 'Item', 'boundary': boundary, 'otelc.lifetime.complete': declared['complete'],
              'otelc.lifetime.instance': '1'}
    if declared['exception_exit'] is not None:
        labels['otelc.destructor.exception_exit'] = declared['exception_exit']
    same(attributes(lifetime.attributes), labels)
    require(lifetime.name == 'Item lifetime' and len(lifetime.trace_id) == 16 and any(lifetime.trace_id)
            and len(lifetime.span_id) == 8 and any(lifetime.span_id) and lifetime.trace_id != root.trace_id
            and not lifetime.parent_span_id and lifetime.kind == 1 and lifetime.flags & 1
            and lifetime.status.code == 0 and not lifetime.status.message
            and not lifetime.trace_state
            and root.start_time_unix_nano <= lifetime.start_time_unix_nano <= root.end_time_unix_nano
            and lifetime.start_time_unix_nano <= lifetime.end_time_unix_nano
            and not lifetime.events and len(lifetime.links) == 1
            and not lifetime.dropped_attributes_count and not lifetime.dropped_events_count
            and not lifetime.dropped_links_count, 'invalid declared lifetime boundary or identity')
    require(lifetime.end_time_unix_nano <= root.end_time_unix_nano if declared['complete']
            else lifetime.end_time_unix_nano >= root.end_time_unix_nano,
            'completed/censored lifetime ends outside its declared boundary')
    link, = lifetime.links
    require(link.trace_id == root.trace_id and link.span_id == root.span_id and not link.trace_state
            and not link.attributes and not link.dropped_attributes_count and not link.flags,
            'lifetime creation link differs from the selected function')
    return {**declared, 'instance': '1', 'boundary': boundary,
            'duration_ns': lifetime.end_time_unix_nano - lifetime.start_time_unix_nano,
            'trace_id': lifetime.trace_id.hex(), 'span_id': lifetime.span_id.hex(),
            'creation_trace_id': root.trace_id.hex(), 'creation_span_id': root.span_id.hex()}


def metric(value, boundary: str, duration_ns: int, series: dict, *, mode: str = 'completed') -> int:
    """Retain every cumulative/gauge point and the exact raw span duration."""
    require(value.name in INSTRUMENTS, 'undeclared lifetime metric')
    require(mode != 'zero' and mode in ('completed', 'censored', 'unwind', 'throwing-destructor')
            and (not value.name.endswith('.completed') or mode != 'censored')
            and (not value.name.endswith('.incomplete') or mode == 'censored'),
            'lifetime metric differs from declared completion/censoring')
    kind, unit = INSTRUMENTS[value.name]
    data = getattr(value, kind)
    require(value.WhichOneof('data') == kind and value.unit == unit and bool(data.data_points)
            and (kind == 'gauge' or data.aggregation_temporality == 2)
            and (kind != 'sum' or data.is_monotonic), 'invalid lifetime metric kind or unit')
    for point in data.data_points:
        end = 'shutdown_censored' if mode == 'censored' and value.name.endswith(('.incomplete', '.duration')) else boundary
        same(common.attributes(point.attributes), {'type': 'Item', 'boundary': end})
        require(not point.flags and not point.exemplars and 0 < point.start_time_unix_nano <= point.time_unix_nano,
                'invalid lifetime point time, flags or exemplars')
        if kind == 'histogram':
            sample = common.histogram(point)
            # Match the SDK's integer-to-double conversion before scaling ticks.
            require(not point.count or point.sum == float(duration_ns) / 1_000_000_000,
                    'lifetime histogram differs from raw span duration')
        else:
            require(point.WhichOneof('value') == 'as_int' and point.as_int in (0, 1),
                    'invalid completed-Item counter or gauge')
            sample = (point.as_int, (), 0)
        series.setdefault(value.name, []).append((point.start_time_unix_nano, point.time_unix_nano, *sample))
    return len(data.data_points)


def totals(series: dict, *, language: str = 'c', mode: str = 'completed') -> None:
    """Declared counts cannot reset, multiply or mix completion and censoring."""
    same(sorted(series), sorted(cases.expected(language, mode)['instruments']))
    for name, rows in series.items():
        rows.sort()
        require(len({row[0] for row in rows}) == 1 and len({row[1] for row in rows}) == len(rows),
                'lifetime metric reset or duplicate cumulative point')
        if not name.endswith('.live'):
            require(all(first[2] <= second[2] for first, second in zip(rows, rows[1:])),
                    'lifetime cumulative count decreased')
        require(rows[-1][2] == int(not name.endswith('.live')), 'wrong final lifetime total')


def receipt(folder: Path, read, language: str, service: str, function: str, *, plain: bool,
            mode: str = 'completed') -> dict | None:
    """Read the complete original transport set; never trust a verified summary."""
    expected = cases.expected(language, mode)
    bodies = common.payloads(folder, read)
    if plain:
        require(not bodies, 'plain lifetime fixture emitted telemetry')
        return None
    spans, metrics = [], []
    digest = hashlib.sha256()
    requests = {'/v1/traces': 0, '/v1/metrics': 0}
    for route, body in bodies:
        digest.update(len(route).to_bytes(8, 'big') + route.encode() + len(body).to_bytes(8, 'big') + body)
        requests[route] += 1
        try:
            message = (ExportTraceServiceRequest if route == '/v1/traces' else ExportMetricsServiceRequest).FromString(body)
        except DecodeError as error:
            raise ValueError('native qualification: malformed lifetime protobuf') from error
        target = spans if route == '/v1/traces' else metrics
        target.extend(common.groups(message, language, service, traces=route == '/v1/traces'))
        require(len(spans) <= expected['spans'] and len(metrics) <= 4096, 'unexpected lifetime signal denominator')
    row = observation(spans, language, function, mode=mode)
    functions, lifetimes, points = {}, {}, 0
    for value in metrics:
        points += (common.function_metric(value, function, functions) if value.name.startswith('otelc.function.')
                   else metric(value, expected['release_boundary'], row['duration_ns'] if row else 0,
                               lifetimes, mode=mode))
        require(points <= 100000, 'native lifetime point budget exceeded')
    common.totals(functions); totals(lifetimes, language=language, mode=mode)
    return {'functions': {function: 1}, 'spans': expected['spans'], 'lifetimes': [row] if row else [], 'metric_points': points,
            'raw_otlp_sha256': digest.hexdigest(), 'trace_requests': requests['/v1/traces'],
            'metric_requests': requests['/v1/metrics']}
