"""Independent qualifier oracles reject matching wrong values and foreign controls."""

import copy
import json
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch
import tomllib

import test_generation_java_handle_witness as handles
import test_generation_java_witness as direct
import java_action_fixture as fixture
import java_action_audit as audit
import qualify_java_generated_actions as qualifier


def graph(value: int, total: int, amount: int, *, result=False, error=False) -> dict:
    reference = {'kind': 'reference', 'node_id': 'receiver'}
    roots = {'receiver': reference, 'argument:0': fixture.integer(amount), 'static:Counter.total': fixture.integer(total)}
    nodes = [{'id': 'receiver', 'type': 'java.object:Counter', 'fields': {'value': fixture.integer(value), 'self': reference}}]
    if result:roots['result'] = reference
    if error:
        roots['error'] = {'kind': 'reference', 'node_id': 'error'}
        nodes += [{'id': 'error', 'type': 'java.lang.IllegalStateException',
                   'fields': {'message': {'kind': 'reference', 'node_id': 'message'}}},
                  {'id': 'message', 'type': 'java.object:java.lang.String',
                   'fields': {'value': {'kind': 'string', 'type': 'java.lang.String', 'encoding': 'utf16_be',
                                        'value': 'negative'.encode('utf-16-be').hex()}}}]
    return {'roots': roots, 'nodes': nodes}


def observation() -> dict:
    steps = []
    for index, (before, after, previous, total, amount) in enumerate(zip(
            (10, 10, 16, 16), (10, 16, 16, 17), (0, 1, 5, 6), (1, 5, 6, 8), (0, 3, -1, 1))):
        failed = index == 2
        outcome = {'kind': 'error' if failed else 'return',
                   'graph': graph(after, total, amount, result=not failed, error=failed)}
        if failed:outcome['category'] = 'exception'
        steps.append({'id': 'step-' + str(index), 'action': 'call', 'gaps': [],
                      'before': graph(before, previous, amount), 'after': graph(after, total, amount), 'outcome': outcome})
    return {'function_id': fixture.COUNTER, 'gaps': [], 'fixture': {'status': 'ready'}, 'steps': steps,
            'before': steps[0]['before'], 'after': steps[-1]['after'], 'outcome': steps[-1]['outcome']}


def history() -> tuple:
    identity = handles.identity()
    expected = dict(identity.hashes)
    ready = {**direct.scope(False), 'route_verified': False}
    armed = {**ready, 'phase': 'armed', 'scope_id': 'd' * 32, 'case_id': 'e' * 64, 'attempt_id': 'f' * 64}
    done = handles.reply('3' * 32)
    value = {'case_id': 'e' * 64, 'attempt_id': 'f' * 64, 'expected': expected,
             'armed': [{'ready': {'thread_id': '41'}, 'scope': armed}], 'completed': [done]}
    arguments = [identity.runtime_id, armed['cookie'], armed['sequence'], value['case_id'], value['attempt_id'],
        expected['build_sha256'], expected['selection_sha256'], expected['tooling_sha256'],
        expected['wrapper_probe_id'], expected['policy_sha256'], '41', expected['route_binding_sha256']]
    rows = [{'operation': 'status', 'arguments': [], 'reply': {**handles.reply('1' * 32), 'scope': ready}},
            {'operation': 'arm', 'arguments': arguments, 'reply': {**handles.reply('2' * 32), 'scope': armed}},
            {'operation': 'end', 'arguments': [identity.runtime_id, armed['scope_id']], 'reply': done}]
    return value, rows, identity


