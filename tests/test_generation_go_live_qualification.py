"""Fixed Go live oracles refuse equal but wrong state, controls and telemetry."""

import copy
import json
from pathlib import Path
import shutil
import tempfile
import tomllib
import unittest
from unittest.mock import Mock, patch

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
                    'termination': {'kind': 'exit', 'code': 0},
                    'witness': None if lane == 'baseline' else {'functions': typed['expected_functions']}}})
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
    def test_explicit_archive_uses_bound_original_receipts_after_every_byte_matches(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary).resolve(); original = root / 'original'; original.mkdir()
            report = report_fixture(original)
            archived = root / 'archive'; shutil.copytree(original, archived)
            with patch.object(receipt, 'check') as runtime, patch.object(oracle.receivers, 'scope_attempt'):
                self.assertEqual(oracle.check_report(archived / 'report.json', 2, start='both-on',
                                                    provider=Path('sdk'), original=report), 8)
            self.assertTrue(all(call.args[0].is_relative_to(original) for call in runtime.call_args_list))
            target = archived / 'identity-0/typed-bundle.json'
            target.write_text('{}')
            with patch.object(receipt, 'check') as runtime, self.assertRaises(ValueError):
                oracle.check_report(archived / 'report.json', 2, start='both-on', provider=Path('sdk'), original=report)
            runtime.assert_not_called()

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


class GoLiveWorkflowTests(unittest.TestCase):
    def test_archive_original_requires_unique_launch_ids_and_identical_complete_evidence(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary).resolve(); original = root / 'actual'; original.mkdir()
            qualifier.write(original / 'report.json', {'cases': [{'case': 'case'}]})
            for lane in ('baseline', 'instrumented_on'):
                for repeat in range(2):
                    runtime = original / 'case' / (lane + '-' + str(repeat)) / 'go-runtime'
                    runtime.mkdir(parents=True)
                    qualifier.write(runtime / 'go-application-start.json', {'launch_id': lane + str(repeat)})
            archived = root / 'shrink/original'; archived.parent.mkdir(); shutil.copytree(original, archived)
            paths = [original / 'report.json', archived / 'report.json']
            self.assertEqual(qualifier.archived_original(paths, root), {paths[1]: paths[0]})
            with self.assertRaises(ValueError): qualifier.archived_original(paths[:1], root)
            duplicate = root / 'duplicate'; shutil.copytree(original, duplicate)
            with self.assertRaises(ValueError): qualifier.archived_original([*paths, duplicate / 'report.json'], root)
            qualifier.write(archived / 'report.json', {'cases': [{'case': 'case'}], 'edited': True})
            with self.assertRaises(ValueError): qualifier.archived_original(paths, root)

    def test_comparison_controls_remove_unreachable_storage_and_freeze_panic_contract(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            report = report_fixture(root)
            output = root / 'controls'; output.mkdir()

            def command(argv, folder, name, expected):
                self.assertEqual(expected, qualifier.shared.CONTROL_VERDICTS[name][0])
                return json.dumps({'verdict': qualifier.shared.CONTROL_VERDICTS[name][1]})

            with patch.object(qualifier, 'command', side_effect=command) as run:
                qualifier.controls(Path('cli'), report, output)
            self.assertEqual(run.call_count, 5)
            changed = receipt.read(output / 'missing-field.json')['cases'][0]
            for attempt in changed['instrumented_on']:
                graph = attempt['observation']['steps'][0]['after']
                fields = next(node for node in graph['nodes'] if node['id'] == 'n16')['fields']
                self.assertNotIn('value', fields)
                self.assertNotIn('n17', {node['id'] for node in graph['nodes']})
                self.assertIn('n15', {node['id'] for node in graph['nodes']})
            changed = receipt.read(output / 'undeclared-intermediate-error.json')['cases'][0]
            self.assertEqual(changed['contract']['steps'][-1]['expected_baseline'], {'kind': 'return'})

    def test_promoted_suites_require_the_new_method_and_preserve_source_spelling(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            source, bundle = root / 'source', root / 'bundle'
            reports = []
            for name in (*fixture.METHODS, 'added'):
                path = root / (name + '.json')
                qualifier.write(path, {'cases': [{'function': fixture.function(name)}]})
                reports.append({'report': str(path)})
            output = '\n'.join(json.dumps(row) for row in [{'project_source': str(source)}, *reports])
            check = Mock()
            with patch.object(qualifier, 'command', return_value=output) as execute:
                qualifier.current_suite(bundle, source, root, 'changed', check, changed=True)
            self.assertEqual(check.call_count, 3)
            self.assertEqual(execute.call_args.args[-1], {'OTELEQ_SOURCE': str(source), 'OTELEQ_WORKSPACE_PARENT': str(root)})
            for rows in (reports[:-1], [reports[0], reports[0], reports[2]]):
                wrong = '\n'.join(json.dumps(row) for row in [{'project_source': str(source)}, *rows])
                with patch.object(qualifier, 'command', return_value=wrong), self.assertRaises(ValueError):
                    qualifier.current_suite(bundle, source, root, 'changed', check, changed=True)

    def test_run_keeps_original_inputs_and_promotes_both_original_and_changed_sources(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary) / 'evidence'
            workspace = root / 'cases/workspace'
            with patch.object(qualifier.shared, 'plan_generate', return_value=workspace) as plan, \
                    patch.object(qualifier.shared, 'exercise_routes') as routes, \
                    patch.object(qualifier, 'current_suite') as current, \
                    patch.object(qualifier, 'command', return_value='{"mode":"dry-run","files":["test.py"]}') as commands:
                qualifier.run(Path('cli'), Path('sdk'), root, 'both-off', {'frozen': 'inputs'}, min_free_bytes=123)
            configured = tomllib.loads((root / 'cases/equivalence.toml').read_text())
            self.assertEqual(configured['adapters']['go']['build_min_free_bytes'], 123)
            self.assertEqual(configured['adapters']['go']['build_cache'], {
                'directory': str(root / 'compiler-cache'), 'max_bytes': 1024 ** 3})
            self.assertEqual(plan.call_args.args[-1], set(fixture.FUNCTIONS))
            self.assertEqual(routes.call_count, 1)
            self.assertEqual([call.kwargs['changed'] for call in current.call_args_list], [False, True])
            self.assertEqual([call.args[2] for call in commands.call_args_list], ['promote-plan', 'promote-apply'])
            self.assertEqual(receipt.read(root / 'independent-inputs.json'), oracle.source_facts(root / 'cases/application'))
            self.assertEqual(receipt.read(root / 'current-inputs.json'), oracle.source_facts(root / 'current-source', changed=True))

    def test_incomplete_operation_registry_cannot_pass_a_retained_audit(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            (root / 'cases').mkdir(); (root / 'comparison').mkdir(); (root / 'shrink').mkdir()
            (root / 'cases/plan.stdout').write_text(str(root / 'cases/workspace'))
            qualifier.write(root / 'comparison/report.json', {'cases': [
                {'function': fixture.function(name), 'case': name} for name in fixture.METHODS]})
            qualifier.write(root / 'shrink/shrink.json', {'workspace': str(root / 'shrink/workspace')})
            with self.assertRaises(ValueError):
                qualifier.check_operations(root, Path('cli'), Path('sdk'))


if __name__ == '__main__':
    unittest.main()
