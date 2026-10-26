"""Independent literal Rust call intent, protobuf receipt and closed-health checks."""

import copy
import json
from pathlib import Path
import sys
import unittest

ROOT = Path(__file__).resolve().parents[1]
sys.path[:0] = [str(ROOT / 'adapters/generation'), str(ROOT / 'examples')]
import rust_execution as execution
import rust_prepared as prepared
import rust_telemetry as receipt
import test_generation_native_telemetry as protobuf
import test_generation_rust_execution as literal
import test_generation_rust_prepared as preparation


def messages(name: str, service: str, bounds: list):
    """Author ordinary Rust resources independently of the production decoder."""
    traces, metrics = protobuf.messages()
    for group in (traces.resource_spans[0], metrics.resource_metrics[0]):
        for attribute in group.resource.attributes:
            if attribute.key == 'otelc.language': attribute.value.string_value = 'rust'
            if attribute.key == 'service.name': attribute.value.string_value = service
    for span in traces.resource_spans[0].scope_spans[0].spans:
        span.name = name
        next(a for a in span.attributes if a.key == 'function').value.string_value = name
    for metric in metrics.resource_metrics[0].scope_metrics[0].metrics:
        for point in getattr(metric, metric.WhichOneof('data')).data_points:
            next(a for a in point.attributes if a.key == 'function').value.string_value = name
            if metric.WhichOneof('data') == 'histogram':
                point.explicit_bounds[:] = bounds
                buckets = [0] * (len(bounds) + 1)
                buckets[next((i for i, bound in enumerate(bounds) if .01 <= bound), len(bounds))] = 3
                point.bucket_counts[:] = buckets
    return traces, metrics


def bodies(traces, metrics=None):
    result = [('/v1/traces', traces.SerializeToString())]
    if metrics is not None: result.append(('/v1/metrics', metrics.SerializeToString()))
    return result


