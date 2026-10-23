"""The independent startup qualifier must keep all four states and call roots."""

import copy
import json
from pathlib import Path
import sys
import tempfile
from types import SimpleNamespace as NS
import tomllib
import unittest
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parent))
import java_startup_receipts as alterations
import qualify_java_controls as controls
import qualify_java_startup as qualifier
from test_generation_java_control_receipt import history, status
from test_generation_java_controls_qualification import populate
from test_generation_java_health import report as health_report
from test_generation_java_telemetry import metrics, span, traces


def populate_rotated(folder, states):
    populate(folder)
    steps, previous, completed, cursor = [], states[0], 0, 0
    for index, state in enumerate(states):
        before = {'history': history(dict(zip(('collection', 'emission'), previous)),
            dict(zip(('collection', 'emission'), state)), completed), 'cursor': cursor}
        completed += int(state[0])
        after = {key: status(dict(zip(('collection', 'emission'), state)), completed)
            for key in ('status', 'flush', 'settled')}
        received = []
        if state == (True, True):
            cursor = 1;received = [0]
        after.update(cursor=cursor, metric_bodies=received, held_ns=0 if state[1] else 1000000000)
        steps.append({'id': 'step-' + str(index), 'requested': dict(zip(('collection', 'emission'), state)),
            'before': before, 'after': after})
        previous = state
    record = {'control_schema_version': 1, 'plain': False, 'pid': 123,
        'interval_ms': 1000, 'steps': steps,
        'restored': {'history': history(dict(zip(('collection', 'emission'), previous)),
            {'collection': True, 'emission': True}, completed),
            'flush': status({'collection': True, 'emission': True}, completed), 'cursor': 3}}
    (folder / 'java-controls.json').write_text(json.dumps(record))
    return record


class JavaStartupQualificationTests(unittest.TestCase):
    def test_rotations_are_complete_immutable_and_unknown_names_refuse(self):
        for offset, name in enumerate(qualifier.STARTS):
            states = qualifier.startup_states(name)
            self.assertEqual(states, qualifier.STATES[offset:] + qualifier.STATES[:offset])
            self.assertEqual(set(states), set(qualifier.STATES))
        with self.assertRaises(ValueError):
            qualifier.startup_states('unknown')

    def test_all_six_policy_fixtures_keep_the_selected_initial_flags(self):
        for name in qualifier.STARTS:
            states = qualifier.startup_states(name)
            with self.subTest(name=name), tempfile.TemporaryDirectory() as temporary:
                root = Path(temporary)
                def command(arguments, folder, stage):
                    if stage == 'plan':
                        workspace = folder / 'workspace';workspace.mkdir()
                        (workspace / 'plan.json').write_text(json.dumps({'inventory': [
                            {'otelc_function': function, 'status': 'ready'} for function in controls.FUNCTIONS]}))
                        return str(workspace)
                    return ''
                with patch.object(controls, 'command', side_effect=command):
                    controls.prepare(root / 'cli', root / 'provider', root / 'case',
                        'safe-methods-v1', states=states, case_timeout_ms=60000)
                policy = tomllib.loads((root / 'case/equivalence.toml').read_text())
                self.assertEqual(policy['limits']['case_timeout_ms'], 60000)
                self.assertEqual(len(policy['fixtures']), 6)
                for fixture in policy['fixtures']:
                    actual = [(row['metrics']['collection'], row['metrics']['emission']) for row in fixture['sequence']]
                    self.assertEqual(tuple(actual), states)
                self.assertEqual(controls.STATES[0], (True, True))

    def test_receipt_and_positive_window_oracles_follow_each_rotation(self):
        for name in qualifier.STARTS:
            states = qualifier.startup_states(name)
            with self.subTest(name=name), tempfile.TemporaryDirectory() as temporary:
                folder = Path(temporary);populate_rotated(folder, states)
                controls.controls(folder, 'identity', plain=False, states=states)
                runtime = folder / 'sdk-runtime';runtime.mkdir()
                health = health_report();health['span_accounting'].update(sampled_started='4', sampled_ended='4')
                health['trace_exports'].update(units_started='4', units_succeeded='4')
                health['metric_exports'].update(batches_started='2', batches_succeeded='2', units_started='4', units_succeeded='4')
                (runtime / 'health.json').write_text(json.dumps(health))
                nodes = [span(bytes([index + 1]) * 8) for index in range(4)]
                for index, node in enumerate(nodes):
                    node.trace_id = bytes([index + 1]) * 16;node.name = 'Counter.identity'
                trace = traces(nodes)
                positive = sum(state[0] for state in states[:states.index((True, True)) + 1])
                launch = {'policy_sha256': 'a' * 64, 'selection_sha256': 'b' * 64}
                trace_decoder = NS(FromString=lambda _: trace)
                metric_decoder = NS(FromString=lambda raw: metrics(positive if raw == b'on' else 2))
                controls.verify_receipt(folder, launch, 123, trace_decoder, metric_decoder, states=states)
                metric_decoder = NS(FromString=lambda raw: metrics(positive - 1 if raw == b'on' else 2))
                with self.assertRaises(AssertionError):
                    controls.verify_receipt(folder, launch, 123, trace_decoder, metric_decoder, states=states)

    def test_alterations_target_actual_startup_flags_and_emission_off_window(self):
        for name in qualifier.STARTS:
            states = qualifier.startup_states(name)
            with tempfile.TemporaryDirectory() as temporary:
                original = populate_rotated(Path(temporary), states)
                edits = alterations.receipt_edits(states)
                self.assertEqual(len(edits), 8)
                for key in ('collection', 'emission'):
                    changed = copy.deepcopy(original);edits['initial-' + key](changed)
                    first = changed['steps'][0]['before']['history'][0]['status']
                    self.assertIs(first[key], not original['steps'][0]['before']['history'][0]['status'][key])
                    self.assertEqual(first['effective_emission_off'], not first['emission'] and first['in_flight_exports'] == 0)
                changed = copy.deepcopy(original);edits['held-window'](changed)
                index = next(index for index, state in enumerate(states) if not state[1])
                self.assertEqual(changed['steps'][index]['after']['held_ns'], 0)
                self.assertNotEqual(changed, original)

    def test_framework_keeps_explicit_states_and_refuses_duplicate_methods(self):
        states = qualifier.startup_states('both-off')
        rows = [{'report': '/reports/' + str(index)} for index in range(6)]
        with patch.object(qualifier, 'command', return_value='\n'.join(map(json.dumps, rows))), \
             patch.object(qualifier, 'check_report', side_effect=list(controls.FUNCTIONS)) as check:
            qualifier.framework(Path('/suite'), Path('/output'), 'framework', states)
            self.assertTrue(all(call.args[1] == states for call in check.call_args_list))
        with patch.object(qualifier, 'command', return_value='\n'.join(map(json.dumps, rows))), \
             patch.object(qualifier, 'check_report', return_value='Counter.identity(int)'), \
             self.assertRaises(AssertionError):
            qualifier.framework(Path('/suite'), Path('/output'), 'framework', states)


if __name__ == '__main__':
    unittest.main()
