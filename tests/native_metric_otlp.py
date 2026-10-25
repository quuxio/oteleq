"""Decode the native metric corpus independently of SDK and product receipt code."""

import bisect
import hashlib
import math

from google.protobuf.message import DecodeError
from opentelemetry.proto.collector.metrics.v1.metrics_service_pb2 import ExportMetricsServiceRequest
from opentelemetry.proto.collector.trace.v1.trace_service_pb2 import ExportTraceServiceRequest

import native_prepared_otlp as wire
import native_metric_histogram as feasible
from native_prepared_otlp import require, same


def decoded(bodies: list, language: str, service: str, *, traces: bool) -> list:
    decoder = ExportTraceServiceRequest if traces else ExportMetricsServiceRequest
    route = '/v1/traces' if traces else '/v1/metrics'
    result = []
    for path, body in bodies:
        if path != route:
            continue
        try:
            result.extend(wire.groups(decoder.FromString(body), language, service, traces=traces))
        except DecodeError as error:
            raise ValueError('native metric corpus: malformed protobuf') from error
    return result


def traces(bodies: list, language: str, service: str, name: str, calls: int, *, failed: bool) -> int:
    """Require four serial roots, with the exact independently prescribed call chains."""
    values = decoded(bodies, language, service, traces=True)
    spans = {}
    for span in values:
        key = (span.trace_id, span.span_id)
        require(key not in spans and span.name == name and span.kind == 1
                and len(span.trace_id) == 16 and any(span.trace_id)
                and len(span.span_id) == 8 and any(span.span_id)
                and span.start_time_unix_nano <= span.end_time_unix_nano
                and span.start_time_unix_nano > 0 and span.flags & 1 and not span.trace_state
                and not span.status.message and not span.events and not span.links
                and not span.dropped_attributes_count and not span.dropped_events_count
                and not span.dropped_links_count, 'invalid selected function span')
        spans[key] = span
    roots = sorted((key for key, span in spans.items() if not span.parent_span_id),
                   key=lambda key: spans[key].start_time_unix_nano)
    require(len(roots) == 4 and len(spans) == 4 * calls, 'wrong root or recursive-call denominator')
    require(len({spans[key].trace_id for key in roots}) == 4, 'independent selected roots reused a trace')
    require(all(spans[first].end_time_unix_nano <= spans[second].start_time_unix_nano
                for first, second in zip(roots, roots[1:])), 'selected roots overlap')
    children = {key: [] for key in spans}
    for key, span in spans.items():
        if span.parent_span_id:
            parent = (span.trace_id, span.parent_span_id)
            require(parent in spans and spans[parent].start_time_unix_nano <= span.start_time_unix_nano
                    <= span.end_time_unix_nano <= spans[parent].end_time_unix_nano,
                    'recursive child is unbound or outside its parent')
            children[parent].append(key)
    seen = set()
    for index, root in enumerate(roots):
        key = root
        for depth in range(calls):
            require(key not in seen, 'duplicate or cyclic selected call')
            seen.add(key)
            span = spans[key]
            error = failed and index == 1 and depth == 0
            same(span.status.code, 2 if error else 0)
            same(wire.attributes(span.attributes), {'function': name, **({'error.type': 'exception'} if error else {})})
            require(len(children[key]) == int(depth + 1 < calls), 'wrong recursive call-chain shape')
            if children[key]: key = children[key][0]
    require(seen == set(spans), 'unobserved selected spans')
    return len(spans)


def histogram(point) -> tuple:
    require(list(point.explicit_bounds) == wire.BOUNDS and len(point.bucket_counts) == len(wire.BOUNDS) + 1
            and sum(point.bucket_counts) == point.count and point.HasField('sum')
            and math.isfinite(point.sum) and point.sum >= 0, 'invalid native cumulative histogram')
    if not point.count:
        require(point.sum == 0 and (not point.HasField('min') or point.min == 0)
                and (not point.HasField('max') or point.max == 0), 'empty histogram has a sum or extrema')
        return point.count, tuple(point.bucket_counts), point.sum, 0., 0.
    require(point.HasField('min') and point.HasField('max') and math.isfinite(point.min)
            and math.isfinite(point.max) and 0 <= point.min <= point.max, 'missing histogram extrema')
    occupied = [index for index, count in enumerate(point.bucket_counts) if count]
    require(occupied[0] == bisect.bisect_left(wire.BOUNDS, point.min)
            and occupied[-1] == bisect.bisect_left(wire.BOUNDS, point.max), 'histogram extrema differ from buckets')
    result = point.count, tuple(point.bucket_counts), point.sum, point.min, point.max
    feasible.sample(result, wire.BOUNDS)
    return result


def metrics(bodies: list, language: str, service: str, name: str, count: int, errors: int) -> int:
    """Keep every sample; compare each visible prefix to independently known totals."""
    series, points = {}, 0
    instruments = {'otelc.function.calls': ('sum', '{call}'), 'otelc.function.errors': ('sum', '{error}'),
                   'otelc.function.duration': ('histogram', 's')}
    for metric in decoded(bodies, language, service, traces=False):
        require(metric.name in instruments, 'foreign metric instrument')
        kind, unit = instruments[metric.name]
        data = getattr(metric, kind)
        require(metric.WhichOneof('data') == kind and metric.unit == unit
                and data.aggregation_temporality == 2 and bool(data.data_points)
                and (kind != 'sum' or data.is_monotonic), 'invalid native metric type/unit/temporality')
        for point in data.data_points:
            same(wire.attributes(point.attributes), {'function': name,
                 **({'error.type': 'exception'} if metric.name.endswith('.errors') else {})})
            require(not point.flags and not point.exemplars
                    and 0 < point.start_time_unix_nano <= point.time_unix_nano, 'invalid metric point')
            if kind == 'histogram':
                sample = histogram(point)
            else:
                require(point.WhichOneof('value') == 'as_int' and point.as_int >= 0, 'invalid cumulative counter')
                sample = (point.as_int,)
            series.setdefault(metric.name, []).append((point.start_time_unix_nano, point.time_unix_nano, sample))
            points += 1
    require(points <= 65536, 'native metric point budget exceeded')
    wanted = {key: errors if key.endswith('.errors') else count for key in instruments}
    require(count > 0 or not points, 'uncollected prefix emitted measurements')
    if count: require({'otelc.function.calls', 'otelc.function.duration'} <= set(series), 'missing measurements')
    if errors: require('otelc.function.errors' in series, 'missing collected error')
    for instrument, rows in series.items():
        rows.sort()
        require(len({row[0] for row in rows}) == 1, 'cumulative start time reset')
        for first, second in zip(rows, rows[1:]):
            require(first[2][0] <= second[2][0] and (first[1] != second[1] or first == second),
                    'cumulative sample reset or contradictory duplicate')
            if instrument.endswith('.duration'):
                feasible.cumulative(first[2], second[2], wire.BOUNDS)
        require(rows[-1][2][0] == wanted[instrument], 'wrong independently expected function total')
    return points


def witness(bodies: list, name: str, total: int) -> dict:
    digest = hashlib.sha256()
    for route, body in bodies:
        digest.update(len(route).to_bytes(8, 'big') + route.encode() + len(body).to_bytes(8, 'big') + body)
    return {'decoder': 'native owned live controls, scalar frames and complete raw OTLP',
        'raw_otlp_sha256': digest.hexdigest(), 'functions': {name: total}, 'spans': total,
        'losses': {'function_lost': 0, 'metadata_errors': 0, 'queue_dropped': 0, 'diagnostic_dropped': 0}, 'pending': 0}
