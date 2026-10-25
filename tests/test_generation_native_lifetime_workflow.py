"""Literal workflow controls, not compiler/SDK/application qualification."""

import copy
import errno
import json
from pathlib import Path
import tempfile
import tomllib
from unittest import TestCase, main
from unittest.mock import Mock, patch

import qualify_native_lifetimes as qualifier


class NativeLifetimeWorkflowTests(TestCase):
    def setUp(self):
        temporary = tempfile.TemporaryDirectory()
        self.addCleanup(temporary.cleanup)
        self.root = Path(temporary.name).resolve()

    def report(self, difference=False, *, amount=5, language='c'):
        function = 'selected(int)' if language == 'cpp' else 'selected'
        entry = {'id': 'sample', 'status': 'ready', 'language': language, 'otelc_function': function,
                 'native_options': {'profile': qualifier.PROFILES[language]},
                 'globals': [{'name': 'state'}, {'name': 'observed_errno'}]}
        result = {'case': 'sample-0', 'arguments': [amount], 'function': function, 'exit_code': int(difference),
                  'comparison': {'verdict': 'different_observed' if difference else 'equivalent_observed'}}
        value = {'claim': 'equivalence over these tests and observations', 'exit_code': int(difference),
                 'source_preserved': True, 'blocked': [], 'inventory': [entry], 'cases': [result]}
        before = {'global:state': qualifier.scalar(language, 7), 'global:observed_errno': qualifier.scalar(language, 0)}
        bundle = {'contract': {'required_roots': list(before)}, 'baseline': [], 'instrumented_on': []}
        for lane in ('baseline', 'instrumented_on'):
            after = {'global:state': qualifier.scalar(language, 7 + amount + int(difference and lane == 'instrumented_on')),
                     'global:observed_errno': qualifier.scalar(language, errno.ECHILD)}
            observation = {'gaps': [], 'before': {'roots': before, 'nodes': []},
                'after': {'roots': after, 'nodes': []}, 'outcome': {'kind': 'return', 'graph': {
                    'roots': {**after, 'result': qualifier.scalar(language, 42)}, 'nodes': []}}}
            attempt = {'observation': observation, 'execution': {'capture_complete': True,
                'channels': {'stdout': [], 'stderr': []}, 'termination': {'kind': 'exit', 'code': 0}, 'witness': None}}
            bundle[lane] = [copy.deepcopy(attempt), copy.deepcopy(attempt)]
        folder = self.root / (('different' if difference else 'matching') +
                              ('-cpp' if language == 'cpp' else '') + '-' + str(amount))
        (folder / 'sample-0').mkdir(parents=True)
        qualifier.write(folder / 'report.json', value)
        qualifier.write(folder / 'sample-0/typed-bundle.json', {'cases': [bundle]})
        return folder / 'report.json', bundle

    def test_completed_cpp_and_c_fixtures_have_explicit_independent_contracts(self):
        for language in ('c', 'cpp'):
            for difference in (False, True):
                folder = self.root / (language + str(difference)); folder.mkdir()
                source, config = qualifier.fixture(folder, language, difference, self.root / 'sdk')
                parsed = tomllib.loads(config.read_text())
                self.assertEqual(parsed['adapters'][language]['profile'], qualifier.PROFILES[language])
                self.assertEqual(parsed['fixtures'][0]['lifetimes'][0]['complete'], True)
                self.assertEqual(parsed['fixtures'][0]['lifetimes'][0].get('exception_exit'), False if language == 'cpp' else None)
                extension = '.cpp' if language == 'cpp' else '.c'
                body = (source / ('src/app' + extension)).read_text()
                self.assertIn('observed_errno=errno', body)
                self.assertEqual('getenv(' in body, difference)
                self.assertIn('keep_item(&item)' if language == 'cpp' else 'keep_item(item)', body)
                self.assertNotIn('struct Item {', body)
                self.assertIn('struct Item {', (source / 'include/item.h').read_text())
                self.assertEqual((source / ('src/keep' + extension)).read_text(),
                                 '#include "item.h"\nvoid keep_item(struct Item *item){(void)item;}\n')
                target, = parsed['adapters'][language]['targets']
                units = ['src/app' + extension, 'src/keep' + extension]
                self.assertEqual(target['units'], [{'source': name} for name in units])
                self.assertEqual(target['link_flags'], ['-pthread'])
                database = json.loads((source / parsed['adapters'][language]['compilation_database']).read_text())
                self.assertEqual([row['file'] for row in database], ['../' + name for name in units])
                for row in database:
                    self.assertEqual(row['directory'], str(source / 'build'))
                    self.assertIn('-O2', row['arguments'])
                    self.assertNotIn('-flto', row['arguments'])
                    self.assertIn('../include', row['arguments'])
        with self.assertRaises(ValueError):
            qualifier.fixture(self.root, 'python', False, self.root / 'sdk')

    def test_known_return_state_and_errno_are_checked_in_every_repeat(self):
        for language in ('c', 'cpp'):
            for difference in (False, True):
                path, _ = self.report(difference, language=language)
                audit = Mock()
                self.assertEqual(qualifier.check_report(path, difference, audit), 4)
                self.assertEqual(audit.attempt.call_count, 4)

    def test_equal_but_wrong_observations_and_missing_repeats_refuse(self):
        path, original = self.report()
        bundle_path = path.parent / 'sample-0/typed-bundle.json'
        for change in ('return', 'state', 'errno', 'type', 'before', 'gaps', 'capture', 'capture-type', 'exit-type', 'repeats'):
            value = copy.deepcopy(original)
            for lane in ('baseline', 'instrumented_on'):
                for attempt in value[lane]:
                    observed = attempt['observation']
                    if change == 'return': observed['outcome']['graph']['roots']['result']['value'] = '43'
                    elif change == 'state': observed['after']['roots']['global:state']['value'] = '99'
                    elif change == 'errno': observed['after']['roots']['global:observed_errno']['value'] = '0'
                    elif change == 'type': observed['after']['roots']['global:state']['bits'] = 64
                    elif change == 'before': observed['before']['roots']['global:state']['value'] = '8'
                    elif change == 'gaps': observed['gaps'] = ['unobserved']
                    elif change == 'capture': attempt['execution']['capture_complete'] = False
                    elif change == 'capture-type': attempt['execution']['capture_complete'] = 1
                    elif change == 'exit-type': attempt['execution']['termination']['code'] = False
                if change == 'repeats': value[lane].pop()
            qualifier.write(bundle_path, {'cases': [value]})
            with self.subTest(change=change), self.assertRaises((AssertionError, ValueError)):
                qualifier.check_report(path, False, Mock())

    def test_framework_uses_isolated_retained_entrypoint_and_one_report(self):
        report = self.root / 'report.json'
        with patch.object(qualifier, 'command', return_value=json.dumps({'report': str(report)})) as command, \
                patch.object(qualifier, 'check_report', return_value=4) as check:
            audit = object()
            self.assertEqual(qualifier.framework(self.root / 'workspace', self.root, 'framework', True, audit), 4)
            self.assertEqual(command.call_args.args[0][1:3], ['-I', '-B'])
            self.assertEqual(command.call_args.kwargs['expected'], 1)
            check.assert_called_once_with(report, True, audit, expected=(5,))
        with patch.object(qualifier, 'command', return_value='{}\n{}'), self.assertRaises(AssertionError):
            qualifier.framework(self.root, self.root, 'bad', False, Mock())

    def test_actual_run_envelope_binds_exit_verdict_inventory_and_case_identity(self):
        path, _ = self.report()
        original = json.loads(path.read_text())
        self.assertNotIn('verdict', original)
        self.assertNotIn('entry', original['cases'][0])
        self.assertEqual(qualifier.check_report(path, False, Mock()), 4)
        for change in ('source', 'blocked', 'claim', 'exit', 'case-exit', 'verdict', 'inventory', 'function', 'case'):
            value = copy.deepcopy(original)
            if change == 'source': value['source_preserved'] = False
            elif change == 'blocked': value['blocked'] = [{'status': 'blocked'}]
            elif change == 'claim': value['claim'] = 'unbounded proof'
            elif change == 'exit': value['exit_code'] = 1
            elif change == 'case-exit': value['cases'][0]['exit_code'] = 1
            elif change == 'verdict': value['cases'][0]['comparison']['verdict'] = 'inconclusive'
            elif change == 'inventory': value['inventory'].append(copy.deepcopy(value['inventory'][0]))
            elif change == 'function': value['cases'][0]['function'] = 'foreign'
            elif change == 'case': value['cases'][0]['case'] = 'foreign-0'
            qualifier.write(path, value)
            with self.subTest(change=change), self.assertRaises(AssertionError):
                qualifier.check_report(path, False, Mock())

    def test_complete_captured_report_and_bundle_use_the_public_run_shape(self):
        """Check unchanged archived observations; mock only original filesystem auditing."""
        fixtures = Path(__file__).with_name('fixtures')
        report = fixtures / 'native-lifetime-workflow-c-report.json'
        bundle = fixtures / 'native-lifetime-workflow-c-typed-bundle.json'
        self.assertEqual(qualifier.digest(report), '5aa4e704ace9dbe7d2934e2255bdb9bb2693b9c2ff87c2f23d0788d0e8fd845e')
        self.assertEqual(qualifier.digest(bundle), 'b1e51d2727f25620a72e19c8ef91832658e31895828d3a0a7df10c1ecc1090a4')
        document = json.loads(report.read_text())
        location = self.root / 'captured/report.json'
        records = {location: document,
                   location.parent / document['cases'][0]['case'] / 'typed-bundle.json': json.loads(bundle.read_text())}
        self.assertNotIn('verdict', document)
        self.assertNotIn('entry', document['cases'][0])
        audit = Mock()
        with patch.object(qualifier.retained, 'read', side_effect=records.__getitem__):
            self.assertEqual(qualifier.check_report(location, False, audit), 4)
        self.assertEqual(audit.attempt.call_count, 4)
        self.assertTrue(all(call.args[-1] == (5,) for call in audit.attempt.call_args_list))

    def test_complete_captured_graphs_refuse_equal_python_values_with_wrong_wire_types(self):
        fixtures = Path(__file__).with_name('fixtures')
        document = json.loads((fixtures / 'native-lifetime-workflow-c-report.json').read_text())
        original = json.loads((fixtures / 'native-lifetime-workflow-c-typed-bundle.json').read_text())
        location = self.root / 'captured/report.json'
        for field, replacement in (('signed', 1), ('bits', 32.0)):
            bundle = copy.deepcopy(original)
            def replace(value):
                if isinstance(value, list): return sum(replace(item) for item in value)
                if not isinstance(value, dict): return 0
                changed = int(field in value)
                if changed: value[field] = replacement
                return changed + sum(replace(item) for item in value.values())
            self.assertEqual(replace(bundle), 28)
            records = {location: document,
                location.parent / document['cases'][0]['case'] / 'typed-bundle.json': bundle}
            with self.subTest(field=field), patch.object(qualifier.retained, 'read', side_effect=records.__getitem__), \
                    self.assertRaises(ValueError):
                qualifier.check_report(location, False, Mock())

    def test_full_route_driver_keeps_replay_detach_and_actual_shrink_report_set(self):
        calls = []
        def command(argv, folder, label, expected=0, **kwargs):
            calls.append((label, list(map(str, argv)), expected))
            if label == 'plan':
                workspace = folder / 'workspace'; workspace.mkdir(); return str(workspace)
            if label == 'run':
                output = folder / 'comparison'; output.mkdir()
                qualifier.write(output / 'report.json', {'cases': [{'case': 'sample'}]})
            if label == 'replay': return json.dumps({'report': str(folder / 'replay/report.json')})
            if label == 'shrink':
                output = folder / 'shrinking'; output.mkdir()
                qualifier.write(output / 'shrink.json', {'original_arguments': [5], 'reduced_arguments': [0],
                    'status': 'candidate_rule_minimal', 'source_preserved': True, 'workspace': str(folder / 'reduced'),
                    'trials': [{'arguments': [2], 'report': str(folder / 'trial/report.json')}]})
            return ''
        fake = Mock(); fake.finish.return_value = {'actual_application_records': 52}
        with patch.object(qualifier, 'command', side_effect=command), \
                patch.object(qualifier, 'Audit', return_value=fake), \
                patch.object(qualifier, 'check_report', return_value=4) as check, \
                patch.object(qualifier, 'framework', return_value=4) as framework, \
                patch.object(qualifier, 'digest', return_value='a' * 64):
            result = qualifier.exercise(self.root / 'cli', self.root / 'provider', self.root / 'sdk', self.root)
        self.assertEqual(result['actual_application_launches'], 52)
        self.assertEqual(len(result['cases']), 3)
        self.assertEqual(framework.call_count, 7)
        self.assertEqual(check.call_count, 9)
        self.assertEqual(check.call_args_list[-2].kwargs, {'expected': (0,)})
        self.assertEqual(check.call_args_list[-1].kwargs, {'expected': (2,)})
        self.assertEqual(framework.call_args.kwargs, {'expected': (0,)})
        self.assertEqual([row[0] for row in calls].count('shrink'), 1)
        self.assertIn('independent complete raw lifetime audit and evidence refusals', result['remaining'])

    def test_original_source_facts_detect_restored_bytes_with_new_write_facts(self):
        path = self.root / 'source.py'; path.write_text('original')
        with patch.object(qualifier.subprocess, 'check_output', return_value=b'source.py\0'):
            before = qualifier.source_facts(self.root)
            path.write_text('original')
            self.assertNotEqual(qualifier.source_facts(self.root), before)

    def audit_fixture(self, lane='baseline', *, suffix=''):
        folder = self.root / (lane + suffix); runtime = folder / 'native-runtime'; runtime.mkdir(parents=True)
        request = {'plain': lane == 'baseline', 'runtime': str(runtime), 'launch_id': 'a' * 32}
        values = {'native-request.json': request,
            'native-application-start.json': {'pid': 23, 'launch_id': request['launch_id']},
            'oteleq-native-finish.json': {'application_pid': 23, 'application_exit_code': 0}}
        for name, value in values.items(): qualifier.write(runtime / name, value)
        qualifier.write(folder / 'http-capture.json', {'errors': [], 'bodies': []})
        for name in ('expected-lifetimes-before-build.json', 'expected-lifetimes.json'):
            qualifier.write(folder / name, {}); (folder / name).chmod(0o600)
        entry = {'language': 'c', 'otelc_runtime_function': 'src/app.c::selected'}
        (folder / 'native-caller').mkdir()
        qualifier.write(folder / 'native-caller/caller.json', {'entry': entry, 'arguments': [5]})
        witness = None
        if lane == 'instrumented_on':
            (runtime / 'app').mkdir()
            health = {'resource_accounting': {'types': '1', 'admitted': '1', 'completed': '1', 'censored': '0'}}
            qualifier.write(runtime / 'app/health.json', health)
            witness = {'functions': {entry['otelc_runtime_function']: 1}, 'spans': 1, 'pending': 0,
                       'losses': {'lifetime_lost': 0}, 'raw_otlp_sha256': 'a' * 64}
            verified = {**witness, 'spans': 2, 'sdk_pid': 23, 'health': health,
                'lifetimes': [{'type_usr': 'c:@S@Item', 'name': 'Item', 'creation_path': [0], 'release_path': [0],
                    'complete': True, 'exception_exit': None, 'instance': '1', 'boundary': 'free_entry', 'duration_ns': 1}]}
            qualifier.write(folder / 'native-verified-lifetimes.json', verified)
        audit = object.__new__(qualifier.Audit)
        audit.registry = Mock(); audit.registry.original.return_value = self.root / 'report.json'
        audit.registry.archived = set(); audit.records = {}; audit.files = {}
        return audit, folder, entry, witness

    def test_launch_records_complete_receipt_and_original_file_facts_remain_bound(self):
        for lane in ('baseline', 'instrumented_on'):
            audit, folder, entry, witness = self.audit_fixture(lane)
            audit.attempt(self.root / 'report.json', folder, entry, lane, witness, (5,))
            result = audit.finish()
            self.assertEqual(result['actual_application_records'], 1)
            self.assertGreater(result['original_evidence_files_held'], 4)
            path = folder / 'expected-lifetimes.json'; path.write_bytes(path.read_bytes())
            with self.assertRaises(AssertionError): audit.finish()

    def test_wrong_lifetime_counts_and_broader_witness_cannot_replace_bound_receipt(self):
        audit, folder, entry, witness = self.audit_fixture('instrumented_on')
        path = folder / 'native-verified-lifetimes.json'; original = json.loads(path.read_text())
        for changes in ({'spans': 1}, {'sdk_pid': 99}, {'lifetimes': []}):
            qualifier.write(path, {**original, **changes})
            with self.subTest(changes=changes), self.assertRaises((AssertionError, ValueError)):
                audit.attempt(self.root / 'report.json', folder, entry, 'instrumented_on', witness, (5,))

    def test_lifetime_and_witness_literals_keep_json_integer_boolean_distinctions(self):
        for index, change in enumerate(('complete', 'path', 'function', 'spans', 'pending', 'loss', 'health')):
            audit, folder, entry, witness = self.audit_fixture('instrumented_on', suffix=str(index))
            path = folder / 'native-verified-lifetimes.json'; value = json.loads(path.read_text())
            if change == 'complete': value['lifetimes'][0]['complete'] = 1
            elif change == 'path': value['lifetimes'][0]['creation_path'] = [False]
            elif change == 'function': value['functions'][entry['otelc_runtime_function']] = True
            elif change == 'spans': witness['spans'] = True
            elif change == 'pending': witness['pending'] = False
            elif change == 'loss': witness['losses']['lifetime_lost'] = False
            elif change == 'health':
                value['health']['closed'] = 1
                qualifier.write(folder / 'native-runtime/app/health.json', {**value['health'], 'closed': True})
            qualifier.write(path, value)
            with self.subTest(change=change), self.assertRaises(ValueError):
                audit.attempt(self.root / 'report.json', folder, entry, 'instrumented_on', witness, (5,))

    def test_main_pins_sdk_source_and_preserves_noncoverage_products(self):
        provider = self.root / 'provider'; provider.mkdir()
        cli = self.root / 'cli'; cli.write_bytes(b'literal consumer; never executed')
        report, sdk = self.root / 'evidence', self.root / 'sdk'
        argv = ['qualifier', '--otelc-root', str(provider), '--cli', str(cli),
                '--report-dir', str(report), '--sdk-build', str(sdk)]
        def build(arguments, *args, **kwargs):
            self.assertNotIn('--coverage', arguments)
            sdk.mkdir(); qualifier.write(sdk / 'native-sdk-build.json', {'coverage': False})
            (sdk / 'libotelc_native_runtime.so').write_bytes(b'literal library; never loaded')
            return ''
        with patch('sys.argv', argv), patch.dict(qualifier.os.environ, {}, clear=False), \
                patch.object(qualifier.subprocess, 'check_output', side_effect=lambda argv, **kwargs:
                             b'' if argv[1] == 'status' else qualifier.SDK_HEAD.encode()), \
                patch.object(qualifier, 'source_facts', return_value={'literal.py': {'original': True}}), \
                patch.object(qualifier, 'command', side_effect=build), \
                patch.object(qualifier, 'exercise', return_value={'status': 'literal component only'}):
            qualifier.main()
        self.assertEqual(json.loads((report / 'qualification.json').read_text()), {'status': 'literal component only'})
        self.assertTrue((report / 'sdk-original-products.json').is_file())

    def test_main_refuses_source_overlaps_before_build_or_new_outputs(self):
        provider = self.root / 'provider'; provider.mkdir()
        cli = self.root / 'cli'; cli.write_bytes(b'not executed')
        alias = self.root / 'PROVIDER'
        if not alias.exists(): alias.symlink_to(provider, target_is_directory=True)
        self.assertTrue(alias.samefile(provider))
        for directory in (provider, alias):
            for kind in ('sdk', 'report'):
                sdk = directory / 'inside' if kind == 'sdk' else self.root / 'sdk'
                report = directory / 'inside' if kind == 'report' else self.root / 'evidence'
                with self.subTest(directory=directory, kind=kind), \
                        patch('sys.argv', ['qualifier', '--otelc-root', str(provider), '--cli', str(cli),
                                          '--sdk-build', str(sdk), '--report-dir', str(report)]), \
                        patch.object(qualifier, 'command') as command, self.assertRaises(AssertionError):
                    qualifier.main()
                command.assert_not_called()
                self.assertFalse((provider / 'inside').exists())

    def test_self_consistent_wrong_fixed_or_reduced_input_refuses(self):
        for amount in (0, 4):
            path, _ = self.report(amount=amount)
            with self.subTest(amount=amount), self.assertRaises(AssertionError):
                qualifier.check_report(path, False, Mock())
        path = self.root / 'matching-0/report.json'
        self.assertEqual(qualifier.check_report(path, False, Mock(), expected=(0,)), 4)
        with self.assertRaises(AssertionError):
            qualifier.check_report(self.root / 'matching-4/report.json', False, Mock(), expected=(0,))
        for value in ([], [False], [True], [0.0], [-1], [6], [1, 2], None):
            with self.subTest(value=value), self.assertRaises(AssertionError): qualifier.arguments(value)

    def test_trial_candidate_and_actual_report_arguments_must_match(self):
        path, _ = self.report(amount=3)
        self.assertEqual(qualifier.check_report(path, False, Mock(), expected=qualifier.arguments([3])), 4)
        with self.assertRaises(AssertionError):
            qualifier.check_report(path, False, Mock(), expected=qualifier.arguments([2]))

    def test_caller_arguments_cannot_disagree_with_the_checked_input(self):
        audit, folder, entry, witness = self.audit_fixture()
        for actual, expected in (([4], (5,)), ([False], (0,)), ([True], (1,)), ([0.0], (0,))):
            qualifier.write(folder / 'native-caller/caller.json', {'entry': entry, 'arguments': actual})
            with self.subTest(actual=actual), self.assertRaises(AssertionError):
                audit.attempt(self.root / 'report.json', folder, entry, 'baseline', witness, expected)
        qualifier.write(folder / 'native-caller/caller.json', {'entry': entry, 'arguments': [0]})
        audit.attempt(self.root / 'report.json', folder, entry, 'baseline', witness, (0,))

    def test_dirty_pinned_sdk_refuses_before_initial_snapshot_or_build(self):
        provider = self.root / 'provider'; provider.mkdir()
        cli = self.root / 'cli'; cli.write_bytes(b'never executed')
        report = self.root / 'evidence'
        def git(argv, **kwargs):
            return b' M source.cpp\n' if argv[1] == 'status' else qualifier.SDK_HEAD.encode()
        with patch('sys.argv', ['qualifier', '--otelc-root', str(provider), '--cli', str(cli),
                                '--sdk-build', str(self.root / 'sdk'), '--report-dir', str(report)]), \
                patch.object(qualifier.subprocess, 'check_output', side_effect=git), \
                patch.object(qualifier, 'command') as command, self.assertRaisesRegex(AssertionError, 'dirty'):
            qualifier.main()
        command.assert_not_called()
        self.assertFalse(report.exists())


if __name__ == '__main__':
    main()
