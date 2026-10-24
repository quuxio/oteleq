"""The live-control qualifier's fixed schedules and literal state denominators."""

import json
from pathlib import Path
import tempfile
import tomllib
import unittest

import python_live_qualification as oracle
from qualify_python_controls import evidence_facts


class PythonLiveQualificationTests(unittest.TestCase):
    def test_every_startup_rotates_all_four_states_and_restores_positive_control(self):
        for index, start in enumerate(oracle.STARTS):
            states = oracle.states(start)
            self.assertEqual((states[0]['collection'], states[0]['emission']), oracle.STATES[index])
            self.assertEqual({tuple(row.values()) for row in states[:4]}, set(oracle.STATES))
            self.assertEqual(states[-1], {'collection': True, 'emission': True})
            self.assertEqual(sum(row['collection'] for row in states), 3)
        with self.assertRaises(ValueError):
            oracle.states('unknown')

    def test_policy_fixes_all_methods_creation_arguments_profiles_and_error_boundary(self):
        for profile in oracle.PROFILES:
            for start in oracle.STARTS:
                policy = tomllib.loads(oracle.policy(profile, start))
                self.assertEqual(policy['adapters']['python']['profile'], profile)
                self.assertEqual(policy['functions']['include'], list(oracle.FUNCTIONS))
                self.assertEqual(len(policy['fixtures']), 6)
                for fixture in policy['fixtures']:
                    self.assertEqual(fixture['cases'], [[7]])
                    self.assertEqual(fixture['receiver']['arguments'], [10])
                    self.assertEqual([step['metrics'] for step in fixture['sequence']], list(oracle.states(start)))
                    self.assertEqual([step['arguments'] for step in fixture['sequence']], ['case', [2], [2], [2], [2]])
                    errors = [i for i, step in enumerate(fixture['sequence']) if step['expected_baseline']['kind'] == 'error']
                    self.assertEqual(errors, [0] if fixture['function'].endswith('.fail') else [])

    def test_recursive_and_error_metrics_count_only_collected_trees_and_initial_creator(self):
        for start in oracle.STARTS:
            states = oracle.states(start)
            initial = states[0]['collection']
            counts, calls, errors = oracle.expected_counts('recursive', 7, states, 12, 3)
            self.assertEqual(counts, [2] * 5)
            self.assertEqual(calls, {12: 6, **({3: 1} if initial else {})})
            _, calls, errors = oracle.expected_counts('fail', 7, states, 12, 3)
            self.assertEqual(calls[12], 3)
            self.assertEqual(errors, {12: int(initial), **({3: 0} if initial else {})})
            counts, calls, _ = oracle.expected_counts('recursive', 0, states, 12, 3)
            self.assertEqual(counts, [1, 2, 2, 2, 2])
            self.assertEqual(calls[12], 6 - int(initial))

    def test_five_call_graphs_include_complete_history_and_restored_intermediate_difference(self):
        for active in (False, True):
            raw = oracle.expected_raw('secret', 7, active)
            receiver = raw['after']['nodes'][raw['after']['roots']['receiver']['ref']]
            self.assertIn(['value', {'type': 'int', 'value': '25'}], receiver['fields'])
            self.assertEqual(raw['after']['roots']['static:Counter.total'], {'type': 'int', 'value': '15'})
            transient = oracle.expected_raw('transient', 7, active)
            first = transient['steps'][0]['after']
            receiver = first['nodes'][first['roots']['receiver']['ref']]
            self.assertIn(['value', {'type': 'int', 'value': str(17 + int(active))}], receiver['fields'])
        plain = oracle.expected_raw('transient', 7, False)
        instrumented = oracle.expected_raw('transient', 7, True)
        self.assertNotEqual(plain['steps'][0]['after'], instrumented['steps'][0]['after'])
        self.assertEqual(plain['after'], instrumented['after'])

    def test_current_source_oracle_changes_literal_token_without_mutating_original(self):
        for method in oracle.METHODS:
            original = json.dumps(oracle.expected_raw(method, 7, False), sort_keys=True)
            changed = json.dumps(oracle.expected_raw(method, 7, False, changed=True), sort_keys=True)
            self.assertIn('"value": "99"', original)
            self.assertNotIn('"value": "99"', changed)
            self.assertIn('"value": "101"', changed)
            self.assertEqual(original, json.dumps(oracle.expected_raw(method, 7, False), sort_keys=True))
        self.assertIn(b'self._token=101', oracle.sources(changed=True)[oracle.PATH])

    def test_retained_audit_facts_include_nested_files_bytes_and_inode_times(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            (root / 'nested').mkdir()
            path = root / 'nested/value'
            path.write_bytes(b'original')
            original = evidence_facts(root)
            self.assertEqual(set(original), {'nested/value'})
            self.assertEqual(len(original['nested/value']), 7)
            self.assertEqual(evidence_facts(root), original)
            path.write_bytes(b'changed')
            self.assertNotEqual(evidence_facts(root), original)
