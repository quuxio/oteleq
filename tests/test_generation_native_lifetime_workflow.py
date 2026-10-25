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

    def report(self, difference=False):
        entry = {'language': 'c', 'native_options': {'profile': qualifier.PROFILES['c']},
                 'globals': [{'name': 'state'}, {'name': 'observed_errno'}]}
        result = {'entry': entry, 'case': 'sample', 'arguments': [5]}
        value = {'verdict': 'different_observed' if difference else 'equivalent_observed', 'cases': [result]}
        before = {'global:state': qualifier.scalar('c', 7), 'global:observed_errno': qualifier.scalar('c', 0)}
        bundle = {'contract': {'required_roots': list(before)}, 'baseline': [], 'instrumented_on': []}
        for lane in ('baseline', 'instrumented_on'):
            after = {'global:state': qualifier.scalar('c', 12 + int(difference and lane == 'instrumented_on')),
                     'global:observed_errno': qualifier.scalar('c', errno.ECHILD)}
            observation = {'gaps': [], 'before': {'roots': before, 'nodes': []},
                'after': {'roots': after, 'nodes': []}, 'outcome': {'kind': 'return', 'graph': {
                    'roots': {**after, 'result': qualifier.scalar('c', 42)}, 'nodes': []}}}
            attempt = {'observation': observation, 'execution': {'capture_complete': True,
                'channels': {'stdout': [], 'stderr': []}, 'termination': {'kind': 'exit', 'code': 0}, 'witness': None}}
            bundle[lane] = [copy.deepcopy(attempt), copy.deepcopy(attempt)]
        folder = self.root / ('different' if difference else 'matching'); (folder / 'sample').mkdir(parents=True)
        qualifier.write(folder / 'report.json', value)
        qualifier.write(folder / 'sample/typed-bundle.json', {'cases': [bundle]})
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
                body = next((source / 'src').iterdir()).read_text()
                self.assertIn('observed_errno=errno', body)
                self.assertEqual('getenv(' in body, difference)
        with self.assertRaises(ValueError):
            qualifier.fixture(self.root, 'python', False, self.root / 'sdk')

    def test_known_return_state_and_errno_are_checked_in_every_repeat(self):
        for difference in (False, True):
            path, _ = self.report(difference)
            audit = Mock()
            self.assertEqual(qualifier.check_report(path, difference, audit), 4)
            self.assertEqual(audit.attempt.call_count, 4)

    def test_equal_but_wrong_observations_and_missing_repeats_refuse(self):
        path, original = self.report()
        bundle_path = path.parent / 'sample/typed-bundle.json'
        for change in ('return', 'state', 'errno', 'type', 'before', 'gaps', 'capture', 'repeats'):
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
                if change == 'repeats': value[lane].pop()
            qualifier.write(bundle_path, {'cases': [value]})
            with self.subTest(change=change), self.assertRaises(AssertionError):
                qualifier.check_report(path, False, Mock())

    def test_framework_uses_isolated_retained_entrypoint_and_one_report(self):
        report = self.root / 'report.json'
        with patch.object(qualifier, 'command', return_value=json.dumps({'report': str(report)})) as command, \
                patch.object(qualifier, 'check_report', return_value=4) as check:
            audit = object()
            self.assertEqual(qualifier.framework(self.root / 'workspace', self.root, 'framework', True, audit), 4)
            self.assertEqual(command.call_args.args[0][1:3], ['-I', '-B'])
            self.assertEqual(command.call_args.kwargs['expected'], 1)
            check.assert_called_once_with(report, True, audit)
        with patch.object(qualifier, 'command', return_value='{}\n{}'), self.assertRaises(AssertionError):
            qualifier.framework(self.root, self.root, 'bad', False, Mock())

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
                    'trials': [{'report': str(folder / 'trial/report.json')}]})
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
        self.assertEqual([row[0] for row in calls].count('shrink'), 1)
        self.assertIn('independent complete raw lifetime audit and evidence refusals', result['remaining'])

    def test_original_source_facts_detect_restored_bytes_with_new_write_facts(self):
        path = self.root / 'source.py'; path.write_text('original')
        with patch.object(qualifier.subprocess, 'check_output', return_value=b'source.py\0'):
            before = qualifier.source_facts(self.root)
            path.write_text('original')
            self.assertNotEqual(qualifier.source_facts(self.root), before)

    def audit_fixture(self, lane='baseline'):
        folder = self.root / lane; runtime = folder / 'native-runtime'; runtime.mkdir(parents=True)
        request = {'plain': lane == 'baseline', 'runtime': str(runtime), 'launch_id': 'a' * 32}
        values = {'native-request.json': request,
            'native-application-start.json': {'pid': 23, 'launch_id': request['launch_id']},
            'oteleq-native-finish.json': {'application_pid': 23, 'application_exit_code': 0}}
        for name, value in values.items(): qualifier.write(runtime / name, value)
        qualifier.write(folder / 'http-capture.json', {'errors': [], 'bodies': []})
        for name in ('expected-lifetimes-before-build.json', 'expected-lifetimes.json'):
            qualifier.write(folder / name, {}); (folder / name).chmod(0o600)
        entry = {'language': 'c', 'otelc_runtime_function': 'src/app.c::selected'}
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
            audit.attempt(self.root / 'report.json', folder, entry, lane, witness)
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
            with self.subTest(changes=changes), self.assertRaises(AssertionError):
                audit.attempt(self.root / 'report.json', folder, entry, 'instrumented_on', witness)

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
                patch.object(qualifier.subprocess, 'check_output', return_value=qualifier.SDK_HEAD.encode()), \
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


if __name__ == '__main__':
    main()
