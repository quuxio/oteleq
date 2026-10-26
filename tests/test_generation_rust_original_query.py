"""The original-query pipeline owns commands, inputs and the complete result set."""

import copy
import json
import os
from pathlib import Path
import subprocess
import sys
import tempfile
from types import SimpleNamespace
from dataclasses import replace
import unittest
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[1]
sys.path[:0] = [str(ROOT / 'adapters/generation'), str(ROOT / 'examples')]
import rust_build_fixture
import rust_original_query as query
import rust_tools
from test_generation_rust_body_bindings import document
from test_generation_rust_tools import fact


class RustOriginalQueryTests(unittest.TestCase):
    def setUp(self):
        temporary = tempfile.TemporaryDirectory()
        self.addCleanup(temporary.cleanup)
        self.base = Path(temporary.name).resolve()
        self.fixture = rust_build_fixture.Fixture(self.base)
        self.output = self.base / 'original-query'
        self.calls = []
        self.effect = None
        self.returncode = 0
        self.free = patch.object(query.shutil, 'disk_usage', return_value=SimpleNamespace(free=query.FLOOR))
        self.free.start()
        self.addCleanup(self.free.stop)

    def values(self):
        original = self.fixture.original
        def location(path):
            return {'file': str(path), 'start': 0, 'end': path.stat().st_size, 'expanded': False}
        module = {'schema_version': 1, 'kind': 'otelc.rust.module-inventory',
            'mode': 'module-inspect', 'crate_name': 'otelc_app', 'byte_coordinates': 'original-utf8',
            'sources': original.sources.hashes(), 'source_complete': False,
            'modules': [{'compiler_name': '', 'parent': None, 'kind': 'crate',
                'declaration': location(original.main), 'body': location(original.main),
                'eligible': True, 'reason': None}]}
        return {'inspect': original.inspect, 'module-inspect': module,
                'binding-inspect': document(original), 'lifetime-inspect': original.lifetime}

    def execute(self, argv, cwd, *, env, folder, timeout, max_output_bytes, record_process):
        self.calls.append((argv, cwd, dict(env)))
        self.assertGreater(timeout, 0)
        self.assertEqual(max_output_bytes, 8 * 1024**2)
        self.assertTrue(record_process)
        request = json.loads(Path(env['OTELC_RUST_REQUEST']).read_text()) if 'OTELC_RUST_REQUEST' in env else None
        stdout = b''
        if folder.name == 'compiler-version':
            stdout = self.fixture.version.encode()
        elif folder.name == 'compiler-sysroot':
            stdout = (str(self.fixture.sysroot) + '\n').encode()
        elif request:
            self.assertEqual(request['selected'], [])
            Path(request['output']).write_text(json.dumps(self.values()[request['mode']]))
        else:
            depfile = Path(next(arg.split('=', 2)[2] for arg in argv if arg.startswith('--emit=dep-info=')))
            depfile.write_text('original: ' + ' '.join(map(str, self.fixture.dependencies)) + '\n')
        (folder / 'process.json').write_text(json.dumps({'pid': 123, 'argv': argv}))
        (folder / 'stdout').write_bytes(stdout)
        (folder / 'stderr').write_bytes(b'literal compiler warning')
        if self.effect is not None:
            self.effect(folder, request)
        return subprocess.CompletedProcess(argv, self.returncode, stdout, b'literal compiler warning')

    def prepare(self, **changes):
        options = {'execute': self.execute} | changes
        return query.prepare(self.fixture.tools, self.fixture.project, self.fixture.original.main,
                             self.output, self.fixture.dependencies, **options)

    def test_all_fixed_queries_and_sealed_source_context_precede_application_build(self):
        with patch.dict(os.environ, {'RUSTFLAGS': 'foreign', 'OTELC_RUST_REQUEST': '/foreign',
                                    'LD_PRELOAD': '/foreign', 'PYTHONPATH': '/foreign'}):
            held = self.prepare(lifetime=True)
        self.assertEqual(len(self.calls), 7)
        self.assertEqual(set(path.relative_to(self.output).as_posix() for path in self.output.rglob('*')
                             if path.is_file()), query.names(True) | {'original-query.json'})
        for argv, cwd, env in self.calls:
            self.assertEqual(cwd, self.fixture.project)
            self.assertNotIn('RUSTFLAGS', env)
            self.assertNotIn('PYTHONPATH', env)
            self.assertNotIn('LD_PRELOAD', env)
            self.assertEqual(env['LD_LIBRARY_PATH'], str(self.fixture.sysroot / 'lib'))
            if len(argv) > 3:
                self.assertIn('--edition=2024', argv)
                self.assertIn('-Copt-level=2', argv)
        self.assertEqual(held.inspection.value(), self.fixture.original.inspect)
        self.assertIsNotNone(held.lifetime_inspection)
        self.assertFalse(self.fixture.output.exists())
        self.assertFalse((self.output / 'forbidden-application').exists())
        held.verify()

    def test_function_only_query_has_no_lifetime_or_foreign_outputs(self):
        held = self.prepare()
        self.assertEqual(len(self.calls), 6)
        self.assertIsNone(held.lifetime_inspection)
        (self.output / 'unexpected').write_bytes(b'extra')
        with self.assertRaises(ValueError): held.verify()

    def test_summary_record_roles_and_original_directory_are_not_interchangeable(self):
        held = self.prepare()
        self.assertFalse(held.manifest.value()['semantic_complete'])
        held.manifest.value()['sources'].clear()
        held.verify()
        for changed in (replace(held, optimisation=3), replace(held, body_inspection=held.inspection)):
            with self.assertRaises(ValueError): changed.verify()
        self.output.chmod(0o755)
        with self.assertRaises(ValueError): held.verify()

    def test_original_inputs_and_outputs_cannot_be_restored_or_repaired(self):
        held = self.prepare()
        path = held.body_inspection.file.path
        raw = path.read_bytes()
        path.write_bytes(raw + b' ')
        path.write_bytes(raw)
        with self.assertRaises(ValueError): held.verify()

    def test_foreign_dep_info_or_image_is_not_an_original_query(self):
        def image(folder, request):
            if request is not None:
                (self.output / 'forbidden-application').write_bytes(b'not allowed')
        self.effect = image
        with self.assertRaisesRegex(ValueError, 'foreign file'):
            self.prepare()
        self.assertFalse((self.output / 'original-query.json').exists())

    def test_query_failure_preserves_primary_error_and_original_channels(self):
        primary = RuntimeError('compiler failed')
        def fail(folder, request):
            self.fixture.original.main.write_bytes(b'changed original')
            raise primary
        self.effect = fail
        with self.assertRaises(RuntimeError) as caught:
            self.prepare()
        self.assertIs(caught.exception, primary)
        self.assertTrue(any('input recheck' in note for note in primary.__notes__))
        result = json.loads((self.output / 'compiler-version/result.json').read_text())
        self.assertEqual(result['error'], 'RuntimeError')
        self.assertTrue((self.output / 'compiler-version/stderr').exists())
        self.assertFalse((self.output / 'original-query.json').exists())

    def test_low_space_expired_deadline_and_invalid_intent_never_execute(self):
        with patch.object(query.shutil, 'disk_usage', return_value=SimpleNamespace(free=query.FLOOR - 1)):
            with self.assertRaisesRegex(ValueError, '8 GiB'): self.prepare()
        self.assertFalse(self.calls)
        self.output = self.base / 'deadline'
        with patch.object(query.time, 'monotonic', side_effect=(0, 121)):
            with self.assertRaisesRegex(ValueError, 'deadline'): self.prepare()
        self.assertFalse(self.calls)
        self.output = self.base / 'invalid'
        for changes in ({'optimisation': True}, {'lifetime': 1}, {'timeout': float('nan')}):
            with self.subTest(changes=changes), self.assertRaises(ValueError): self.prepare(**changes)
        self.assertFalse(self.output.exists())

    def test_actual_compiler_queries_must_match_the_held_version_and_sysroot(self):
        original = self.fixture.version
        self.fixture.version = original.replace('(literal)', '(foreign)')
        with self.assertRaisesRegex(ValueError, 'actual Rust compiler'): self.prepare()
        self.assertEqual(len(self.calls), 2)
        self.assertFalse((self.output / 'original-query.json').exists())
        self.fixture.version = original
        self.fixture.sysroot = self.base / 'foreign-sysroot'
        self.output = self.base / 'other-query'
        with self.assertRaisesRegex(ValueError, 'actual Rust compiler'): self.prepare()

    def test_nonzero_or_boolean_exit_and_changed_channels_refuse(self):
        for index, code in enumerate((7, False)):
            self.output = self.base / str(index)
            self.returncode = code
            with self.assertRaisesRegex(ValueError, 'query failed'): self.prepare()
        self.output = self.base / 'channels'
        self.returncode = 0
        self.effect = lambda folder, request: (folder / 'stdout').write_bytes(b'changed')
        with self.assertRaisesRegex(ValueError, 'channels differ'): self.prepare()

    def test_output_alias_existing_directory_and_cargo_refuse_before_commands(self):
        self.output = self.fixture.project / 'query'
        with self.assertRaises(ValueError): self.prepare()
        self.assertFalse(self.output.exists())
        self.output = self.fixture.original.output
        with self.assertRaises(ValueError): self.prepare()
        self.output = self.base / 'new'
        (self.fixture.project / 'Cargo.toml').write_text('[package]\n')
        with self.assertRaisesRegex(ValueError, 'Cargo'): self.prepare()
        self.assertFalse(self.calls)

    def test_failed_results_retention_keeps_the_original_query_failure(self):
        primary = RuntimeError('query failed before retention')
        def fail(folder, request):
            (folder / 'result.json').write_text('earlier record')
            raise primary
        self.effect = fail
        with self.assertRaises(RuntimeError) as caught: self.prepare()
        self.assertIs(caught.exception, primary)
        self.assertTrue(any('retention' in note for note in primary.__notes__))
        self.assertEqual((self.output / 'compiler-version/result.json').read_text(), 'earlier record')

    def test_default_executor_runs_only_controlled_python_query_helpers(self):
        payload = json.dumps(self.values())
        dependencies = list(map(str, self.fixture.dependencies))
        script = ('#!' + sys.executable + ' -S\nimport json,os,pathlib,sys\n'
            + 'values=json.loads(' + repr(payload) + ')\n'
            + 'request=os.environ.get("OTELC_RUST_REQUEST")\n'
            + 'if "-vV" in sys.argv:\n print(' + repr(self.fixture.version) + ',end="")\n'
            + 'elif "--print" in sys.argv:\n print(' + repr(str(self.fixture.sysroot)) + ')\n'
            + 'elif request:\n data=json.loads(pathlib.Path(request).read_text())\n'
            + ' pathlib.Path(data["output"]).write_text(json.dumps(values[data["mode"]]))\n'
            + 'else:\n output=next(a.split("=",2)[2] for a in sys.argv if a.startswith("--emit=dep-info="))\n'
            + ' pathlib.Path(output).write_text("original: "+" ".join(' + repr(dependencies) + ')+"\\n")\n')
        for path in (self.fixture.sysroot / 'bin/rustc', self.fixture.products[0]):
            path.write_text(script)
            path.chmod(0o700)
        compiler = rust_tools.compiler(self.fixture.sysroot / 'bin/rustc', self.fixture.sysroot,
            host=self.fixture.host, version=self.fixture.version)
        manifest = json.loads((self.fixture.tools_directory / 'rust-compiler-tools.json').read_text())
        manifest['tools'] = [fact(file.path) for file in compiler.files]
        manifest['products'] = [fact(path) for path in self.fixture.products]
        (self.fixture.tools_directory / 'rust-compiler-tools.json').write_text(json.dumps(manifest))
        self.fixture.tools = rust_tools.read(self.fixture.sdk.root, self.fixture.tools_directory, compiler)
        held = self.prepare(execute=None)
        process = json.loads((self.output / 'binding-inspect/process.json').read_text())
        self.assertGreater(process['pid'], 0)
        self.assertNotEqual(process['pid'], os.getpid())
        held.verify()
