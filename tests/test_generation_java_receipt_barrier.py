"""A flush reply cannot close a positive window before actual OTLP arrives."""

from pathlib import Path
import sys
import tempfile
import time
import unittest
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[1]
sys.path[:0] = [str(ROOT / 'adapters/generation'), str(ROOT / 'examples')]
import java_live
import java_telemetry
import generation
from java_live_fixture import metric_body
from test_generation_java_control_receipt import history, status
from opentelemetry.proto.collector.metrics.v1.metrics_service_pb2 import ExportMetricsServiceRequest

ON = {'collection': True, 'emission': True}
OFF = {'collection': False, 'emission': False}


class JavaReceiptBarrierTests(unittest.TestCase):
    def test_execution_binds_the_sdk_method_component_and_actual_service(self):
        with tempfile.TemporaryDirectory() as temporary:
            folder = Path(temporary).resolve()
            sequence = [{'id': 'step-0', 'action': 'call', 'metrics': ON.copy()}]
            entry = {'language': 'java', 'java_backend': 'prepared',
                'otelc_function': 'sample.Counter.identity(int)',
                'sequence_configuration': sequence}
            bodies = [('/v1/metrics', metric_body(1, method='identity'))]
            options = generation.execution_options(entry, {'sequence': sequence},
                'instrumented_on', folder, folder / 'runtime', bodies, {}, service='case')
            session = options['interaction']
            self.assertTrue(options['record_process'])
            self.assertEqual(session.service, 'case')
            self.assertEqual(session.method, 'identity')
            self.assertTrue(session.metrics_ready({}, 0, 1))

    def session(self, folder: Path, bodies: list) -> java_live.Session:
        sequence = [{'id': 'step-0', 'action': 'call', 'metrics': ON.copy()}]
        return java_live.Session(folder, folder / 'runtime', sequence, bodies,
            plain=False, service='case', method='identity')

    def test_receipt_bindings_are_required_before_checkpoint_creation(self):
        with tempfile.TemporaryDirectory() as temporary:
            folder = Path(temporary).resolve()
            for service, method in ((None, 'Counter.identity'), ('case', ''), ('', 'Counter.identity')):
                with self.assertRaisesRegex(ValueError, 'receipt identity'):
                    java_live.Session(folder, folder / 'runtime', [], [], plain=False,
                        service=service, method=method)
                self.assertFalse((folder / 'java-rendezvous').exists())

    def test_positive_checkpoint_waits_for_both_actual_series_without_extra_commands(self):
        with tempfile.TemporaryDirectory() as temporary:
            folder = Path(temporary).resolve();bodies = []
            session = self.session(folder, bodies)
            session.record['steps'] = [{'id': 'step-0', 'requested': ON.copy(),
                'before': {'cursor': 0, 'history': []}, 'after': None}]
            session.holding = {'index': 0, 'status': status(ON, 1), 'flush': status(ON, 1),
                'started_ns': time.monotonic_ns()}
            with patch.object(session, 'query', return_value=status(ON, 1)) as query, \
                 patch.object(session, 'acknowledge') as acknowledge:
                session.settle(time.monotonic() + 1)
                acknowledge.assert_not_called()
                self.assertIsNone(session.record['steps'][0]['after'])
                bodies.append(('/v1/traces', b'trace outside the metric decoder'))
                bodies.append(('/v1/metrics', metric_body(0)))
                session.settle(time.monotonic() + 1)
                acknowledge.assert_not_called()
                bodies.append(('/v1/metrics', metric_body(1)))
                session.settle(time.monotonic() + 1)
                acknowledge.assert_called_once()
                query.assert_called_once_with('flush', unittest.mock.ANY)
            self.assertIsNone(session.holding)
            self.assertEqual(session.record['steps'][0]['after']['cursor'], 3)
            self.assertEqual(session.record['steps'][0]['after']['metric_bodies'], [1, 2])

    def test_restoration_requires_a_fresh_receipt_and_does_not_repeat_setters(self):
        with tempfile.TemporaryDirectory() as temporary:
            bodies = [('/v1/metrics', metric_body(2))]
            session = self.session(Path(temporary).resolve(), bodies)
            session.record['steps'] = [{'after': {'cursor': 1, 'settled': status(OFF, 2)}}]
            with patch.object(session, 'transition', return_value=history(OFF, ON, 2)) as transition, \
                 patch.object(session, 'query', return_value=status(ON, 2)) as query, \
                 patch.object(session, 'acknowledge') as acknowledge:
                session.restore(time.monotonic() + 1)
                acknowledge.assert_not_called()
                self.assertIsNone(session.record['restored'])
                bodies.append(('/v1/metrics', metric_body(2)))
                session.restore(time.monotonic() + 1)
                transition.assert_called_once()
                query.assert_called_once()
                acknowledge.assert_called_once()
            self.assertIsNone(session.restoring)
            self.assertEqual(session.record['restored']['cursor'], 2)

    def test_incomplete_series_cannot_release_the_checkpoint_and_is_decoded_once(self):
        with tempfile.TemporaryDirectory() as temporary:
            message = ExportMetricsServiceRequest.FromString(metric_body(1))
            del message.resource_metrics[0].scope_metrics[0].metrics[1]
            bodies = [('/v1/metrics', message.SerializeToString())]
            session = self.session(Path(temporary).resolve(), bodies)
            pending = {}
            self.assertFalse(session.metrics_ready(pending, 0, 1))
            with patch.object(java_telemetry, 'decode', side_effect=AssertionError('decoded again')):
                self.assertFalse(session.metrics_ready(pending, 0, 1))

    def test_foreign_service_method_excess_counts_and_malformed_bodies_refuse(self):
        for body, reason in ((metric_body(1, service='foreign'), 'resource identity'),
                (metric_body(1, method='Other.run'), 'unbound function'),
                (metric_body(2), 'uncollected calls'), (b'bad protobuf', 'invalid OTLP')):
            with self.subTest(reason=reason), tempfile.TemporaryDirectory() as temporary:
                session = self.session(Path(temporary).resolve(), [('/v1/metrics', body)])
                with self.assertRaisesRegex(ValueError, reason):
                    session.metrics_ready({}, 0, 1)


if __name__ == '__main__':
    unittest.main()
