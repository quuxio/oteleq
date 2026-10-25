"""Rehashed native build metadata cannot replace independent caller intent."""

import copy
from dataclasses import replace
import json
from pathlib import Path
import sys
import tempfile
import unittest

ROOT = Path(__file__).resolve().parents[1]
sys.path[:0] = [str(ROOT / 'adapters/generation'), str(ROOT / 'examples')]
import native_build
import native_sdk
import native_provider_fixture as fixture


class NativeToolchainAndSDKTests(unittest.TestCase):
    def test_selected_tools_retain_six_native_queries_and_immutable_descriptions(self):
        with tempfile.TemporaryDirectory(prefix='native provider ') as temporary:
            tools, queries = fixture.toolchain(Path(temporary).resolve())
            self.assertEqual(len(queries), 6)
            self.assertEqual([row.command for row in tools.queries], queries)
            self.assertEqual(tools.version, '22.1.8')
            before = tools.metadata(); changed = tools.metadata(); changed['version'] = '22.0.0'
            self.assertEqual(tools.metadata(), before)
            tools.verify()
            tools.clang.resolved.write_text('changed compiler')
            with self.assertRaises(ValueError): tools.verify()

    def test_compiler_version_stderr_and_missing_flags_are_refused(self):
        for kind in ('version', 'stderr', 'flags'):
            with self.subTest(kind=kind), tempfile.TemporaryDirectory() as temporary:
                def mutate(result):
                    if kind == 'version' and Path(result.args[0]).name == 'clang':
                        result.stdout = b'clang version 22.1.7\n'
                    elif kind == 'stderr': result.stderr = b'warning'
                    elif kind == 'flags' and '--cxxflags' in result.args: result.stdout = b''
                    return result
                with self.assertRaises(ValueError): fixture.toolchain(Path(temporary).resolve(), mutate=mutate)

    def test_sdk_recipe_library_sources_and_original_record_are_all_bound(self):
        with tempfile.TemporaryDirectory() as temporary:
            sdk = fixture.sdk(Path(temporary).resolve())
            self.assertEqual(len(sdk.sources), 5)
            self.assertEqual(sdk.record.value()['library'], fixture.identity(sdk.library.path))
            sdk.verify()
            (sdk.root / 'adapters/native/extra.cpp').write_text('extra input')
            with self.assertRaises(ValueError): sdk.verify()

    def test_sdk_refuses_repaired_wrong_record_fields_and_selected_paths(self):
        for kind in ('schema', 'coverage', 'source-complete', 'sources', 'tool', 'library', 'command'):
            with self.subTest(kind=kind), tempfile.TemporaryDirectory() as temporary:
                sdk = fixture.sdk(Path(temporary).resolve())
                value = sdk.record.value()
                if kind == 'schema': value['schema_version'] = True
                elif kind == 'coverage': value['coverage'] = 0
                elif kind == 'source-complete': value['source_complete'] = 0
                elif kind == 'sources': value['sources'].pop()
                elif kind == 'tool': value['build_tools'].reverse()
                elif kind == 'library': value['library']['path'] = str(sdk.directory / 'decoy')
                else: value['commands'][0].append('-DUNDECLARED=1')
                fixture.write(sdk.record.file.path, value)
                with self.assertRaises(ValueError):
                    native_sdk.capture(sdk.root, sdk.directory, sdk.toolchain, cmake=sdk.cmake.path, ninja=sdk.ninja.path, platform='linux')


