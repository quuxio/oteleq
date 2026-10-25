"""Literal native protobuf observations and independent owned completion controls."""

import json
import math
from pathlib import Path
import sys
import tempfile
import unittest
from unittest.mock import patch

from opentelemetry.proto.collector.metrics.v1.metrics_service_pb2 import ExportMetricsServiceRequest
from opentelemetry.proto.collector.trace.v1.trace_service_pb2 import ExportTraceServiceRequest

ROOT = Path(__file__).resolve().parents[1]
sys.path[:0] = [str(ROOT / 'adapters/generation'), str(ROOT / 'examples')]
import native_execution
import native_provider_fixture as fixture
import native_telemetry as receipt
from test_generation_native_execution import complete, start, write

NAME = 'unit0.cpp::workload(int)'
SERVICE = 'native-telemetry-unit'
BOUNDS = [1e-6, 1e-5, .0001, .001, .01, .1, 1.]


def labels(rows, values):
    for key, value in values.items(): rows.add(key=key).value.string_value = value


def resource(group):
    labels(group.resource.attributes, {'service.name': SERVICE, 'telemetry.sdk.language': 'cpp',
        'telemetry.sdk.name': 'opentelemetry', 'telemetry.sdk.version': '1.30.0', 'otelc.language': 'cpp'})


def messages():
    traces = ExportTraceServiceRequest(); group = traces.resource_spans.add(); resource(group)
    scope = group.scope_spans.add(); scope.scope.name = 'io.quux.otelc.native'
    for index, (trace, parent, begin, end) in enumerate(((1, None, 10, 40), (1, 1, 20, 30), (2, None, 50, 60))):
        span = scope.spans.add(name=NAME, kind=1, trace_id=bytes([trace]) * 16,
            span_id=bytes([index + 1]) * 8, start_time_unix_nano=begin, end_time_unix_nano=end, flags=3)
        if parent: span.parent_span_id = bytes([parent]) * 8
        labels(span.attributes, {'function': NAME})
        if index == 1: span.status.code = 2; labels(span.attributes, {'error.type': 'exception'})
    metrics = ExportMetricsServiceRequest(); group = metrics.resource_metrics.add(); resource(group)
    scope = group.scope_metrics.add(); scope.scope.name = 'io.quux.otelc.native'
    for name, unit in (('calls', '{call}'), ('duration', 's'), ('errors', '{error}')):
        metric = scope.metrics.add(name='otelc.function.' + name, unit=unit)
        data = metric.histogram if name == 'duration' else metric.sum; data.aggregation_temporality = 2
        point = data.data_points.add(start_time_unix_nano=1, time_unix_nano=100)
        labels(point.attributes, {'function': NAME})
        if name == 'duration':
            point.count = 3; point.sum = .03; point.min = .01; point.max = .01
            point.explicit_bounds.extend(BOUNDS); point.bucket_counts.extend([0, 0, 0, 0, 3, 0, 0, 0])
        else:
            metric.sum.is_monotonic = True; point.as_int = 1 if name == 'errors' else 3
            if name == 'errors': labels(point.attributes, {'error.type': 'exception'})
    return traces, metrics


def bodies(traces=None, metrics=None):
    trace, metric = messages()
    return [('/v1/traces', (traces or trace).SerializeToString()),
            ('/v1/metrics', (metrics or metric).SerializeToString())]


def metric_prefix(values, timestamp, bounds=BOUNDS):
    """Aggregate concrete observations independently of the production reader."""
    _, message = messages()
    scope = message.resource_metrics[0].scope_metrics[0]
    scope.metrics[0].sum.data_points[0].as_int = len(values)
    for instrument in scope.metrics:
        data = instrument.histogram if instrument.name == receipt.DURATION else instrument.sum
        data.data_points[0].time_unix_nano = timestamp
    point = scope.metrics[1].histogram.data_points[0]
    point.count, point.sum, point.min, point.max = len(values), sum(values), min(values), max(values)
    point.explicit_bounds[:] = bounds
    buckets = [0] * (len(bounds) + 1)
    for value in values:
        index = next((index for index, boundary in enumerate(bounds) if value <= boundary), len(bounds))
        buckets[index] += 1
    point.bucket_counts[:] = buckets
    return message


