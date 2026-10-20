"""Complete native value oracles reject matching wrong observations."""
import copy
import json
import os
from pathlib import Path
import subprocess
import tempfile
import unittest

import qualify_native_types as qualification
import test_generation_native as native
import typed_capture


class NativeQualificationTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        # Real plain workers exercise the codec. Synthetic witnessed lanes test
        # the independent checker; they are not instrumentation qualification.
        temporary = tempfile.TemporaryDirectory()
        cls.addClassCleanup(temporary.cleanup)
        root, worker = Path(temporary.name), native.NativeScalarTests()
        cls.cases, cls.bundles = [], {}
        for language in ('c', 'cpp'):
            for name, argument in (('selected_macro', 3), ('selected_good', 7),
                                   ('selected_bool', True), ('selected_bool', False)):
                case_id = language + '-' + name + '-' + str(argument)
                folder = root / case_id
                folder.mkdir()
                boolean = '_Bool' if language == 'c' else 'bool'
                parameter = boolean if name == 'selected_bool' else 'int'
                function = name + '(' + parameter + ')' if language == 'cpp' else name
                globals_ = [{'name': 'state', 'type': 'int'}] if name == 'selected_macro' else []
                entry = {**native.entry(language, [parameter], globals_=globals_), 'name': name}
                if globals_:
                    source = 'int state=4;int* address(){__builtin_trap();return &state;}\n'
                    source += 'int selected_macro(int value){state+=value;return state;}\n#define state (*address())\n'
                elif name == 'selected_good':
                    source = 'int selected_good(int value){return value+1;}\n'
                else:
                    source = 'int selected_bool(' + parameter + ' value){return value?1:0;}\n'
                compiled, binary = worker.compile(folder, entry, source, [argument])
                worker.assertEqual(compiled.returncode, 0, compiled.stderr)
                raw_path = folder / 'observation'
                executed = subprocess.run([binary], env={**os.environ, 'OTELEQ_OBSERVATION': str(raw_path)},
                                          capture_output=True, check=False, timeout=10)
                worker.assertEqual(executed.returncode, 0, executed.stderr)
                contract = {'case_id': case_id, 'function_id': function, 'fixture_sha256': 'a' * 64,
                            'required_roots': ['global:state'] if globals_ else []}
                observed = typed_capture.observation(raw_path.read_bytes(), entry, contract)
                captured = {'capture_complete': True, 'termination': {'kind': 'exit', 'code': 0},
                            'channels': {'stdout': list(executed.stdout), 'stderr': list(executed.stderr),
                                         'state-and-outcome': list(raw_path.read_bytes())}}
                attempt = {'observation': observed, 'execution': {'witness': {'functions': {function: 1}}}}
                cls.cases.append({'case': case_id, 'function': function, 'arguments': [argument], 'exit_code': 0})
                cls.bundles[case_id] = {
                    'bundle.json': {'scope': {'language': language}, 'cases': [{
                        'expected_functions': {function: 1}, 'baseline': [captured, captured],
                        'instrumented_on': [captured, captured]}]},
                    'typed-bundle.json': {'cases': [{'contract': contract,
                        'baseline': [attempt, attempt], 'instrumented_on': [attempt, attempt]}]}}

    def setUp(self):
        temporary = tempfile.TemporaryDirectory()
        self.addCleanup(temporary.cleanup)
        self.folder = Path(temporary.name)
        for case in self.cases:
            folder = self.folder / case['case']
            folder.mkdir()
            for name, value in self.bundles[case['case']].items():
                (folder / name).write_text(json.dumps(value))
        self.report = self.folder / 'report.json'
        self.report.write_text(json.dumps({'source_preserved': True, 'cases': self.cases}))

    def test_all_native_inputs_have_complete_independent_value_oracles(self):
        self.assertEqual(qualification.check_report(self.report), 32)
        report = {'source_preserved': True, 'cases': [self.cases[0]] * 8}
        self.report.write_text(json.dumps(report))
        with self.assertRaises(AssertionError):
            qualification.check_report(self.report)

    def test_matching_wrong_state_return_width_output_raw_values_and_witness_are_rejected(self):
        case = self.cases[0]
        folder = self.folder / case['case']
        for change in ('before', 'after', 'result', 'width', 'output', 'raw', 'witness', 'repeat', 'argument'):
            bundles, altered_case = copy.deepcopy(self.bundles[case['case']]), copy.deepcopy(case)
            typed, raw = bundles['typed-bundle.json']['cases'][0], bundles['bundle.json']['cases'][0]
            if change == 'repeat':
                typed['baseline'] = typed['baseline'][:1]
            elif change == 'argument':
                altered_case['arguments'] = [4]
            else:
                for lane in ('baseline', 'instrumented_on'):
                    for captured, attempt in zip(raw[lane], typed[lane]):
                        observed = attempt['observation']
                        if change in ('before', 'after'):
                            observed[change]['roots']['global:state']['value'] = '40'
                        elif change == 'result':
                            observed['outcome']['graph']['roots']['result']['value'] = '70'
                        elif change == 'width':
                            observed['outcome']['graph']['roots']['result']['bits'] = 64
                        elif change == 'output':
                            captured['channels']['stdout'] = [88]
                        elif change == 'raw':
                            captured['channels']['state-and-outcome'] = list(b'abi:{}\nbefore\nreturn:int:07000000\nafter\n')
                        else:
                            attempt['execution']['witness']['functions'] = {}
            for name, value in bundles.items():
                (folder / name).write_text(json.dumps(value))
            with self.subTest(change=change), self.assertRaises(AssertionError):
                qualification.check_case(folder, altered_case)


if __name__ == '__main__':
    unittest.main()
