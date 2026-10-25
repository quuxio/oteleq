"""Literal promotion/oracle controls; no SDK, compiler or application runs."""

import copy
import errno
import json
from pathlib import Path
import tempfile
import unittest
from unittest.mock import Mock, patch

import qualify_native_lifetimes as qualifier


class NativeLifetimePromotionTests(unittest.TestCase):
    def setUp(self):
        temporary = tempfile.TemporaryDirectory()
        self.addCleanup(temporary.cleanup)
        self.root = Path(temporary.name).resolve()

    def report(self, folder: Path, language: str, function: str, contracts: tuple,
               *, difference: bool = False, amount: int = 5) -> Path:
        """Create explicit literal observations for one declared promoted call."""
        folder.mkdir(parents=True)
        named = lambda name: name + ('(int)' if language == 'cpp' else '')
        entries = [{'id': name, 'status': 'ready', 'language': language, 'otelc_function': named(name),
                    'native_options': {'profile': qualifier.PROFILES[language]},
                    'globals': [{'name': 'state'}, {'name': 'observed_errno'}]} for name, _ in contracts]
        case = function + '-0'
        document = {'source_preserved': True, 'blocked': [], 'claim': 'equivalence over these tests and observations',
                    'exit_code': int(difference), 'inventory': entries,
                    'cases': [{'case': case, 'function': named(function), 'arguments': [amount], 'exit_code': int(difference),
                               'comparison': {'verdict': 'different_observed' if difference else 'equivalent_observed'}}]}
        before = {'global:state': qualifier.scalar(language, 7), 'global:observed_errno': qualifier.scalar(language, 0)}
        bundle = {'contract': {'required_roots': list(before)}}
        for lane in ('baseline', 'instrumented_on'):
            after = {'global:state': qualifier.scalar(language, 7 + amount + int(difference and lane == 'instrumented_on')),
                     'global:observed_errno': qualifier.scalar(language, errno.ECHILD)}
            observation = {'gaps': [], 'before': {'roots': before, 'nodes': []}, 'after': {'roots': after, 'nodes': []},
                           'outcome': {'kind': 'return', 'graph': {'roots': {
                               **after, 'result': qualifier.scalar(language, dict(contracts)[function])}, 'nodes': []}}}
            attempt = {'observation': observation, 'execution': {'capture_complete': True,
                       'channels': {'stdout': [], 'stderr': []}, 'termination': {'kind': 'exit', 'code': 0}, 'witness': None}}
            bundle[lane] = [copy.deepcopy(attempt), copy.deepcopy(attempt)]
        (folder / case).mkdir()
        qualifier.write(folder / case / 'typed-bundle.json', {'cases': [bundle]})
        qualifier.write(folder / 'report.json', document)
        return folder / 'report.json'

    def test_promoted_reports_bind_both_inventory_functions_and_each_declared_return(self):
        for language in ('c', 'cpp'):
            for function, _ in qualifier.PROMOTED_CALLS:
                path = self.report(self.root / language / function, language, function, qualifier.PROMOTED_CALLS)
                audit = Mock()
                self.assertEqual(qualifier.check_report(path, False, audit, function=function,
                                                       contracts=qualifier.PROMOTED_CALLS), 4)
                self.assertEqual(audit.attempt.call_count, 4)
                self.assertTrue(all(call.kwargs == {'function': function, 'mode': 'completed'}
                                    for call in audit.attempt.call_args_list))
                with self.assertRaises(AssertionError): qualifier.check_report(path, False, Mock())

    def test_missing_extra_duplicate_id_and_foreign_inventory_function_refuse(self):
        path = self.report(self.root / 'report', 'c', 'selected', qualifier.PROMOTED_CALLS)
        original = qualifier.retained.read(path)
        for change in ('missing', 'duplicate-id', 'foreign', 'wrong-case', 'wrong-language'):
            value = copy.deepcopy(original)
            if change == 'missing': value['inventory'].pop()
            elif change == 'duplicate-id': value['inventory'][1]['id'] = value['inventory'][0]['id']
            elif change == 'foreign': value['inventory'][1]['otelc_function'] = 'selected_foreign'
            elif change == 'wrong-case': value['cases'][0]['case'] = 'selected_extra-0'
            else: value['inventory'][1]['language'] = 'cpp'
            qualifier.write(path, value)
            with self.subTest(change=change), self.assertRaises(AssertionError):
                qualifier.check_report(path, False, Mock(), contracts=qualifier.PROMOTED_CALLS)

    def test_stale_and_cross_function_returns_refuse_even_when_both_lanes_agree(self):
        for function, wrong in (('selected', 42), ('selected_extra', 43)):
            path = self.report(self.root / function, 'c', function, qualifier.PROMOTED_CALLS)
            bundle_path = path.parent / (function + '-0') / 'typed-bundle.json'
            value = qualifier.retained.read(bundle_path)
            for lane in ('baseline', 'instrumented_on'):
                for attempt in value['cases'][0][lane]:
                    attempt['observation']['outcome']['graph']['roots']['result']['value'] = str(wrong)
            qualifier.write(bundle_path, value)
            with self.subTest(function=function), self.assertRaises(ValueError):
                qualifier.check_report(path, False, Mock(), function=function, contracts=qualifier.PROMOTED_CALLS)

    def run_promotion(self, language: str, *, fault: str = '', mode: str = 'completed'):
        case = self.root / (language + '-' + mode + '-' + (fault or 'valid')); case.mkdir()
        source, _ = qualifier.fixture(case, language, True, self.root / 'sdk', mode=mode)
        original = qualifier.fixture_facts(source)
        folder = case / 'promotion'
        stages = []
        def command(argv, destination, label, **options):
            stages.append(label)
            bundle = folder / 'project-tests'
            if label == 'promote-plan':
                if fault == 'dry-run-write': bundle.mkdir(parents=True)
                return json.dumps({'mode': 'dry-run', 'files': ['test_equivalence.py']})
            if label == 'promote-apply':
                bundle.mkdir(); (bundle / 'test_equivalence.py').write_text('# literal; never executed\n')
                return ''
            self.assertEqual(options['expected'], 1)
            self.assertEqual(argv[1:3], ['-I', '-B'])
            application = Path(options['environment']['OTELEQ_SOURCE'])
            parent = Path(options['environment']['OTELEQ_WORKSPACE_PARENT'])
            contracts = qualifier.BASE_CALLS if label == 'current-original' else qualifier.PROMOTED_CALLS
            if label == 'current-changed':
                extension = '.cpp' if language == 'cpp' else '.c'
                body = (application / ('src/app' + extension)).read_text()
                self.assertEqual(body.count('int selected(int amount)'), 1)
                self.assertEqual(body.count('int selected_extra(int amount)'), 1)
                self.assertIn('return 43;', body); self.assertIn('return 44;', body)
                self.assertEqual(body.count('keep_item('), 2)
                database = qualifier.retained.read(application / 'build/compile_commands.json')
                self.assertEqual(len(database), 2)
                self.assertTrue(all(row['directory'] == str(application / 'build') for row in database))
            rows = [{'project_source': str(application)}]
            for function, _ in contracts:
                path = self.report(parent / label / function, language, function, contracts, difference=True,
                                   amount=0 if mode == 'zero' else 5)
                rows.append({'report': str(path)})
            if fault == 'mutated-source':
                path = application / 'include/item.h'; path.write_bytes(path.read_bytes())
            elif fault == 'wrong-source': rows[0]['project_source'] = str(self.root)
            elif fault == 'foreign-report': rows[1]['report'] = str(self.root / 'report.json')
            elif fault == 'missing-report': rows.pop()
            elif fault == 'duplicate-report' and label == 'current-changed': rows[-1] = rows[1]
            elif fault == 'wrong-database' and label == 'current-original':
                path = source / 'build/compile_commands.json'; value = qualifier.retained.read(path)
                value[0]['directory'] = str(self.root); qualifier.write(path, value)
            return '\n'.join(json.dumps(row) for row in rows)
        audit = Mock()
        audit.records = {'previous-application': {}}
        if fault != 'reused-launches':
            audit.attempt.side_effect = lambda report, folder, *args, **kwargs: audit.records.setdefault(str(folder), {})
        with patch.object(qualifier, 'command', side_effect=command):
            result = qualifier.promotion(self.root / 'cli', case / 'workspace', source, folder, language, True, audit, mode=mode)
        self.assertEqual(qualifier.fixture_facts(source), original)
        self.assertEqual(stages, ['promote-plan', 'promote-apply', 'current-original', 'current-changed'])
        self.assertEqual(audit.attempt.call_count, 12)
        self.assertTrue(all(call.kwargs['mode'] == mode for call in audit.attempt.call_args_list))
        self.assertEqual(result['application_observations'], 12)
        self.assertEqual(result['changed_calls'], {'selected': 43, 'selected_extra': 44})
        self.assertEqual(len(result['reports']), 3)
        return result

    def test_current_and_changed_relocated_sources_cover_both_languages(self):
        for language in ('c', 'cpp'):
            with self.subTest(language=language): self.run_promotion(language)

    def test_promoted_zero_censor_and_unwind_cases_keep_their_declared_inputs(self):
        for language, mode in (('c', 'zero'), ('cpp', 'zero'), ('c', 'censored'), ('cpp', 'censored'),
                               ('cpp', 'unwind'), ('cpp', 'throwing-destructor')):
            with self.subTest(language=language, mode=mode): self.run_promotion(language, mode=mode)

    def test_incomplete_foreign_or_mutated_promotion_cannot_pass(self):
        for fault in ('dry-run-write', 'wrong-source', 'foreign-report', 'missing-report',
                      'duplicate-report', 'mutated-source', 'wrong-database', 'reused-launches'):
            with self.subTest(fault=fault), self.assertRaises((AssertionError, ValueError)):
                self.run_promotion('c', fault=fault)


if __name__ == '__main__':
    unittest.main()
