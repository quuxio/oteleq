"""Prepared Java startup flags must be real before the first control setters."""

import json
from pathlib import Path
import sys
import tempfile
import time
import tomllib
import unittest
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[1]
sys.path[:0] = [str(ROOT / 'adapters/generation'), str(ROOT / 'examples')]
import java_control_receipt as receipt
import java_launch
import java_live
import java_provider
import sequences
from test_generation_java_control_receipt import STATES, history, status


def controlled_entry(states):
    return {'language': 'java', 'java_backend': 'prepared', 'path': 'Counter.java',
        'otelc_function': 'Counter.run(int)',
        'sequence_configuration': [{'id': 'step-' + str(index), 'action': 'call',
            'metrics': state.copy()} for index, state in enumerate(states)]}


def rotated_fixture(states):
    bodies, series, steps = [], {}, []
    previous, completed = states[0], 0
    for index, (state, size) in enumerate(zip(states, (1, 2, 3, 4))):
        before = {'history': history(previous, state, completed), 'cursor': len(bodies)}
        completed += size if state['collection'] else 0
        received = []
        if all(state.values()):
            received = [len(bodies)]
            series[len(bodies)] = {name: [(20, completed)]
                for name in ('otelc.function.calls', 'otelc.function.duration')}
            bodies.append(('/v1/metrics', b'positive'))
        after = {key: status(state, completed) for key in ('status', 'flush', 'settled')}
        after.update(cursor=len(bodies), metric_bodies=received,
            held_ns=0 if state['emission'] else 1000000000)
        steps.append({'id': 'step-' + str(index), 'requested': state.copy(),
            'before': before, 'after': after})
        previous = state
    series[len(bodies)] = {name: [(40, completed)]
        for name in ('otelc.function.calls', 'otelc.function.duration')}
    bodies.append(('/v1/metrics', b'restored'))
    record = {'control_schema_version': 1, 'plain': False, 'pid': 123,
        'interval_ms': 1000, 'steps': steps,
        'restored': {'history': history(previous, STATES[0], completed),
            'flush': status(STATES[0], completed), 'cursor': len(bodies)}}
    return record, controlled_entry(states), bodies, series, completed


class JavaStartupTests(unittest.TestCase):
    def test_complete_policy_and_fixed_properties_retain_each_initial_state(self):
        for offset in range(4):
            states = STATES[offset:] + STATES[:offset]
            entry = controlled_entry(states)
            with self.subTest(initial=states[0]):
                sequences.configure_controls(entry, entry['sequence_configuration'])
                data = java_provider.configuration(entry, 'http://127.0.0.1:4318', 'case')
                self.assertEqual(tomllib.loads(java_provider.policy(entry,
                    'http://127.0.0.1:4318', 'case')), data)
                properties = java_launch.plan_values(Path('/runtime'), data, {'methods': {}})
                for key, value in states[0].items():
                    self.assertIs(data['metrics'][key], value)
                    self.assertEqual(properties['metrics.' + key], str(value).lower())
                data['metrics']['collection'] = not states[0]['collection']
                self.assertEqual(entry['sequence_configuration'][0]['metrics'], states[0])

    def test_ordinary_calls_keep_enabled_startup_defaults(self):
        entry = controlled_entry(STATES)
        del entry['sequence_configuration']
        data = java_provider.configuration(entry, 'http://127.0.0.1:4318', 'case')
        self.assertTrue(data['metrics']['collection'])
        self.assertTrue(data['metrics']['emission'])

    def test_every_schedule_still_requires_a_positive_call(self):
        entry = controlled_entry(STATES)
        with self.assertRaisesRegex(ValueError, 'positive control'):
            sequences.configure_controls(entry, controlled_entry(STATES[1:])['sequence_configuration'])

    def test_complete_post_run_receipts_accept_every_startup_state(self):
        for offset in range(4):
            states = STATES[offset:] + STATES[:offset]
            record, entry, bodies, series, completed = rotated_fixture(states)
            with self.subTest(initial=states[0]), tempfile.TemporaryDirectory() as temporary:
                folder = Path(temporary)
                path = folder / 'java-controls.json'
                path.write_text(json.dumps(record));path.chmod(0o600)
                retained = receipt.read(folder, entry, 123, bodies, plain=False)
                self.assertEqual(receipt.qualify(retained, 123, bodies, [1, 2, 3, 4], series), completed)

    def test_post_run_initial_state_cannot_be_repaired_by_later_setters(self):
        for offset, state in enumerate(STATES):
            for key in ('collection', 'emission'):
                wrong = {**state, key: not state[key]}
                rows = history(wrong, state, 0)
                with self.subTest(state=state, key=key), self.assertRaisesRegex(ValueError, 'initial metric state'):
                    receipt.history(rows, 123, state, 0, initial=True)
                self.assertEqual(receipt.history(rows, 123, state, 0), 3)
                record, _, bodies, series, _ = rotated_fixture(STATES[offset:] + STATES[:offset])
                record['steps'][0]['before']['history'] = rows
                with self.assertRaisesRegex(ValueError, 'initial metric state'):
                    receipt.qualify(record, 123, bodies, [1, 2, 3, 4], series)

    def test_live_initial_state_is_checked_before_resuming_application(self):
        for state in STATES:
            with self.subTest(initial=state), tempfile.TemporaryDirectory() as temporary:
                folder = Path(temporary).resolve()
                entry = controlled_entry([state])
                session = java_live.Session(folder, folder / 'runtime',
                    entry['sequence_configuration'], [], plain=False, service="case", method="Counter.identity")
                session.pid = 123
                wrong = {**state, 'collection': not state['collection']}
                with patch.object(session, 'transition', return_value=history(wrong, state, 0)), \
                     patch.object(session, 'acknowledge') as acknowledge:
                    with self.assertRaisesRegex(ValueError, 'initial metric state'):
                        session.before(0, time.monotonic() + 1)
                    acknowledge.assert_not_called()
                    self.assertEqual(session.record['steps'], [])

    def test_live_initial_state_accepts_actual_matching_flags(self):
        for state in STATES:
            with self.subTest(initial=state), tempfile.TemporaryDirectory() as temporary:
                folder = Path(temporary).resolve()
                sequence = controlled_entry([state])['sequence_configuration']
                session = java_live.Session(folder, folder / 'runtime', sequence, [], plain=False, service="case", method="Counter.identity")
                session.pid = 123
                with patch.object(session, 'transition', return_value=history(state, state, 0)), \
                     patch.object(session, 'acknowledge') as acknowledge:
                    session.before(0, time.monotonic() + 1)
                    acknowledge.assert_called_once()
                self.assertEqual(session.record['steps'][0]['requested'], state)


if __name__ == '__main__':
    unittest.main()