def execution(root, *, plain=False, collection=True, emission=True):
    values = {'traces': {'enabled': True, 'sample_ratio': 1.0},
              'metrics': {'collection': collection, 'emission': emission, 'histogram_boundaries_seconds': BOUNDS}}
    with patch.dict(fixture.POLICY, values):
        launch, owner = start(root, plain=plain)
    bound = native_execution.bind(launch, owner); final = complete(bound)
    if not plain:
        health = final['sdk_health']
        health['controls'].update(collection=collection, emission=emission,
                                  effective_emission_off=not (collection and emission))
        if not collection or not emission:
            health['metric_exports'].update(units_started='0', units_succeeded='0')
        write(launch.intent.runtime / 'app/health.json', health)
        write(launch.intent.runtime / 'native-execution.json', final)
    return native_execution.finish(bound, 0)


class NativeTelemetryTests(unittest.TestCase):
    def test_service_argument_and_both_resources_cannot_replace_prepared_service(self):
        with tempfile.TemporaryDirectory() as temporary:
            completed = execution(Path(temporary).resolve())
            trace, metric = messages()
            for group in (trace.resource_spans[0], metric.resource_metrics[0]):
                group.resource.attributes[0].value.string_value = 'foreign-service'
            with self.assertRaises(ValueError):
                receipt.witness(completed, bodies(trace, metric), 'foreign-service', (NAME, NAME))

    def test_impossible_histogram_sum_and_decreasing_cumulative_sum_refuse(self):
        trace, metric = messages()
        histogram = metric.resource_metrics[0].scope_metrics[0].metrics[1].histogram.data_points[0]
        histogram.sum = 1000
        with self.subTest(kind='impossible-single-sum'), self.assertRaises(ValueError):
            receipt.metrics(bodies(trace, metric), 'cpp', SERVICE, {NAME: 3}, {NAME: 1}, BOUNDS, True)
        trace, previous = messages(); _, current = messages()
        scope = current.resource_metrics[0].scope_metrics[0]
        for instrument in scope.metrics:
            data = instrument.histogram if instrument.name == receipt.DURATION else instrument.sum
            data.data_points[0].time_unix_nano = 200
        scope.metrics[0].sum.data_points[0].as_int = 6
        histogram = scope.metrics[1].histogram.data_points[0]
        histogram.count, histogram.sum, histogram.min = 6, .02, .0015
        histogram.bucket_counts[4] = 6
        payload = [('/v1/metrics', value.SerializeToString()) for value in (current, previous)]
        with self.subTest(kind='decreasing-cumulative-sum'), self.assertRaises(ValueError):
            receipt.metrics(payload, 'cpp', SERVICE, {NAME: 6}, {NAME: 1}, BOUNDS, True)

    def test_real_histogram_prefixes_rounding_and_selected_boundaries_are_accepted(self):
        values = [0., math.ulp(0.), 1e-6, math.nextafter(.01, math.inf), .1, .1, .1, 1e300]
        payload = [('/v1/metrics', metric_prefix(values[:count], count + 100).SerializeToString())
                   for count in range(1, len(values) + 1)]
        self.assertEqual(receipt.metrics(list(reversed(payload)), 'cpp', SERVICE,
            {NAME: len(values)}, {NAME: 1}, BOUNDS, True), 3 * len(values))
        repeated = [('/v1/metrics', metric_prefix([.1] * 3, timestamp).SerializeToString())
                    for timestamp in (100, 200)]
        self.assertEqual(receipt.metrics(repeated, 'cpp', SERVICE, {NAME: 3}, {NAME: 1}, BOUNDS, True), 6)
        custom = [.02, .3]
        payload = [('/v1/metrics', metric_prefix([.01, .1, .2], 100, custom).SerializeToString())]
        self.assertEqual(receipt.metrics(payload, 'cpp', SERVICE, {NAME: 3}, {NAME: 1}, custom, True), 3)

    def test_histogram_bucket_extrema_and_added_sum_regressions_refuse(self):
        for kind in ('bucket-regression', 'lost-extreme', 'no-new-observations', 'added-sum-high', 'added-sum-low'):
            previous = metric_prefix([.01] * 3, 100)
            current = metric_prefix([.01, .01, .03, .03, .03, .03], 200)
            if kind == 'lost-extreme':
                previous = metric_prefix([.004, .01, .01], 100)
                current = metric_prefix([.005] * 5 + [.01], 200)
            elif kind == 'no-new-observations':
                current = metric_prefix([.01] * 3, 200)
                current.resource_metrics[0].scope_metrics[0].metrics[1].histogram.data_points[0].sum = math.nextafter(.03, math.inf)
            elif kind.startswith('added-sum'):
                previous = metric_prefix([.002, .004, .01], 100)
                current = metric_prefix([.002] * 5 + [.01], 200)
                current.resource_metrics[0].scope_metrics[0].metrics[1].histogram.data_points[0].sum = .05 if kind.endswith('high') else .02
            count = current.resource_metrics[0].scope_metrics[0].metrics[0].sum.data_points[0].as_int
            payload = [('/v1/metrics', message.SerializeToString()) for message in (previous, current)]
            with self.subTest(kind=kind), self.assertRaises(ValueError):
                receipt.metrics(payload, 'cpp', SERVICE, {NAME: count}, {NAME: 1}, BOUNDS, True)

    def test_complete_recursive_call_trees_and_metrics_join_owned_completion(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary).resolve(); completed = execution(root)
            value = receipt.witness(completed, bodies(), SERVICE, (NAME, NAME), folder=root)
            self.assertEqual(value['functions'], {NAME: 3})
            self.assertEqual(value['spans'], 3)
            self.assertEqual(value['pending'], 0)
            saved = json.loads((root / 'native-verified-telemetry.json').read_bytes())
            self.assertEqual(saved['received'], {'spans': 3, 'metric_points': 3, 'trace_requests': 1, 'metric_requests': 1})
            # Two successful SDK API batches can include one empty export;
            # final units, rather than API-batch count, join literal receipt.
            self.assertEqual(saved['health']['metric_exports']['batches_succeeded'], '2')

    def test_plain_absence_and_all_fixed_metric_startups_keep_traces_independent(self):
        with tempfile.TemporaryDirectory() as temporary:
            completed = execution(Path(temporary).resolve(), plain=True)
            self.assertIsNone(receipt.witness(completed, [], SERVICE, (NAME, NAME)))
            with self.assertRaises(ValueError): receipt.witness(completed, bodies(), SERVICE, (NAME, NAME))
        for collection, emission in ((False, True), (True, False), (False, False)):
            with self.subTest(collection=collection, emission=emission), tempfile.TemporaryDirectory() as temporary:
                completed = execution(Path(temporary).resolve(), collection=collection, emission=emission)
                value = receipt.witness(completed, bodies()[:1], SERVICE, (NAME, NAME))
                self.assertEqual(value['spans'], 3)
                with self.assertRaises(ValueError): receipt.witness(completed, bodies(), SERVICE, (NAME, NAME))

    def test_resource_scope_missing_or_duplicate_call_and_causal_corruption_refuse(self):
        for kind in ('resource', 'scope', 'missing', 'duplicate', 'foreign', 'parent', 'cycle', 'time', 'error', 'labels', 'dropped', 'flags'):
            trace, metric = messages(); group = trace.resource_spans[0]; scope = group.scope_spans[0]
            span = scope.spans[1]
            if kind == 'resource': group.resource.attributes[0].value.string_value = 'foreign-service'
            elif kind == 'scope': scope.scope.name = 'foreign-scope'
            elif kind == 'missing': del scope.spans[-1]
            elif kind == 'duplicate': scope.spans.add().CopyFrom(span)
            elif kind == 'foreign': span.name = 'foreign-call'
            elif kind == 'parent': span.parent_span_id = b'x' * 8
            elif kind == 'cycle': scope.spans[0].parent_span_id = span.span_id
            elif kind == 'time': span.end_time_unix_nano = 45
            elif kind == 'error': span.attributes[1].value.string_value = 'unknown'
            elif kind == 'labels': labels(span.attributes, {'function': NAME})
            elif kind == 'dropped': span.dropped_events_count = 1
            else: span.flags = 0
            with self.subTest(kind=kind), self.assertRaises(ValueError):
                receipt.traces(bodies(trace, metric), 'cpp', SERVICE, (NAME, NAME))

    def test_metric_types_cumulative_totals_and_histogram_integrity_refuse_changes(self):
        for kind in ('count', 'error', 'kind', 'unit', 'temporality', 'label', 'bounds', 'buckets', 'sum', 'extrema', 'exemplar', 'timestamp', 'duplicate'):
            trace, metric = messages(); scope = metric.resource_metrics[0].scope_metrics[0]
            histogram = scope.metrics[1].histogram.data_points[0]
            if kind == 'count': scope.metrics[0].sum.data_points[0].as_int = 2
            elif kind == 'error': scope.metrics[2].sum.data_points[0].as_int = 0
            elif kind == 'kind': scope.metrics[0].ClearField('sum'); scope.metrics[0].gauge.data_points.add(as_int=3)
            elif kind == 'unit': scope.metrics[0].unit = 'wrong'
            elif kind == 'temporality': scope.metrics[0].sum.aggregation_temporality = 1
            elif kind == 'label': labels(histogram.attributes, {'extra': 'field'})
            elif kind == 'bounds': histogram.explicit_bounds[0] = .2
            elif kind == 'buckets': histogram.bucket_counts[0] = 1
            elif kind == 'sum': histogram.sum = float('nan')
            elif kind == 'extrema': histogram.ClearField('min')
            elif kind == 'exemplar': histogram.exemplars.add(as_double=.01)
            elif kind == 'timestamp': histogram.start_time_unix_nano = 101
            else: scope.metrics[0].sum.data_points.add().CopyFrom(scope.metrics[0].sum.data_points[0])
            with self.subTest(kind=kind), self.assertRaises(ValueError):
                receipt.metrics(bodies(trace, metric), 'cpp', SERVICE, {NAME: 3}, {NAME: 1}, BOUNDS, True)

    def test_unknown_routes_malformed_payloads_roots_and_final_unit_changes_refuse(self):
        with tempfile.TemporaryDirectory() as temporary:
            completed = execution(Path(temporary).resolve())
            for roots in ((), [NAME], ('foreign',), (True,)):
                with self.subTest(roots=roots), self.assertRaises(ValueError):
                    receipt.witness(completed, bodies(), SERVICE, roots)
            for raw in ([('/unexpected', b'x')], [('/v1/traces', b'\xff')], [('/v1/traces', b'')]):
                with self.subTest(raw=raw), self.assertRaises(ValueError):
                    receipt.witness(completed, raw, SERVICE, (NAME, NAME))
            # Original health bytes/facts are held; a matching rehashed final
            # document cannot repair this accepted execution.
            path = completed.health.file.path; value = completed.health.value()
            value['metric_exports']['units_started'] = value['metric_exports']['units_succeeded'] = '4'
            write(path, value)
            with self.assertRaises(ValueError): receipt.witness(completed, bodies(), SERVICE, (NAME, NAME))


if __name__ == '__main__':
    unittest.main()
