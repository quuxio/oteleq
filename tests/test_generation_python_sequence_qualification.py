"""Complete literal Python oracles reject equal but incorrect sequence evidence."""

import argparse
import copy
import json
import os
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest

from sequence_receipt_fixture import write_receipts, reject_bad_receipts

ROOT = Path(__file__).resolve().parents[1]
sys.path[:0] = [str(ROOT / 'adapters/generation'), str(ROOT / 'examples')]
import discovery
import generation
import harness
import policy
import typed_capture
import python_sequence_fixture as fixture
import qualify_python_sequences as qualifier


class PythonSequenceQualificationTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.temporary = tempfile.TemporaryDirectory(prefix='python-sequence-oracle-')
        cls.addClassCleanup(cls.temporary.cleanup)
        cls.folder = Path(cls.temporary.name)
        cls.observations = {method: cls.capture(method) for method in fixture.METHODS}
        cls.altered = cls.capture('transient', active=True)
        cls.bounded = cls.capture('identity', compact=True, steps=32)
        cls.budget = cls.capture('identity', padding=True, steps=32)

    @classmethod
    def capture(cls, method, *, active=False, compact=False, padding=False, rebound=False, steps=2):
        suffix = '-active' if active else '-compact' if compact else '-padding' if padding else '-rebound' if rebound else ''
        folder = cls.folder / (method + suffix)
        package = folder / 'src/pkg'
        package.mkdir(parents=True)
        (package / '__init__.py').write_text('')
        text = fixture.COMPACT_SOURCE if compact else fixture.BUDGET_SOURCE if padding else fixture.REBOUND_SOURCE if rebound else fixture.SOURCE
        if active:
            # A separately labelled plain component fixture, without a fake SDK.
            text = text.replace(fixture.ACTIVE, 'True')
        source = package / 'state.py'
        source.write_text(text)
        discovered = discovery.python_inventory(text)
        discovered['entrypoints'] = []
        calls = [{'action': 'call', 'arguments': 'case'},
                 *[{'action': 'call', 'arguments': [2 if steps == 2 else 0]}
                   for _ in range(steps - 1)]]
        if method == 'fail':
            calls[0]['expected_baseline'] = {'kind': 'error', 'category': 'exception',
                                           'type': 'python.builtins.ValueError'}
        declaration = {'function': fixture.function(method), 'cases': [[7]],
                       'receiver': {'factory': 'make_counter' if method == 'secret' else 'Counter',
                                    'arguments': [10]}, 'sequence': calls}
        configuration = policy.validate({'languages': ['python'],
            'adapters': {'python': {'import_roots': ['src']}},
            'functions': {'include': [fixture.function(method)]}, 'fixtures': [declaration]})
        selected = next(row for row in discovered['functions'] if row['name'] == 'Counter.' + method)
        entry = generation.inventory_entry(selected, discovered, 'src/pkg/state.py', 'python',
            'a' * 64, folder, argparse.Namespace(configuration=configuration, cases=1))
        assert entry['status'] == 'ready', entry['reason']
        driver = harness.materialise(folder, entry, [7])
        output = folder / 'observation'
        result = subprocess.run([sys.executable, '-B', driver], cwd=folder,
            env={**os.environ, 'OTELEQ_OBSERVATION': str(output)},
            capture_output=True, check=False, timeout=30)
        if rebound:
            assert result.returncode != 0 and result.stdout == b'' and not output.exists()
            assert b'receiver class binding differs from its frozen source identity' in result.stderr
            return None
        assert (result.returncode, result.stdout, result.stderr) == (0, b'', b''), result.stderr
        raw = output.read_bytes()
        assert json.loads(raw) == fixture.raw_observation(method, 7, active, steps=steps,
                                                         compact=compact, padding=padding)
        observed = typed_capture.observation(raw, entry,
            {'case_id': 'case', 'function_id': entry['otelc_function'], 'fixture_sha256': 'b' * 64})
        return observed

    def test_six_actual_plain_package_callers_match_complete_independent_oracles(self):
        for method, observed in self.observations.items():
            with self.subTest(method=method):
                fixture.check_observation(observed, method, 7, False)

    def test_compact_thirty_two_calls_cover_all_state_without_exceeding_budget(self):
        fixture.check_observation(self.bounded, 'identity', 7, False, steps=32, compact=True)
        self.assertLess(len(json.dumps(self.bounded).encode()), 262144)
        self.assertEqual(len(self.bounded['steps']), 32)

    def test_padding_profile_has_complete_raw_graphs_but_exceeds_capture_budget(self):
        raw = fixture.raw_observation('identity', 7, False, steps=32, padding=True)
        self.assertGreater(len(json.dumps(raw).encode()), 262144)
        self.assertLessEqual(len(json.dumps(raw).encode()), 1048576)
        self.assertEqual(len(self.budget['steps']), 32)

    def test_restored_final_state_does_not_hide_an_intermediate_difference(self):
        original = self.observations['transient']
        for boundary in ('before', 'outcome', 'after'):
            self.assertEqual(original[boundary], self.altered[boundary])
        self.assertNotEqual(original['steps'][0]['after'], self.altered['steps'][0]['after'])
        fixture.check_observation(self.altered, 'transient', 7, True)
        with self.assertRaises(AssertionError):
            fixture.check_observation(self.altered, 'transient', 7, False)

    def test_fixture_rebinding_both_module_and_instance_class_refuses_before_capture(self):
        self.assertIsNone(self.capture('identity', rebound=True))

    def test_refusal_verifier_requires_binding_failure_and_no_captured_observation(self):
        with tempfile.TemporaryDirectory() as temporary:
            folder = Path(temporary)
            comparison = folder / 'comparison'
            attempt = comparison / 'case/baseline-0'
            attempt.mkdir(parents=True)
            case = {'function': fixture.function('identity'), 'arguments': [7],
                    'exit_code': 4, 'sequence': [{}, {}],
                    'error': 'application exit or OTLP capture failed; inspect retained stdout/stderr'}
            (comparison / 'report.json').write_text(json.dumps(
                {'source_preserved': True, 'blocked': [], 'cases': [case]}))
            (attempt / 'command.json').write_text('[]')
            (attempt / 'stdout').write_bytes(b'')
            diagnostic = b'ValueError: receiver class binding differs from its frozen source identity\n'
            (attempt / 'stderr').write_bytes(diagnostic)
            self.assertEqual(qualifier.verify_class_refusal(folder), 1)
            for filename, data in [('observation', b'{}'), ('typed-observation.json', b'{}'),
                                   ('stdout', b'unexpected output'), ('stderr', b'unrelated error\n')]:
                path = attempt / filename
                previous = path.read_bytes() if path.exists() else None
                path.write_bytes(data)
                with self.subTest(filename=filename), self.assertRaises(AssertionError):
                    qualifier.verify_class_refusal(folder)
                if previous is None:
                    path.unlink()
                else:
                    path.write_bytes(previous)

    def test_each_observed_field_argument_global_static_and_alias_is_required(self):
        for boundary in ('before', 'after', 'outcome'):
            for fault in ('field', 'argument', 'global', 'static', 'alias', 'shared', 'private', 'order'):
                value = copy.deepcopy(self.observations['identity'])
                graph = value['steps'][0][boundary]
                if boundary == 'outcome':
                    graph = graph['graph']
                fields = fixture.node(graph, graph['roots']['receiver'])['fields']
                if fault in ('alias', 'shared'):
                    fields['property:' + fault] = graph['roots']['arguments']
                elif fault == 'order':
                    fields['order:0']['value'] = '00000078'
                else:
                    selected = (fixture.node(graph, graph['roots']['arguments'])['fields']['item:0']
                        if fault == 'argument' else graph['roots']['global:created'] if fault == 'global'
                        else graph['roots']['static:Counter.total'] if fault == 'static'
                        else fields['property:_token'] if fault == 'private' else fields['property:value'])
                    selected['value'] = '999'
                with self.subTest(boundary=boundary, fault=fault), self.assertRaises(AssertionError):
                    fixture.check_observation(value, 'identity', 7, False)

    def test_missing_reordered_outer_error_and_none_observations_refuse(self):
        for fault in ('missing', 'reordered', 'outer', 'error', 'none'):
            method = 'fail' if fault == 'error' else 'touch' if fault == 'none' else 'identity'
            value = copy.deepcopy(self.observations[method])
            if fault == 'missing':
                value['steps'].pop()
            elif fault == 'reordered':
                value['steps'].reverse()
            elif fault == 'outer':
                value['before'] = value['after']
            elif fault == 'error':
                graph = value['steps'][0]['outcome']['graph']
                arguments = fixture.node(graph, graph['roots']['error'])['fields']['exception:args']
                fixture.node(graph, arguments)['fields']['item:0']['value'] = '00000078'
            else:
                value['steps'][0]['outcome']['graph']['roots']['result'] = {'kind': 'unbound'}
            with self.subTest(fault=fault), self.assertRaises(AssertionError):
                fixture.check_observation(value, method, 7, False)


    def test_every_route_requires_exact_terminal_command_and_refusal_receipts(self):
        with tempfile.TemporaryDirectory(prefix='python-route-oracle-') as temporary:
            folder = Path(temporary)
            cli = write_receipts(folder, qualifier.function, ('edge-rich-thirty-two', 'rebound-class'))
            self.assertEqual(qualifier.verify_operations(folder, cli), 34)
            marker_path = folder / 'changed-source.started.json'
            original_marker = marker_path.read_bytes()
            marker = json.loads(original_marker)
            marker['expected_exit'] = 2
            marker_path.write_text(json.dumps(marker))
            with self.assertRaises(AssertionError):
                qualifier.verify_operations(folder, cli)
            marker_path.write_bytes(original_marker)
            self.assertEqual(qualifier.verify_operations(folder, cli), 34)
            for suffix, additions in (('stderr', ('prefix', 'suffix')), ('stdout', ('output',))):
                path = folder / ('changed-source.' + suffix)
                original = path.read_bytes()
                for addition in additions:
                    changed = (b'unrelated diagnostic\n' + original if addition == 'prefix' else
                        original + b'unrelated diagnostic\n' if addition == 'suffix' else b'application output\n')
                    path.write_bytes(changed)
                    with self.subTest(addition=addition), self.assertRaises(AssertionError):
                        qualifier.verify_operations(folder, cli)
                    path.write_bytes(original)
            (folder / 'changed-source.exit').write_text('2\n')
            with self.assertRaises(AssertionError):
                qualifier.verify_operations(folder, cli)
            (folder / 'changed-source.exit').write_text('4\n')
            marker_path.write_bytes(original_marker)
            reject_bad_receipts(self, qualifier.verify_operations, folder, cli)


if __name__ == '__main__':
    unittest.main()
