"""Private cache copies retain the input and ordinary loader decision."""

import copy
from contextlib import redirect_stdout
import io
import os
from pathlib import Path
import py_compile
import shutil
import stat
import subprocess
import sys
import tempfile
from types import SimpleNamespace
import unittest
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[1]
sys.path[:0] = [str(ROOT / 'adapters/generation'), str(ROOT / 'examples')]
import generation as workflow
import python_cache as cache

CONFIGURATION = {'adapters': {'python': {'backend': 'prepared', 'profile': 'python-native-cache-origins-v3'}}}
SOURCE = 'def workload(value:int)->int:return value*2+3\n'


class PythonCacheContextTests(unittest.TestCase):
    def test_retained_routes_copy_the_context_only_when_its_manifest_is_present(self):
        self.assertEqual(workflow.retained_provider_directories({}), [])
        self.assertEqual(workflow.retained_provider_directories({'python_cache_context_manifest': {}}),
                         [cache.DIRECTORY])

    def test_generated_harness_keeps_source_metadata_before_attempt_cache_materialisation(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary).resolve()
            source, workspace, data, compiled = self.fixture(root)
            entry = {'id': 'workload', 'language': 'python', 'path': 'target.py',
                     'name': 'workload', 'line': 1, 'globals': [], 'parameters': ['int'],
                     'output': 'int', 'status': 'ready', 'input_cases': [[7]],
                     'expected_baseline': {'kind': 'return'}, 'python_backend': 'prepared',
                     'python_profile': 'python-native-cache-origins-v3'}
            data.update(inventory=[entry], cases_per_function=1)
            original = cache.selection.freeze(source / 'target.py')
            with patch.object(workflow, 'load_workspace', return_value=(workspace, data)), \
                    patch.dict(os.environ, {'OTELEQ_EXECUTABLE': '/unused/oteleq'}), redirect_stdout(io.StringIO()):
                self.assertEqual(workflow.generate(SimpleNamespace(workspace=workspace)), 0)
            project = root / 'private'
            shutil.copytree(workspace / 'snapshot', project)
            shutil.copytree(workspace / 'tests/harnesses/workload-0', project, dirs_exist_ok=True)
            frozen = cache.materialise(workflow, workspace, data, project)
            copied = cache.selection.freeze(project / 'target.py')
            self.assertEqual((copied.content, copied.mode, copied.mtime_ns),
                             (original.content, original.mode, original.mtime_ns))
            self.assertEqual(frozen[0].content, compiled.read_bytes())
            self.assertEqual(cache.selection.freeze(source / 'target.py'), original)

    def fixture(self, root: Path, *, mode=py_compile.PycInvalidationMode.TIMESTAMP, level=0):
        source, workspace = root / 'application', root / 'workspace'
        source.mkdir(); workspace.mkdir()
        path = source / 'target.py'; path.write_text(SOURCE)
        os.chmod(path, 0o640)
        os.utime(path, ns=(1_700_000_000_123456789, 1_700_000_000_123456789))
        compiled = Path(py_compile.compile(str(path), doraise=True, invalidation_mode=mode, optimize=level))
        manifest = workflow.manifest(source, excluded={'__pycache__'})
        workflow.snapshot_source(source, workspace, manifest)
        context = cache.prepare(workflow, source, workspace, manifest, CONFIGURATION)
        data = {'source': str(source), 'source_manifest': manifest, 'configuration': CONFIGURATION,
                'python_cache_context_manifest': context}
        return source, workspace, data, compiled

    def test_normal_cache_modes_and_optimisations_keep_bytes_timestamps_permissions_and_loader_use(self):
        for mode in py_compile.PycInvalidationMode:
            for level in (0, 1, 2):
                with self.subTest(mode=mode, level=level), tempfile.TemporaryDirectory() as temporary:
                    root = Path(temporary).resolve()
                    source, workspace, data, compiled = self.fixture(root, mode=mode, level=level)
                    before = workflow.manifest(source)
                    project = root / 'private'
                    shutil.copytree(workspace / 'snapshot', project)
                    frozen = cache.materialise(workflow, workspace, data, project)
                    self.assertEqual(len(frozen), 1)
                    self.assertEqual(frozen[0].content, compiled.read_bytes())
                    self.assertEqual((project / 'target.py').stat().st_mtime_ns, (source / 'target.py').stat().st_mtime_ns)
                    self.assertEqual(stat.S_IMODE((project / 'target.py').stat().st_mode), 0o640)
                    code = "import sys;sys.path.insert(0,sys.argv[1]);seen=[];sys.addaudithook(lambda name,args:seen.append(name));import target;print(target.workload(7));print(seen.count('marshal.loads'),seen.count('compile'))"
                    result = subprocess.run([sys.executable, '-I', '-B', *(['-' + 'O' * level] if level else []),
                        '-c', code, str(project)], capture_output=True, timeout=15, check=True)
                    self.assertEqual(result.stdout, b'17\n1 0\n')
                    self.assertEqual(result.stderr, b'')
                    self.assertEqual(cache.freeze_attempt(workflow, workspace, project), frozen)
                    cache.verify(workflow, workspace, data)
                    self.assertEqual(workflow.manifest(source), before)

    def test_default_profiles_do_not_inspect_or_create_cache_context(self):
        for options in ({}, {'backend': 'prepared', 'profile': 'python-native-origins-v2'},
                        {'backend': 'legacy', 'profile': 'python-native-cache-origins-v3'}):
            config = {'adapters': {'python': options}}
            with self.subTest(options=options), patch.object(cache, '_gather', side_effect=AssertionError('not requested')):
                self.assertIsNone(cache.prepare(workflow, Path('/absent'), Path('/absent'), {}, config))
                cache.verify(workflow, Path('/absent'), {'configuration': config})

    def test_frozen_originals_and_private_metadata_or_bytes_cannot_change(self):
        for fault in ('original-cache', 'new-cache', 'original-time', 'snapshot-time', 'snapshot-mode', 'stored-cache', 'extra-context'):
            with self.subTest(fault=fault), tempfile.TemporaryDirectory() as temporary:
                root = Path(temporary).resolve(); source, workspace, data, compiled = self.fixture(root)
                if fault == 'original-cache':
                    compiled.write_bytes(compiled.read_bytes() + b'changed')
                elif fault == 'new-cache':
                    (compiled.parent / 'target.foreign.pyc').write_bytes(b'new')
                elif fault == 'original-time':
                    os.utime(source / 'target.py', ns=(0, 0))
                elif fault == 'snapshot-time':
                    os.utime(workspace / 'snapshot/target.py', ns=(0, 0))
                elif fault == 'snapshot-mode':
                    (workspace / 'snapshot/target.py').chmod(0o600)
                elif fault == 'stored-cache':
                    (workspace / cache.DIRECTORY / 'files' / compiled.relative_to(source)).write_bytes(b'changed')
                else:
                    (workspace / cache.DIRECTORY / 'extra').write_bytes(b'unaccounted')
                with self.assertRaises((ValueError, OSError)):
                    cache.verify(workflow, workspace, data)

    def test_detached_retention_uses_sealed_inputs_without_originals(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary).resolve(); source, workspace, data, _ = self.fixture(root)
            detached = root / 'detached'; shutil.copytree(workspace, detached)
            updated = {**data, 'original_source': str(source), 'source': str(detached / 'snapshot')}
            shutil.rmtree(source)
            cache.verify(workflow, detached, updated)
            project = root / 'private'; shutil.copytree(detached / 'snapshot', project)
            self.assertEqual(len(cache.materialise(workflow, detached, updated, project)), 1)

    def test_missing_cache_is_allowed_but_source_and_existing_cache_links_refuse(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary).resolve(); source, workspace = root / 'app', root / 'work'
            source.mkdir(); workspace.mkdir(); (source / 'target.py').write_text(SOURCE)
            contents = workflow.manifest(source); workflow.snapshot_source(source, workspace, contents)
            sealed = cache.prepare(workflow, source, workspace, contents, CONFIGURATION)
            self.assertEqual(set(sealed), {'context.json'})
            cache.verify(workflow, workspace, {'source': str(source), 'source_manifest': contents,
                'configuration': CONFIGURATION, 'python_cache_context_manifest': sealed})
            outside = root / 'outside'; outside.mkdir()
            (source / '__pycache__').symlink_to(outside, target_is_directory=True)
            with self.assertRaises(ValueError):
                cache._gather(source, contents)
            (source / '__pycache__').unlink(); (source / '__pycache__').mkdir()
            (outside / 'entry').write_bytes(b'foreign')
            (source / '__pycache__/target.cpython-312.pyc').symlink_to(outside / 'entry')
            with self.assertRaises(ValueError):
                cache._gather(source, contents)

    def test_failed_capture_or_linked_destination_does_not_change_external_files(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary).resolve(); source, workspace, data, compiled = self.fixture(root)
            project = root / 'private'; shutil.copytree(workspace / 'snapshot', project)
            outside = root / 'outside'; outside.mkdir()
            (project / '__pycache__').symlink_to(outside, target_is_directory=True)
            with self.assertRaises(ValueError):
                cache.materialise(workflow, workspace, data, project)
            self.assertEqual(list(outside.iterdir()), [])
            with self.assertRaises(ValueError):
                cache._gather(source, {'../outside.py': '0' * 64})
            with patch.object(cache, 'MAX_FILES', 0), self.assertRaises(ValueError):
                cache._gather(source, data['source_manifest'])
            with patch.object(cache.inputs, 'MAX_BYTES', 1), self.assertRaises(ValueError):
                cache._gather(source, data['source_manifest'])

    def test_context_schema_names_typed_facts_and_complete_inventory_refuse_even_if_resealed(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary).resolve(); source, workspace, data, _ = self.fixture(root)
            path = workspace / cache.DIRECTORY / cache.METADATA
            original = workflow.read(path)
            candidates = [{**original, 'schema_version': True}, {**original, 'extra': 1},
                          {**original, 'sources': {}}, {**original, 'sources': {'../target.py': original['sources']['target.py']}}]
            for field, value in [('inode', True), ('mode', stat.S_IFDIR | 0o700), ('size', -1), ('sha256', 'bad')]:
                changed = copy.deepcopy(original); changed['sources']['target.py'][field] = value; candidates.append(changed)
            for changed in candidates:
                workflow.write(path, changed)
                resealed = {**data, 'python_cache_context_manifest': workflow.manifest(workspace / cache.DIRECTORY)}
                with self.subTest(value=changed), self.assertRaises(ValueError):
                    cache.verify(workflow, workspace, resealed)
