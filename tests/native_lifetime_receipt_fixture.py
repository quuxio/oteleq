"""Literal lifecycle protobufs and prelaunch records; no SDK process is executed."""

from collections import Counter
from pathlib import Path
from unittest.mock import patch

from opentelemetry.proto.collector.metrics.v1.metrics_service_pb2 import ExportMetricsServiceRequest
from opentelemetry.proto.collector.trace.v1.trace_service_pb2 import ExportTraceServiceRequest

import native_lifetime_intent as caller
import native_provider_fixture as fixed
from test_generation_native_lifetime_execution import setup, checkpoint, completed

NAME = 'work.cpp::workload(int)'
SERVICE = 'native-telemetry-unit'
BOUNDS = [1e-6, 1e-5, .0001, .001, .01, .1, 1.]


def labels(rows, values):
    for key, value in values.items():
        row = rows.add(key=key)
        if type(value) is bool:
            row.value.bool_value = value
        else:
            row.value.string_value = value


def resource(group, kind):
    labels(group.resource.attributes, {'service.name': SERVICE, 'telemetry.sdk.language': 'cpp',
        'telemetry.sdk.name': 'opentelemetry', 'telemetry.sdk.version': '1.30.0',
        'otelc.language': 'cpp' if kind == 'object' else 'c'})


def messages(kind, roots, observations):
    trace = ExportTraceServiceRequest()
    group = trace.resource_spans.add(); resource(group, kind)
    scope = group.scope_spans.add(); scope.scope.name = 'io.quux.otelc.native'
    for index, name in enumerate(roots, 1):
        span = scope.spans.add(name=name, kind=1, trace_id=bytes([index]) * 16,
            span_id=bytes([index]) * 8, flags=3,
            start_time_unix_nano=10 + (index-1) * 100, end_time_unix_nano=90 + (index-1) * 100)
        labels(span.attributes, {'function': name})
    boundary = 'destructor_entry' if kind == 'object' else 'free_entry'
    counts, durations = Counter(), {}
    for index, observation in enumerate(observations, 1):
        creation = observation.creation_path[0]
        release = observation.release_path[0] if observation.complete else None
        end = boundary if observation.complete else 'shutdown_censored'
        start_time = 20 + creation * 100
        end_time = 60 + release * 100 if release is not None else len(roots) * 100 + 40
        span = scope.spans.add(name=observation.name + ' lifetime', kind=1,
            trace_id=bytes([10 + index]) * 16, span_id=bytes([10 + index]) * 8, flags=3,
            start_time_unix_nano=start_time, end_time_unix_nano=end_time)
        values = {'type': observation.name, 'boundary': end, 'otelc.lifetime.complete': observation.complete,
                  'otelc.lifetime.instance': str(index)}
        if observation.exception_exit is not None:
            values['otelc.destructor.exception_exit'] = observation.exception_exit
        labels(span.attributes, values)
        span.links.add(trace_id=bytes([creation + 1]) * 16, span_id=bytes([creation + 1]) * 8)
        counts['otelc.lifetime.admitted', observation.name, boundary] += 1
        counts['otelc.lifetime.completed' if observation.complete else 'otelc.lifetime.incomplete',
               observation.name, end] += 1
        counts['otelc.lifetime.live', observation.name, boundary] = 0
        durations.setdefault((observation.name, end), []).append((end_time-start_time)/1_000_000_000)
    metric = ExportMetricsServiceRequest()
    group = metric.resource_metrics.add(); resource(group, kind)
    scope = group.scope_metrics.add(); scope.scope.name = 'io.quux.otelc.native'

    def instrument(name, unit, values, count=None, times=None):
        entry = scope.metrics.add(name=name, unit=unit)
        data = entry.histogram if times is not None else entry.gauge if name.endswith('.live') else entry.sum
        if not name.endswith('.live'):
            data.aggregation_temporality = 2
        point = data.data_points.add(start_time_unix_nano=1, time_unix_nano=1000)
        labels(point.attributes, values)
        if times is not None:
            point.count, point.sum, point.min, point.max = len(times), sum(times), min(times), max(times)
            point.explicit_bounds.extend(BOUNDS)
            buckets = [0] * (len(BOUNDS) + 1)
            for value in times:
                index = next((index for index, bound in enumerate(BOUNDS) if value <= bound), len(BOUNDS))
                buckets[index] += 1
            point.bucket_counts.extend(buckets)
        else:
            point.as_int = count
            if not name.endswith('.live'):
                data.is_monotonic = True

    for name, count in Counter(roots).items():
        instrument('otelc.function.calls', '{call}', {'function': name}, count=count)
        instrument('otelc.function.duration', 's', {'function': name}, times=[.01] * count)
    for (name, type_name, end), count in counts.items():
        instrument(name, '{object}', {'type': type_name, 'boundary': end}, count=count)
    for (type_name, end), values in durations.items():
        instrument('otelc.lifetime.duration', 's', {'type': type_name, 'boundary': end}, times=values)
    return trace, metric


def fixture(root: Path, *, kind='object', plain=False, collection=True, emission=True,
            observations=None, roots=(NAME,), health_change=None):
    if observations is None:
        observations = (caller.Observation('c:@S@Item', 'Item', (0,), (0,), True,
                                          False if kind == 'object' else None),)
    additions = {'traces': {'enabled': True, 'sample_ratio': 1.0},
                 'metrics': {'collection': collection, 'emission': emission,
                             'histogram_boundaries_seconds': BOUNDS}}
    with patch.dict(fixed.POLICY, additions):
        launch = setup(root, kind, plain=plain)
    intent = caller.freeze(launch, root / 'expected-lifetimes.json', roots, observations)
    trace, metric = messages(kind, roots, observations)
    enabled = collection and emission
    points = sum(len(getattr(value, value.WhichOneof('data')).data_points)
                 for value in metric.resource_metrics[0].scope_metrics[0].metrics) if enabled else 0
    value = None
    if not plain:
        value = checkpoint(launch)
        value[kind + '_accounting'].update(types=str(len({row.type_usr for row in observations})),
            admitted=str(len(observations)), completed=str(sum(row.complete for row in observations)),
            censored=str(sum(not row.complete for row in observations)))
        value['controls'].update(collection=collection, emission=emission,
                                 effective_emission_off=not enabled)
        value['function_accounting'].update(registered=str(len(set(roots))), started=str(len(roots)), ended=str(len(roots)))
        spans = len(roots) + len(observations)
        value['span_accounting'].update(sampled_started=str(spans), sampled_ended=str(spans))
        value['trace_exports'].update(units_started=str(spans), units_succeeded=str(spans))
        value['metric_exports'].update(units_started=str(points), units_succeeded=str(points))
        if health_change is not None:
            health_change(value)
    final = completed(launch, value)
    bodies = [] if plain else [('/v1/traces', trace.SerializeToString())]
    if enabled and not plain:
        bodies.append(('/v1/metrics', metric.SerializeToString()))
    return final, intent, bodies, trace, metric
