"""Independent native metric oracles reject altered literal fixture evidence."""

import copy
from functools import partial
import json
from pathlib import Path
import tempfile
import unittest

from opentelemetry.proto.collector.metrics.v1.metrics_service_pb2 import ExportMetricsServiceRequest
from opentelemetry.proto.collector.trace.v1.trace_service_pb2 import ExportTraceServiceRequest

import native_metric_cases as cases
import native_metric_frames as frames
import native_metric_health as health
import native_metric_otlp as otlp
import native_metric_receipt as receipt
import native_prepared_receipt as retained
from native_metric_test_capture import Capture


class NativeMetricQualificationTests(unittest.TestCase):
    def capture(self, **options) -> Capture:
        temporary = tempfile.TemporaryDirectory()
        self.addCleanup(temporary.cleanup)
        return Capture(Path(temporary.name).resolve(), **options)

    def verify(self, value: Capture) -> tuple:
        checker = partial(receipt.receipt, entry=value.entry, mode=value.mode, start=value.start,
                          amount=value.amount, version=value.version)
        result = checker(value.folder, retained.read, value.language, value.service, value.name, plain=value.plain)
        self.assertEqual(result[0], value.witness)
        retained.attempt(value.folder, value.entry, 'baseline' if value.plain else 'instrumented_on', value.witness,
            value.provider, [value.amount], receipt_check=checker,
            policy_check=partial(retained.policy, metric_flags=cases.schedule(value.start)[0]),
            health_check=partial(retained.health, functions=value.total))
        return result

    def controls(self, value: Capture, record=None, bodies=None):
        return receipt.controls(value.record if record is None else record,
            value.bodies if bodies is None else bodies, value.entry, value.start, value.mode, value.amount,
            value.policy, 130, 120, plain=value.plain)

    def test_all_28_workloads_have_complete_plain_and_instrumented_owned_receipts(self):
        count = 0
        for language, modes in cases.MODES.items():
            for mode in modes:
                for start in cases.STARTS:
                    for plain in (False, True):
                        with self.subTest(language=language, mode=mode, start=start, plain=plain):
                            value = self.capture(language=language, mode=mode, start=start, plain=plain)
                            result = self.verify(value)
                            self.assertEqual(result[1], sum(route == '/v1/metrics' for route, _ in value.bodies) * 3)
                            count += 1
        self.assertEqual(count, 56)

    def test_reduced_promoted_and_big_endian_frames_keep_literal_values_and_newline_errors(self):
        for language, mode in (('c', 'transient'), ('cpp', 'error'), ('cpp', 'recursive')):
            for version in (43, 44):
                value = self.capture(language=language, mode=mode, start='00', amount=0,
                                     version=version, byte_order='big')
                self.verify(value)
        plain = cases.expected('c', 'transient', 0, instrumented=False)
        changed = cases.expected('c', 'transient', 0, instrumented=True)
        self.assertEqual(plain[-1]['after'], changed[-1]['after'])
        self.assertNotEqual(plain[1]['after'], changed[1]['after'])
        self.assertEqual([row['after']['roots']['global:state']['value'] for row in changed], ['7', '8', '8', '7'])
        error = cases.expected('cpp', 'error', 5, instrumented=True)[1]['outcome']
        self.assertEqual(bytes.fromhex(error['graph']['nodes'][0]['fields']['message']['hex']), b'failure-42\nafter')

    def test_fixed_schedule_and_source_contracts_reject_unlisted_shapes(self):
        for start in cases.STARTS:
            flags = cases.schedule(start)
            self.assertEqual({tuple(row.values()) for row in flags}, set(cases.STATES))
            self.assertEqual(''.join('1' if value else '0' for value in flags[0].values()), start)
        for arguments in (('rust', 'normal', '11'), ('c', 'error', '11'), ('c', 'normal', '12')):
            with self.subTest(arguments=arguments), self.assertRaises(ValueError): cases.validate(*arguments)
        for operation in (lambda: cases.schedule(''), lambda: cases.function('c', 'foreign'),
                          lambda: cases.source('c', 'normal', changed=1),
                          lambda: cases.expected('c', 'normal', True, instrumented=False),
                          lambda: cases.expected('c', 'normal', 6, instrumented=False),
                          lambda: cases.expected('c', 'normal', 0, instrumented=1),
                          lambda: cases.expected('c', 'normal', 0, instrumented=False, version=45)):
            with self.assertRaises(ValueError): operation()
        source = cases.source('cpp', 'recursive', changed=True)
        self.assertIn('selected_extra(amount-1)', source)
        self.assertIn(':43;', source); self.assertIn(':44;', source)
        value = self.capture()
        with tempfile.TemporaryDirectory() as temporary:
            source, config = cases.fixture(Path(temporary), 'c', 'normal', '11', value.provider)
            self.assertTrue(source.is_dir()); self.assertTrue(config.is_file())

    def test_json_abi_original_frames_and_checkpoint_denominators_refuse_mutations(self):
        for raw in (b'{"x":1,"x":2}', b'{"x":NaN}', b'[]'):
            with self.subTest(raw=raw), self.assertRaises(ValueError): frames.loads(raw)
        value = self.capture(language='cpp', mode='error')
        expected = cases.expected('cpp', 'error', 5, instrumented=True)
        path = value.folder / 'native-rendezvous/step-1.observation'
        raw = path.read_bytes()
        for changed in (b'', raw[:-1], raw.replace(b'failure-42', b'failure-43'),
                        raw.replace(b'calls:int:', b'other:int:'), raw.replace(b'"int": 32', b'"int": 64'),
                        raw.replace(b'"char_bits": 8', b'"char_bits": true'),
                        raw.replace(b'"byte_order": "little"', b'"byte_order": "unknown"')):
            with self.subTest(raw=changed), self.assertRaises(ValueError): frames.frame(changed, value.entry, expected[1])
        path = value.folder / 'native-rendezvous/finish.resume.json'
        record = retained.read(path); record['nonce'] = 'f' * 32
        path.write_text(json.dumps(record))
        with self.assertRaises(ValueError): frames.evidence(value.folder, value.entry, expected)
        path.write_text(json.dumps({'nonce': 'e' * 32, 'phase': 'finish'}))
        (value.folder / 'native-rendezvous/extra').mkdir()
        with self.assertRaises(ValueError): frames.evidence(value.folder, value.entry, expected)

    def test_frame_container_private_modes_and_host_snapshot_prefixes_are_bound(self):
        for mutation in ('schema', 'id', 'bytes', 'mode', 'snapshot', 'extra-snapshot', 'missing-frame', 'flag-content'):
            with self.subTest(mutation=mutation):
                value = self.capture()
                path = value.folder / 'observation'; record = retained.read(path)
                if mutation == 'schema': record['schema_version'] = True
                elif mutation == 'id': record['frames'][1]['id'] = 'step-0'
                elif mutation == 'bytes': record['frames'][0]['raw_hex'] = record['frames'][0]['raw_hex'].upper()
                elif mutation == 'mode': path.chmod(0o644)
                elif mutation == 'snapshot':
                    path = value.folder / 'native-live-0.json'; changed = retained.read(path)
                    changed['restored'] = value.record['restored']; path.write_text(json.dumps(changed))
                elif mutation == 'extra-snapshot': (value.folder / 'native-live-9.json').write_text('{}')
                elif mutation == 'missing-frame': (value.folder / 'native-rendezvous/step-0.observation').unlink()
                else: (value.folder / 'native-rendezvous/before-0.ready/extra').write_text('foreign')
                if mutation in ('schema', 'id', 'bytes'): path.write_text(json.dumps(record))
                with self.assertRaises((ValueError, FileNotFoundError)): self.verify(value)

    def test_schedule_setters_health_holds_and_restoration_have_independent_expected_values(self):
        value = self.capture(language='cpp', mode='error')
        self.controls(value)
        operations = [
            lambda row: row.update(schema_version=True),
            lambda row: row.update(pid=131),
            lambda row: row['steps'][0]['requested'].update(collection=False),
            lambda row: row['steps'][1]['before'].update(history=[]),
            lambda row: row['steps'][1]['before']['history'][-1]['status'].update(effective_emission_off=False),
            lambda row: row['steps'][1]['after'].update(held_ns=0),
            lambda row: row['steps'][0]['before']['health']['function_accounting'].update(started='1'),
            lambda row: row['steps'][0]['after']['health']['span_accounting'].update(queue_pending='0'),
            lambda row: row['steps'][2]['after']['settled']['metric_exports'].update(units_started='999'),
            lambda row: row['steps'][1]['after'].update(metric_bodies=[0]),
            lambda row: row['steps'][0]['after'].update(cursor=True),
            lambda row: row['restored']['health']['controls'].update(collection=False)]
        for operation in operations:
            changed = copy.deepcopy(value.record); operation(changed)
            with self.subTest(operation=operation), self.assertRaises(ValueError): self.controls(value, changed)
        malformed = [*value.bodies, ('/v1/metrics', b'\xff')]
        with self.assertRaises(ValueError):
            otlp.metrics(malformed, value.language, value.service, value.name, value.collected, value.errors)
        plain = self.capture(plain=True)
        with self.assertRaises(ValueError): self.controls(plain, bodies=[('/v1/metrics', b'foreign')])

    def test_running_health_counter_types_export_losses_and_registration_cannot_be_repaired(self):
        value = self.capture()
        original = value.record['steps'][0]['after']['settled']
        for bad in (True, 1, '', '00', '-1', str(2**64)):
            with self.subTest(bad=bad), self.assertRaises(ValueError): health.count(bad)
        for path, bad in [('schema_version', True), ('phase', 'final'), ('function_accounting.registered', '0'),
                          ('function_accounting.closed', True), ('span_accounting.queue_dropped', '0'),
                          ('metric_exports.batches_pending', '1'), ('trace_exports.units_succeeded', '99'),
                          ('trace_exports.batches_failed', '1'), ('metric_flush.failed_attempts', '1'),
                          ('lifecycle.flush', 'failed')]:
            changed = copy.deepcopy(original); target = changed; names = path.split('.')
            for name in names[:-1]: target = target[name]
            target[names[-1]] = bad
            with self.subTest(path=path), self.assertRaises(ValueError):
                health.running(changed, value.policy, 'c', 130, {'collection': True, 'emission': True}, 1)
        pending = copy.deepcopy(original['trace_exports'])
        pending.update(batches_started='2', batches_succeeded='1', batches_pending='1', units_started='2', units_succeeded='1')
        health.exports(pending, 'spans')
        for flags in ({}, {'collection': 1, 'emission': True}):
            with self.assertRaises(ValueError): health.status(original['controls'], 130, flags)
        later = copy.deepcopy(original); later['trace_exports']['units_succeeded'] = '0'
        with self.assertRaises(ValueError): health.progress([original, later])

    def test_original_otlp_traces_counters_histograms_and_receipt_hashes_reject_alterations(self):
        value = self.capture(language='cpp', mode='recursive')
        trace_index = next(i for i, (route, _) in enumerate(value.bodies) if route == '/v1/traces')
        for kind in ('parent', 'name', 'duplicate', 'event', 'error'):
            bodies = copy.deepcopy(value.bodies)
            message = ExportTraceServiceRequest.FromString(bodies[trace_index][1])
            spans = message.resource_spans[0].scope_spans[0].spans
            if kind == 'parent': spans[0].parent_span_id = b'x' * 8
            elif kind == 'name': spans[0].name = 'foreign'
            elif kind == 'duplicate': spans.add().CopyFrom(spans[0])
            elif kind == 'event': spans[0].events.add(name='foreign')
            else: spans[0].status.code = 2
            bodies[trace_index] = ('/v1/traces', message.SerializeToString())
            with self.subTest(kind=kind), self.assertRaises(ValueError):
                otlp.traces(bodies, 'cpp', value.service, value.name, 6, failed=False)
        metric_index = next(i for i, (route, _) in enumerate(value.bodies) if route == '/v1/metrics')
        for kind in ('count', 'bucket', 'sum', 'extrema', 'label', 'instrument', 'type', 'monotonic'):
            bodies = copy.deepcopy(value.bodies)
            message = ExportMetricsServiceRequest.FromString(bodies[metric_index][1])
            metrics = message.resource_metrics[0].scope_metrics[0].metrics
            if kind == 'count': metrics[0].sum.data_points[0].as_int = 999
            elif kind == 'bucket': metrics[2].histogram.data_points[0].bucket_counts[0] = 999
            elif kind == 'sum': metrics[2].histogram.data_points[0].sum = float('nan')
            elif kind == 'extrema': metrics[2].histogram.data_points[0].min = .02
            elif kind == 'label': metrics[0].sum.data_points[0].attributes[0].value.string_value = 'foreign'
            elif kind == 'instrument': metrics[0].name = 'foreign'
            elif kind == 'type': metrics[0].sum.data_points[0].as_double = 1.
            else: metrics[0].sum.is_monotonic = False
            bodies[metric_index] = ('/v1/metrics', message.SerializeToString())
            with self.subTest(kind=kind), self.assertRaises(ValueError):
                otlp.metrics(bodies, 'cpp', value.service, value.name, 12, 0)
        with self.assertRaises(ValueError): otlp.traces([('/v1/traces', b'\xff')], 'cpp', value.service, value.name, 6, failed=False)
        self.assertNotEqual(otlp.witness(value.bodies[:-1], value.name, 24), value.witness)


if __name__ == '__main__':
    unittest.main()
