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

    @classmethod
    def capture(cls, method, *, active=False):
        folder = cls.folder / (method + ('-active' if active else ''))
        folder.mkdir()
        (folder / 'app.cpp').write_text(qualifier.SOURCE)
        function = next(row for row in cls.model['functions']
            if row['name'] == 'sample::Counter::' + method and row.get('cpp_function', {}).get('has_body'))
        entry = {**copy.deepcopy(function), 'language': 'cpp', 'path': 'app.cpp',
            'globals': copy.deepcopy(cls.model['globals']), 'expected_baseline': {'kind': 'return'}}
        factory = 'sample::Counter::create' if method == 'secret' else 'sample::Counter'
        generation.receiver_fixture(entry, cls.model, {'factory': factory, 'arguments': [10]})
        assert not entry['reason'], entry['reason']
        calls = [{'action': 'call', 'arguments': 'case'}, {'action': 'call', 'arguments': [2]}]
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
            cli, provider = folder / 'cli', folder / 'provider'
            workspace, reduced = folder / 'cases/workspace', folder / 'shrink/workspace'
            workspace.mkdir(parents=True)
            reduced.mkdir(parents=True)
            (folder / 'cases/plan.stdout').write_text(str(workspace))
            (workspace / 'plan.json').write_text(json.dumps({'otelc_root': str(provider)}))
            (folder / 'shrink/shrink.json').write_text(json.dumps({'workspace': str(reduced)}))
            (folder / 'comparison').mkdir()
            cases = [{'function': qualifier.function(method), 'case': method} for method in qualifier.METHODS]
            (folder / 'comparison/report.json').write_text(json.dumps({'cases': cases}))
            operations = {
                'run': (1, [cli, 'run', '--workspace', workspace, '--report-dir', folder / 'comparison']),
                'framework': (1, [sys.executable, workspace / 'tests/test_equivalence.py']),
                'export': (0, [cli, 'export-tests', '--workspace', workspace, '--destination', folder / 'exported', '--apply']),
                'export-run': (1, [cli, 'run', '--workspace', folder / 'exported', '--report-dir', folder / 'export-comparison']),
                'export-framework': (1, [sys.executable, folder / 'exported/tests/test_equivalence.py']),
                'shrink': (1, [cli, 'shrink', '--workspace', workspace, '--case', 'transient', '--report-dir', folder / 'shrink', '--trials', '1']),
                'reduced-framework': (1, [sys.executable, reduced / 'tests/test_equivalence.py']),
                'reduced-replay': (1, [cli, 'replay', '--workspace', reduced, '--case', 'transient']),
                'changed-source': (2, [cli, 'replay', '--workspace', workspace, '--case', 'transient']),
            }
            for method in qualifier.METHODS:
                operations['replay-' + method] = (int(method == 'transient'), [cli, 'replay', '--workspace', workspace, '--case', method])
            for name, (expected, _) in qualifier.CONTROL_VERDICTS.items():
                operations[name] = (expected, [cli, 'compare-observations', folder / (name + '.json')])

            def receipt(base, name, expected, argv):
                (base / (name + '.started.json')).write_text(json.dumps({'expected_exit': expected, 'argv': list(map(str, argv))}))
                (base / (name + '.exit')).write_text(str(expected) + '\n')
                (base / (name + '.stdout')).write_text(json.dumps({'verdict': qualifier.CONTROL_VERDICTS[name][1]}) if name in qualifier.CONTROL_VERDICTS else '')
                (base / (name + '.stderr')).write_text('application source or immutable snapshot changed' if name == 'changed-source' else '')

            for name, (expected, argv) in operations.items():
                receipt(folder, name, expected, argv)
            for name in ('cases', 'edge-one', 'edge-thirty-two'):
                route = folder / name
                route.mkdir(exist_ok=True)
                selected = route / 'workspace'
                receipt(route, 'plan', 0, [cli, 'plan', '--source', route / 'application', '--otelc-root', provider,
                    '--workspace-parent', route, '--config', route / 'equivalence.toml'])
                receipt(route, 'generate', 0, [cli, 'generate', '--workspace', selected])
                if name != 'cases':
                    receipt(route, 'run', 0, [cli, 'run', '--workspace', selected, '--report-dir', route / 'comparison'])
                (route / 'plan.stdout').write_text(str(selected))
            (folder / 'cases/plan.stdout').write_text(str(workspace))
            self.assertEqual(qualifier.verify_operations(folder, cli), 28)
            for fault in ('missing', 'exit', 'argv', 'verdict'):
                path = folder / ('export-framework.exit' if fault in ('missing', 'exit') else
                    'run.started.json' if fault == 'argv' else 'missing-call.stdout')
                original = path.read_bytes()
                if fault == 'missing':
                    path.unlink()
                elif fault == 'exit':
                    path.write_text('0\n')
                elif fault == 'argv':
                    marker = json.loads(original)
                    marker['argv'][1] = 'clean'
                    path.write_text(json.dumps(marker))
                else:
                    path.write_text('{"verdict":"equivalent_observed"}')
                with self.subTest(fault=fault), self.assertRaises((AssertionError, FileNotFoundError)):
                    qualifier.verify_operations(folder, cli)
                path.write_bytes(original)


if __name__ == '__main__':
    unittest.main()
