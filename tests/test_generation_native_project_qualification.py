"""The native project oracle rejects equal-but-wrong values and missing witnesses."""
import copy
import json
from pathlib import Path
import tempfile
import unittest

import qualify_native_project as qualification


class NativeProjectQualificationTests(unittest.TestCase):
    def fixture(self, root: Path, *, difference: bool = False) -> tuple[Path, Path]:
        entry = {'status': 'ready', 'language': 'c', 'unit': 'one', 'globals': [
            {'name': 'total', 'unit': 'two'}, {'name': 'unit:one:local', 'unit': 'one'},
            {'name': 'unit:two:local', 'unit': 'two'}]}
        report = {'source_preserved': True, 'blocked': [], 'inventory': [entry], 'cases': [
            {'case': 'fixture', 'function': 'selected', 'arguments': [5], 'exit_code': int(difference)}]}
        case = root / 'fixture'
        case.mkdir()
        bundle = {'cases': [{'contract': {'required_roots': ['global:' + item['name'] for item in entry['globals']]},
                             'baseline': [], 'instrumented_on': []}]}
        initial = {'global:' + item['name']: qualification.scalar('c', value)
                   for item, value in zip(entry['globals'], (7, 3, 4))}
        for lane in ('baseline', 'instrumented_on'):
            active = difference and lane == 'instrumented_on'
            after = {'global:' + item['name']: qualification.scalar('c', value + int(active and item['name'] == 'total'))
                     for item, value in zip(entry['globals'], (12, 8, 9))}
            observed = {'gaps': [], 'before': {'roots': initial, 'nodes': []}, 'after': {'roots': after, 'nodes': []},
                        'outcome': {'kind': 'return', 'graph': {'roots': {**after, 'result': qualification.scalar('c', 24)}, 'nodes': []}}}
            execution = {'channels': {'stdout': [], 'stderr': []}, 'capture_complete': True,
                         'termination': {'kind': 'exit', 'code': 0}, 'witness': None}
            if lane == 'instrumented_on':
                execution['witness'] = {'functions': {'selected': 1}, 'spans': 1, 'pending': 0, 'losses': {'queue': 0}}
            for index in range(2):
                bundle['cases'][0][lane].append(copy.deepcopy({'execution': execution, 'observation': observed}))
                folder = case / (lane + '-' + str(index))
                folder.mkdir()
                rows = [b'abi:' + json.dumps({'bits': {'int': 32}, 'char_bits': 8, 'byte_order': 'little'}).encode(), b'before']
                for graph in (initial, after):
                    for item in entry['globals']:
                        value = int(graph['global:' + item['name']]['value'])
                        rows.append((item['name'] + ':int:' + value.to_bytes(4, 'little', signed=True).hex()).encode())
                    if graph is initial:
                        rows.extend([b'return:int:18000000', b'after'])
                (folder / 'observation').write_bytes(b'\n'.join(rows) + b'\n')
        path = root / 'report.json'
        path.write_text(json.dumps(report))
        bundle_path = case / 'typed-bundle.json'
        bundle_path.write_text(json.dumps(bundle))
        return path, bundle_path

    def test_complete_equal_and_deliberate_state_difference_have_four_actual_repeats(self):
        for difference in (False, True):
            with self.subTest(difference=difference), tempfile.TemporaryDirectory() as temporary:
                report, _ = self.fixture(Path(temporary), difference=difference)
                self.assertEqual(qualification.check_report(report, difference=difference)[0], 4)

    def test_mutated_results_state_types_and_health_never_become_a_match(self):
        with tempfile.TemporaryDirectory() as temporary:
            report, path = self.fixture(Path(temporary))
            original = json.loads(path.read_text())
            for mutation in ('result', 'state', 'type', 'witness', 'pending', 'loss'):
                data = copy.deepcopy(original)
                for lane in ('baseline', 'instrumented_on'):
                    for attempt in data['cases'][0][lane]:
                        graph = attempt['observation']['outcome']['graph']
                        if mutation == 'result':
                            graph['roots']['result']['value'] = '25'
                        elif mutation == 'state':
                            attempt['observation']['after']['roots']['global:unit:two:local']['value'] = '10'
                        elif mutation == 'type':
                            graph['roots']['result']['bits'] = 64
                        elif lane == 'instrumented_on':
                            witness = attempt['execution']['witness']
                            if mutation == 'witness':
                                witness['functions'] = {}
                            elif mutation == 'pending':
                                witness['pending'] = 1
                            elif mutation == 'loss':
                                witness['losses']['queue'] = 1
                path.write_text(json.dumps(data))
                with self.subTest(mutation=mutation), self.assertRaises(AssertionError):
                    qualification.check_report(report)
            path.write_text(json.dumps(original))
            raw = report.parent / 'fixture/baseline-0/observation'
            raw.write_bytes(raw.read_bytes().replace(b'return:int:18000000', b'return:int:19000000'))
            with self.assertRaises(AssertionError):
                qualification.check_report(report)

    def test_observer_and_report_cannot_substitute_another_function_identity(self):
        with tempfile.TemporaryDirectory() as temporary:
            report, bundle = self.fixture(Path(temporary))
            data = json.loads(report.read_text())
            data['cases'][0]['function'] = 'substituted'
            report.write_text(json.dumps(data))
            observed = json.loads(bundle.read_text())
            for attempt in observed['cases'][0]['instrumented_on']:
                attempt['execution']['witness']['functions'] = {'substituted': 1}
            bundle.write_text(json.dumps(observed))
            with self.assertRaises(AssertionError):
                qualification.check_report(report)


if __name__ == '__main__':
    unittest.main()
