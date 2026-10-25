"""Actual Clang binds generated observations to original overloads and unit state."""

import copy
from dataclasses import replace
from pathlib import Path
import sys
import unittest

ROOT = Path(__file__).resolve().parents[1]
sys.path[:0] = [str(ROOT / 'adapters/generation'), str(ROOT / 'examples')]
import native_inputs
import native_unit_caller as caller
import native_provider_fixture as fixed
import test_generation_native_workers as workers


class NativeUnitCallerTests(unittest.TestCase):
    def materialise(self, language: str, *, throws: bool = False, presence_probe: bool = False, probe_exists: bool = False):
        fixture = workers.NativeWorkersTests('test_c_real_target_captures_all_state_without_calling_application_memcpy')
        fixture.setUp(); self.addCleanup(fixture.doCleanups)
        profile, entry, _ = fixture.prepare(language, throws=throws, presence_probe=presence_probe, probe_exists=probe_exists)
        sdk_root = fixture.base / 'literal-sdk'; sdk_root.mkdir()
        sdk = fixed.sdk(sdk_root, language=language)
        # This fixture supplies recipe data only. Its fake SDK/product is never executed.
        compiler = native_inputs.capture(Path(profile['compiler']['path']), allow_links=True)
        sdk = replace(sdk, toolchain=replace(sdk.toolchain, selected_compiler=compiler))
        (sdk.toolchain.directory / 'llvm-objcopy').write_text('literal object tool; never executed')
        source = caller.freeze(sdk, fixture.project, profile, fixture.base / 'evidence', entry, [5], fixed.POLICY)
        result = caller.prepare(source, fixture.base / 'helpers', fixture.base / 'caller-evidence', fixture.base / 'sdk-build', workers.execute)
        return fixture, result

    def test_c_target_wide_state_macros_and_exact_scalar_call_are_compiler_bound(self):
        fixture, result = self.materialise('c')
        result.verify()
        incomplete = replace(result, files=())
        with self.assertRaises(ValueError): incomplete.verify()
        recipe = result.intent.recipe()
        self.assertEqual(len(recipe['units']), 3)
        self.assertEqual([row['role'] for row in recipe['units']], ['application', 'application', 'driver'])
        self.assertEqual(result.source.arguments_json, '[5]')
        for path in (fixture.base / 'helpers').glob('*.c'):
            if path.name != 'driver.c':
                self.assertIn(b'no_profile_instrument_function', path.read_bytes())
        self.assertFalse(result.intent.output.exists())
        held = {item.path for item in result.files}
        self.assertIn(result.source.retained / 'frontend/source/native_discover.cpp', held)
        self.assertNotIn(Path(caller.__file__).with_name('native_discover.cpp'), held)
        records = result.recheck(fixture.base / 'after-build-inputs', workers.execute)
        self.assertTrue(records)

    def test_cpp_overload_and_original_exception_path_keep_their_compiler_context(self):
        _, result = self.materialise('cpp', throws=True)
        result.verify()
        self.assertIn('short', result.source.entry_json)
        self.assertTrue(all('-O0' in row['flags'] for row in result.intent.recipe()['units'][:2]))

    def test_changed_helper_and_restored_bytes_cannot_repair_caller_identity(self):
        fixture, result = self.materialise('c')
        path = fixture.base / 'helpers/driver.c'
        original = path.read_bytes(); path.write_bytes(original + b'\n')
        with self.assertRaises(ValueError): result.verify()
        path.write_bytes(original)
        with self.assertRaises(ValueError): result.verify()

    def test_binding_refuses_substituted_target_signature_reference_or_helper_set(self):
        source = Path('/application/main.c')
        target = {'kind': 'FunctionDecl', 'name': 'work', 'mangledName': 'work', 'id': 'selected',
                  'loc': {'file': str(source), 'offset': 0}, 'type': {'qualType': 'int (int)'},
                  'inner': [{'kind': 'CompoundStmt'}]}
        invoke = {'kind': 'FunctionDecl', 'name': '__oteleq_invoke',
                  'inner': [{'kind': 'NoProfileFunctionAttr'},
                            {'kind': 'CompoundStmt', 'inner': [{'referencedDecl': {'id': 'selected'}}]}]}
        entry = {'native_kind': 'FunctionDecl', 'symbol': 'work', 'source_offset': 0, 'unit': 'main', 'globals': []}
        original = {'ast': {'inner': [target]}}
        document = {'ast': {'inner': [target, invoke]}}
        caller.bind(document, original, source, entry, 'main')
        for kind in ('signature', 'reference', 'helper', 'source', 'offset', 'definition', 'profiling', 'identity'):
            changed = copy.deepcopy(document)
            if kind == 'signature': changed['ast']['inner'][0]['type']['qualType'] = 'int (short)'
            elif kind == 'reference': changed['ast']['inner'][1]['inner'][1]['inner'][0]['referencedDecl']['id'] = 'other'
            elif kind == 'helper': changed['ast']['inner'].append(copy.deepcopy(invoke))
            elif kind == 'source': changed['ast']['inner'][0]['loc']['file'] = '/other/main.c'
            elif kind == 'offset': changed['ast']['inner'][0]['loc']['offset'] = 1
            elif kind == 'definition': changed['ast']['inner'][0]['inner'] = []
            elif kind == 'profiling': changed['ast']['inner'][1]['inner'].pop(0)
            else: changed['ast']['inner'][0].pop('id')
            with self.subTest(kind=kind), self.assertRaises(ValueError):
                caller.bind(changed, original, source, entry, 'main')

    def test_new_existence_only_header_refuses_compiler_recheck(self):
        fixture, result = self.materialise('c', presence_probe=True)
        (fixture.project / 'include/optional.h').write_text('/* newly present, never included */\n')
        result.verify()
        with self.assertRaisesRegex(ValueError, 'preprocessor probes changed'):
            result.recheck(fixture.base / 'changed-probes', workers.execute)

    def test_positive_existence_only_input_is_held_through_compiler_recheck(self):
        fixture, result = self.materialise('c', presence_probe=True, probe_exists=True)
        path = fixture.project / 'include/optional.h'
        self.assertIn(path, {item.path for item in result.files})
        self.assertIn('optional.h', result.states_json)
        result.recheck(fixture.base / 'unchanged-probes', workers.execute)

    def test_semantic_language_switch_is_removed_only_when_it_matches_the_unit(self):
        unit = {'language': 'cpp', 'flags': ['-O2', '-x', 'c++']}
        self.assertEqual(caller.flags(unit, 'cpp'), ['-O2'])
        for changed in ({'language': 'c', 'flags': []}, {'language': 'cpp', 'flags': ['-x', 'c']}):
            with self.subTest(unit=changed), self.assertRaises(ValueError): caller.flags(changed, 'cpp')


if __name__ == '__main__':
    unittest.main()
