"""Retained cache audits require independent bytes and complete original/private facts."""
import copy
import json
import os
from pathlib import Path
import py_compile
import shutil
import subprocess
import sys
import tempfile
import tomllib
import unittest
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[1]
sys.path[:0] = [str(ROOT / 'adapters/generation'), str(ROOT / 'examples')]
import generation
import python_cache
from python_cache_qualification import CacheInputs, file_facts
import qualify_python_caches as qualifier

CONFIGURATION = {'adapters': {'python': {'backend': 'prepared', 'profile': 'python-native-cache-origins-v3'}}}
SOURCE = b'def selected(value:int)->int:return value+1\n'


class PythonCacheQualificationTests(unittest.TestCase):
    def test_repeated_retained_comparisons_use_the_exact_public_verdict_and_preserve_receipts(self):
        expected = {'verdict': 'equivalent_observed', 'scope': {'language': 'python'}}
        complete = subprocess.CompletedProcess([], 0, json.dumps(expected).encode(), b'')
        with patch.object(qualifier.subprocess, 'run', return_value=complete) as execute:
            for _ in range(2):
                qualifier.recompute_case(Path('/consumer'), Path('/retained/bundle.json'), expected)
            self.assertEqual(execute.call_count, 2)
            self.assertEqual(execute.call_args.args[0],
                             ['/consumer', 'compare-observations', '/retained/bundle.json'])
            self.assertEqual(execute.call_args.kwargs['timeout'], 30)
        for returned, code in [({'verdict': 'equivalent', 'scope': {'language': 'python'}}, 0),
                               ({**expected, 'scope': {'language': 'java'}}, 0), (expected, 1)]:
            result = subprocess.CompletedProcess([], code, json.dumps(returned).encode(), b'')
            with self.subTest(returned=returned, code=code), \
                    patch.object(qualifier.subprocess, 'run', return_value=result), self.assertRaises(AssertionError):
                qualifier.recompute_case(Path('/consumer'), Path('/retained/bundle.json'), expected)

    def fixture(self, root: Path, *, cached: bool = True):
        source, workspace = root / 'application', root / 'workspace'
        source.mkdir(); workspace.mkdir(); path = source / 'target.py'; path.write_bytes(SOURCE)
        os.utime(path, ns=(1_700_000_000_123456789, 1_700_000_000_123456789))
        if cached:
            py_compile.compile(str(path), doraise=True)
        inputs = CacheInputs.capture(source, {'target.py': SOURCE})
        contents = generation.manifest(source, excluded={'__pycache__'})
        generation.snapshot_source(source, workspace, contents)
        context = python_cache.prepare(generation, source, workspace, contents, CONFIGURATION)
        data = {'configuration': CONFIGURATION, 'source_manifest': contents, 'source': str(source),
                'python_cache_context_manifest': context}
        generation.write(workspace / 'plan.json', data)
        attempt = root / 'attempt'; attempt.mkdir(); project = attempt / 'project'
        shutil.copytree(workspace / 'snapshot', project)
        caches = python_cache.materialise(generation, workspace, data, project)
        rows = [{'path_hex': x.path.hex(), 'sha256': x.sha256, 'device': x.device, 'inode': x.inode,
                 'mtime_ns': x.mtime_ns, 'mode': x.mode} for x in caches]
        return inputs, workspace, attempt, {'caches': rows}

    def test_originals_workspace_and_attempts_are_bound_to_literal_sources_and_cache_facts(self):
        for cached in (False, True):
            with self.subTest(cached=cached), tempfile.TemporaryDirectory() as temporary:
                inputs, workspace, attempt, facts = self.fixture(Path(temporary).resolve(), cached=cached)
                inputs.verify_originals(); inputs.verify_workspace(workspace)
                self.assertEqual(inputs.receipt(), {'sources': inputs.source_facts, 'caches': inputs.cache_facts})
                result = inputs.frozen_caches(attempt, {'python_profile': 'python-native-cache-origins-v3'}, facts)
                self.assertEqual(len(result), int(cached))

    def test_scalar_selection_uses_literal_declarations_and_every_private_source_fact(self):
        with tempfile.TemporaryDirectory() as temporary:
            inputs, _, attempt, facts = self.fixture(Path(temporary).resolve())
            path = attempt / 'project/target.py'; current = file_facts(path)
            row = {'path_hex': os.fsencode(path).hex(), 'qualname': 'selected', 'line': 1,
                   **{key: current[key] for key in ('sha256', 'device', 'inode', 'mtime_ns', 'mode')}}
            origin = {**facts, 'selected': [row]}; entry = {'path': 'target.py', 'name': 'selected', 'line': 1}
            generation.write(attempt / 'python-expected-origins.json', origin)
            _, selected = inputs.scalar_selection(attempt, entry)
            self.assertEqual((selected[0].qualname, selected[0].source.content), ('selected', SOURCE))
            for field, value in [('line', 2), ('sha256', '0' * 64), ('mtime_ns', 0), ('mode', 0)]:
                changed = copy.deepcopy(origin); changed['selected'][0][field] = value
                generation.write(attempt / 'python-expected-origins.json', changed)
                with self.subTest(field=field), self.assertRaises(AssertionError):
                    inputs.scalar_selection(attempt, entry)

    def test_loader_matrix_has_independent_current_source_and_cached_result_expectations(self):
        self.assertEqual(len(set(qualifier.MODES)), 8)
        for mode in qualifier.MODES:
            configured = tomllib.loads(qualifier.policy(mode))
            fixture, = configured['fixtures']
            self.assertEqual(fixture['cases'], [[7]])
            self.assertEqual(fixture['expected_baseline']['value']['value'],
                             '18' if mode in ('stale-timestamp', 'stale-checked') else '17')
            self.assertEqual('value*2+4' in qualifier.literal_source(mode),
                             mode in ('stale-timestamp', 'stale-checked', 'older-unchecked'))

    def test_full_raw_and_typed_graph_oracles_refuse_equal_wrong_results_or_hidden_state(self):
        with tempfile.TemporaryDirectory() as temporary:
            folder = Path(temporary); report = folder / 'report.json'
            case = {'case': 'fixed-0', 'function': 'target.workload', 'arguments': [7], 'exit_code': 0}
            generation.write(report, {'source_preserved': True, 'blocked': [], 'cases': [case]})
            contract = {'required_roots': ['arguments', 'global:counter'],
                        'expected_baseline': {'kind': 'return_value', 'value': qualifier.scalar(17)},
                        'fixture_sha256': 'a' * 64}
            typed = {'case_id': 'fixed-0', 'function_id': 'target.workload', 'observation_schema_version': 1,
                     'fixture_sha256': 'a' * 64, 'fixture': {'status': 'ready'}, 'gaps': [],
                     'before': qualifier.typed_graph(0), 'after': qualifier.typed_graph(7),
                     'outcome': {'kind': 'return', 'graph': qualifier.typed_graph(7, 17)}}
            raw = {'before': qualifier.raw_graph(0), 'after': qualifier.raw_graph(7),
                   'outcome': {'kind': 'return', 'value': qualifier.raw_graph(7, 17)}}
            original = {'contract': contract}
            for lane in ('baseline', 'instrumented_on'):
                witness = None if lane == 'baseline' else {'functions': {'target.workload': 1},
                                                         'spans': 1, 'pending': 0, 'losses': {'incomplete': 0}}
                original[lane] = [{'observation': copy.deepcopy(typed), 'execution': {
                    'capture_complete': True, 'termination': {'kind': 'exit', 'code': 0},
                    'channels': {'stdout': [], 'stderr': []}, 'witness': copy.deepcopy(witness)}} for _ in range(2)]
                for repeat in range(2):
                    attempt_folder = folder / 'fixed-0' / (lane + '-' + str(repeat))
                    attempt_folder.mkdir(parents=True)
                    generation.write(attempt_folder / 'observation', raw)
            path = folder / 'fixed-0/typed-bundle.json'
            generation.write(path, {'cases': [original]})
            self.assertEqual(qualifier.check_report(report, 'timestamp'), 4)
            for fault in ('typed-result', 'typed-state', 'missing-argument', 'incomplete', 'witness', 'equal-wrong'):
                changed = copy.deepcopy(original)
                observed = changed['instrumented_on'][0]
                if fault == 'typed-result':
                    observed['observation']['outcome']['graph']['roots']['result']['value'] = '18'
                elif fault == 'typed-state':
                    observed['observation']['after']['roots']['global:counter']['value'] = '8'
                elif fault == 'missing-argument':
                    observed['observation']['before']['nodes'][0]['fields'].clear()
                elif fault == 'incomplete':
                    observed['execution']['capture_complete'] = False
                elif fault == 'witness':
                    observed['execution']['witness']['functions'] = {}
                else:
                    changed['contract']['expected_baseline']['value']['value'] = '18'
                    for lane in ('baseline', 'instrumented_on'):
                        for attempt in changed[lane]:
                            attempt['observation']['outcome']['graph']['roots']['result']['value'] = '18'
                generation.write(path, {'cases': [changed]})
                with self.subTest(fault=fault), self.assertRaises(AssertionError):
                    qualifier.check_report(report, 'timestamp')
            generation.write(path, {'cases': [original]})
            changed = copy.deepcopy(raw); changed['before']['roots']['global:counter']['value'] = '1'
            generation.write(folder / 'fixed-0/baseline-0/observation', changed)
            with self.assertRaises(AssertionError):
                qualifier.check_report(report, 'timestamp')

    def test_original_or_private_byte_timestamp_mode_and_inode_changes_cannot_hide(self):
        for fault in ('original-source-time', 'original-cache-inode', 'snapshot-mode', 'private-cache-bytes',
                      'context-bytes', 'context-facts', 'manifest-inventory'):
            with self.subTest(fault=fault), tempfile.TemporaryDirectory() as temporary:
                inputs, workspace, attempt, facts = self.fixture(Path(temporary).resolve())
                cached = next(iter(inputs.caches))
                if fault == 'original-source-time':
                    os.utime(inputs.root / 'target.py', ns=(0, 0))
                elif fault == 'original-cache-inode':
                    path = inputs.root / cached; replacement = path.with_name('replacement')
                    replacement.write_bytes(path.read_bytes()); os.replace(replacement, path)
                elif fault == 'snapshot-mode':
                    (workspace / 'snapshot/target.py').chmod(0o600)
                elif fault == 'private-cache-bytes':
                    (attempt / 'project' / cached).write_bytes(b'changed')
                elif fault == 'context-bytes':
                    (workspace / 'python-cache-context/files' / cached).write_bytes(b'changed')
                elif fault == 'context-facts':
                    path = workspace / 'python-cache-context/context.json'
                    changed = generation.read(path); changed['sources']['target.py']['inode'] += 1
                    generation.write(path, changed)
                    plan = generation.read(workspace / 'plan.json')
                    plan['python_cache_context_manifest'] = generation.manifest(path.parent)
                    generation.write(workspace / 'plan.json', plan)
                else:
                    path = workspace / 'plan.json'; changed = generation.read(path)
                    changed['python_cache_context_manifest']['extra'] = '0' * 64; generation.write(path, changed)
                with self.assertRaises(AssertionError):
                    inputs.verify_originals(); inputs.verify_workspace(workspace)
                    inputs.frozen_caches(attempt, {'python_profile': 'python-native-cache-origins-v3'}, facts)

    def test_expected_cache_catalogue_cannot_be_omitted_duplicated_relabelled_or_replaced(self):
        with tempfile.TemporaryDirectory() as temporary:
            inputs, _, attempt, original = self.fixture(Path(temporary).resolve())
            changed = copy.deepcopy(original); changed['caches'][0]['path_hex'] += '00'
            variants = [{'caches': []}, {'caches': original['caches'] * 2}, changed]
            for field, value in [('sha256', '0' * 64), ('inode', 1), ('mtime_ns', 0), ('mode', 0)]:
                changed = copy.deepcopy(original); changed['caches'][0][field] = value; variants.append(changed)
            for facts in variants:
                with self.subTest(facts=facts), self.assertRaises(AssertionError):
                    inputs.frozen_caches(attempt, {'python_profile': 'python-native-cache-origins-v3'}, facts)
            with self.assertRaises(AssertionError):
                inputs.frozen_caches(attempt, {'python_profile': 'python-native-origins-v2'}, original)
            self.assertNotEqual(file_facts(attempt / 'project/target.py')['inode'], inputs.source_facts['target.py']['inode'])
