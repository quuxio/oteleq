"""Owned native schedules use actual private files and literal SDK replies, without SDK builds."""

from contextlib import ExitStack
import copy
from pathlib import Path
import os
import sys
import tempfile
import unittest
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[1]
sys.path[:0] = [str(ROOT / 'adapters/generation'), str(ROOT / 'examples')]

import native_control
import native_live
import native_protocol
import native_session
import sequences
from test_generation_native_controls import running, status
from test_generation_native_execution import complete, write
from test_generation_native_rendezvous import private, ready
from test_generation_native_sequence import entry, frame
from test_generation_native_session import setup
import native_provider_fixture as fixture


class SDK:
    """Only literal command semantics; no SDK implementation or renderer is imported."""

    def __init__(self, live):
        self.live, self.calls, self.flushes = live, 0, 0
        metrics = live.launch.intent.policy()['metrics']
        self.flags = {key: metrics[key] for key in ('collection', 'emission')}

    def request(self, command, deadline):
        if command == 'health':
            value = running(self.calls, self.flags)
            value.update(policy_sha256=self.live.record['policy_sha256'],
                         selection_sha256=self.live.record['selection_sha256'])
            value['metric_flush']['attempts'] = str(self.flushes)
            return value
        if command == 'flush': self.flushes += 1
        elif command.startswith(('collection ', 'emission ')):
            name, setting = command.split(); self.flags[name] = setting == 'on'
        return status(**self.flags)

    switch = native_control.Client.switch

    def verify(self):
        native_control.status(status(**self.flags), 23)


class Fixture:
    """The regular native owner still binds original start/completion records."""

    def __init__(self, base, *, flags=((True, True), (False, True), (True, False), (False, False)),
                 plain=False, error_steps=()):
        self.stack = ExitStack()
        metrics = {'collection': flags[0][0], 'emission': flags[0][1],
                   'histogram_boundaries_seconds': [1e-6, 1e-5, 1e-4, .001, .01, .1, 1.]}
        with patch.dict(fixture.POLICY, {'metrics': metrics, 'traces': {'enabled': True, 'sample_ratio': 1.}}):
            self.owner, self.process, identities = setup(base, plain=plain)
        self.entry = entry(flags=flags)
        for index in error_steps:
            self.entry['sequence_configuration'][index]['expected_baseline'] = {'kind': 'error'}
        concrete = sequences.concrete(self.entry, [7], lambda selected, args: args)
        self.bodies, self.clock = [], [100.]
        self.live = native_live.Session(self.owner.launch, base, self.entry, concrete, [7], self.bodies, 65536)
        self.owner.controls = self.live
        self.sdk = SDK(self.live)
        self.stack.enter_context(patch.object(native_session, 'kernel', side_effect=lambda pid, deadline: identities[pid]))
        self.stack.enter_context(patch.object(native_control, 'connect', return_value=self.sdk))
        self.stack.enter_context(patch.object(native_live.time, 'monotonic', side_effect=lambda: self.clock[0]))
        self.stack.enter_context(patch.object(native_live.time, 'monotonic_ns', side_effect=lambda: int(self.clock[0] * 1e9)))
        self.owner.poll(self.process, 1000)

    def close(self):
        self.stack.close()

    def phase(self, *, raw=None, publish=True):
        phase = self.live.checkpoints.phases[self.live.checkpoints.position]
        if publish: ready(self.live.checkpoints)
        if phase.startswith('after-'):
            index = int(phase.split('-')[1])
            private(self.live.checkpoints.root / ('step-' + str(index) + '.observation'),
                    frame(10 + index, 11 + index) if raw is None else raw)
            self.sdk.calls += 1
        self.owner.poll(self.process, 1000)
        if self.live.holding is not None:
            self.clock[0] += 1.
            self.owner.poll(self.process, 1000)

    def finish(self):
        while self.live.checkpoints.position < len(self.live.checkpoints.phases): self.phase()
        final = complete(self.owner.started)
        if final['sdk_health'] is not None:
            final['sdk_health']['function_accounting'].update(started=str(self.sdk.calls), ended=str(self.sdk.calls))
            final['sdk_health']['span_accounting'].update(sampled_started=str(self.sdk.calls), sampled_ended=str(self.sdk.calls))
            final['sdk_health']['metric_flush']['attempts'] = str(self.sdk.flushes)
            write(self.owner.launch.intent.runtime / 'app/health.json', final['sdk_health'])
        write(self.owner.launch.intent.runtime / 'native-execution.json', final)
        self.owner.finish(self.process)
        return self.owner.execution


