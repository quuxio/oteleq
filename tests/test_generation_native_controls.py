"""Native controls retain canonical identity, paused work and independent setters."""

import copy
import json
from pathlib import Path
import sys
import tempfile
import time
import unittest
from unittest.mock import Mock, patch

ROOT = Path(__file__).resolve().parents[1]
sys.path[:0] = [str(ROOT / 'adapters/generation'), str(ROOT / 'examples')]

import native_control as control


def status(collection=True, emission=True, effective=None):
    return {'schema_version': 1, 'pid': 23, 'collection': collection, 'emission': emission,
            'effective_emission_off': not (collection and emission) if effective is None else effective}


def running(calls=0, flags=None):
    """Literal native running schema: unavailable queues remain null."""
    def exports(unit):
        return {'exporters_observed': 1, 'unit': unit, 'batches_started': '0',
                'batches_succeeded': '0', 'batches_failed': '0', 'batches_pending': '0',
                'units_started': '0', 'units_succeeded': '0', 'units_failed': '0'}
    return {'schema_version': 1, 'kind': 'otelc.runtime-health', 'language': 'cpp',
        'scope': 'sdk_pipeline', 'pid': 23, 'phase': 'running', 'sdk_attached': True,
        'policy_sha256': 'a' * 64, 'selection_sha256': 'b' * 64, 'source_complete': False,
        'downstream_receipt': 'unavailable', 'otlp_partial_rejection': 'unavailable',
        'diagnostics': {'dropped': '0'}, 'controls': status(**(flags or {})),
        'lifecycle': {'flush': 'succeeded', 'shutdown': 'not_started'},
        'metric_flush': {'attempts': '1', 'failed_attempts': '0'},
        'function_accounting': {'registered': '1', 'started': str(calls), 'ended': str(calls),
            'active': '0', 'lost': '0', 'invalid': '0', 'metadata_errors': '0', 'closed': False},
        'span_accounting': {'processors_observed': 1, 'batch_processors_observed': 1,
            'sampled_started': str(calls), 'sampled_ended': str(calls), 'sampled_active': '0',
            'queue_pending': None, 'queue_dropped': None, 'queue_evidence': 'unavailable'},
        'trace_exports': exports('spans'), 'metric_exports': exports('metric_points')}


