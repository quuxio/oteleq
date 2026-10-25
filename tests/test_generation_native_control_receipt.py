"""Literal raw native OTLP distinguishes suppressed collection from retained emission."""

import copy
from pathlib import Path
import sys
import tempfile
import unittest
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[1]
sys.path[:0] = [str(ROOT / 'adapters/generation'), str(ROOT / 'examples')]

from opentelemetry.proto.collector.metrics.v1.metrics_service_pb2 import ExportMetricsServiceRequest
from opentelemetry.proto.collector.trace.v1.trace_service_pb2 import ExportTraceServiceRequest

import native_control_receipt as receipt
import native_telemetry
from test_generation_native_controls import status
from test_generation_native_execution import complete
from test_generation_native_live import Fixture
from test_generation_native_sequence import frame

NAME = 'selected.cpp::selected'


def labels(rows, values):
    for key, value in values.items(): rows.add(key=key).value.string_value = value


def resource(group, service):
    labels(group.resource.attributes, {'service.name': service, 'telemetry.sdk.language': 'cpp',
        'telemetry.sdk.name': 'opentelemetry', 'telemetry.sdk.version': '1.30.0', 'otelc.language': 'cpp'})


class Signals:
    """Authored wire values and arithmetic do not use the production telemetry reader."""

    def __init__(self, value, error_steps):
        self.value, self.collected, self.errors = value, [], set(error_steps)
        self.metrics = self.traces = self.clock = 0
        self.original_request = value.sdk.request
        self.service = value.owner.launch.intent.policy()['resource']['service_name']

    def called(self, index):
        message = ExportTraceServiceRequest()
        group = message.resource_spans.add(); resource(group, self.service)
        scope = group.scope_spans.add(); scope.scope.name = native_telemetry.SCOPE
        span = scope.spans.add(name=NAME, kind=1, flags=1, trace_id=bytes([index + 1]) * 16,
            span_id=bytes([index + 1]) * 8, start_time_unix_nano=100 * (index + 1),
            end_time_unix_nano=100 * (index + 1) + 20)
        labels(span.attributes, {'function': NAME})
        if index in self.errors:
            span.status.code = 2; labels(span.attributes, {'error.type': 'exception'})
        self.value.bodies.append(('/v1/traces', message.SerializeToString()))
        self.traces += 1
        if self.value.live.sequence()[index]['metrics']['collection']: self.collected.append(index)

    def metric(self):
        message = ExportMetricsServiceRequest()
        group = message.resource_metrics.add(); resource(group, self.service)
        scope = group.scope_metrics.add(); scope.scope.name = native_telemetry.SCOPE
        self.clock += 1
        bounds = self.value.owner.launch.intent.policy()['metrics']['histogram_boundaries_seconds']
        for name, unit in (('calls', '{call}'), ('errors', '{error}'), ('duration', 's')):
            item = scope.metrics.add(name='otelc.function.' + name, unit=unit)
            data = item.histogram if name == 'duration' else item.sum
            data.aggregation_temporality = 2
            point = data.data_points.add(start_time_unix_nano=1, time_unix_nano=1000 + self.clock)
            labels(point.attributes, {'function': NAME})
            if name == 'duration':
                point.count = len(self.collected); point.sum = .01 * point.count; point.min = point.max = .01
                point.explicit_bounds.extend(bounds)
                buckets = [0] * (len(bounds) + 1); buckets[bounds.index(.01)] = point.count
                point.bucket_counts.extend(buckets)
            else:
                data.is_monotonic = True
                point.as_int = len(set(self.collected) & self.errors) if name == 'errors' else len(self.collected)
                if name == 'errors': labels(point.attributes, {'error.type': 'exception'})
        self.value.bodies.append(('/v1/metrics', message.SerializeToString()))
        self.metrics += 1

    def exports(self, value):
        for name, batches, units in (('trace_exports', self.traces, self.traces),
                                     ('metric_exports', self.metrics, 3 * self.metrics)):
            value[name].update(batches_started=str(batches), batches_succeeded=str(batches),
                               units_started=str(units), units_succeeded=str(units))

    def request(self, command, deadline):
        if command == 'flush' and all(self.value.sdk.flags.values()) and self.collected: self.metric()
        value = self.original_request(command, deadline)
        if command == 'health': self.exports(value)
        return value

    def complete(self, started):
        value = complete(started)
        if value['sdk_health'] is not None: self.exports(value['sdk_health'])
        return value


