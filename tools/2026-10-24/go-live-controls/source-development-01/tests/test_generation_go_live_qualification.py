"""Fixed Go live oracles refuse equal but wrong state, controls and telemetry."""

import copy
import json
from pathlib import Path
import tempfile
import tomllib
import unittest
from unittest.mock import patch

import go_live_fixture as fixture
import go_live_qualification as oracle
import go_live_receipt as receipt
import qualify_go_controls as qualifier


class GoLiveFixtureTests(unittest.TestCase):
    def test_all_startups_cover_four_states_and_restore_collected_panic_later(self):
        for start, initial in zip(fixture.STARTS, fixture.STATES):
            schedule = fixture.states(start)
            self.assertEqual(tuple(schedule[0].values()), initial)
            self.assertEqual({tuple(row.values()) for row in schedule}, set(fixture.STATES))
            self.assertEqual(schedule[-1], {'collection': True, 'emission': False})
            self.assertEqual(sum(row['collection'] for row in schedule), 2 + int(initial[0]))
            policy = tomllib.loads(fixture.policy(start))
            self.assertEqual(policy['adapters']['go']['backend'], 'source-scope-v1')
            self.assertEqual(policy['functions']['include'], [fixture.function(name) for name in (*fixture.METHODS, 'added')])
            item, = policy['fixtures']
            self.assertEqual(item['cases'], [[7]])
            self.assertEqual(item['receiver'], {'factory': 'New', 'arguments': [10]})
            self.assertEqual([row['metrics'] for row in item['sequence']], list(schedule))
            self.assertEqual([row['arguments'] for row in item['sequence']], ['case', [2], [4], [1], [-2]])
            self.assertEqual([i for i, row in enumerate(item['sequence']) if row['expected_baseline']['kind'] == 'error'], [4])
        with self.assertRaises(ValueError):
            fixture.states('unknown')

    def test_complete_graph_has_all_storage_locations_roots_and_first_field_alias(self):
        graph = fixture.graph(17, 7, 1, 7)
        self.assertEqual(len(graph['nodes']), 26)
        self.assertEqual(set(graph['roots']), fixture.ROOTS)
        nodes = graph['nodes']
        self.assertEqual(nodes[14]['fields']['location'], nodes[17]['fields']['location'])
        self.assertEqual(nodes[20]['fields']['value'], graph['roots']['receiver'])
        self.assertEqual(nodes[12]['fields']['value'], graph['roots']['receiver'])
        self.assertEqual(nodes[17]['fields']['value'], fixture.number(17))
        self.assertEqual(nodes[18]['fields']['value'], fixture.number(1))
        self.assertEqual(nodes[22]['fields']['value'], fixture.number(7))
        for value in fixture.SHADOWS:
            self.assertIn('global:' + value, graph['roots'])

    def test_intermediate_difference_is_restored_with_same_returns_and_final_graph(self):
        for amount in (0, 7):
            plain = fixture.observation('transient', amount, False, 'case', 'a' * 64)
            active = fixture.observation('transient', amount, True, 'case', 'a' * 64)
            self.assertEqual(plain['before'], active['before'])
            self.assertEqual(plain['after'], active['after'])
            self.assertEqual(plain['outcome'], active['outcome'])
            self.assertNotEqual(plain['steps'][0]['after'], active['steps'][0]['after'])
            self.assertNotEqual(plain['steps'][1]['before'], active['steps'][1]['before'])
            self.assertEqual(plain['steps'][1]['after'], active['steps'][1]['after'])
            for left, right in zip(plain['steps'][:4], active['steps'][:4]):
                self.assertEqual(left['outcome']['graph']['roots']['result'], right['outcome']['graph']['roots']['result'])

    def test_promoted_source_adds_method_and_changes_returns_without_changing_original(self):
        original = fixture.sources()
        changed = fixture.sources(changed=True)
        self.assertEqual(set(original), {'go.mod', 'counter/api.go', 'domain/types.go'})
        self.assertEqual(original['domain/types.go'], changed['domain/types.go'])
        self.assertNotIn(b') Added(', original['counter/api.go'])
        self.assertIn(b') Added(', changed['counter/api.go'])
        self.assertIn(b'return value.value+100}', changed['counter/api.go'])
        for method in fixture.METHODS:
            first = fixture.observation(method, 7, False, 'case', 'a' * 64)
            second = fixture.observation(method, 7, False, 'case', 'a' * 64, changed=True)
            self.assertEqual(first['after'], second['after'])
            a, b = (value['steps'][0]['outcome']['graph']['roots']['result'] for value in (first, second))
            self.assertEqual(int(b['value']) - int(a['value']), 100)
        self.assertEqual(original, fixture.sources())

    def test_strict_json_equality_refuses_boolean_numeric_and_float_substitutions(self):
        fixture.exact({'value': 1}, {'value': 1})
        for value in (True, 1.0, '1', None):
            with self.subTest(value=value), self.assertRaises(ValueError):
                fixture.exact({'value': value}, {'value': 1})

    def test_source_receipt_detects_new_files_edits_and_file_identity_changes(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            before = oracle.make_source(root)
            self.assertEqual(before, oracle.source_facts(root))
            source = root / 'counter/api.go'
            raw = source.read_bytes()
            source.unlink()
            source.write_bytes(raw)
            self.assertNotEqual(before, oracle.source_facts(root))
            (root / 'extra.go').write_text('package extra')
            with self.assertRaises(ValueError):
                oracle.source_facts(root)


def report_fixture(root: Path) -> Path:
    cases = []
    for method in fixture.METHODS:
        case_id = method + '-0'
        contract = {'observation_schema_version': 1, 'case_id': case_id, 'function_id': fixture.runtime_function(method),
                    'fixture_sha256': 'a' * 64, 'required_roots': sorted(fixture.ROOTS),
                    'expected_baseline': {'kind': 'error', 'category': 'panic', 'type': 'go.string'},
                    'steps': [{'id': 'step-' + str(index), 'action': 'call', 'required_roots': sorted(fixture.ROOTS),
                               'expected_baseline': {'kind': 'error', 'category': 'panic', 'type': 'go.string'}
                               if index == 4 else {'kind': 'return'}} for index in range(5)]}
        typed = {'contract': contract, 'expected_functions': {fixture.runtime_function(method): 5, receipt.FACTORY: 1},
                 'expected_spans': 6}
        for lane in ('baseline', 'instrumented_on'):
            typed[lane] = []
            for repeat in range(2):
                target = root / case_id / (lane + '-' + str(repeat))
                target.mkdir(parents=True)
                observation = fixture.observation(method, 7, lane != 'baseline', case_id, 'a' * 64)
                qualifier.write(target / 'typed-observation.json', observation)
                typed[lane].append({'observation': observation, 'execution': {
                    'capture_complete': True, 'channels': {'stdout': [], 'stderr': []},
                    'source_sha256_before': 'b' * 64, 'source_sha256_after': 'b' * 64,
                    'termination': {'kind': 'exit', 'code': 0}, 'witness': None}})
        qualifier.write(root / case_id / 'typed-bundle.json', {'typed_schema_version': 1, 'cases': [typed]})
        cases.append({'function': fixture.function(method), 'case': case_id, 'exit_code': int(method == 'transient'),
                      'arguments': [7], 'arguments_requested': [7], 'receiver_fixture': {'arguments': [10]},
                      'sequence': [{'metrics': row} for row in fixture.states('both-on')]})
    path = root / 'report.json'
    qualifier.write(path, {'source_preserved': True, 'blocked': [], 'claim': 'equivalence over these tests and observations',
                          'source_sha256': 'b' * 64, 'exit_code': 1, 'cases': cases,
                          'inventory': [{'status': 'ready', 'otelc_function': name} for name in fixture.FUNCTIONS]})
    return path


class GoLiveReportTests(unittest.TestCase):
    def test_every_lane_repeat_and_complete_literal_graph_is_checked(self):
        with tempfile.TemporaryDirectory() as temporary:
            path = report_fixture(Path(temporary))
            with patch.object(receipt, 'check') as runtime, patch.object(oracle.receivers, 'scope_attempt') as tooling:
                self.assertEqual(oracle.check_report(path, 2, start='both-on', provider=Path('sdk')), 8)
            self.assertEqual(runtime.call_count, 8)
            self.assertEqual(tooling.call_count, 8)

    def test_equal_wrong_values_types_aliases_and_panic_bytes_are_refused(self):
        for change in ('value', 'width', 'kind', 'alias', 'root', 'extra-node', 'error', 'step-order', 'return', 'fixture'):
            with self.subTest(change=change), tempfile.TemporaryDirectory() as temporary:
                root = Path(temporary)
                path = report_fixture(root)
                bundle_path = root / 'identity-0/typed-bundle.json'
                bundle = receipt.read(bundle_path)
                for lane in ('baseline', 'instrumented_on'):
                    for index, attempt in enumerate(bundle['cases'][0][lane]):
                        observed = attempt['observation']
                        graph = observed['steps'][0]['after']
                        if change == 'value': graph['nodes'][17]['fields']['value']['value'] = '999'
                        elif change == 'width': graph['nodes'][17]['fields']['value']['bits'] = 32
                        elif change == 'kind': graph['nodes'][17]['fields']['value']['signed'] = 1
                        elif change == 'alias': graph['nodes'][20]['fields']['value'] = fixture.reference(12)
                        elif change == 'root': graph['roots'].pop('global:nil')
                        elif change == 'extra-node': graph['nodes'].append({'id': 'extra', 'type': 'go.location', 'fields': {}})
                        elif change == 'error': observed['steps'][-1]['outcome']['graph']['roots']['error']['value'] = '00'
                        elif change == 'step-order': observed['steps'].reverse()
                        elif change == 'return': observed['steps'][0]['outcome']['graph']['roots']['result']['value'] = '99'
                        else: observed['fixture'] = {'status': 'blocked'}
                        qualifier.write(root / 'identity-0' / (lane + '-' + str(index)) / 'typed-observation.json', observed)
                qualifier.write(bundle_path, bundle)
                with patch.object(receipt, 'check'), patch.object(oracle.receivers, 'scope_attempt'), self.assertRaises(ValueError):
                    oracle.check_report(path, 2, start='both-on', provider=Path('sdk'))

    def test_missing_repeat_and_incomplete_inventory_are_refused(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            path = report_fixture(root)
            report = receipt.read(path)
            report['inventory'].pop()
            qualifier.write(path, report)
            with self.assertRaises(ValueError):
                oracle.check_report(path, 2, start='both-on', provider=Path('sdk'))
            report_fixture_again = root / 'other'
            report_fixture_again.mkdir()
            path = report_fixture(report_fixture_again)
            bundle_path = report_fixture_again / 'identity-0/typed-bundle.json'
            bundle = receipt.read(bundle_path)
            bundle['cases'][0]['baseline'].pop()
            qualifier.write(bundle_path, bundle)
            with self.assertRaises(ValueError):
                oracle.check_report(path, 2, start='both-on', provider=Path('sdk'))


class GoLiveReceiptTests(unittest.TestCase):
    def test_independent_setter_history_refuses_coupled_flags_and_missing_replies(self):
        previous, requested = {'collection': True, 'emission': False}, {'collection': False, 'emission': True}
        rows = [{'command': 'status', 'response': receipt.status(22, previous)},
                {'command': 'collection off', 'response': receipt.status(22, {'collection': False, 'emission': False})},
                {'command': 'emission on', 'response': receipt.status(22, requested)}]
        receipt.transition(rows, 22, previous, requested)
        for kind in ('pid', 'other-flag', 'missing', 'order', 'boolean'):
            changed = copy.deepcopy(rows)
            if kind == 'pid': changed[0]['response']['pid'] += 1
            elif kind == 'other-flag': changed[1]['response']['emission'] = True
            elif kind == 'missing': changed.pop()
            elif kind == 'order': changed.reverse()
            else: changed[2]['response']['collection'] = 0
            with self.subTest(kind=kind), self.assertRaises(ValueError):
                receipt.transition(changed, 22, previous, requested)

    def test_counter_encoding_is_exact_unsigned_decimal(self):
        for value in ('0', '1', str((1 << 64) - 1)):
            self.assertEqual(receipt.counter(value), int(value))
        for value in (False, 0, '01', '-1', '1.0', str(1 << 64), '\u0661'):
            with self.subTest(value=value), self.assertRaises(ValueError):
                receipt.counter(value)

    def test_metric_windows_refuse_uncollected_future_and_missing_restored_measurements(self):
        name = fixture.runtime_function('identity')
        calls = {name: 2, receipt.FACTORY: 0, '_error': 1}
        window = {(receipt.CALLS, name, ''): (1, 3, 2), (receipt.DURATION, name, ''): (1, 3, 2),
                  (receipt.ERRORS, name, 'panic'): (1, 3, 1)}
        receipt.metric_window({0: window}, 0, 1, calls, required=True)
        for kind in ('future', 'factory', 'missing-duration', 'missing-error'):
            changed = copy.deepcopy(window)
            if kind == 'future': changed[receipt.CALLS, name, ''] = (1, 3, 3)
            elif kind == 'factory': changed[receipt.CALLS, receipt.FACTORY, ''] = (1, 3, 1)
            elif kind == 'missing-duration': changed.pop((receipt.DURATION, name, ''))
            else: changed.pop((receipt.ERRORS, name, 'panic'))
            with self.subTest(kind=kind), self.assertRaises(ValueError):
                receipt.metric_window({0: changed}, 0, 1, calls, required=True)

    def test_framework_supplies_its_fixed_count_and_callback(self):
        with patch.object(qualifier.shared, 'framework', return_value=8) as execute:
            self.assertEqual(qualifier.framework(Path('workspace'), Path('folder'), 'test', check_report='oracle'), 8)
        execute.assert_called_once_with(Path('workspace'), Path('folder'), 'test', 2, 'oracle')


if __name__ == '__main__':
    unittest.main()