class RustTelemetryTests(unittest.TestCase):
    def fixture(self, *, collection=True, emission=True, plain=False, lifetime=False):
        helper = preparation.RustPreparedTests('test_both_source_profiles_and_lanes_hold_literal_arguments_without_processes')
        self.addCleanup(helper.doCleanups)
        original, initial = helper.fixture(lifetime=lifetime, plain=plain)
        policy = initial.policy()
        policy['metrics'].update(collection=collection, emission=emission)
        path = initial.policy_file.path
        lines = ['schema_version=3', 'languages=["rust"]']
        for name, values in policy.items():
            if type(values) is dict:
                lines += ['[' + name + ']', *[key + '=' + json.dumps(value) for key, value in values.items()]]
        path.write_text('\n'.join(lines) + '\n')
        intent = prepared.freeze(initial.build, initial.runtime, initial.python.path, path, policy,
                                 plain=plain, wait_ms=12345)
        helper.publish(intent)
        launch = prepared.read(intent)
        name = intent.source().intent.selected()[0]
        roots = (name, name)
        traces, metrics = messages(name, policy['resource']['service_name'],
                                   policy['metrics']['histogram_boundaries_seconds'])
        health = literal.health(intent)
        health['controls'].update(collection=collection, emission=emission,
                                  effective_emission_off=not (collection and emission))
        count = '3' if collection and emission else '0'
        health['metric_exports'].update(units_started=count, units_succeeded=count)
        return original, launch, roots, health, traces, metrics

    def complete(self, launch, health):
        owner = execution.Owner(22, 21, 23, tuple(prepared.command(launch)))
        for name, value in zip(execution.START_FILES,
                              (execution.supervisor(launch, owner), execution.application(launch, owner)), strict=True):
            literal.publish(launch.intent.runtime / name, value)
        started = execution.bind(launch, owner)
        helper = literal.RustExecutionTests()
        final = helper.complete(started)
        if not launch.intent.plain:
            literal.publish(launch.intent.runtime / 'app/health.json', health)
            final['sdk_health'] = health
            literal.publish(launch.intent.runtime / execution.FINAL, final)
        return execution.finish(started, 0)

    def test_all_four_fixed_states_join_prelaunch_calls_closed_health_and_actual_point_units(self):
        for collection, emission in ((True, True), (False, True), (True, False), (False, False)):
            with self.subTest(collection=collection, emission=emission):
                source, launch, roots, health, traces, metrics = self.fixture(collection=collection, emission=emission)
                intent = receipt.freeze(launch, roots, source.base / 'call-intent.json')
                completed = self.complete(launch, health)
                result = receipt.witness(completed, intent, bodies(traces, metrics if collection and emission else None))
                self.assertEqual(result['functions'], {roots[0]: 3})
                self.assertEqual(result['spans'], 3)
                self.assertEqual(result['metric_points'], 3 if collection and emission else 0)
                self.assertEqual(result['sdk_pid'], 23)
                self.assertEqual(result['received']['trace_requests'], 1)
                self.assertEqual(result['caller_intent'], intent.record.file.gate_identity())
                self.assertEqual(len(result['raw_otlp_sha256']), 64)

    def test_plain_lane_requires_no_sdk_health_or_wire_evidence(self):
        source, launch, roots, health, traces, metrics = self.fixture(plain=True)
        intent = receipt.freeze(launch, roots, source.base / 'call-intent.json')
        completed = self.complete(launch, health)
        self.assertIsNone(receipt.witness(completed, intent, []))
        for value in (None, (), bodies(traces, metrics)):
            with self.subTest(value=type(value).__name__), self.assertRaises(ValueError):
                receipt.witness(completed, intent, value)

    def test_call_intent_refuses_unknown_roots_used_runtime_protected_paths_and_restoration(self):
        source, launch, roots, health, _, _ = self.fixture()
        for value in ((), ['foreign'], ('foreign',), (True,), roots * 33):
            with self.subTest(roots=value), self.assertRaises(ValueError):
                receipt.expected(launch, value)
        with self.assertRaises(ValueError): receipt.expected(None, roots)
        for path in (source.project / 'intent.json', launch.intent.runtime / 'intent.json',
                     source.base / 'missing/intent.json', Path('intent.json')):
            with self.subTest(path=path), self.assertRaises((ValueError, FileNotFoundError)):
                receipt.freeze(launch, roots, path)
        path = source.base / 'call-intent.json'
        intent = receipt.freeze(launch, roots, path)
        with self.assertRaises(ValueError): receipt.freeze(launch, roots, path)
        raw = path.read_bytes(); path.write_bytes(raw)
        with self.assertRaises(ValueError): intent.verify()
        self.complete(launch, health)
        with self.assertRaises(ValueError): receipt.freeze(launch, roots, source.base / 'late-intent.json')

    def test_drop_profiles_and_foreign_owned_completion_cannot_be_relabelled_as_function_receipt(self):
        _, launch, roots, _, _, _ = self.fixture(lifetime=True)
        with self.assertRaisesRegex(ValueError, 'lifetime observations'): receipt.expected(launch, roots)
        with self.assertRaises(ValueError): receipt.witness(None, None, [])
        source, launch, roots, health, traces, metrics = self.fixture()
        intent = receipt.freeze(launch, roots, source.base / 'call-intent.json')
        _, foreign, _, foreign_health, _, _ = self.fixture()
        with self.assertRaises(ValueError):
            receipt.witness(self.complete(foreign, foreign_health), intent, bodies(traces, metrics))

    def test_raw_receipt_refuses_unbound_resources_missing_spans_and_forged_units(self):
        _, launch, roots, health, traces, metrics = self.fixture()
        policy = launch.intent.policy(); selected = tuple(launch.intent.source().intent.selected())
        def observe(raw, checkpoint=health, current=policy):
            return receipt.observe(raw, current, selected, roots, checkpoint, pid=23)
        for raw in (None, (), [], [('foreign', b'x')], [('/v1/traces', b'\xff')],
                    [('/v1/traces', b'')], [('/v1/traces', b'x', b'x')]):
            with self.subTest(raw=repr(raw)), self.assertRaises(ValueError): observe(raw)
        for field in ('function_accounting', 'trace_exports', 'metric_exports'):
            value = copy.deepcopy(health)
            key = 'registered' if field == 'function_accounting' else 'units_succeeded'
            value[field][key] = '4'
            with self.subTest(field=field), self.assertRaises(ValueError): observe(bodies(traces, metrics), value)
        for kind in ('resource', 'name', 'parent', 'missing', 'extra'):
            changed = copy.deepcopy(traces); group = changed.resource_spans[0]; spans = group.scope_spans[0].spans
            if kind == 'resource': group.resource.attributes[0].value.string_value = 'foreign'
            elif kind == 'name': spans[0].name = 'foreign'
            elif kind == 'parent': spans[2].parent_span_id = spans[0].span_id
            elif kind == 'missing': del spans[-1]
            else: spans.add().CopyFrom(spans[0])
            with self.subTest(kind=kind), self.assertRaises(ValueError): observe(bodies(changed, metrics))

    def test_histogram_nonfinite_impossible_and_nonmonotonic_metrics_refuse(self):
        _, launch, roots, health, traces, metrics = self.fixture()
        policy = launch.intent.policy(); selected = tuple(launch.intent.source().intent.selected())
        for kind in ('nan', 'negative', 'bucket', 'temporality', 'monotonic', 'function', 'duplicate'):
            changed = copy.deepcopy(metrics); instruments = changed.resource_metrics[0].scope_metrics[0].metrics
            histogram = instruments[1].histogram.data_points[0]
            if kind == 'nan': histogram.sum = float('nan')
            elif kind == 'negative': histogram.min = -1
            elif kind == 'bucket': histogram.bucket_counts[0] += 1
            elif kind == 'temporality': instruments[0].sum.aggregation_temporality = 1
            elif kind == 'monotonic': instruments[0].sum.is_monotonic = False
            elif kind == 'function': instruments[0].sum.data_points[0].attributes[0].value.string_value = 'foreign'
            else: instruments.add().CopyFrom(instruments[0])
            with self.subTest(kind=kind), self.assertRaises(ValueError):
                receipt.observe(bodies(traces, changed), policy, selected, roots, health, pid=23)

    def test_unsupported_trace_policy_bounds_and_counter_denominators_stay_incomplete(self):
        _, launch, roots, health, traces, metrics = self.fixture()
        policy = launch.intent.policy(); selected = tuple(launch.intent.source().intent.selected())
        for kind in ('sampling', 'lifetime', 'bounds', 'service', 'flags'):
            current = copy.deepcopy(policy)
            if kind == 'sampling': current['traces']['sample_ratio'] = .5
            elif kind == 'lifetime': current['lifetimes']['enabled'] = True
            elif kind == 'bounds': current['metrics']['histogram_boundaries_seconds'] = [1., .1]
            elif kind == 'service': current['resource']['service_name'] = ''
            else: current['metrics']['collection'] = 1
            with self.subTest(kind=kind), self.assertRaises(ValueError):
                receipt.observe(bodies(traces, metrics), current, selected, roots, health, pid=23)
        for expected in ((), ('foreign',), (True,)):
            with self.subTest(selected=expected), self.assertRaises(ValueError):
                receipt.observe(bodies(traces, metrics), policy, expected, roots, health, pid=23)


if __name__ == '__main__':
    unittest.main()