class NativeControlReceiptTests(unittest.TestCase):
    def test_complete_sampling_keeps_exact_numeric_one_and_refuses_nearby_or_boolean_values(self):
        for ratio in (1, 1.):
            receipt.complete_sampling({'traces': {'enabled': True, 'sample_ratio': ratio}})
        for ratio in (True, False, 0, 1 << 4096, .9999999999999999, 1.0000000000000002, '1', None,
                      float('nan'), float('inf')):
            policy = {'traces': {'enabled': True, 'sample_ratio': ratio}}
            with self.subTest(ratio=ratio), self.assertRaises(ValueError):
                receipt.complete_sampling(policy)
        for enabled in (False, 1):
            policy = {'traces': {'enabled': enabled, 'sample_ratio': 1.}}
            with self.subTest(enabled=enabled), self.assertRaises(ValueError):
                receipt.complete_sampling(policy)

    def capture(self, base, *, error_steps=(2,), plain=False):
        value = Fixture(Path(base).resolve(), error_steps=error_steps, plain=plain)
        self.addCleanup(value.close)
        signals = Signals(value, error_steps)
        with patch.object(value.sdk, 'request', side_effect=signals.request):
            while value.live.checkpoints.position < len(value.live.checkpoints.phases):
                phase = value.live.checkpoints.phases[value.live.checkpoints.position]
                raw = None
                if phase.startswith('after-'):
                    index = int(phase.split('-')[1])
                    if not plain: signals.called(index)
                    raw = frame(10 + index, 11 + index, error=b'retained\nafter\x00error' if index in error_steps else None)
                value.phase(raw=raw)
            with patch('test_generation_native_live.complete', side_effect=signals.complete): completed = value.finish()
        return value, completed, signals

    def witness(self, value, completed, bodies=None, service=None):
        return receipt.witness(completed, value.live, value.bodies if bodies is None else bodies,
            service or value.owner.launch.intent.policy()['resource']['service_name'],
            (NAME,) * len(value.live.sequence()), value.live.folder)

    def test_complete_raw_receipt_counts_all_traces_but_only_collected_measurements(self):
        with tempfile.TemporaryDirectory() as base:
            value, completed, signals = self.capture(base)
            observed = self.witness(value, completed)
            self.assertEqual(observed['functions'], {NAME: 4})
            self.assertEqual(observed['spans'], 4)
            import json
            verified = json.loads((value.live.folder / 'native-verified-controls.json').read_bytes())
            self.assertEqual(verified['collected_functions'], {NAME: 2})
            self.assertEqual(verified['collected_errors'], {NAME: 1})
            self.assertEqual(verified['metric_points'], 3 * signals.metrics)
            self.assertFalse(value.live.record['steps'][2]['after']['metric_bodies'])
            self.assertEqual(value.live.record['restored']['cursor'], len(value.bodies))

    def test_plain_same_schedule_has_no_sdk_evidence_and_foreign_service_refuses(self):
        with tempfile.TemporaryDirectory() as base:
            value, completed, _ = self.capture(base, plain=True)
            self.assertIsNone(self.witness(value, completed))
            with self.assertRaises(ValueError): self.witness(value, completed, bodies=[('/v1/traces', b'foreign')])
            with self.assertRaises(ValueError): self.witness(value, completed, service='foreign-service')

    def test_changed_metric_totals_missing_roots_and_raw_root_error_disagreement_refuse(self):
        for kind in ('count', 'missing', 'error', 'route'):
            with self.subTest(kind=kind), tempfile.TemporaryDirectory() as base:
                value, completed, _ = self.capture(base)
                bodies = copy.deepcopy(value.bodies)
                if kind == 'count':
                    index = next(i for i, (route, _) in enumerate(bodies) if route == '/v1/metrics')
                    message = ExportMetricsServiceRequest.FromString(bodies[index][1])
                    message.resource_metrics[0].scope_metrics[0].metrics[0].sum.data_points[0].as_int += 1
                    bodies[index] = ('/v1/metrics', message.SerializeToString())
                elif kind == 'missing': bodies = [row for row in bodies if row[0] != '/v1/traces']
                elif kind == 'route': bodies[0] = ('/v1/foreign', bodies[0][1])
                else:
                    message = ExportTraceServiceRequest.FromString(bodies[0][1])
                    span = message.resource_spans[0].scope_spans[0].spans[0]
                    span.status.code = 2; labels(span.attributes, {'error.type': 'exception'})
                    bodies[0] = ('/v1/traces', message.SerializeToString())
                with self.assertRaises(ValueError): self.witness(value, completed, bodies=bodies)
                value.close()

    def test_independent_transition_replies_retain_initial_flags_and_exact_setter_order(self):
        before = {'collection': True, 'emission': True}; after = {'collection': False, 'emission': False}
        rows = [{'command': 'status', 'status': status()},
                {'command': 'collection off', 'status': status(False, True, False)},
                {'command': 'emission off', 'status': status(False, False, False)},
                {'command': 'status', 'status': status(False, False)}]
        receipt.transition(rows, 23, after, before)
        for kind in ('empty', 'missing', 'order', 'flag', 'barrier'):
            changed = copy.deepcopy(rows)
            if kind == 'empty': changed = []
            elif kind == 'missing': changed = changed[:2]
            elif kind == 'order': changed[1]['command'] = 'emission off'
            elif kind == 'flag': changed[1]['status']['emission'] = False
            else: changed[-1]['status']['effective_emission_off'] = False
            with self.subTest(kind=kind), self.assertRaises(ValueError): receipt.transition(changed, 23, after, before)

    def test_recursive_children_stay_with_their_original_ordered_root(self):
        from test_generation_native_telemetry import messages, NAME as recursive_name
        trace, _ = messages()
        spans, _ = native_telemetry.function_graph(iter(trace.resource_spans[0].scope_spans[0].spans),
                                                  (recursive_name, recursive_name))
        groups = receipt.call_trees(spans, [{'outcome': {'kind': 'return'}}] * 2)
        self.assertEqual([len(group) for group in groups], [2, 1])


if __name__ == '__main__':
    unittest.main()
