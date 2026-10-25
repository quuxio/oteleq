"""Literal public-workflow orchestration controls; no SDK or native execution."""

import copy
import json
from pathlib import Path
import sys
import tempfile
import tomllib
from types import SimpleNamespace
import unittest
from unittest.mock import Mock, patch

import native_metric_cases as cases
import native_metric_refusals as refusals
from native_metric_test_capture import Capture
import qualify_native_metrics as driver


class NativeMetricWorkflowTests(unittest.TestCase):
    def setUp(self):
        temporary = tempfile.TemporaryDirectory(); self.addCleanup(temporary.cleanup)
        self.root = Path(temporary.name).resolve(); self.counter = 0

    def test_all_28_generated_configurations_pass_the_actual_public_policy_validator(self):
        sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'adapters/generation'))
        import policy

        count = 0
        for language, modes in cases.MODES.items():
            for mode in modes:
                for start in cases.STARTS:
                    with self.subTest(language=language, mode=mode, start=start):
                        folder = self.root / (language + '-' + mode + '-' + start); folder.mkdir()
                        _, config = cases.fixture(folder, language, mode, start, self.root / 'sdk')
                        fixture, = policy.validate(tomllib.loads(config.read_text()))['fixtures']
                        for index, step in enumerate(fixture['sequence']):
                            expected = ({'kind': 'error', 'category': 'exception', 'type': 'cpp.std::runtime_error'}
                                        if mode == 'error' and index == 1 else {'kind': 'return'})
                            self.assertEqual(step['expected_baseline'], expected)
                        count += 1
        self.assertEqual(count, 28)

    def audit(self, language='c', start='11'):
        audit = SimpleNamespace(language=language, start=start, provider=self.root, records={})
        def attempt(path, folder, entry, lane, witness, amount, function, version, repeat):
            audit.records[str(folder)] = {'plain': lane == 'baseline'}
        audit.attempt = Mock(side_effect=attempt)
        return audit

    def report(self, parent: Path, audit, mode: str, *, function='selected', contracts=driver.BASE_CALLS, amount=5):
        self.counter += 1
        folder = parent / str(self.counter); folder.mkdir(parents=True)
        entries = [{'id': name, 'status': 'ready', 'language': audit.language, 'path': 'app.' + ('cpp' if audit.language == 'cpp' else 'c'),
            'otelc_function': cases.function(audit.language, name), 'parameters': ['int'], 'output': 'int',
            'native_backend': 'prepared', 'native_options': {'profile': 'native-owned-v1', 'sdk_source_profile': 'resource-v1'},
            'globals': [{'name': key, 'type': 'int'} for key in ('calls', 'depth', 'state')],
            'sequence_configuration': cases.configuration(audit.language, mode, audit.start, audit.provider)['fixtures'][0]['sequence']}
            for name, _ in contracts]
        entry = next(row for row in entries if row['id'] == function)
        case = function + '-0'; roots = ['global:' + row['name'] for row in entry['globals']]
        sequence = entry['sequence_configuration']
        contract = {'case_id': case, 'function_id': entry['path'] + '::' + entry['otelc_function'], 'fixture_sha256': 'a' * 64,
            'observation_schema_version': 1, 'required_roots': roots, 'expected_baseline': {'kind': 'return'},
            'steps': [{'id': 'step-' + str(index), 'action': 'call', 'required_roots': roots,
                       'expected_baseline': row['expected_baseline']} for index, row in enumerate(sequence)]}
        total = 4 * (amount + 1 if mode == 'recursive' else 1)
        bundle = {'contract': contract, 'expected_functions': {contract['function_id']: total}, 'expected_spans': total}
        for lane in ('baseline', 'instrumented_on'):
            steps = cases.expected(audit.language, mode, amount, instrumented=lane == 'instrumented_on', version=dict(contracts)[function])
            observed = {'observation_schema_version': 1, 'case_id': case, 'function_id': contract['function_id'],
                'fixture_sha256': contract['fixture_sha256'], 'fixture': {'status': 'ready'}, 'gaps': [],
                'before': steps[0]['before'], 'outcome': steps[-1]['outcome'], 'after': steps[-1]['after'], 'steps': steps}
            attempt = {'observation': observed, 'execution': {'capture_complete': True, 'channels': {'stdout': [], 'stderr': []},
                'termination': {'kind': 'exit', 'code': 0}, 'witness': None}}
            bundle[lane] = [copy.deepcopy(attempt), copy.deepcopy(attempt)]
        (folder / case).mkdir()
        driver.write(folder / case / 'typed-bundle.json', {'cases': [bundle]})
        driver.write(folder / 'report.json', {'source_preserved': True, 'blocked': [], 'claim': 'equivalence over these tests and observations',
            'exit_code': int(mode == 'transient'), 'inventory': entries, 'cases': [{'case': case, 'function': entry['otelc_function'],
                'arguments': [amount], 'exit_code': int(mode == 'transient'),
                'comparison': {'verdict': 'different_observed' if mode == 'transient' else 'equivalent_observed'}}]})
        return folder / 'report.json'

    def test_every_report_profile_and_promoted_function_has_four_exact_observations(self):
        for language, modes in cases.MODES.items():
            for start in cases.STARTS:
                audit = self.audit(language, start)
                for mode in modes:
                    for function, contracts in [('selected', driver.BASE_CALLS), ('selected', driver.PROMOTED_CALLS),
                                                ('selected_extra', driver.PROMOTED_CALLS)]:
                        path = self.report(self.root / 'reports', audit, mode, function=function, contracts=contracts)
                        self.assertEqual(driver.check_report(path, audit, mode=mode, function=function, contracts=contracts), 4)

    def test_equal_wrong_intermediate_graphs_foreign_inputs_inventory_and_repeats_refuse(self):
        for kind in ('graph', 'arguments', 'inventory', 'repeat', 'schema', 'step'):
            audit = self.audit('cpp')
            path = self.report(self.root / 'reports', audit, 'normal')
            report = driver.retained.read(path)
            bundle_path = path.parent / report['cases'][0]['case'] / 'typed-bundle.json'
            bundle = driver.retained.read(bundle_path)
            if kind == 'arguments': report['cases'][0]['arguments'] = [True]
            elif kind == 'inventory': report['inventory'][0]['otelc_function'] = 'foreign'
            elif kind == 'repeat': bundle['cases'][0]['baseline'].pop()
            else:
                for lane in ('baseline', 'instrumented_on'):
                    observed = bundle['cases'][0][lane][0]['observation']
                    if kind == 'graph': observed['steps'][1]['after']['roots']['global:state']['value'] = '999'
                    elif kind == 'schema': observed['observation_schema_version'] = True
                    else: observed['steps'].pop()
            driver.write(path, report); driver.write(bundle_path, bundle)
            with self.subTest(kind=kind), self.assertRaises((ValueError, AssertionError)):
                driver.check_report(path, audit, mode='normal')
        for value in ([], [True], [6], [1, 2]):
            with self.assertRaises(AssertionError): driver.argument(value)

    def test_owned_audit_reuses_original_requests_and_retains_every_file_fact(self):
        root = self.root / 'normal'; root.mkdir()
        value = Capture(root / 'case', lane_name='instrumented_on-0')
        audit = driver.Audit(self.root, value.provider, 'c', '11')
        report = root / 'report.json'
        driver.write(report, {'literal': True})
        with patch.object(audit.registry, 'original', return_value=report):
            for _ in range(2):
                audit.attempt(report, value.folder, value.entry, 'instrumented_on', value.witness, 5, 'selected', 42, 0)
        self.assertEqual(len(audit.records), 1); self.assertGreater(len(audit.files), 50)
        self.assertEqual(next(iter(audit.contexts.values()))['repeat'], 0)
        with self.assertRaises(AssertionError): audit.finish()
        with self.assertRaises(AssertionError): audit.mode(self.root / 'foreign')
        path = value.folder / 'observation'; path.write_bytes(path.read_bytes() + b' ')
        with self.assertRaises(ValueError): audit.finish()

    def test_literal_captures_require_all_fourteen_refusals_without_native_processes(self):
        selected = {}
        for mode in cases.MODES['c']:
            root = self.root / mode; root.mkdir()
            value = Capture(root, mode=mode, start='01', lane_name='instrumented_on-0')
            audit = self.audit(start='01')
            report = self.report(self.root / 'reports', audit, mode)
            case = driver.retained.read(report)['cases'][0]['case']
            bundle = driver.retained.read(report.parent / case / 'typed-bundle.json')
            driver.write(value.folder.parent / 'typed-bundle.json', bundle)
            selected[mode] = {'folder': str(value.folder), 'entry': value.entry, 'mode': mode,
                'start': '01', 'amount': 5, 'version': 42, 'repeat': 0}
        audit = SimpleNamespace(language='c', contexts=selected)
        result = refusals.refusals(audit, self.root / 'refusals')
        self.assertEqual(set(result), set(cases.MODES['c']))
        self.assertTrue(all(row['count'] == 14 and row['new_application_launches'] == 0 for row in result.values()))

    def test_framework_replay_and_current_source_promotion_use_separate_fresh_reports(self):
        audit = self.audit('cpp', '10')
        path = self.report(self.root / 'reports', audit, 'normal')
        with patch.object(driver, 'command', return_value=json.dumps({'report': str(path)})):
            driver.framework(self.root, self.root, 'framework', audit, 'normal')
            driver.replay(self.root / 'cli', self.root, 'selected-0', self.root, 'replay', audit, 'normal')
        source, _ = cases.fixture(self.root, 'cpp', 'recursive', '10', self.root)
        audit.records.clear()
        def command(argv, folder, label, **options):
            if label == 'promote-plan': return json.dumps({'mode': 'dry-run', 'files': ['test_equivalence.py']})
            if label == 'promote-apply': Path(argv[argv.index('--destination') + 1]).mkdir(); return ''
            application = Path(options['environment']['OTELEQ_SOURCE'])
            contracts = driver.BASE_CALLS if label == 'current-original' else driver.PROMOTED_CALLS
            parent = Path(options['environment']['OTELEQ_WORKSPACE_PARENT'])
            rows = [{'project_source': str(application)}]
            for function, version in contracts:
                self.assertIn(':' + str(version) + ';', (application / 'app.cpp').read_text())
                rows.append({'report': str(self.report(parent, audit, 'recursive', function=function, contracts=contracts))})
            return '\n'.join(json.dumps(row) for row in rows)
        with patch.object(driver, 'command', side_effect=command):
            result = driver.promotion(self.root / 'cli', self.root, source, self.root / 'promotion', audit, 'recursive')
        self.assertEqual(len(result['reports']), 3); self.assertEqual(len(audit.records), 12)
        self.assertTrue(result['relocated_compilation_database'])
        unchanged = self.root / 'plain'; unchanged.mkdir()
        self.assertFalse(driver.relocate(source, unchanged))

    def test_scalar_reduction_requires_original_trial_confirmation_framework_and_replay(self):
        audit = self.audit(); folder = self.root / 'transient'; folder.mkdir()
        def add(count):
            for _ in range(count): audit.records[str(len(audit.records))] = {}
        def command(argv, folder, label, **options):
            root = folder / 'shrinking'; root.mkdir()
            driver.write(root / 'shrink.json', {'original_arguments': [5], 'reduced_arguments': [0],
                'status': 'candidate_rule_minimal', 'source_preserved': True, 'incomplete_trials': 0,
                'trials': [{'arguments': [0], 'report': str(root / 'trial/report.json')}], 'workspace': str(root / 'workspace')})
            return ''
        with patch.object(driver, 'command', side_effect=command), patch.object(driver, 'check_report', side_effect=lambda *a, **k: add(4)), \
                patch.object(driver, 'framework', side_effect=lambda *a, **k: add(4)), \
                patch.object(driver, 'replay', side_effect=lambda *a, **k: add(4)):
            driver.reduction(self.root / 'cli', self.root, 'selected-0', folder, audit)
        self.assertEqual(len(audit.records), 20)

    def test_every_workload_runs_generated_replay_detached_and_promotion_routes(self):
        for language in cases.MODES:
            root = self.root / language; root.mkdir()
            provider = self.root / ('provider-' + language); provider.mkdir()
            cli = self.root / ('cli-' + language); cli.write_bytes(b'literal CLI; never executed')
            audit = SimpleNamespace(root=root, provider=provider, language=language, start='00',
                                    records={}, files={}, contexts={}, reports=set(), registry=SimpleNamespace(archived=set()))
            def add(count):
                for _ in range(count):
                    audit.records[str(len(audit.records))] = {'plain': len(audit.records) % 4 < 2}
            finish = driver.Audit.finish
            audit.finish = lambda: finish(audit)
            def command(argv, folder, label, **options):
                if label == 'plan':
                    workspace = folder / 'workspace'; workspace.mkdir(); return str(workspace)
                if label == 'run':
                    output = Path(argv[argv.index('--report-dir') + 1]); output.mkdir()
                    driver.write(output / 'report.json', {'cases': [{'case': 'held-case'}]})
                if label == 'export': Path(argv[argv.index('--destination') + 1]).mkdir()
                return ''
            def framework(workspace, folder, label, *args, **options):
                if label == 'detached-framework': self.assertFalse((folder / 'application').exists())
                add(4)
            with patch.object(driver, 'Audit', return_value=audit), patch.object(driver, 'command', side_effect=command), \
                    patch.object(driver, 'check_report', side_effect=lambda *a, **k: add(4)), \
                    patch.object(driver, 'framework', side_effect=framework), patch.object(driver, 'replay', side_effect=lambda *a, **k: add(4)), \
                    patch.object(driver, 'promotion', side_effect=lambda *a, **k: (add(12) or {'scope': 'literal only'})), \
                    patch.object(driver, 'reduction', side_effect=lambda *a, **k: add(20)), \
                    patch.object(refusals, 'refusals', return_value={'scope': 'literal only'}):
                result = driver.exercise(cli, provider, self.root / 'sdk', root, language, '00')
            self.assertEqual(len(result['workloads']), len(cases.MODES[language]))
            self.assertEqual(len(audit.records), 28 * len(cases.MODES[language]) + 20)

    def test_main_requires_new_external_outputs_and_preserves_original_products(self):
        provider = self.root / 'provider'; provider.mkdir()
        cli = self.root / 'cli'; cli.write_bytes(b'literal executable; never run')
        output, sdk = self.root / 'evidence', self.root / 'sdk'
        argv = ['qualifier', '--otelc-root', str(provider), '--cli', str(cli), '--sdk-build', str(sdk),
                '--report-dir', str(output), '--language', 'c', '--start', '11']
        def build(arguments, *args, **kwargs):
            self.assertNotIn('--coverage', arguments); sdk.mkdir()
            driver.write(sdk / 'native-sdk-build.json', {'coverage': False})
            for name in ('libotelc_native_runtime.so', 'libotelc_native_runtime.dylib'):
                (sdk / name).write_bytes(b'literal library; never loaded')
            return ''
        def git(arguments, **options):
            if arguments[1] == 'status': return b''
            return (cases.SDK_HEAD if options['cwd'] == provider else 'c' * 40).encode()
        with patch('sys.argv', argv), patch.object(driver.subprocess, 'check_output', side_effect=git), \
                patch.object(driver, 'source_facts', return_value={'known': 'literal fixture'}), \
                patch.object(driver, 'command', side_effect=build), patch.object(driver, 'exercise', return_value={'scope': 'literal only'}), \
                patch.dict(driver.os.environ, {}, clear=False):
            driver.main()
        self.assertEqual(driver.retained.read(output / 'qualification.json')['consumer_source'], 'c' * 40)
        self.assertTrue((output / 'sdk-original-products.json').is_file())
        products = driver.retained.read(output / 'sdk-original-products.json')
        library = 'libotelc_native_runtime.dylib' if driver.sys.platform == 'darwin' else 'libotelc_native_runtime.so'
        self.assertEqual({Path(name).name for name in products}, {'native-sdk-build.json', library})
        for child in ('sdk', 'evidence'):
            arguments = argv.copy()
            arguments[arguments.index('--sdk-build' if child == 'sdk' else '--report-dir') + 1] = str(provider / 'inside')
            other = self.root / ('new-' + child)
            arguments[arguments.index('--report-dir' if child == 'sdk' else '--sdk-build') + 1] = str(other)
            with patch('sys.argv', arguments), self.assertRaises(AssertionError): driver.main()


if __name__ == '__main__':
    unittest.main()
