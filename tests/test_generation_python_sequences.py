"""Independent Python calls retain one receiver and every declared boundary."""

import argparse
import copy
import json
import os
from pathlib import Path
import subprocess
import sys
import tempfile
import tomllib
from types import ModuleType
import unittest

ROOT = Path(__file__).resolve().parents[1]
sys.path[:0] = [str(ROOT / 'adapters/generation'), str(ROOT / 'examples')]
import discovery
import generation
import harness
import observe
import policy
import sequences
import typed_capture

SOURCE = '''constructed=0
class Counter:
 total=0
 def __init__(self,start:int):
  global constructed
  constructed+=1
  self.value=start
  self.alias=self
  self.calls=0
 def step(self,amount:int):
  self.calls+=1
  self.value+=amount
  Counter.total+=amount
  return self
 def fail(self,amount:int)->int:
  self.calls+=1
  self.value+=amount
  if amount==3:raise ValueError("third")
  return self.value
def make(start:int)->Counter:
 return Counter(start)
'''
CALLS = [{'action': 'call', 'arguments': 'case'},
         *[{'action': 'call', 'arguments': [value]} for value in (2, 3, 4)]]


class PythonSequenceTests(unittest.TestCase):
    def candidate(self, folder, source=SOURCE, method='step', steps=None, factory='make'):
        (folder / 'app.py').write_text(source)
        discovered = discovery.python_inventory(source)
        discovered['entrypoints'] = []
        identity = 'app.Counter.' + method
        declared = {'function': identity, 'cases': [[7]],
                    'receiver': {'factory': factory, 'arguments': [10]},
                    'sequence': copy.deepcopy(CALLS if steps is None else steps)}
        configuration = policy.validate({'languages': ['python'],
                                          'functions': {'include': [identity]},
                                          'fixtures': [declared]})
        function = next(item for item in discovered['functions']
                        if item['name'] == 'Counter.' + method)
        return generation.inventory_entry(
            function, discovered, 'app.py', 'python', 'a' * 64, folder,
            argparse.Namespace(configuration=configuration, cases=1))

    def worker(self, folder, difference=False, **options):
        entry = self.candidate(folder, **options)
        self.assertEqual(entry['status'], 'ready', entry['reason'])
        driver = harness.materialise(folder, entry, [7])
        output = folder / 'observation.json'
        environment = {**os.environ, 'OTELEQ_OBSERVATION': str(output)}
        environment.pop('OTELEQ_TEST_DIFFERENCE', None)
        if difference:
            environment['OTELEQ_TEST_DIFFERENCE'] = '1'
        result = subprocess.run(
            [sys.executable, '-B', driver], cwd=folder,
            env=environment,
            capture_output=True, timeout=30, check=False)
        raw = json.loads(output.read_text()) if output.exists() else None
        return result, raw, entry

    def typed(self, raw, entry):
        return typed_capture.observation(json.dumps(raw).encode(), entry,
            {'case_id': 'case', 'function_id': entry['otelc_function'],
             'fixture_sha256': 'b' * 64})

    def value(self, graph, name):
        receiver = graph['roots']['receiver']['node_id']
        node = next(item for item in graph['nodes'] if item['id'] == receiver)
        return node['fields']['property:' + name]

    def test_calls_construct_once_and_keep_intermediate_aliases_statics_and_inputs(self):
        for factory in ('make', 'Counter'):
            with self.subTest(factory=factory), tempfile.TemporaryDirectory() as temporary:
                result, raw, entry = self.worker(Path(temporary), factory=factory)
                self.assertEqual(result.returncode, 0, result.stderr)
                self.assertEqual((result.stdout, result.stderr), (b'', b''))
                typed = self.typed(raw, entry)
                self.assertEqual(len(typed['steps']), 4)
                for index, (step, total) in enumerate(zip(typed['steps'], (17, 19, 22, 26))):
                    self.assertEqual((step['id'], step['action'], step['gaps']),
                                     ('step-' + str(index), 'call', []))
                    graph = step['outcome']['graph']
                    self.assertEqual(graph['roots']['result'], graph['roots']['receiver'])
                    self.assertEqual(self.value(graph, 'alias'), graph['roots']['receiver'])
                    self.assertEqual(self.value(graph, 'value')['value'], str(total))
                    self.assertEqual(self.value(graph, 'calls')['value'], str(index + 1))
                    self.assertEqual(graph['roots']['global:constructed']['value'], '1')
                    self.assertEqual(graph['roots']['static:Counter.total']['value'], str(total - 10))
                self.assertEqual(raw['before'], raw['steps'][0]['before'])
                self.assertEqual(raw['outcome'], raw['steps'][-1]['outcome'])
                self.assertEqual(raw['after'], raw['steps'][-1]['after'])
                case = generation.generation_case(entry, 0, [7])
                self.assertEqual([step['arguments'] for step in case['sequence']],
                                 [[7], [2], [3], [4]])

    def test_expected_error_keeps_its_state_and_later_calls_still_execute(self):
        calls = copy.deepcopy(CALLS)
        calls[2]['expected_baseline'] = {
            'kind': 'error', 'category': 'exception', 'type': 'python.builtins.ValueError'}
        with tempfile.TemporaryDirectory() as temporary:
            result, raw, entry = self.worker(Path(temporary), method='fail', steps=calls)
            self.assertEqual(result.returncode, 0, result.stderr)
            typed = self.typed(raw, entry)
            self.assertEqual([step['outcome']['kind'] for step in typed['steps']],
                             ['return', 'return', 'error', 'return'])
            self.assertEqual(typed['steps'][2]['outcome']['category'], 'exception')
            self.assertEqual(self.value(typed['steps'][2]['after'], 'value')['value'], '22')
            self.assertEqual(self.value(typed['after'], 'value')['value'], '26')
            self.assertEqual(self.value(typed['after'], 'calls')['value'], '4')

    def test_one_and_thirty_two_calls_keep_the_requested_denominator(self):
        for count in (1, 32):
            steps = [CALLS[0], *[{'action': 'call', 'arguments': [0]}
                                for _ in range(count - 1)]]
            with self.subTest(count=count), tempfile.TemporaryDirectory() as temporary:
                result, raw, entry = self.worker(Path(temporary), steps=steps)
                self.assertEqual(result.returncode, 0, result.stderr)
                typed = self.typed(raw, entry)
                self.assertEqual(len(typed['steps']), count)
                self.assertEqual(self.value(typed['after'], 'calls')['value'], str(count))

    def test_restored_difference_remains_visible_with_equal_outer_observations(self):
        source = 'import os\n' + SOURCE.replace('  return self\n', '''  if os.environ.get("OTELEQ_TEST_DIFFERENCE"):
   if self.calls==1:self.value+=1
   if self.calls==2:self.value-=1
  return 42
''')
        results = []
        for difference in (False, True):
            with tempfile.TemporaryDirectory() as temporary:
                result, raw, entry = self.worker(Path(temporary), source=source,
                                                 steps=CALLS[:2], difference=difference)
                self.assertEqual(result.returncode, 0, result.stderr)
                results.append(self.typed(raw, entry))
        baseline, changed = results
        for boundary in ('before', 'outcome', 'after'):
            self.assertEqual(baseline[boundary], changed[boundary])
        self.assertEqual(self.value(baseline['steps'][0]['after'], 'value')['value'], '17')
        self.assertEqual(self.value(changed['steps'][0]['after'], 'value')['value'], '18')
        self.assertNotEqual(baseline['steps'][1]['before'], changed['steps'][1]['before'])

    def test_transport_and_queue_budgets_preserve_the_bounded_call_schedule(self):
        for count in (1, 2, 4, 5, 16, 17, 32):
            steps = [CALLS[0], *[{'action': 'call', 'arguments': [0]}
                                for _ in range(count - 1)]]
            with self.subTest(count=count), tempfile.TemporaryDirectory() as temporary:
                entry = self.candidate(Path(temporary), steps=steps)
                self.assertEqual(entry['status'], 'ready', entry['reason'])
                settings = tomllib.loads(generation.policy(entry, 'http://127.0.0.1:1234'))
                self.assertEqual(settings['export'].get('max_queued_batches', 8), max(8, 2 * count))
                options = generation.attempt_receiver_options(entry, None)
                self.assertEqual(options.get('max_requests', 32), max(32, 2 * count))
                self.assertNotIn('allow_chunked', options)
                self.assertNotIn('max_bytes', options)

    def test_rebound_source_method_or_instance_shadow_cannot_be_a_matching_call(self):
        replacements = [
            'Counter.step=lambda self,amount:99',
            'self.step=99',
            'self.__class__=type("Other",(),{})',
            'globals()["Counter"]=object',
            'Counter.step.__code__=(lambda self,amount:99).__code__',
        ]
        for replacement in replacements:
            source = SOURCE.replace('  return self\n', '  ' + replacement + '\n  return self\n')
            with self.subTest(replacement=replacement), tempfile.TemporaryDirectory() as temporary:
                result, raw, _ = self.worker(Path(temporary), source=source)
                self.assertNotEqual(result.returncode, 0)
                self.assertIsNone(raw)

    def test_method_binding_checks_class_origin_without_application_lookup(self):
        faults = [lambda module: module.__dict__.update(__name__=7),
                  lambda module: setattr(module.Counter, '__module__', 'other'),
                  lambda module: setattr(module.Counter, '__qualname__', 'Other')]
        for fault in faults:
            with self.subTest(fault=fault):
                module = ModuleType('fixture')
                exec(SOURCE, vars(module))
                receiver = module.Counter(10)
                expected = module.Counter.step.__code__
                fault(module)
                with self.assertRaises(ValueError):
                    observe.bound_method(module, 'Counter', 'step', receiver, expected)
        with self.assertRaises(ValueError):
            observe.bound_method(object(), 'Counter', 'step', receiver, expected)
        module = ModuleType('fixture')
        exec(SOURCE.replace('class Counter:', 'class Base: pass\nclass Counter(Base):'), vars(module))
        receiver = module.Counter(10)
        with self.assertRaises(ValueError):
            observe.bound_method(module, 'Counter', 'step', receiver, module.Counter.step.__code__)

    def test_nonstring_instance_keys_do_not_invoke_comparison_hooks(self):
        class Key:
            def __hash__(self):
                return 0

            def __eq__(self, other):
                raise AssertionError('application comparison hook invoked')

        module = ModuleType('fixture')
        exec(SOURCE, vars(module))
        receiver = module.Counter(10)
        receiver.__dict__[Key()] = 1
        with self.assertRaisesRegex(ValueError, 'instance storage'):
            observe.bound_method(module, 'Counter', 'step', receiver, module.Counter.step.__code__)

    def test_missing_steps_and_inconsistent_outer_boundaries_are_refused(self):
        with tempfile.TemporaryDirectory() as temporary:
            result, raw, entry = self.worker(Path(temporary))
            self.assertEqual(result.returncode, 0, result.stderr)
            faults = [lambda value: value.pop('steps'),
                      lambda value: value['steps'].pop(),
                      lambda value: value['steps'][0].update(id='wrong'),
                      lambda value: value.update(before=value['after']),
                      lambda value: value.update(outcome=value['steps'][0]['outcome']),
                      lambda value: value.update(after=value['before'])]
            for fault in faults:
                with self.subTest(fault=fault):
                    altered = copy.deepcopy(raw)
                    fault(altered)
                    with self.assertRaises(ValueError):
                        self.typed(altered, entry)

    def test_release_collection_and_live_controls_remain_explicit_blockers(self):
        schedules = [CALLS + [{'action': 'release'}],
                     CALLS + [{'action': 'release'}, {'action': 'collect'}],
                     [{'action': 'call', 'arguments': 'case',
                       'metrics': {'collection': True, 'emission': True}}]]
        for steps in schedules:
            with self.subTest(steps=steps), tempfile.TemporaryDirectory() as temporary:
                entry = self.candidate(Path(temporary), steps=steps)
                self.assertEqual(entry['status'], 'blocked')


if __name__ == '__main__':
    unittest.main()
