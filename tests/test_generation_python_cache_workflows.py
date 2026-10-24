"""Portable cache qualification keeps literal stage oracles and rechecks without execution."""

from contextlib import redirect_stdout
import copy
import hashlib
import io
import json
import os
from pathlib import Path
import py_compile
import sys
import tempfile
import tomllib
import unittest
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[1]
sys.path[:0] = [str(ROOT / 'adapters/generation'), str(ROOT / 'examples')]
import generation
import python_cache
import python_cache_effect_workflows as effects
import python_cache_receiver_workflows as receivers
from python_cache_qualification import CacheInputs
import qualify_python_cached_workflows as qualifier
from test_generation_python_cache_qualification import CONFIGURATION


class CachedWorkflowTests(unittest.TestCase):
    def test_retained_cli_requires_new_separate_audit_output_before_accessing_the_sdk(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary).resolve(); cli, sdk, folder = root / 'cli', root / 'sdk', root / 'evidence'
            cli.write_bytes(b'fixed executable'); sdk.mkdir(); folder.mkdir()
            arguments = ['--component', 'effects', '--recheck', '--cli', str(cli),
                         '--otelc-root', str(sdk), '--report-dir', str(folder)]
            with patch.object(qualifier.python_inputs, 'artefacts') as inspect, \
                    redirect_stdout(io.StringIO()), patch('sys.stderr', io.StringIO()):
                for extra in ([], ['--audit-dir', str(folder / 'new')]):
                    with self.subTest(extra=extra), self.assertRaises(SystemExit) as error:
                        qualifier.main(arguments + extra)
                    self.assertEqual(error.exception.code, 2)
                inspect.assert_not_called()
            self.assertFalse((folder / 'new').exists())

    def test_receiver_policy_freezes_all_methods_factories_calls_errors_and_shrinking_domain(self):
        policy = tomllib.loads(receivers.policy())
        self.assertEqual(policy['adapters']['python'], {'backend': 'prepared',
            'profile': 'python-native-cache-origins-v3', 'import_roots': ['src']})
        self.assertEqual(set(policy['functions']['include']), set(receivers.FUNCTIONS))
        self.assertEqual(len(policy['fixtures']), 6)
        for fixture in policy['fixtures']:
            method = receivers.FUNCTIONS[fixture['function']]
            self.assertEqual(fixture['cases'], [[7]])
            self.assertEqual(fixture['receiver'], {'factory': 'make_counter' if method == 'secret' else 'Counter',
                                                  'arguments': [10]})
            self.assertEqual([step['arguments'] for step in fixture['sequence']], ['case', [2]])
            self.assertEqual('expected_baseline' in fixture['sequence'][0], method == 'fail')
            self.assertEqual('domains' in fixture, method == 'transient')

    def effect_fixture(self, root: Path):
        source, workspace = root / 'application', root / 'workspace'
        source.mkdir(); workspace.mkdir(); path = source / 'app.py'
        path.write_text(effects.effects.SOURCE); os.utime(path, ns=(effects.TIME, effects.TIME))
        py_compile.compile(str(path), doraise=True)
        initial = CacheInputs.capture(source, {'app.py': effects.effects.SOURCE.encode()})
        contents = generation.manifest(source, excluded={'__pycache__'})
        generation.snapshot_source(source, workspace, contents)
        context = python_cache.prepare(generation, source, workspace, contents, CONFIGURATION)
        generation.write(workspace / 'plan.json', {'configuration': CONFIGURATION, 'source_manifest': contents,
            'source': str(source), 'python_cache_context_manifest': context,
            'source_sha256': generation.identity({'source': generation.identity(contents), 'python_cache_context': context})})
        return initial, workspace

    def test_every_mutation_restores_bytes_and_original_file_facts_even_if_the_control_fails(self):
        with tempfile.TemporaryDirectory() as temporary:
            initial, workspace = self.effect_fixture(Path(temporary).resolve())
            for fault in effects.REFUSALS:
                with self.subTest(fault=fault):
                    with self.assertRaisesRegex(RuntimeError, 'deliberate control failure'):
                        with effects.mutated_input(initial, workspace, fault):
                            with self.assertRaises((AssertionError, ValueError)):
                                initial.verify_originals(); initial.verify_workspace(workspace)
                            raise RuntimeError('deliberate control failure')
                    initial.verify_originals(); initial.verify_workspace(workspace)
                    self.assertFalse(next(iter(initial.root.glob('__pycache__/app.foreign.pyc')), None))

    def test_historical_stages_use_their_literal_body_timestamp_and_unchanged_cache(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary).resolve(); initial, workspace = self.effect_fixture(root)
            (root / 'plan.stdout').write_text(str(workspace) + '\n')
            for index, name in enumerate(effects.PROMOTED):
                text = effects.effects.stage_source(name)
                facts = {**initial.source_facts['app.py'], 'sha256': hashlib.sha256(text.encode()).hexdigest(),
                         'size': len(text.encode()), 'mtime_ns': effects.TIME + index * 2_000_000_000}
                generation.write(root / (name + '-inputs.json'), {'sources': {'app.py': facts}, 'caches': initial.cache_facts})
                amount = 6 if index == 2 else 3
                rows = [{'workspace': str(root / name), 'project_source': str(initial.root)}]
                rows += [{'report': str(root / name / (str(n) + '.json'))} for n in range(amount)]
                (root / (name + '.stdout')).write_text('\n'.join(json.dumps(row) for row in rows) + '\n')
            stages = effects.stages(root, initial)
            self.assertEqual(len(stages), 14)
            changed = next(stage for stage in stages if stage.name == 'promoted-changed-body')
            self.assertEqual(changed.inputs.sources['app.py'], effects.effects.stage_source(changed.name).encode())
            self.assertNotEqual(changed.inputs.sources, initial.sources)
            initial.verify_originals()
            path = root / 'promoted-changed-body-inputs.json'; wrong = generation.read(path)
            wrong['sources']['app.py']['mtime_ns'] = effects.TIME; generation.write(path, wrong)
            with self.assertRaises(AssertionError):
                effects.stages(root, initial)

    def test_complete_typed_effect_oracle_rejects_equal_wrong_results_and_hidden_intermediate_state(self):
        for value in (0, 1, 7):
            for shift in (0, 1):
                case = {'case': 'fixed', 'function': 'app.exercise', 'arguments': [value]}
                observed = {'case_id': 'fixed', 'function_id': 'app.exercise', 'observation_schema_version': 1,
                    'fixture_sha256': 'a' * 64, 'fixture': {'status': 'ready'}, 'gaps': [],
                    'before': effects.typed_graph(value, 0), 'after': effects.typed_graph(value, value + shift),
                    'outcome': {'kind': 'return', 'graph': effects.typed_graph(value, value + shift, result=True)}}
                bundle = {'contract': {'fixture_sha256': 'a' * 64},
                          'baseline': [{'observation': copy.deepcopy(observed)} for _ in range(2)],
                          'instrumented_on': [{'observation': copy.deepcopy(observed)} for _ in range(2)]}
                effects.check_typed(case, bundle, shift)
                for fault in ('result', 'state', 'argument', 'gap'):
                    wrong = copy.deepcopy(bundle)
                    for lane in ('baseline', 'instrumented_on'):
                        observation = wrong[lane][0]['observation']
                        if fault == 'result':
                            observation['outcome']['graph']['roots']['result']['value'] = '8'
                        elif fault == 'state':
                            observation['after']['roots']['global:counter']['value'] = '99'
                        elif fault == 'argument':
                            observation['before']['nodes'][0]['fields'].clear()
                        else:
                            observation['gaps'] = ['unobserved']
                    with self.subTest(value=value, shift=shift, fault=fault), self.assertRaises(AssertionError):
                        effects.check_typed(case, wrong, shift)

    def test_retained_component_never_calls_execution_or_mutation_and_requires_held_process_records(self):
        with tempfile.TemporaryDirectory() as temporary:
            folder = Path(temporary).resolve(); marker = folder / 'operation.started.json'; marker.write_text('{}')
            receipt = folder / 'python-application-start.json'; receipt.write_text('{"pid":123}')
            counts = {'actual_application_launches': 72}
            with patch.object(qualifier.effects, 'retained', return_value=counts) as audit, \
                    patch.object(qualifier.effects, 'run') as run:
                result = qualifier.audit_component('effects', Path('/cli'), Path('/sdk'), folder, {}, {})
                audit.assert_called_once(); run.assert_not_called()
                self.assertEqual(result['new_application_launches_in_audit'], 0)
                self.assertEqual(result['operation_and_process_records_held'], 2)
            def alter(*args):
                marker.write_text('{"changed":true}')
                return counts
            with patch.object(qualifier.effects, 'retained', side_effect=alter), self.assertRaises(AssertionError):
                qualifier.audit_component('effects', Path('/cli'), Path('/sdk'), folder, {}, {})

    def test_recheck_cli_selects_only_the_requested_existing_component(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary).resolve(); cli, sdk, folder = root / 'cli', root / 'sdk', root / 'evidence'
            cli.write_bytes(b'fixed executable'); sdk.mkdir(); folder.mkdir()
            audit_directory = root / 'audit'
            catalogue = {'pinned': True}
            counts = {'actual_application_launches': 72, 'sdk_processes': 36, 'reports': 14,
                      'complete_raw_and_typed_observations': 72, 'recomputed_comparisons': 18}
            with patch.object(qualifier.python_inputs, 'artefacts', return_value=catalogue), \
                    patch.object(qualifier.origins, 'interpreter_probe', return_value={}), \
                    patch.object(qualifier, 'run_component') as run, \
                    patch.object(qualifier, 'audit_component', return_value=counts) as audit, \
                    patch.dict(os.environ), redirect_stdout(io.StringIO()):
                qualifier.main(['--component', 'effects', '--recheck', '--cli', str(cli),
                                '--otelc-root', str(sdk), '--report-dir', str(folder),
                                '--audit-dir', str(audit_directory)])
                run.assert_not_called()
                self.assertEqual(audit.call_args.args[:4], ('effects', cli, sdk, folder))
            result = generation.read(audit_directory / 'retained-audit.json')
            self.assertEqual(result['totals']['actual_application_launches'], 72)
            self.assertEqual(set(result['components']), {'effects'})
            self.assertFalse((folder / 'retained-audit.json').exists())
