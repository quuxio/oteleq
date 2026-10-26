"""Real C++ callers retain every declared call on one source-bound receiver."""

import copy
import json
import os
from pathlib import Path
import shutil
import subprocess
import sys
import tempfile
import unittest
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[1]
sys.path[:0] = [str(ROOT / 'adapters/generation'), str(ROOT / 'examples')]
import cpp_graph
import discovery
import generation
import harness
import policy
import sequences
import typed_capture

SOURCE = '''#include <cstdlib>
#include <stdexcept>
class Counter {
 int value_;Counter* self_;int calls_;
 inline static int total_=0;
public:
 explicit Counter(int seed):value_(seed),self_(this),calls_(0){}
 Counter& step(int amount){++calls_;value_+=amount;total_+=amount;return *this;}
 int fail(int amount){++calls_;value_+=amount;if(amount==3)throw std::runtime_error("third");return value_;}
 void touch(int amount){++calls_;value_+=amount;}
 int restored(int amount){++calls_;value_+=amount;
  if(std::getenv("OTELEQ_TEST_DIFFERENCE")){if(calls_==1)++value_;if(calls_==2)--value_;}
  return 7;}
};
'''
CALLS = [{'action': 'call', 'arguments': 'case'},
         *[{'action': 'call', 'arguments': [value]} for value in (2, 3, 4)]]


class CppSequenceTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.compiler = os.environ.get('OTELC_CLANGXX') or shutil.which('clang++')
        cls.temporary = tempfile.TemporaryDirectory(prefix='cpp-sequence-model-')
        cls.addClassCleanup(cls.temporary.cleanup)
        folder = Path(cls.temporary.name)
        source = folder / 'app.cpp';source.write_text(SOURCE)

        def execute(command, cwd, **kwargs):
            return subprocess.run(command, cwd=cwd, capture_output=True, check=False,
                timeout=30, input=kwargs.get('input_data'))

        cls.discovered = discovery.discover(source, 'cpp', folder, {'clang++': cls.compiler}, execute)

    def entry(self, method='step', steps=None):
        function = next(row for row in self.discovered['functions']
            if row['name'] == 'Counter::' + method and row.get('cpp_function', {}).get('has_body'))
        entry = {**copy.deepcopy(function), 'language': 'cpp', 'path': 'app.cpp',
            'globals': copy.deepcopy(self.discovered['globals']), 'expected_baseline': {'kind': 'return'}}
        generation.receiver_fixture(entry, self.discovered, {'factory': 'Counter', 'arguments': [10]})
        self.assertEqual(entry['reason'], '')
        if steps is not False:
            declared = sequences.validate(copy.deepcopy(CALLS if steps is None else steps), policy.expected_baseline)
            sequences.configure(entry, declared, harness.concrete_arguments)
        return entry

    def worker(self, method='step', steps=None, *, difference=False, source=SOURCE, budget=False):
        temporary = tempfile.TemporaryDirectory(prefix='cpp-sequence-worker-')
        self.addCleanup(temporary.cleanup)
        folder = Path(temporary.name);(folder / 'app.cpp').write_text(source)
        entry = self.entry(method, steps)
        driver = harness.materialise(folder, entry, [7])
        binary = folder / 'application'
        built = subprocess.run([self.compiler, '-std=c++17', '-O2', '-pthread', driver, '-o', binary],
            capture_output=True, check=False, timeout=30)
        self.assertEqual(built.returncode, 0, built.stderr.decode())
        output = folder / 'observation'
        environment = dict(os.environ, OTELEQ_OBSERVATION=str(output))
        environment.pop('OTELEQ_TEST_DIFFERENCE', None)
        if difference:environment['OTELEQ_TEST_DIFFERENCE'] = '1'
        actual = subprocess.run([binary], env=environment, capture_output=True, check=False, timeout=15)
        if budget:
            self.assertEqual((actual.returncode, actual.stdout), (91, b''), actual.stderr)
            self.assertIn(b'sequence capture budget exceeded', actual.stderr)
        else:
            self.assertEqual((actual.returncode, actual.stdout, actual.stderr), (0, b'', b''))
        raw = output.read_bytes()
        if budget:return entry, None, raw
        typed = cpp_graph.boundaries(raw, entry, typed_capture.native_scalar)
        return entry, typed, raw

    @staticmethod
    def node(graph, reference):
        return graph['nodes'][int(reference['node_id'][1:])]

    def scalar(self, graph, reference):
        return self.node(graph, reference)['fields']['value']['value']

    def field(self, graph, name):
        receiver = self.node(graph, graph['roots']['receiver'])
        return self.scalar(graph, receiver['fields']['field:' + name])

    def test_calls_keep_one_receiver_intermediate_fields_arguments_statics_and_aliases(self):
        entry, capture, raw = self.worker()
        self.assertEqual(sequences.call_count(entry), 4)
        self.assertEqual(len(capture['steps']), 4)
        for index, (step, argument, before, after, total) in enumerate(zip(
                capture['steps'], (7, 2, 3, 4), (10, 17, 19, 22), (17, 19, 22, 26), (7, 9, 12, 16))):
            self.assertEqual((step['id'], step['action'], step['gaps']), ('step-' + str(index), 'call', []))
            self.assertEqual(self.field(step['before'], 'value_'), str(before))
            self.assertEqual(self.field(step['after'], 'value_'), str(after))
            self.assertEqual(self.field(step['after'], 'calls_'), str(index + 1))
            self.assertEqual(self.scalar(step['before'], step['before']['roots']['argument:0']), str(argument))
            self.assertEqual(self.scalar(step['after'], step['after']['roots']['global:Counter::total_']), str(total))
            graph = step['outcome']['graph']
            self.assertEqual(self.node(graph, graph['roots']['result'])['fields']['value'], graph['roots']['receiver'])
            receiver = self.node(graph, graph['roots']['receiver'])
            self.assertEqual(self.node(graph, receiver['fields']['field:self_'])['fields']['value'], graph['roots']['receiver'])
        self.assertEqual(capture['before'], capture['steps'][0]['before'])
        for name in ('outcome', 'after'):self.assertEqual(capture[name], capture['steps'][-1][name])
        contract = {'case_id': 'case', 'function_id': 'Counter::step(int)', 'fixture_sha256': 'a' * 64}
        self.assertEqual(typed_capture.observation(raw, entry, contract)['steps'], capture['steps'])

    def test_intermediate_exception_keeps_mutation_and_later_calls(self):
        steps = copy.deepcopy(CALLS)
        steps[2]['expected_baseline'] = {'kind': 'error', 'category': 'exception',
            'type': 'cpp.exception.std::runtime_error'}
        _, capture, _ = self.worker('fail', steps)
        self.assertEqual([step['outcome']['kind'] for step in capture['steps']], ['return', 'return', 'error', 'return'])
        self.assertEqual(self.field(capture['steps'][2]['after'], 'value_'), '22')
        error = capture['steps'][2]['outcome']['graph']['roots']['error']
        self.assertEqual(error, {'kind': 'bytes', 'type': 'cpp.exception.std::runtime_error', 'hex': b'third'.hex()})
        self.assertEqual(self.field(capture['after'], 'value_'), '26')

    def test_void_calls_keep_complete_unit_results(self):
        _, capture, _ = self.worker('touch')
        for step in capture['steps']:
            self.assertEqual(step['outcome']['graph']['roots']['result'], {'kind': 'unit', 'type': 'cpp.unit'})
        self.assertEqual(self.field(capture['after'], 'value_'), '26')

    def test_restored_final_state_keeps_the_real_intermediate_difference(self):
        steps = CALLS[:2]
        _, plain, _ = self.worker('restored', steps)
        _, altered, _ = self.worker('restored', steps, difference=True)
        self.assertEqual(plain['before'], altered['before'])
        self.assertEqual(plain['after'], altered['after'])
        self.assertNotEqual(plain['steps'][0]['after'], altered['steps'][0]['after'])
        self.assertEqual(self.field(plain['steps'][0]['after'], 'value_'), '17')
        self.assertEqual(self.field(altered['steps'][0]['after'], 'value_'), '18')

    def test_thirty_two_calls_use_fresh_bounded_graphs_without_reconstructing_the_receiver(self):
        steps = [CALLS[0], *[{'action': 'call', 'arguments': [0]} for _ in range(31)]]
        _, capture, _ = self.worker(steps=steps)
        self.assertEqual(len(capture['steps']), 32)
        self.assertEqual(self.field(capture['after'], 'value_'), '17')
        self.assertEqual(self.field(capture['after'], 'calls_'), '32')

    def test_sequence_capture_budget_cannot_become_a_partial_success(self):
        source = SOURCE.replace('int value_;', 'int values_[128];int value_;')
        source = source.replace('):value_(seed)', '):values_{},value_(seed)')
        with tempfile.TemporaryDirectory(prefix='cpp-sequence-budget-') as temporary:
            folder = Path(temporary);path = folder / 'app.cpp';path.write_text(source)

            def execute(command, cwd, **kwargs):
                return subprocess.run(command, cwd=cwd, capture_output=True, check=False,
                    timeout=30, input=kwargs.get('input_data'))

            model = discovery.discover(path, 'cpp', folder, {'clang++': self.compiler}, execute)
            steps = [CALLS[0], *[{'action': 'call', 'arguments': [0]} for _ in range(31)]]
            with patch.object(self, 'discovered', model):
                entry, _, raw = self.worker(steps=steps, source=source, budget=True)
        self.assertGreater(len(raw), 790528)
        with self.assertRaisesRegex(ValueError, 'capture budget'):
            cpp_graph.boundaries(raw, entry, typed_capture.native_scalar)

    def test_missing_reordered_foreign_and_contradictory_steps_are_refused(self):
        entry, _, raw = self.worker()
        abi, payload = raw.split(b'\n', 1)
        original = json.loads(payload)
        for fault in ('missing', 'short', 'reordered', 'id', 'action', 'schema', 'boolean', 'outer', 'extra', 'field'):
            value = copy.deepcopy(original)
            if fault == 'missing':del value['steps']
            elif fault == 'short':value['steps'].pop()
            elif fault == 'reordered':value['steps'].reverse()
            elif fault == 'id':value['steps'][1]['id'] = 'foreign'
            elif fault == 'action':value['steps'][1]['action'] = 'release'
            elif fault == 'schema':value['cpp_receiver_schema_version'] = 1
            elif fault == 'boolean':value['cpp_receiver_schema_version'] = True
            elif fault == 'outer':value['before'] = value['after']
            elif fault == 'extra':value['steps'][1]['unknown'] = True
            else:del value['steps'][1]['after']['nodes'][0]['fields']['field:value_']
            with self.subTest(fault=fault), self.assertRaises(ValueError):
                cpp_graph.boundaries(abi + b'\n' + json.dumps(value).encode(), entry, typed_capture.native_scalar)

    def test_cpp_release_collection_controls_missing_receiver_and_invalid_arguments_refuse(self):
        entry = self.entry(steps=False)
        for actions in ([CALLS[0], {'action': 'release'}],
                        [CALLS[0], {'action': 'release'}, {'action': 'collect'}],
                        [{**CALLS[0], 'metrics': {'collection': True, 'emission': True}}],
                        [CALLS[0], {'action': 'call', 'arguments': []}]):
            with self.subTest(actions=actions), self.assertRaises(ValueError):
                sequences.configure(entry, sequences.validate(actions, policy.expected_baseline), harness.concrete_arguments)
            self.assertNotIn('sequence_configuration', entry)
        del entry['cpp_receiver']
        with self.assertRaises(ValueError):sequences.configure(entry, CALLS, harness.concrete_arguments)

