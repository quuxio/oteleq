"""Actual caller compiler binding with explicit nonexecuted literal SDK tooling."""

import copy
from dataclasses import replace
import json
from pathlib import Path
import shlex
import struct
import subprocess
import sys
import tempfile
from types import SimpleNamespace
import unittest
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[1]
sys.path[:0] = [str(ROOT / 'adapters/generation'), str(ROOT / 'examples')]
import native_inputs
import native_lifetime_caller as caller
import native_lifetime_fixture
import native_lifetime_inventory as inventory
import native_unit_caller
import test_generation_native_workers as workers


class NativeLifetimeCallerTests(unittest.TestCase):
    def materialise(self, kind='object', *, presence_probe=False):
        fixture = workers.NativeWorkersTests('test_c_real_target_captures_all_state_without_calling_application_memcpy')
        fixture.setUp()
        self.addCleanup(fixture.doCleanups)
        language = 'cpp' if kind == 'object' else 'c'
        profile, entry, _ = fixture.prepare(language, presence_probe=presence_probe)
        literal_root = fixture.base / 'literal'
        literal_root.mkdir()
        literal = native_lifetime_fixture.build(literal_root, kind=kind)
        sdk = literal.base.sdk
        compiler = native_inputs.capture(Path(profile['compiler']['path']), allow_links=True)
        sdk = replace(sdk, toolchain=replace(sdk.toolchain, selected_compiler=compiler))
        old = literal.tool
        tool = inventory.freeze_tool(sdk, kind, tuple(row.path for row in old.dependencies),
                                     old.library_directory, tuple(row.path for row in old.libraries))
        source = native_unit_caller.freeze(sdk, fixture.project, profile, fixture.base / 'evidence',
                                          entry, [5], literal.base.policy())
        self.changed_semantics = False

        def execute(argv, directory):
            words = list(map(str, argv))
            if words[0] == str(sdk.toolchain.directory / 'clang++'):
                if '-M' in words:
                    path = Path(words[words.index('-MF') + 1])
                    path.write_text('otelc-inputs: ' + ' '.join(shlex.quote(str(row.path))
                                                             for row in tool.dependencies) + '\n')
                elif '-o' in words:
                    Path(words[words.index('-o') + 1]).write_bytes(b'literal semantic product; never executed')
                else:
                    self.assertIn('-print-target-triple', words)
                    return subprocess.CompletedProcess(words, 0, b'aarch64-unknown-linux-gnu\n', b'')
                return subprocess.CompletedProcess(words, 0, b'', b'')
            if words[0].endswith('/semantic-tool/lifetimes'):
                value = native_lifetime_fixture.facts(Path(words[2]), kind, empty=not self.changed_semantics)
                return subprocess.CompletedProcess(words, 0, json.dumps(value).encode(), b'')
            return workers.execute(words, directory)

        result = caller.prepare(source, fixture.base / 'helpers', fixture.base / 'caller-evidence',
                                fixture.base / 'sdk-build', tool, execute)
        return fixture, result, execute

    def test_both_profiles_bind_real_generated_units_and_repeat_compiler_probes(self):
        for kind in ('object', 'resource'):
            with self.subTest(kind=kind):
                fixture, result, execute = self.materialise(kind)
                result.verify()
                self.assertEqual(result.intent.version, 4 if kind == 'object' else 5)
                self.assertEqual(len(result.intent.semantics), 2)
                self.assertEqual(len(result.intent.base.recipe()['units']), 3)
                self.assertTrue(result.intent.base.policy()['lifetimes']['enabled'])
                self.assertFalse(result.intent.base.output.exists())
                self.assertIn(result.tool.path, result.binding.paths)
                self.assertTrue(result.recheck(fixture.base / 'after-build', execute))

    def test_changed_semantics_refuse_without_changing_original_records(self):
        fixture, result, execute = self.materialise()
        self.changed_semantics = True
        with self.assertRaisesRegex(ValueError, 'semantic facts changed'):
            result.recheck(fixture.base / 'changed-semantics', execute)
        result.verify()
        with self.assertRaises(ValueError):
            replace(result, binding=replace(result.binding, intent=copy.copy(result.intent.base))).verify()
        with self.assertRaises(ValueError):
            replace(result, tool=replace(result.tool, path=fixture.base / 'foreign-tool')).verify()

    def test_new_existence_only_header_refuses_after_sdk_build(self):
        fixture, result, execute = self.materialise('resource', presence_probe=True)
        (fixture.project / 'include/optional.h').write_text('/* new existence-only input */\n')
        result.verify()
        with self.assertRaisesRegex(ValueError, 'preprocessor probes changed'):
            result.recheck(fixture.base / 'changed-probes', execute)

    def test_changed_tool_and_restored_bytes_cannot_repair_original_binding(self):
        _, result, _ = self.materialise('resource')
        path = result.tool.path
        original = path.read_bytes()
        path.write_bytes(original + b'changed')
        with self.assertRaises(ValueError):
            result.verify()
        path.write_bytes(original)
        with self.assertRaises(ValueError):
            result.verify()

    def test_command_failures_budgets_and_original_channels_remain_visible(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary).resolve()
            def execute(argv, directory):
                return subprocess.CompletedProcess(argv, 7, b'original stdout', b'original error')
            with self.assertRaisesRegex(ValueError, 'original channels retained'):
                caller.command(root, 'failed', ['fixed-tool'], root, execute)
            self.assertEqual((root / 'failed/stdout').read_bytes(), b'original stdout')
            self.assertEqual((root / 'failed/stderr').read_bytes(), b'original error')
            with patch.object(inventory, 'MAX_AST', 1), self.assertRaises(ValueError):
                caller.command(root, 'too-large', ['fixed-tool'], root, execute)

    def test_external_paths_refuse_source_sdk_aliases_existing_and_relative_paths(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary).resolve()
            directories = [root / name for name in ('project', 'sdk', 'products')]
            for path in directories:
                path.mkdir()
            source = SimpleNamespace(project=directories[0],
                                     sdk=SimpleNamespace(root=directories[1], directory=directories[2]))
            alias = root / 'alias'
            alias.symlink_to(directories[0], target_is_directory=True)
            paths = [Path('relative'), root, alias / 'foreign', root / 'missing/../foreign']
            paths.extend(path / 'foreign' for path in directories)
            for path in paths:
                with self.subTest(path=path), self.assertRaises((ValueError, FileNotFoundError)):
                    caller.new_evidence(path, source)
            self.assertTrue(all(not (path / 'foreign').exists() for path in directories))

    def test_darwin_tool_and_debug_images_use_bounded_bytes_and_matching_uuids(self):
        for changed in (False, True):
            with self.subTest(changed=changed), tempfile.TemporaryDirectory() as temporary:
                root = Path(temporary).resolve()
                literal = root / 'literal'
                literal.mkdir()
                original = native_lifetime_fixture.build(literal).tool
                tool = replace(original, sdk=replace(original.sdk, platform='darwin'),
                               host_target='arm64-apple-darwin25')
                evidence = root / 'evidence'
                evidence.mkdir()
                def image(uuid):
                    return struct.pack('<8I', 0xFEEDFACF, 0x0100000C, 0, 2, 1, 24, 0, 0) + struct.pack('<II16s', 0x1B, 24, uuid)
                def execute(argv, directory):
                    if '-M' in argv:
                        Path(argv[argv.index('-MF') + 1]).write_text('otelc-inputs: ' + ' '.join(
                            shlex.quote(str(row.path)) for row in tool.dependencies) + '\n')
                    else:
                        product = Path(argv[argv.index('-o') + 1])
                        product.write_bytes(image(b'1' * 16))
                        for name in inventory.debug_names('darwin', tool.host_target):
                            path = product.parent / name
                            path.parent.mkdir(parents=True, exist_ok=True)
                            path.write_bytes(image(b'2' * 16 if changed else b'1' * 16)
                                             if '/DWARF/' in name else b'literal auxiliary file')
                    return subprocess.CompletedProcess(argv, 0, b'', b'')
                if changed:
                    with self.assertRaisesRegex(ValueError, 'debug identity differs'):
                        caller.semantic_tool(tool, evidence, execute)
                else:
                    result = caller.semantic_tool(tool, evidence, execute)
                    self.assertIsNone(result.content)
                    result.verify()


if __name__ == '__main__':
    unittest.main()
