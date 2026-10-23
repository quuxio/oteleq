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
    def capture(cls, method, *, active=False, compact=False, padding=False, steps=2):
        suffix = '-active' if active else '-compact' if compact else '-padding' if padding else ''
        folder = cls.folder / (method + suffix)
        package = folder / 'src/pkg'
        package.mkdir(parents=True)
        (package / '__init__.py').write_text('')
        text = fixture.COMPACT_SOURCE if compact else fixture.BUDGET_SOURCE if padding else fixture.SOURCE
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
                'changed-source': (4, [cli, 'replay', '--workspace', workspace, '--case', 'transient']),
            }
            for method in qualifier.METHODS:
                operations['replay-' + method] = (int(method == 'transient'), [cli, 'replay', '--workspace', workspace, '--case', method])
            for name, (expected, _) in qualifier.CONTROL_VERDICTS.items():
                operations[name] = (expected, [cli, 'compare-observations', folder / (name + '.json')])

            def receipt(base, name, expected, argv):
                (base / (name + '.started.json')).write_text(json.dumps({'expected_exit': expected, 'argv': list(map(str, argv))}))
                (base / (name + '.exit')).write_text(str(expected) + '\n')
                (base / (name + '.stdout')).write_text(json.dumps({'verdict': qualifier.CONTROL_VERDICTS[name][1]}) if name in qualifier.CONTROL_VERDICTS else '')
                (base / (name + '.stderr')).write_text('oteleq: application source or immutable snapshot changed\n' if name == 'changed-source' else '')

            for name, (expected, argv) in operations.items():
                receipt(folder, name, expected, argv)
            for name in ('cases', 'edge-one', 'edge-thirty-two', 'edge-rich-thirty-two'):
                route = folder / name
                route.mkdir(exist_ok=True)
                selected = route / 'workspace'
                receipt(route, 'plan', 0, [cli, 'plan', '--source', route / 'application', '--otelc-root', provider,
                    '--workspace-parent', route, '--config', route / 'equivalence.toml'])
                receipt(route, 'generate', 0, [cli, 'generate', '--workspace', selected])
                if name != 'cases':
                    receipt(route, 'run', 4 if name == 'edge-rich-thirty-two' else 0,
                        [cli, 'run', '--workspace', selected, '--report-dir', route / 'comparison'])
                (route / 'plan.stdout').write_text(str(selected))
            (folder / 'cases/plan.stdout').write_text(str(workspace))
            self.assertEqual(qualifier.verify_operations(folder, cli), 31)
            marker_path = folder / 'changed-source.started.json'
            original_marker = marker_path.read_bytes()
            marker = json.loads(original_marker)
            marker['expected_exit'] = 2
            marker_path.write_text(json.dumps(marker))
            with self.assertRaises(AssertionError):
                qualifier.verify_operations(folder, cli)
            marker_path.write_bytes(original_marker)
            self.assertEqual(qualifier.verify_operations(folder, cli), 31)
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
