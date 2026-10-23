"""The independent startup qualifier must keep all four states and call roots."""

import copy
from contextlib import redirect_stdout
import io
import json
import os
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
    def test_retained_alteration_recheck_keeps_names_reasons_and_zero_launches(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary);workspace = root / 'workspace';workspace.mkdir()
            destination = root / 'controls';destination.mkdir()
            (workspace / 'plan.json').write_text(json.dumps({'inventory': [{'otelc_function': 'Counter.identity(int)'}]}))
            states = qualifier.startup_states('both-off')
            names = [*alterations.receipt_edits(states), 'missing-trace', 'retained-metric',
                'sdk-pid', 'sdk-policy', 'sdk-loss', 'sdk-drain']
            rows = [{'name': name, 'refused': True, 'reason':
                'initial metric state differs' if name.startswith('initial-') else
                'independent state differs' if name == 'setter' else 'refused-' + name} for name in names]
            record = {'actual_applications': 0, 'copied_attempts': 15, 'evidence_refusals': 14, 'controls': rows}
            path = destination / 'QUALIFICATION.json';path.write_text(json.dumps(record));original = path.read_bytes()
            with patch.object(alterations, 'verify', side_effect=[None, *[ValueError(row['reason']) for row in rows]]) as verify, \
                 patch.object(alterations.shutil, 'copytree') as copytree:
                self.assertEqual(alterations.recheck(destination, workspace, states), record)
            self.assertEqual(verify.call_count, 15);copytree.assert_not_called()
            self.assertEqual(path.read_bytes(), original)
            with patch.object(alterations, 'verify', return_value=None), self.assertRaises(AssertionError):
                alterations.recheck(destination, workspace, states)
            changed = copy.deepcopy(record);changed['controls'][0]['name'] = 'foreign'
            path.write_text(json.dumps(changed))
            with self.assertRaises(AssertionError):alterations.recheck(destination, workspace, states)
            for name in ('initial-collection', 'initial-emission', 'setter'):
                with self.assertRaisesRegex(ValueError, 'unrelated'):
                    alterations.refusal_reason(name, ValueError('unrelated SDK failure'))

    def test_explicit_recheck_never_runs_routes_or_overwrites_the_original_result(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary).resolve()
            folder = root / 'evidence';folder.mkdir()
            original = folder / 'QUALIFICATION.json';original.write_text('preserve original result')
            provider = root / 'provider';provider.mkdir()
            cli = root / 'cli';cli.touch()
            arguments = ['qualifier', '--cli', str(cli), '--otelc-root', str(provider),
                '--report-dir', str(folder), '--java-profile', 'archive-methods-v1', '--startup-state', 'both-off', '--recheck']
            output = io.StringIO()
            with patch.object(sys, 'argv', arguments), patch.dict(os.environ), redirect_stdout(output), \
                 patch.object(qualifier, 'retained_workspace', return_value=folder / 'workspace') as workspace, \
                 patch.object(qualifier, 'routes') as routes, \
                 patch.object(alterations, 'qualify') as execute_controls, \
                 patch.object(alterations, 'recheck', return_value={'evidence_refusals': 14}) as existing_controls, \
                 patch.object(qualifier, 'recheck', return_value={'actual_jvm_launches': 188}) as audit:
                qualifier.main()
            result = json.loads(output.getvalue())
            self.assertEqual(result['new_application_launches'], 0)
            self.assertEqual(result['mode'], 'retained_recheck')
            self.assertEqual(original.read_text(), 'preserve original result')
            self.assertEqual(json.loads((Path(result['audit_directory']) / 'QUALIFICATION.json').read_text()), result)
            routes.assert_not_called();execute_controls.assert_not_called()
            workspace.assert_called_once_with(folder, provider, 'archive-methods-v1', cli)
            self.assertEqual(audit.call_args.kwargs['java_profile'], 'archive-methods-v1')
            self.assertEqual(audit.call_args.kwargs['comparison_directory'], Path(result['audit_directory']) / 'comparisons')
            existing_controls.assert_called_once_with(folder / 'evidence-controls', folder / 'workspace', qualifier.startup_states('both-off'))

    def test_retained_workspace_refuses_unfinished_operations_and_profile_substitution(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary).resolve();provider = root / 'provider';provider.mkdir()
            workspace = root / 'corpus/cases/oteleq-run-fixture';workspace.mkdir(parents=True)
            plan = {'otelc_root': str(provider), 'inventory': [
                {'id': str(index), 'status': 'ready', 'otelc_function': name, 'java_profile': 'archive-methods-v1'}
                for index, name in enumerate(controls.FUNCTIONS)], 'source': str(root / 'corpus/cases/application')}
            (workspace / 'plan.json').write_text(json.dumps(plan))
            cli = root / 'cli'
            operations = qualifier.route_operations(root / 'corpus', workspace, cli)
            for name, expected in operations.items():
                for suffix in ('.stdout', '.stderr'):(root / 'corpus' / (name + suffix)).touch()
                (root / 'corpus' / (name + '.started.json')).write_text(json.dumps(expected))
                (root / 'corpus' / (name + '.exit')).write_text(str(expected['expected_exit']) + '\n')
            check = lambda: qualifier.retained_workspace(root, provider, 'archive-methods-v1', cli)
            self.assertEqual(check(), workspace)
            marker = root / 'corpus/run.started.json'
            (root / 'corpus/run.exit').write_text('0\n')
            with self.assertRaises(AssertionError):check()
            (root / 'corpus/run.exit').write_text('1\n')
            self.assertEqual(check(), workspace)
            with self.assertRaises(AssertionError):qualifier.retained_workspace(root, provider, 'stock-methods-v1', cli)
            foreign = root / 'foreign';foreign.mkdir()
            with self.assertRaises(AssertionError):qualifier.retained_workspace(root, foreign, 'archive-methods-v1', cli)
            for name in operations:
                with self.subTest(missing=name):
                    selected = root / 'corpus' / (name + '.started.json')
                    original = selected.read_bytes();selected.unlink()
                    exit_path = root / 'corpus' / (name + '.exit')
                    exit_bytes = exit_path.read_bytes();exit_path.unlink()
                    with self.assertRaises(AssertionError):check()
                    selected.write_bytes(original);exit_path.write_bytes(exit_bytes)
            for change in ('argv', 'exit', 'bool', 'extra'):
                record = copy.deepcopy(operations['run'])
                if change == 'argv':record['argv'][1] = 'clean'
                elif change == 'extra':record['foreign'] = True
                else:record['expected_exit'] = True if change == 'bool' else 0
                marker.write_text(json.dumps(record))
                with self.subTest(substitution=change), self.assertRaises(AssertionError):check()
            marker.write_text(json.dumps(operations['run']))
            for suffix in ('.stdout', '.stderr'):
                selected = root / 'corpus' / ('export-run' + suffix);selected.unlink()
                with self.subTest(missing=suffix), self.assertRaises(AssertionError):check()
                selected.touch()
            # Optional historical comparator records do not supply route evidence.
            optional = root / 'corpus/comparison/startup-recomparison.started.json'
            optional.parent.mkdir();optional.write_text('{}')
            self.assertEqual(check(), workspace)

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
