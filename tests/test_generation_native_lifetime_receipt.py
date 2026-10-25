"""Lifetime identity, temporal, metric and prelaunch substitution controls."""

import copy
from dataclasses import replace
import json
import math
from pathlib import Path
import sys
import tempfile
import unittest
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[1]
sys.path[:0] = [str(ROOT / 'adapters/generation'), str(ROOT / 'examples')]
import native_lifetime_fixture
import native_lifetime_intent as caller
import native_lifetime_receipt as receipt
import native_lifetime_receipt_fixture as fixture
import native_telemetry


class NativeLifetimeReceiptTests(unittest.TestCase):
    def test_both_profiles_all_fixed_startup_states_and_plain_lanes(self):
        for kind in ('object', 'resource'):
            for collection, emission in ((True, True), (False, True), (True, False), (False, False)):
                with self.subTest(kind=kind, collection=collection, emission=emission), tempfile.TemporaryDirectory() as temporary:
                    final, intent, bodies, *_ = fixture.fixture(Path(temporary).resolve(), kind=kind,
                                                               collection=collection, emission=emission)
                    value = receipt.witness(final, intent, bodies)
                    self.assertEqual(value['spans'], 2)
                    self.assertEqual(value['metric_points'], 6 if collection and emission else 0)
                    self.assertEqual(value['lifetimes'][0]['duration_ns'], 40)
                    self.assertEqual(value['lifetimes'][0]['boundary'],
                                     'destructor_entry' if kind == 'object' else 'free_entry')
                    intent.verify()
            with tempfile.TemporaryDirectory() as temporary:
                final, intent, bodies, *_ = fixture.fixture(Path(temporary).resolve(), kind=kind, plain=True)
                self.assertIsNone(receipt.witness(final, intent, bodies))
                with self.assertRaises(ValueError): receipt.witness(final, intent, [('/v1/traces', b'foreign')])

    def test_shutdown_censoring_and_destructor_exception_exit_remain_distinct(self):
        for kind in ('object', 'resource'):
            with self.subTest(kind=kind), tempfile.TemporaryDirectory() as temporary:
                observation = caller.Observation('c:@S@Item', 'Item', (0,), None, False)
                final, intent, bodies, *_ = fixture.fixture(Path(temporary).resolve(), kind=kind,
                                                            observations=(observation,))
                value = receipt.witness(final, intent, bodies)
                self.assertEqual(value['lifetimes'][0]['boundary'], 'shutdown_censored')
                self.assertEqual(value['health'][kind + '_accounting']['completed'], '0')
        with tempfile.TemporaryDirectory() as temporary:
            expected = caller.Observation('c:@S@Item', 'Item', (0,), (0,), True, True)
            final, intent, bodies, *_ = fixture.fixture(Path(temporary).resolve(), observations=(expected,))
            self.assertIs(receipt.witness(final, intent, bodies)['lifetimes'][0]['exception_exit'], True)

    def test_lifetimes_can_cross_declared_serial_calls_and_be_absent(self):
        with tempfile.TemporaryDirectory() as temporary:
            expected = caller.Observation('c:@S@Item', 'Item', (0,), (1,), True, False)
            final, intent, bodies, *_ = fixture.fixture(Path(temporary).resolve(), roots=(fixture.NAME, fixture.NAME),
                                                       observations=(expected,))
            self.assertEqual(receipt.witness(final, intent, bodies)['lifetimes'][0]['duration_ns'], 140)
        with tempfile.TemporaryDirectory() as temporary:
            final, intent, bodies, *_ = fixture.fixture(Path(temporary).resolve(), observations=())
            self.assertEqual(receipt.witness(final, intent, bodies)['lifetimes'], [])

    def test_long_durations_match_cpp_chrono_conversion_and_refuse_wrong_values(self):
        for nanoseconds in ((1 << 53) - 1, 1 << 53, (1 << 53) + 3):
            with self.subTest(nanoseconds=nanoseconds), tempfile.TemporaryDirectory() as temporary:
                final, intent, _, trace, metric = fixture.fixture(Path(temporary).resolve())
                spans = trace.resource_spans[0].scope_spans[0].spans
                lifespan, function = spans[1], spans[0]
                lifespan.end_time_unix_nano = lifespan.start_time_unix_nano + nanoseconds
                function.end_time_unix_nano = lifespan.end_time_unix_nano + 10
                for entry in metric.resource_metrics[0].scope_metrics[0].metrics:
                    point = getattr(entry, entry.WhichOneof('data')).data_points[0]
                    point.time_unix_nano = function.end_time_unix_nano + 100
                    if entry.name.endswith('.duration'):
                        duration = nanoseconds if entry.name.startswith('otelc.lifetime.') else (
                            function.end_time_unix_nano - function.start_time_unix_nano)
                        seconds = float(duration) / 1_000_000_000
                        point.sum = point.min = point.max = seconds
                        del point.bucket_counts[:]
                        point.bucket_counts.extend([0] * len(fixture.BOUNDS) + [1])
                bodies = [('/v1/traces', trace.SerializeToString()), ('/v1/metrics', metric.SerializeToString())]
                self.assertEqual(receipt.witness(final, intent, bodies)['lifetimes'][0]['duration_ns'], nanoseconds)
                duration = next(entry for entry in metric.resource_metrics[0].scope_metrics[0].metrics
                                if entry.name == 'otelc.lifetime.duration').histogram.data_points[0]
                duration.sum = duration.min = duration.max = math.nextafter(duration.sum, math.inf)
                with self.assertRaisesRegex(ValueError, 'differs from observed span durations'):
                    receipt.witness(final, intent, [bodies[0], ('/v1/metrics', metric.SerializeToString())])

    def test_prelaunch_expectations_refuse_wrong_types_paths_bounds_and_late_freeze(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary).resolve()
            final, intent, _, *_ = fixture.fixture(root)
            original = intent.observations[0]
            for changes in ({'name': 'Unknown'}, {'type_usr': 'foreign'}, {'complete': 1},
                            {'creation_path': None}, {'creation_path': []}, {'creation_path': ()},
                            {'creation_path': (True,)}, {'creation_path': (1,)}, {'creation_path': (-1,)},
                            {'creation_path': (0,) * 65}, {'release_path': None}, {'exception_exit': None}):
                with self.subTest(changes=changes), self.assertRaises(ValueError):
                    caller.validate(intent.launch, intent.roots, (replace(original, **changes),))
            for roots in (None, [], (), ('',), ('bad\0root',), (fixture.NAME,) * 65):
                with self.subTest(roots=roots), self.assertRaises(ValueError):
                    caller.validate(intent.launch, roots, intent.observations)
            with self.assertRaises(ValueError): caller.validate(intent.launch, intent.roots, (object(),))
            with self.assertRaisesRegex(ValueError, 'precede owned execution'):
                caller.freeze(intent.launch, root / 'late.json', intent.roots, intent.observations)
            with self.assertRaises(ValueError): receipt.witness(final, replace(intent, roots=('changed',)), [])

    def test_multiple_instances_keep_admission_order_and_censored_durations(self):
        for kind in ('object', 'resource'):
            with self.subTest(kind=kind), tempfile.TemporaryDirectory() as temporary:
                exception = False if kind == 'object' else None
                expected = (caller.Observation('c:@S@Item', 'Item', (0,), (1,), True, exception),
                            caller.Observation('c:@S@Item', 'Item', (1,), None, False),
                            caller.Observation('c:@S@Item', 'Item', (2,), (2,), True, exception))
                final, intent, _, trace, metric = fixture.fixture(
                    Path(temporary).resolve(), kind=kind, roots=(fixture.NAME,) * 3,
                    observations=expected)
                spans = trace.resource_spans[0].scope_spans[0].spans
                reversed_spans = list(reversed([copy.deepcopy(row) for row in spans]))
                del spans[:]
                spans.extend(reversed_spans)
                value = receipt.witness(final, intent, [('/v1/traces', trace.SerializeToString()),
                                                        ('/v1/metrics', metric.SerializeToString())])
                self.assertEqual([row['instance'] for row in value['lifetimes']], ['1', '2', '3'])
                self.assertEqual([row['duration_ns'] for row in value['lifetimes']], [140, 220, 40])
                self.assertEqual(value['health'][kind + '_accounting']['completed'], '2')
                self.assertEqual(value['health'][kind + '_accounting']['censored'], '1')

    def test_repeated_metric_exports_retain_every_point_and_refuse_resets(self):
        with tempfile.TemporaryDirectory() as temporary:
            def extra_points(value):
                for key in ('units_started', 'units_succeeded'):
                    value['metric_exports'][key] = '12'
            final, intent, _, trace, metric = fixture.fixture(
                Path(temporary).resolve(), health_change=extra_points)
            scope = metric.resource_metrics[0].scope_metrics[0]
            for entry in scope.metrics:
                data = getattr(entry, entry.WhichOneof('data'))
                earlier = data.data_points.add()
                earlier.CopyFrom(data.data_points[0])
                earlier.time_unix_nano = 500
                if entry.name == 'otelc.lifetime.live':
                    earlier.as_int = 1
            bodies = [('/v1/traces', trace.SerializeToString()), ('/v1/metrics', metric.SerializeToString())]
            self.assertEqual(receipt.witness(final, intent, bodies)['metric_points'], 12)
            admitted = next(row for row in scope.metrics if row.name == 'otelc.lifetime.admitted')
            admitted.sum.data_points[1].as_int = 2
            with self.assertRaises(ValueError):
                receipt.witness(final, intent, [bodies[0], ('/v1/metrics', metric.SerializeToString())])

    def test_original_expectation_bytes_facts_and_another_launch_cannot_be_replaced(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary).resolve()
            final, intent, bodies, *_ = fixture.fixture(root)
            with self.assertRaises(ValueError): receipt.witness(final, replace(intent, launch=copy.copy(intent.launch)), bodies)
            path = intent.record.file.path
            path.write_bytes(path.read_bytes())
            with self.assertRaises(ValueError): receipt.witness(final, intent, bodies)

    def test_prelaunch_record_cannot_write_into_source_build_sdk_or_runtime(self):
        with tempfile.TemporaryDirectory() as temporary, patch.object(fixture, 'completed', return_value=None):
            root = Path(temporary).resolve()
            _, intent, *_ = fixture.fixture(root)
            context = intent.launch.intent.context()
            forbidden = [directory / 'expectations.json' for directory in (context.project, context.output,
                         context.sdk.root, context.sdk.directory, intent.launch.intent.runtime)]
            forbidden.extend([Path('relative.json'), root / 'absent/../unexpected.json', intent.record.file.path])
            alias = root / 'alias.json'; alias.symlink_to(intent.record.file.path); forbidden.append(alias)
            for path in forbidden:
                with self.subTest(path=path), self.assertRaises(ValueError):
                    caller.freeze(intent.launch, path, intent.roots, intent.observations)
            with patch.object(caller.inputs, 'MAX_RECORD', 1), self.assertRaises(ValueError):
                caller.freeze(intent.launch, root / 'too-large.json', intent.roots, intent.observations)
            self.assertFalse((root / 'too-large.json').exists())
            value = json.loads(intent.record.file.content)
            value['observations'][0]['complete'] = False
            intent.record.file.path.write_text(json.dumps(value))
            with self.assertRaises(ValueError): intent.verify()

    def test_declared_child_paths_and_censoring_time_must_exist_in_the_call_tree(self):
        for field in ('creation_path', 'release_path'):
            with self.subTest(field=field), tempfile.TemporaryDirectory() as temporary:
                original = caller.Observation('c:@S@Item', 'Item', (0,), (0,), True, False)
                expected = replace(original, **{field: (0, 9)})
                final, intent, bodies, *_ = fixture.fixture(Path(temporary).resolve(), observations=(expected,))
                with self.assertRaisesRegex(ValueError, 'outside the declared'):
                    receipt.witness(final, intent, bodies)
        with tempfile.TemporaryDirectory() as temporary:
            expected = caller.Observation('c:@S@Item', 'Item', (0,), None, False)
            final, intent, _, trace, metric = fixture.fixture(Path(temporary).resolve(), observations=(expected,))
            trace.resource_spans[0].scope_spans[0].spans[1].end_time_unix_nano = 88
            with self.assertRaisesRegex(ValueError, 'censored before'):
                receipt.witness(final, intent, [('/v1/traces', trace.SerializeToString()),
                                                ('/v1/metrics', metric.SerializeToString())])

    def test_ambiguous_source_type_names_refuse_before_a_receipt_can_be_declared(self):
        original = native_lifetime_fixture.facts
        def ambiguous(source, kind, *, empty=False):
            value = original(source, kind, empty=empty)
            if value['types']:
                value['types'].append({**value['types'][0], 'usr': 'another:Item'})
            return value
        with tempfile.TemporaryDirectory() as temporary, patch.object(native_lifetime_fixture, 'facts', side_effect=ambiguous):
            with self.assertRaisesRegex(ValueError, 'ambiguous'):
                fixture.fixture(Path(temporary).resolve())

    def test_every_lifetime_span_field_link_and_instance_refuses_substitution(self):
        with tempfile.TemporaryDirectory() as temporary:
            final, intent, _, original, metric = fixture.fixture(Path(temporary).resolve())
            changes = ('name', 'parent', 'kind', 'status', 'message', 'flags', 'state', 'event', 'dropped',
                'missing-link', 'extra-link', 'link-trace', 'link-span', 'link-state', 'link-flags',
                'link-attributes', 'link-dropped', 'creation-before', 'creation-after', 'release-after',
                'instance', 'instance-type', 'duplicate-instance', 'foreign-trace', 'missing', 'duplicate',
                'type', 'boundary', 'complete', 'exception', 'extra-attribute', 'duplicate-attribute')
            for change in changes:
                trace = copy.deepcopy(original); scope = trace.resource_spans[0].scope_spans[0]
                span = scope.spans[1]
                if change == 'name': span.name = 'foreign lifetime'
                elif change == 'parent': span.parent_span_id = b'\1' * 8
                elif change == 'kind': span.kind = 2
                elif change == 'status': span.status.code = 2
                elif change == 'message': span.status.message = 'foreign'
                elif change == 'flags': span.flags = 0
                elif change == 'state': span.trace_state = 'a=b'
                elif change == 'event': span.events.add(name='extra')
                elif change == 'dropped': span.dropped_links_count = 1
                elif change == 'missing-link': del span.links[:]
                elif change == 'extra-link': span.links.add().CopyFrom(span.links[0])
                elif change == 'link-trace': span.links[0].trace_id = b'\4' * 16
                elif change == 'link-span': span.links[0].span_id = b'\4' * 8
                elif change == 'link-state': span.links[0].trace_state = 'a=b'
                elif change == 'link-flags': span.links[0].flags = 1
                elif change == 'link-attributes': fixture.labels(span.links[0].attributes, {'extra': 'value'})
                elif change == 'link-dropped': span.links[0].dropped_attributes_count = 1
                elif change == 'creation-before': span.start_time_unix_nano = 1
                elif change == 'creation-after': span.start_time_unix_nano = 91; span.end_time_unix_nano = 92
                elif change == 'release-after': span.end_time_unix_nano = 91
                elif change == 'foreign-trace': span.trace_id = scope.spans[0].trace_id
                elif change == 'missing': del scope.spans[1:]
                elif change in ('duplicate', 'duplicate-instance'):
                    scope.spans.add().CopyFrom(span)
                    if change == 'duplicate-instance': scope.spans[-1].trace_id = b'\5' * 16
                elif change == 'extra-attribute': fixture.labels(span.attributes, {'extra': 'value'})
                elif change == 'duplicate-attribute': span.attributes.add().CopyFrom(span.attributes[0])
                else:
                    key = {'instance': 'otelc.lifetime.instance', 'instance-type': 'otelc.lifetime.instance',
                           'type': 'type', 'boundary': 'boundary', 'complete': 'otelc.lifetime.complete',
                           'exception': 'otelc.destructor.exception_exit'}[change]
                    attribute = next(row for row in span.attributes if row.key == key)
                    if change in ('complete', 'exception'): attribute.value.bool_value = not attribute.value.bool_value
                    elif change == 'instance-type': attribute.value.int_value = 1
                    else: attribute.value.string_value = 'wrong'
                with self.subTest(change=change), self.assertRaises(ValueError):
                    receipt.witness(final, intent, [('/v1/traces', trace.SerializeToString()),
                                                    ('/v1/metrics', metric.SerializeToString())])

    def test_metric_labels_kind_units_wire_types_gauge_and_duration_values_are_checked(self):
        with tempfile.TemporaryDirectory() as temporary:
            final, intent, _, trace, original = fixture.fixture(Path(temporary).resolve())
            for change in ('name', 'unit', 'temporality', 'monotonic', 'label', 'boundary', 'integer',
                           'flags', 'exemplar', 'gauge-live', 'gauge-double', 'duration', 'missing', 'duplicate'):
                metric = copy.deepcopy(original); scope = metric.resource_metrics[0].scope_metrics[0]
                admitted = next(row for row in scope.metrics if row.name == 'otelc.lifetime.admitted')
                point = admitted.sum.data_points[0]
                if change == 'name': admitted.name = 'foreign'
                elif change == 'unit': admitted.unit = 's'
                elif change == 'temporality': admitted.sum.aggregation_temporality = 1
                elif change == 'monotonic': admitted.sum.is_monotonic = False
                elif change == 'label': point.attributes[0].value.string_value = 'foreign'
                elif change == 'boundary': point.attributes[1].value.string_value = 'free_entry'
                elif change == 'integer': point.as_double = 1.0
                elif change == 'flags': point.flags = 1
                elif change == 'exemplar': point.exemplars.add()
                elif change.startswith('gauge'):
                    gauge = next(row for row in scope.metrics if row.name == 'otelc.lifetime.live').gauge.data_points[0]
                    if change == 'gauge-live': gauge.as_int = 1
                    else: gauge.as_double = 0.0
                elif change == 'duration':
                    value = next(row for row in scope.metrics if row.name == 'otelc.lifetime.duration').histogram.data_points[0]
                    value.sum = value.min = value.max = 9e-8
                elif change == 'missing': scope.metrics.remove(admitted)
                else: scope.metrics.add().CopyFrom(admitted)
                with self.subTest(change=change), self.assertRaises(ValueError):
                    receipt.witness(final, intent, [('/v1/traces', trace.SerializeToString()),
                                                    ('/v1/metrics', metric.SerializeToString())])

    def test_final_health_must_join_every_raw_unit_and_expected_instance(self):
        changes = ({'object_accounting': {'admitted': '2', 'completed': '2'}},
                   {'trace_exports': {'units_started': '3', 'units_succeeded': '3'}},
                   {'metric_exports': {'units_started': '7', 'units_succeeded': '7'}},
                   {'function_accounting': {'registered': '2'}},
                   {'controls': {'collection': False, 'effective_emission_off': True}})
        for change in changes:
            with self.subTest(change=change), tempfile.TemporaryDirectory() as temporary:
                def alter(value):
                    for key, fields in change.items(): value[key].update(fields)
                final, intent, bodies, *_ = fixture.fixture(Path(temporary).resolve(), health_change=alter)
                with self.assertRaises(ValueError): receipt.witness(final, intent, bodies)

    def test_route_protobuf_and_aggregate_budgets_cannot_hide_missing_receipt(self):
        with tempfile.TemporaryDirectory() as temporary:
            final, intent, bodies, *_ = fixture.fixture(Path(temporary).resolve())
            for changed in ((), [('wrong', b'x')], [('/v1/traces', b'\xff')], [],
                            [['/v1/traces', b'bad']], [('/v1/traces', b'')]):
                with self.subTest(changed=changed), self.assertRaises(ValueError):
                    receipt.witness(final, intent, changed)
            for name, value in (('MAX_BYTES', 1), ('MAX_POINTS', 4), ('MAX_SPANS', 1)):
                with self.subTest(limit=name), patch.object(native_telemetry, name, value), self.assertRaises(ValueError):
                    receipt.witness(final, intent, bodies)


if __name__ == '__main__':
    unittest.main()
