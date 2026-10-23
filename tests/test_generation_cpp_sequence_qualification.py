"""Independent ordered C++ oracles reject complete but incorrect observations."""
import copy
import json
import os
from pathlib import Path
import shutil
import subprocess
import sys
import tempfile
import unittest

from sequence_receipt_fixture import write_receipts, reject_bad_receipts

ROOT = Path(__file__).resolve().parents[1]
sys.path[:0] = [str(ROOT / 'adapters/generation'), str(ROOT / 'examples')]

import cpp_graph
import discovery
import generation
import harness
import policy
import sequences
import typed_capture
import qualify_cpp_sequences as qualifier


class CppSequenceQualificationTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.compiler = os.environ.get('OTELC_CLANGXX') or shutil.which('clang++')
        cls.temporary = tempfile.TemporaryDirectory(prefix='cpp-sequence-oracle-')
        cls.addClassCleanup(cls.temporary.cleanup)
        cls.folder = Path(cls.temporary.name)
        source = cls.folder / 'app.cpp'
        source.write_text(qualifier.SOURCE)

        def execute(command, cwd, **kwargs):
            return subprocess.run(command, cwd=cwd, capture_output=True, check=False,
                timeout=30, input=kwargs.get('input_data'))

        cls.model = discovery.discover(source, 'cpp', cls.folder, {'clang++': cls.compiler}, execute)
        cls.observations = {method: cls.capture(method) for method in qualifier.METHODS}
        cls.altered = cls.capture('transient', active=True)
        cls.bounded = cls.capture('identity', compact=True, steps=32)

    @classmethod
    def capture(cls, method, *, active=False, compact=False, steps=2):
        folder = cls.folder / (method + ('-active' if active else '-compact' if compact else ''))
        folder.mkdir()
        (folder / 'app.cpp').write_text(qualifier.BOUND_SOURCE if compact else qualifier.SOURCE)
        model = cls.model
        if compact:
            def execute(command, cwd, **kwargs):
                return subprocess.run(command, cwd=cwd, capture_output=True, check=False,
                    timeout=30, input=kwargs.get('input_data'))
            model = discovery.discover(folder / 'app.cpp', 'cpp', folder, {'clang++': cls.compiler}, execute)
        function = next(row for row in model['functions']
            if row['name'] == 'sample::Counter::' + method and row.get('cpp_function', {}).get('has_body'))
        entry = {**copy.deepcopy(function), 'language': 'cpp', 'path': 'app.cpp',
            'globals': copy.deepcopy(model['globals']), 'expected_baseline': {'kind': 'return'}}
        factory = 'sample::Counter::create' if method == 'secret' else 'sample::Counter'
        generation.receiver_fixture(entry, model, {'factory': factory, 'arguments': [10]})
        assert not entry['reason'], entry['reason']
        calls = [{'action': 'call', 'arguments': 'case'},
            *[{'action': 'call', 'arguments': [2 if steps == 2 else 0]} for _ in range(steps - 1)]]
        if method == 'fail':
            calls[0]['expected_baseline'] = {'kind': 'error', 'category': 'exception',
                'type': 'cpp.exception.std::runtime_error'}
        sequences.configure(entry, sequences.validate(calls, policy.expected_baseline), harness.concrete_arguments)
        driver = harness.materialise(folder, entry, [7])
        built = subprocess.run([cls.compiler, '-std=c++17', '-O2', '-pthread', driver, '-o', folder / 'app'],
            capture_output=True, check=False, timeout=30)
        assert built.returncode == 0, built.stderr.decode()
        output = folder / 'observation'
        environment = dict(os.environ, OTELEQ_OBSERVATION=str(output))
        environment.pop('OTELC_CONFIG', None)
        if active:
            environment['OTELC_CONFIG'] = 'oracle-control-only'
        result = subprocess.run([folder / 'app'], env=environment, capture_output=True, check=False, timeout=15)
        assert (result.returncode, result.stdout, result.stderr) == (0, b'', b''), result.stderr
        observed = cpp_graph.boundaries(output.read_bytes(), entry, typed_capture.native_scalar)
        observed['gaps'] = []
        return observed

    def test_all_six_real_plain_callers_satisfy_complete_literal_oracles(self):
        for method, observed in self.observations.items():
            with self.subTest(method=method):
                qualifier.check_observation(observed, method, 7, False)

    def test_compact_thirty_two_call_profile_checks_every_boundary_and_alias(self):
        qualifier.check_observation(self.bounded, 'identity', 7, False, steps=32, compact=True)
        altered = copy.deepcopy(self.bounded)
        graph = altered['steps'][-1]['after']
        qualifier.node(graph, graph['roots']['global:sample::Counter::total_'])['fields']['value']['value'] = '999'
        with self.assertRaises(AssertionError):
            qualifier.check_observation(altered, 'identity', 7, False, steps=32, compact=True)

    def test_restored_final_state_does_not_hide_intermediate_difference(self):
        original = self.observations['transient']
        self.assertEqual(original['after'], self.altered['after'])
        self.assertNotEqual(original['steps'][0]['after'], self.altered['steps'][0]['after'])
        qualifier.check_observation(self.altered, 'transient', 7, True)
        with self.assertRaises(AssertionError):
            qualifier.check_observation(self.altered, 'transient', 7, False)

    def test_equal_wrong_fields_arguments_statics_and_aliases_refuse(self):
        for boundary in ('before', 'after', 'outcome'):
            for fault in ('field', 'argument', 'static', 'alias', 'float'):
                observed = copy.deepcopy(self.observations['identity'])
                graph = observed['steps'][0][boundary]
                if boundary == 'outcome':
                    graph = graph['graph']
                fields = qualifier.node(graph, graph['roots']['receiver'])['fields']
                if fault == 'alias':
                    qualifier.node(graph, fields['field:pointer_'])['fields']['value'] = fields['field:other_']
                else:
                    selected = (graph['roots']['argument:0'] if fault == 'argument' else
                        graph['roots']['global:sample::Counter::total_'] if fault == 'static' else
                        fields['field:small_'] if fault == 'float' else fields['field:value_'])
                    scalar = qualifier.node(graph, selected)['fields']['value']
                    scalar['bits' if fault == 'float' else 'value'] = '0' if fault == 'float' else '999'
                with self.subTest(boundary=boundary, fault=fault), self.assertRaises(AssertionError):
                    qualifier.check_observation(observed, 'identity', 7, False)

    def test_missing_reordered_steps_outer_summary_and_error_payload_refuse(self):
        for fault in ('missing', 'reordered', 'outer', 'error', 'unit'):
            method = 'fail' if fault == 'error' else 'touch' if fault == 'unit' else 'identity'
            observed = copy.deepcopy(self.observations[method])
            if fault == 'missing':
                observed['steps'].pop()
            elif fault == 'reordered':
                observed['steps'].reverse()
            elif fault == 'outer':
                observed['before'] = observed['after']
            elif fault == 'error':
                observed['steps'][0]['outcome']['graph']['roots']['error']['hex'] = '00'
            else:
                observed['steps'][0]['outcome']['graph']['roots']['result']['type'] = 'foreign'
            with self.subTest(fault=fault), self.assertRaises(AssertionError):
                qualifier.check_observation(observed, method, 7, False)

    def test_every_route_requires_exact_terminal_command_and_refusal_receipts(self):
        with tempfile.TemporaryDirectory(prefix='cpp-route-oracle-') as temporary:
            folder = Path(temporary)
            cli = write_receipts(folder, qualifier.function, ('edge-rich-thirty-two',))
            self.assertEqual(qualifier.verify_operations(folder, cli), 31)
            marker_path = folder / 'changed-source.started.json'
            original_marker = marker_path.read_bytes()
            marker = json.loads(original_marker)
            marker['expected_exit'] = 2
            marker_path.write_text(json.dumps(marker))
            with self.assertRaises(AssertionError):
                qualifier.verify_operations(folder, cli)
            self.assertEqual(qualifier.verify_operations(folder, cli, historical_source_expectation=True), 31)
            for suffix, additions in (('stderr', ('prefix', 'suffix')), ('stdout', ('output',))):
                path = folder / ('changed-source.' + suffix)
                original = path.read_bytes()
                for addition in additions:
                    changed = (b'unrelated diagnostic\n' + original if addition == 'prefix' else
                        original + b'unrelated diagnostic\n' if addition == 'suffix' else b'application output\n')
                    path.write_bytes(changed)
                    with self.subTest(addition=addition), self.assertRaises(AssertionError):
                        qualifier.verify_operations(folder, cli, historical_source_expectation=True)
                    path.write_bytes(original)
            (folder / 'changed-source.exit').write_text('2\n')
            with self.assertRaises(AssertionError):
                qualifier.verify_operations(folder, cli, historical_source_expectation=True)
            (folder / 'changed-source.exit').write_text('4\n')
            marker_path.write_bytes(original_marker)
            reject_bad_receipts(self, qualifier.verify_operations, folder, cli)


if __name__ == '__main__':
    unittest.main()