class NativeLiveTests(unittest.TestCase):
    def fixture(self, base, **options):
        value = Fixture(Path(base).resolve(), **options)
        self.addCleanup(value.close)
        return value

    def test_one_original_owner_records_every_state_frame_and_restoration(self):
        with tempfile.TemporaryDirectory() as base:
            value = self.fixture(base)
            completed = value.finish()
            self.assertEqual(value.live.record['pid'], 23)
            self.assertEqual(value.live.record['supervisor_pid'], 22)
            self.assertEqual(value.live.statuses, sum(len(step['before']['history']) + 7 for step in value.live.record['steps'])
                             + len(value.live.record['restored']['history']) + 2)
            self.assertTrue(all(value.sdk.flags.values()))
            self.assertEqual(len(value.live.checkpoints.frames), 4)
            value.live.verify(); completed.verify()
            self.assertEqual(len(value.owner.records), 3)
            self.assertEqual(value.owner.environment(), value.live.environment())
            from native_sequence import decode
            observed = decode(value.live.observation.content, value.entry)
            self.assertEqual([step['after']['roots']['global:g']['value'] for step in observed['steps']], ['11', '12', '13', '14'])
            for step in value.live.record['steps'][1:]: self.assertGreaterEqual(step['after']['held_ns'], 1_000_000_000)
            self.assertEqual(value.live.final.value(), value.live.record)

    def test_all_four_startup_states_precede_the_first_call(self):
        for flags in ((False, False), (False, True), (True, False), (True, True)):
            with self.subTest(flags=flags), tempfile.TemporaryDirectory() as base:
                value = self.fixture(base, flags=(flags, (True, True)))
                value.finish()
                self.assertEqual(value.live.record['steps'][0]['before']['history'][0]['status'], status(*flags))
                self.assertEqual(value.sdk.calls, 2)
                value.close()

    def test_plain_worker_uses_the_same_checkpoints_without_any_sdk_requests(self):
        with tempfile.TemporaryDirectory() as base:
            value = self.fixture(base, plain=True)
            completed = value.finish()
            self.assertIsNone(value.live.client)
            self.assertIsNone(completed.health)
            self.assertEqual(value.live.statuses, 0)
            self.assertEqual(value.owner.environment(), value.live.environment())
            self.assertTrue(all(step['before']['health'] is None for step in value.live.record['steps']))
            value.owner.poll(value.process, 1000)

    def test_disabled_window_rejects_actual_receiver_metric_bodies(self):
        with tempfile.TemporaryDirectory() as base:
            value = self.fixture(base, flags=((False, True), (True, True)))
            value.phase()
            ready(value.live.checkpoints)
            private(value.live.checkpoints.root / 'step-0.observation', frame())
            value.sdk.calls += 1
            value.owner.poll(value.process, 1000)
            value.bodies.append(('/v1/metrics', b'actual-window-marker'))
            value.clock[0] += 1
            with self.assertRaisesRegex(ValueError, 'disabled metrics'): value.owner.poll(value.process, 1000)
            self.assertEqual(value.live.checkpoints.position, 1)

    def test_wrong_startup_state_unplanned_calls_and_expired_deadline_cannot_release(self):
        for kind in ('flags', 'calls', 'deadline'):
            with self.subTest(kind=kind), tempfile.TemporaryDirectory() as base:
                value = self.fixture(base); ready(value.live.checkpoints)
                if kind == 'flags': value.sdk.flags['collection'] = False
                elif kind == 'calls': value.sdk.calls = 1
                else: value.clock[0] = 1001
                with self.assertRaises(ValueError): value.owner.poll(value.process, 1000)
                self.assertFalse(value.live.checkpoints.flag('before-0', 'resume').exists())
                value.close()

    def test_missing_frames_bad_outcomes_or_early_exit_are_not_success(self):
        for kind in ('missing', 'malformed', 'early'):
            with self.subTest(kind=kind), tempfile.TemporaryDirectory() as base:
                value = self.fixture(base, flags=((True, True),))
                if kind == 'early':
                    with self.assertRaises(ValueError): value.live.finish(None)
                else:
                    value.phase(); ready(value.live.checkpoints)
                    if kind == 'missing':
                        with self.assertRaises(FileNotFoundError): value.owner.poll(value.process, 1000)
                    else:
                        private(value.live.checkpoints.root / 'step-0.observation', b'bad scalar frame')
                        value.sdk.calls += 1
                        value.owner.poll(value.process, 1000); value.owner.poll(value.process, 1000)
                        with self.assertRaises(ValueError): value.finish()
                value.close()

    def test_published_control_and_original_frame_facts_cannot_be_rebound(self):
        for kind in ('publication', 'frame'):
            with self.subTest(kind=kind), tempfile.TemporaryDirectory() as base:
                value = self.fixture(base, flags=((True, True),)); value.phase(); value.phase()
                held = value.live.publications[0].file if kind == 'publication' else value.live.checkpoints.frames[0]
                held.path.write_bytes(held.path.read_bytes())
                with self.assertRaises(ValueError): value.live.verify()
                value.close()


if __name__ == '__main__':
    unittest.main()
