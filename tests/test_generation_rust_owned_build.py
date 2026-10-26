"""Literal Rust owned envelopes bind original source builds and fixed native gates."""

import copy
from dataclasses import replace
import json
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[1]
sys.path[:0] = [str(ROOT / 'adapters/generation'), str(ROOT / 'examples')]
import rust_owned_build as owned
import rust_source_build
from rust_build_fixture import Fixture, write
from test_generation_rust_tools import fact


class RustOwnedBuildTests(unittest.TestCase):
    def fixture(self, *, lifetime: bool = False):
        temporary = tempfile.TemporaryDirectory()
        self.addCleanup(temporary.cleanup)
        base = Path(temporary.name).resolve()
        fixture = Fixture(base, lifetime=lifetime); fixture.build()
        source = rust_source_build.read(fixture.intent)
        intent = owned.freeze(source, base / 'owned')
        return fixture, intent

    def publish(self, fixture: Fixture, intent: owned.Intent) -> dict:
        directory = intent.output
        directory.mkdir(); (directory / 'gate').mkdir()
        image = directory / 'gate/otelc-exec-gate'; image.write_bytes(b'literal gate; never executed')
        compiler = fixture.sdk.toolchain.clang.resolved
        source = fixture.sdk.root / 'adapters/native/gate/ExecGate.c'
        command = [str(compiler), '-std=c11', '-O2', '-Wall', '-Wextra', '-Werror',
                   str(source), '-o', str(image)]
        record = directory / 'gate/gate.json'
        write(record, {'schema_version': 1, 'kind': 'otelc.native.exec-gate',
            'source': fact(source), 'compiler': fact(compiler), 'executable': fact(image),
            'coverage': False, 'command': command, 'source_complete': False})
        write(directory / 'gate/compile_commands.json', [
            {'directory': str(fixture.sdk.root), 'file': str(source), 'arguments': command}])
        for name in ('compile.stdout', 'compile.stderr'): (directory / 'gate' / name).write_bytes(b'')
        value = {'schema_version': 1, 'kind': 'otelc.rust.owned-build', 'profile': 'rust1981-owned-standalone-v1',
            'source_profile': fixture.value['profile'], 'source_build': fact(fixture.output / 'rust-source-build.json'),
            'gate': fact(record), 'source_complete': False}
        write(directory / owned.MANIFEST, value)
        return value

    def test_both_literal_source_profiles_bind_the_fixed_gate_without_execution(self) -> None:
        for lifetime in (False, True):
            fixture, intent = self.fixture(lifetime=lifetime)
            with patch.object(subprocess, 'Popen', side_effect=AssertionError('must not execute')):
                expected = self.publish(fixture, intent)
                held = owned.read(intent); held.verify()
            self.assertEqual(held.manifest(), expected)
            changed = held.manifest(); changed['gate'].clear()
            self.assertEqual(held.manifest(), expected)

    def test_closed_envelope_and_original_binding_refuse_even_with_rehashed_values(self) -> None:
        fixture, intent = self.fixture(); value = self.publish(fixture, intent)
        path = intent.output / owned.MANIFEST
        for key, changed in (('schema_version', True), ('kind', 'foreign'), ('profile', 'foreign'),
                ('source_profile', 'rust1981-standalone-drop-v2'), ('source_build', {}), ('gate', {}),
                ('source_complete', 0), ('extra', False)):
            write(path, value | {key: changed})
            with self.subTest(key=key), self.assertRaises(ValueError): owned.read(intent)
        for key in ('source_build', 'gate'):
            for substitute in (True, 1.0):
                changed = copy.deepcopy(value); changed[key]['links'] = substitute; write(path, changed)
                with self.subTest(key=key, substitute=substitute), self.assertRaises(ValueError): owned.read(intent)

    def test_gate_source_compiler_image_flags_and_coverage_cannot_be_replaced(self) -> None:
        fixture, intent = self.fixture(); envelope = self.publish(fixture, intent)
        path = intent.output / 'gate/gate.json'; original = json.loads(path.read_text())
        for key, changed in (('schema_version', True), ('coverage', True), ('source_complete', 0),
                            ('source', {}), ('compiler', {}), ('executable', {}), ('command', ['arbitrary'])):
            write(path, original | {key: changed})
            envelope['gate'] = fact(path); write(intent.output / owned.MANIFEST, envelope)
            with self.subTest(key=key), self.assertRaises(ValueError): owned.read(intent)
        for field in ('source', 'compiler', 'executable'):
            changed = copy.deepcopy(original); changed[field]['links'] = True; write(path, changed)
            envelope['gate'] = fact(path); write(intent.output / owned.MANIFEST, envelope)
            with self.subTest(field=field), self.assertRaises(ValueError): owned.read(intent)

    def test_compiler_database_directory_and_command_are_independently_checked(self) -> None:
        fixture, intent = self.fixture(); self.publish(fixture, intent)
        path = intent.output / 'gate/compile_commands.json'; original = json.loads(path.read_text())
        for changed in ([], [original[0] | {'directory': '/foreign'}],
                        [original[0] | {'arguments': original[0]['arguments'] + ['-g']}]):
            write(path, changed)
            with self.assertRaises(ValueError): owned.read(intent)

    def test_original_source_gate_and_all_channels_refuse_after_byte_restoration(self) -> None:
        for role in ('source', 'gate-source', 'gate-compiler', *owned.NAMES):
            fixture, intent = self.fixture(); self.publish(fixture, intent); held = owned.read(intent)
            path = {'source': fixture.output / 'rust-source-build.json', 'gate-source': intent.gate_source.path,
                    'gate-compiler': intent.gate_compiler.path}.get(role, intent.output / role)
            raw = path.read_bytes(); path.write_bytes(raw + b' ')
            with self.subTest(role=role), self.assertRaises(ValueError): held.verify()
            path.write_bytes(raw)
            with self.subTest(role=role, restored=True), self.assertRaises(ValueError): held.verify()

    def test_metadata_never_selects_a_foreign_source_read(self) -> None:
        fixture, intent = self.fixture(); value = self.publish(fixture, intent)
        value['source_build']['path'] = '/never-read/rust-source-build.json'
        write(intent.output / owned.MANIFEST, value)
        with self.assertRaises(ValueError): owned.read(intent)

    def test_output_boundaries_keep_source_tools_runtime_and_original_build_held(self) -> None:
        fixture, intent = self.fixture()
        for root in (fixture.project, fixture.output, fixture.tools.directory, fixture.sdk.directory,
                     fixture.sysroot, fixture.sdk.root / 'native/rust', fixture.sdk.root / 'otelc',
                     fixture.sdk.root / 'adapters/native', fixture.sdk.root / 'native/llvm'):
            with self.subTest(root=root), self.assertRaises(ValueError):
                owned.freeze(intent.source, root / 'new-owned')
        alias = fixture.base / 'alias'; alias.symlink_to(fixture.output, target_is_directory=True)
        with self.assertRaises(ValueError): owned.freeze(intent.source, alias / 'new-owned')
        with self.assertRaises(ValueError): replace(intent, gate_source=intent.gate_compiler).verify()
        with self.assertRaises(ValueError): owned.freeze(None, fixture.base / 'other')
        with self.assertRaises(ValueError): owned.read(None)
        intent.output.mkdir()
        with self.assertRaises(ValueError): owned.freeze(intent.source, intent.output)

    def test_missing_extra_and_aliased_owned_outputs_refuse(self) -> None:
        for kind in ('missing', 'extra', 'alias'):
            fixture, intent = self.fixture(); self.publish(fixture, intent)
            path = intent.output / 'gate/compile.stdout'
            if kind == 'extra': (intent.output / 'extra').write_text('unowned')
            else:
                path.unlink()
                if kind == 'alias': path.symlink_to(intent.output / 'gate/compile.stderr')
            with self.subTest(kind=kind), self.assertRaises(ValueError): owned.read(intent)


if __name__ == '__main__':
    unittest.main()