class NativeControlTests(unittest.TestCase):
    def test_status_retains_draining_off_flags_but_refuses_inconsistent_effective_claims(self):
        for collection, emission in ((True, True), (False, True), (True, False), (False, False)):
            control.status(status(collection, emission), 23)
            control.status(status(collection, emission, False), 23)
        for key, value in (('schema_version', True), ('pid', True), ('pid', 24), ('collection', 1),
                           ('emission', 0), ('effective_emission_off', 0), ('extra', 1)):
            changed = status(); changed[key] = value
            with self.subTest(key=key, value=value), self.assertRaises(ValueError): control.status(changed, 23)
        inconsistent = status(effective=True)
        with self.assertRaises(ValueError): control.status(inconsistent, 23)
        valid = status()
        with self.assertRaises(ValueError): control.status(valid, True)

    def test_running_health_keeps_queues_unknown_and_rejects_bad_identity_losses_and_active_work(self):
        options = {'pid': 23, 'language': 'cpp', 'policy': 'a' * 64, 'selection': 'b' * 64}
        control.running_health(running(3), **options)
        mutations = [('pid', 24), ('schema_version', True), ('phase', 'final'), ('source_complete', True),
            ('function_accounting.active', '1'), ('function_accounting.closed', True),
            ('function_accounting.started', '4'), ('function_accounting.lost', '1'),
            ('function_accounting.registered', '0'),
            ('function_accounting.registered', '01'), ('span_accounting.queue_pending', '0'),
            ('span_accounting.queue_dropped', '0'), ('span_accounting.processors_observed', True),
            ('span_accounting.sampled_started', '2'), ('lifecycle.shutdown', 'succeeded'),
            ('lifecycle.flush', 'failed'), ('metric_flush.failed_attempts', '1'),
            ('trace_exports.batches_failed', '1'), ('metric_exports.units_failed', '1'),
            ('metric_exports.batches_started', '1'), ('trace_exports.units_succeeded', '1'),
            ('metric_exports.units_started', '1'),
            ('trace_exports.exporters_observed', 0), ('controls.pid', 24)]
        for path, value in mutations:
            changed = running(3); target = changed
            names = path.split('.')
            for name in names[:-1]: target = target[name]
            target[names[-1]] = value
            with self.subTest(path=path), self.assertRaises(ValueError): control.running_health(changed, **options)
        for key, value in (('language', 'rust'), ('pid', True), ('policy', 'A' * 64), ('selection', 'bad')):
            changed = {**options, key: value}
            checkpoint = running()
            with self.subTest(key=key), self.assertRaises(ValueError): control.running_health(checkpoint, **changed)

    def test_running_exports_can_be_in_flight_without_inventing_success(self):
        value = running()
        value['trace_exports'].update(batches_started='1', batches_pending='1', units_started='2')
        control.running_health(value, pid=23, language='cpp', policy='a' * 64, selection='b' * 64)

    def test_endpoint_identity_and_fixed_command_set_are_checked_before_and_after_transport(self):
        path = Path('/private/runtime/control.json'); identity = (1, 2, 'digest')
        with patch.object(control.live_control, 'endpoint', return_value=({}, identity)), \
                patch.object(control.native_inputs, 'capture', return_value=Mock()), \
                patch.object(control.live_control, 'exchange', return_value=status()) as exchange:
            client = control.connect(path, 23)
            self.assertEqual(client.request('status', 50), status())
            self.assertEqual(exchange.call_args.kwargs, {'maximum': 4096})
            exchange.return_value = running()
            client.request('health', 50)
            self.assertEqual(exchange.call_args.kwargs, {'maximum': 16384})
            with self.assertRaises(ValueError): client.request('arbitrary command', 50)
        with patch.object(control.live_control, 'endpoint', return_value=({}, (1, 3, 'digest'))), self.assertRaises(ValueError):
            client.verify()
        with self.assertRaises(ValueError): control.connect(path, True)

    def test_descriptor_write_and_restore_is_refused_even_when_its_bytes_match(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary).resolve(); path = root / 'control.json'
            raw = json.dumps({'schema_version': 1, 'kind': 'otelc.control.tcp', 'host': '127.0.0.1',
                              'port': 9, 'pid': 23, 'token': 'a' * 64}).encode()
            path.write_bytes(raw); path.chmod(0o600)
            client = control.connect(path, 23)
            client.verify()
            self.assertIsNone(client.descriptor.content)
            path.write_bytes(raw)
            with self.assertRaises(ValueError): client.verify()

    def test_setters_are_independent_and_wait_for_the_actual_off_barrier(self):
        client = control.Client(Path('/private/runtime/control.json'), 23, ())
        replies = [status(), status(False, True, False), status(False, False, False), status(False, False)]
        with patch.object(control.Client, 'request', side_effect=replies) as request, patch.object(control.time, 'sleep'):
            rows = client.switch({'collection': False, 'emission': False}, time.monotonic() + 5)
        self.assertEqual([row['command'] for row in rows], ['status', 'collection off', 'emission off', 'status'])
        self.assertEqual([call.args[0] for call in request.call_args_list], [row['command'] for row in rows])
        with patch.object(control.Client, 'request', return_value=status()) as request:
            self.assertEqual(len(client.switch({'collection': True, 'emission': True}, time.monotonic() + 5)), 1)
            self.assertEqual(request.call_count, 1)

    def test_wrong_setters_drifting_flags_and_unsettled_barriers_refuse(self):
        client = control.Client(Path('/private/runtime/control.json'), 23, ())
        requested = {'collection': False, 'emission': True}
        for replies in ([status(), status(False, False)],
                        [status(False, True, False), status(True, True)]):
            deadline = time.monotonic() + 5
            with self.subTest(replies=replies), patch.object(control.Client, 'request', side_effect=replies), \
                    patch.object(control.time, 'sleep'), self.assertRaises(ValueError):
                client.switch(requested, deadline)
        unsettled = status(False, True, False)
        expired = time.monotonic() - 1
        with patch.object(control.Client, 'request', return_value=unsettled), self.assertRaises(ValueError):
            client.switch(requested, expired)
        for value in ({}, {'collection': 1, 'emission': True}, None):
            with self.subTest(value=value), self.assertRaises(ValueError): client.switch(value, 5)


if __name__ == '__main__':
    unittest.main()