class NativeBuildTests(unittest.TestCase):
    def test_both_languages_and_multiple_units_use_complete_fixed_recipes(self):
        for language in ('c', 'cpp'):
            with self.subTest(language=language), tempfile.TemporaryDirectory(prefix='native provider ') as temporary:
                intent = fixture.build(Path(temporary).resolve(), language=language, count=2)
                built = native_build.read(intent)
                self.assertEqual(len(built.files), 39)
                self.assertEqual(len(native_build.commands(intent)), 7)
                self.assertEqual(built.manifest()['sdk'], fixture.identity(intent.sdk.record.file.path, gate=True))
                built.manifest()['sdk']['sha256'] = '0' * 64
                built.verify()
                with self.assertRaises(ValueError): built.file('unowned')
                with self.assertRaises(ValueError): replace(built, files=()).verify()
                (intent.output / 'plugin/unowned').write_text('extra')
                with self.assertRaises(ValueError): built.verify()

    def test_published_file_facts_cannot_be_repaired_by_rewriting_identical_bytes(self):
        with tempfile.TemporaryDirectory() as temporary:
            intent = fixture.build(Path(temporary).resolve())
            built = native_build.read(intent)
            path = intent.output / 'plain'
            path.write_bytes(path.read_bytes())
            with self.assertRaises(ValueError): built.verify()

    def test_decoy_sdk_binding_is_refused_after_rehashing(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary).resolve(); intent = fixture.build(root)
            decoy = root / 'unrelated.txt'; decoy.write_text('not an SDK build record')
            path = intent.output / 'native-source-build.json'; value = json.loads(path.read_bytes())
            value['sdk'] = fixture.identity(decoy, gate=True); fixture.write(path, value)
            with self.assertRaisesRegex(ValueError, 'fixed bindings'): native_build.read(intent)

    def test_all_compiler_channels_bootstrap_and_per_unit_inputs_are_checked(self):
        for kind in ('log', 'bootstrap', 'dependency', 'per-unit', 'missing', 'symlink'):
            with self.subTest(kind=kind), tempfile.TemporaryDirectory() as temporary:
                intent = fixture.build(Path(temporary).resolve(), count=2)
                if kind == 'log': (intent.output / 'plugin/build.stderr').write_text('changed compiler channel')
                elif kind == 'bootstrap': (intent.output / 'bootstrap.cpp').write_text('int different;')
                elif kind == 'dependency': (intent.output / 'plain-0.d').write_text('otelc-inputs: /undeclared\n')
                elif kind == 'per-unit':
                    a, b = intent.output / 'plain-0.d', intent.output / 'plain-1.d'
                    first, second = a.read_bytes(), b.read_bytes(); a.write_bytes(second); b.write_bytes(first)
                elif kind == 'missing': (intent.output / 'instrumented-0.stderr').unlink()
                else:
                    path = intent.output / 'plain'; path.unlink(); path.symlink_to(intent.output / 'instrumented')
                with self.assertRaises(ValueError): native_build.read(intent)

    def test_rehashed_native_language_policy_selection_and_commands_are_refused(self):
        for kind in ('language', 'policy', 'selection', 'input', 'duplicate', 'product', 'command', 'schema'):
            with self.subTest(kind=kind), tempfile.TemporaryDirectory() as temporary:
                intent = fixture.build(Path(temporary).resolve())
                path = intent.output / 'native-build.json'; value = json.loads(path.read_bytes())
                if kind == 'language': value['language'] = 'c'
                elif kind == 'policy': value['policy']['functions']['include'] = ['wrong']; value['policy_sha256'] = fixture.digest(value['policy'])
                elif kind == 'selection': value['selection_sha256'] = '0' * 64
                elif kind == 'input': value['inputs'][0]['sha256'] = '0' * 64
                elif kind == 'duplicate': value['inputs'][1] = copy.deepcopy(value['inputs'][0])
                elif kind == 'product': value['products'].reverse()
                elif kind == 'command': value['commands'][0].append('-DUNDECLARED=1')
                else: value['schema_version'] = True
                fixture.write(path, value)
                manifest = intent.output / 'native-source-build.json'; outer = json.loads(manifest.read_bytes())
                outer['native'] = fixture.identity(path, gate=True); fixture.write(manifest, outer)
                with self.assertRaises(ValueError): native_build.read(intent)


if __name__ == '__main__':
    unittest.main()