class JavaActionQualificationTests(unittest.TestCase):
    def test_complete_literal_receiver_oracle_accepts_only_the_known_fixture(self):
        value = observation()
        self.assertEqual(fixture.observation(value, fixture.COUNTER, 0, instrumented=False), 12)
        self.assertEqual(fixture.observation(value, fixture.COUNTER, 0, instrumented=True), 12)
        edits = [lambda item: item['steps'][0]['after']['nodes'][0]['fields']['value'].update(value='99'),
                 lambda item: item['steps'][0]['before']['roots']['argument:0'].update(value='1'),
                 lambda item: item['steps'][0]['after']['nodes'][0]['fields']['self'].update(node_id='other'),
                 lambda item: item['steps'][2]['outcome']['graph']['nodes'][-1]['fields']['value'].update(value='0000'),
                 lambda item: item['steps'][2]['outcome'].update(kind='return'),
                 lambda item: item['steps'].reverse(), lambda item: item['steps'].pop(),
                 lambda item: item['steps'][0].update(gaps=['missing observation']),
                 lambda item: item.update(gaps=['missing observation'])]
        for edit in edits:
            value = copy.deepcopy(observation());edit(value)
            with self.assertRaises(AssertionError):fixture.observation(value, fixture.COUNTER, 0, instrumented=True)

    def test_static_oracle_separately_checks_inputs_global_mutation_and_changed_current_bodies(self):
        for instrumented in (False, True):
            for base, returned in ((10, 7), (20, 9)):
                before = {'roots': {'global:Work.total': fixture.integer(base, scalar=True)}, 'nodes': []}
                after = {'roots': {'global:Work.total': fixture.integer(base + 7 + instrumented, scalar=True)}, 'nodes': []}
                value = {'function_id': fixture.STATIC, 'gaps': [], 'fixture': {'status': 'ready'},
                    'before': before, 'after': after, 'outcome': {'kind': 'return', 'graph': {
                        'roots': {**after['roots'], 'result': fixture.integer(returned, scalar=True)}, 'nodes': []}}}
                self.assertEqual(fixture.observation(value, fixture.STATIC, 7, instrumented=instrumented,
                    static_base=base, static_return=returned), 3)
                value['outcome']['graph']['roots']['result'] = fixture.integer(0, scalar=True)
                with self.assertRaises(AssertionError):fixture.observation(value, fixture.STATIC, 7,
                    instrumented=instrumented, static_base=base, static_return=returned)

    def test_all_initial_states_are_frozen_with_an_independent_both_on_control(self):
        with tempfile.TemporaryDirectory() as temporary:
            folder = Path(temporary)
            for profile in ('safe-methods-v1', 'archive-methods-v1'):
                for start in range(4):
                    config = tomllib.loads(fixture.configuration(folder, profile, start=start).read_text())
                    steps = config['fixtures'][0]['sequence']
                    self.assertEqual(steps[0]['metrics'], dict(zip(('collection', 'emission'), fixture.STATES[start])))
                    self.assertEqual({tuple(step['metrics'].values()) for step in steps}, set(fixture.STATES))
                    self.assertEqual(steps[2]['expected_baseline']['type'], 'java.lang.IllegalStateException')
                    self.assertEqual(len(config['fixtures']), 2)
            self.assertEqual(len(tomllib.loads(fixture.configuration(folder, 'safe-methods-v1', counter_only=True).read_text())['fixtures']), 1)
            for start in (-1, 4, True):
                with self.assertRaises(AssertionError):fixture.states(start)

    def test_control_history_binds_status_arm_end_and_every_retry(self):
        value, rows, identity = history()
        audit.control_history(value, rows, identity)
        retry = copy.deepcopy(rows[2]);retry['reply'].update(error='root_active', scope=value['armed'][0]['scope'])
        audit.control_history(value, rows[:2] + [retry] + rows[2:], identity)
        for key, changed in (('cookie', '0' * 32), ('thread_id', '42'), ('scope_id', '0' * 32),
                             ('sequence', '2'), ('case_id', '0' * 64), ('attempt_id', '0' * 64)):
            bad = copy.deepcopy(retry);bad['reply']['scope'][key] = changed
            with self.subTest(key=key), self.assertRaises(ValueError):
                audit.control_history(value, rows[:2] + [bad] + rows[2:], identity)
        contradictory = copy.deepcopy(rows[2]);contradictory['reply']['error'] = 'incomplete'
        with self.assertRaises(AssertionError):audit.control_history(value, rows[:2] + [contradictory] + rows[2:], identity)
        with self.assertRaises(AssertionError):audit.control_history(value, rows[:-1], identity)

    def test_foreign_arguments_missing_readiness_and_changed_completions_cannot_pass(self):
        value, rows, identity = history()
        for index in range(len(rows[1]['arguments'])):
            changed = copy.deepcopy(rows);changed[1]['arguments'][index] = 'foreign'
            with self.subTest(argument=index), self.assertRaises(AssertionError):audit.control_history(value, changed, identity)
        with self.assertRaises(AssertionError):audit.control_history(value, rows[1:], identity)
        changed = copy.deepcopy(rows);changed[2]['arguments'][1] = '0' * 32
        with self.assertRaises(AssertionError):audit.control_history(value, changed, identity)
        changed = copy.deepcopy(value);changed['completed'][0]['error'] = 'foreign'
        with self.assertRaises(AssertionError):audit.control_history(changed, rows, identity)

    def test_public_fixture_preparation_and_framework_counts_do_not_skip_requested_cases(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary);workspace = root / 'workspace';workspace.mkdir()
            (workspace / 'plan.json').write_text(json.dumps({'inventory': [
                {'otelc_function': function, 'status': 'ready'} for function in (fixture.COUNTER, fixture.STATIC)]}))
            with patch.object(qualifier, 'command', return_value=str(workspace)) as execute:
                current, source = qualifier.prepare(Path('/cli'), Path('/sdk'), root / 'run', Path('/jdk/java'), 'safe-methods-v1')
                self.assertEqual(current, workspace);self.assertIn('private static int target', (source / 'Work.java').read_text())
                self.assertEqual(execute.call_count, 2)
                self.assertEqual(execute.call_args.args[0][1], 'generate')
            output = '\n'.join(json.dumps({'report': name}) for name in ('/one/report.json', '/two/report.json'))
            with patch.object(qualifier, 'command', return_value=output):
                self.assertEqual(len(qualifier.framework(workspace, root, 'framework')), 2)
            with patch.object(qualifier, 'command', return_value=''):
                with self.assertRaises(AssertionError):qualifier.framework(workspace, root, 'framework')


if __name__ == '__main__':
    unittest.main()
