"""Native build3 cannot replace independently frozen units, inputs or tooling."""

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
import native_protocol
import native_unit_build as units
import native_unit_fixture as fixture
import native_provider_fixture as fixed


class NativeUnitBuildTests(unittest.TestCase):
    def test_version_negotiation_keeps_build2_separate(self):
        value = {**native_protocol.PROTOCOLS, 'build': 3, 'unit_recipe': 1}
        self.assertEqual(native_protocol.verify_protocols(value, build_version=3), value)
        for version in (True, 1, 4):
            with self.subTest(version=version), self.assertRaises(ValueError):
                native_protocol.verify_protocols(value, build_version=version)
        with self.assertRaises(ValueError): native_protocol.verify_protocols(value)
        with self.assertRaises(ValueError): native_protocol.verify_protocols(native_protocol.PROTOCOLS, build_version=3)

    def test_per_unit_context_overlay_rename_and_neutral_driver_are_bound(self):
        for tooling in (False, True):
            with self.subTest(tooling=tooling), tempfile.TemporaryDirectory(prefix='native unit ') as temporary:
                intent = fixture.build(Path(temporary).resolve(), tooling=tooling)
                built = units.read(intent)
                self.assertEqual(built.manifest()['schema_version'], 3)
                self.assertEqual(units.commands(intent), fixture.commands(intent.recipe(), intent.output, intent.sdk))
                compile_steps = [row for row in units.commands(intent) if 'unit' in row]
                self.assertTrue(all('-MD' in row['arguments'] for row in compile_steps))
                for row in compile_steps:
                    selected = row['lane'] == 'instrumented' and row['unit'] != 'observer'
                    self.assertEqual(any(value.startswith('-fpass-plugin=') for value in row['arguments']), selected)
                intent.recipe()['units'].clear(); intent.policy()['sources'].clear(); built.manifest().clear()
                built.verify()
                with self.assertRaises(ValueError): built.file('foreign')
                incomplete = replace(built, files=())
                with self.assertRaises(ValueError): incomplete.verify()
                with self.assertRaises(ValueError): native_build.read(intent)

    def test_rehashed_changed_contexts_and_denominators_refuse(self):
        for kind in ('flags', 'cwd', 'role', 'overlay', 'schema', 'input', 'file', 'tool', 'artifact',
                     'dependency', 'command', 'missingfield', 'extra', 'duplicate', 'source-complete'):
            with self.subTest(kind=kind), tempfile.TemporaryDirectory() as temporary:
                intent = fixture.build(Path(temporary).resolve())
                path = intent.output / 'native-build.json'
                value = json.loads(path.read_bytes())
                if kind == 'flags': value['recipe']['units'][0]['flags'].reverse()
                elif kind == 'cwd': value['recipe']['units'][0]['directory'] = '/'
                elif kind == 'role': value['recipe']['units'][-1]['role'] = 'application'
                elif kind == 'overlay': value['recipe']['units'][0]['overlay'] = None
                elif kind == 'schema': value['schema_version'] = True
                elif kind in ('input', 'file', 'artifact'): value[{'input': 'inputs', 'file': 'files', 'artifact': 'artifacts'}[kind]].pop()
                elif kind == 'tool': value['tools'].clear()
                elif kind == 'dependency': value['dependencies']['plain-work'].reverse()
                elif kind == 'command': value['commands'][0]['arguments'].append('-DNEW=1')
                elif kind == 'missingfield': value.pop('files')
                elif kind == 'extra': value['foreign'] = 1
                elif kind == 'duplicate': value['inputs'].append(copy.deepcopy(value['inputs'][0]))
                else: value['source_complete'] = 0
                fixed.write(path, value); fixture.rebind(intent)
                with self.assertRaises(ValueError): units.read(intent)

    def test_changed_header_private_asset_tool_and_product_keep_original_facts(self):
        for kind in ('header', 'asset', 'objcopy', 'product', 'record'):
            with self.subTest(kind=kind), tempfile.TemporaryDirectory() as temporary:
                intent = fixture.build(Path(temporary).resolve()); built = units.read(intent)
                paths = {'header': intent.project / 'state.h', 'asset': Path(intent.recipe()['assets'][0]),
                         'objcopy': intent.objcopy.path, 'product': intent.output / 'plain',
                         'record': intent.output / 'native-build.json'}
                path = paths[kind]; original = path.read_bytes(); path.write_bytes(original + b'\n')
                with self.assertRaises(ValueError): built.verify()
                path.write_bytes(original)
                with self.assertRaises(ValueError): built.verify()

    def test_compiler_channels_cannot_omit_headers_swap_units_or_select_new_paths(self):
        for kind in ('header', 'foreign', 'target', 'per-unit', 'md', 'missing', 'extra', 'database', 'bootstrap'):
            with self.subTest(kind=kind), tempfile.TemporaryDirectory() as temporary:
                intent = fixture.build(Path(temporary).resolve())
                path = intent.output / 'plain-work.d'
                if kind == 'header': path.write_text('otelc-inputs: ' + str(intent.project / 'unit0.cpp') + '\n')
                elif kind == 'foreign': path.write_text('otelc-inputs: /foreign/never-read\n')
                elif kind == 'target': path.write_text('other: ' + str(intent.project / 'unit0.cpp') + '\n')
                elif kind == 'per-unit': path.write_bytes((intent.output / 'plain-state.d').read_bytes())
                elif kind == 'md':
                    value = json.loads((intent.output / 'native-build.json').read_text())
                    value['commands'][0]['arguments'][value['commands'][0]['arguments'].index('-MD')] = '-MMD'
                    fixed.write(intent.output / 'native-build.json', value)
                elif kind == 'missing': path.unlink()
                elif kind == 'extra': (intent.output / 'unowned').write_text('extra')
                elif kind == 'database': fixed.write(intent.output / 'compile_commands.json', [])
                else: (intent.output / 'bootstrap.cpp').write_text('foreign bootstrap')
                fixture.rebind(intent)
                with self.assertRaises(ValueError): units.read(intent)

    def test_invalid_caller_recipe_and_dependency_closure_refuse_before_build(self):
        for kind in ('schema', 'fields', 'repeatid', 'suffix', 'flag', 'optionvalue', 'pathvalue', 'asset',
                     'driver', 'overlay', 'rename', 'link', 'group', 'missing-source', 'policy', 'output'):
            with self.subTest(kind=kind), tempfile.TemporaryDirectory() as temporary:
                intent = fixture.build(Path(temporary).resolve())
                recipe, groups, policy = intent.recipe(), intent.unit_dependencies, intent.policy()
                output = Path(temporary).resolve() / 'new-build'
                if kind == 'schema': recipe['schema_version'] = True
                elif kind == 'fields': recipe['units'][0]['extra'] = 1
                elif kind == 'repeatid': recipe['units'][1]['id'] = recipe['units'][0]['id']
                elif kind == 'suffix': recipe['units'][0]['language'] = 'c'
                elif kind == 'flag': recipe['units'][0]['flags'].append('-fpass-plugin=/foreign')
                elif kind == 'optionvalue': recipe['units'][0]['flags'].append('-D')
                elif kind == 'pathvalue': recipe['units'][0]['flags'] += ['-include', str(intent.project)]
                elif kind == 'asset': recipe['assets'].append(recipe['assets'][0])
                elif kind == 'driver': recipe['units'][-1]['source'] = recipe['units'][0]['source']
                elif kind == 'overlay': recipe['units'][0]['overlay'] = recipe['assets'][0]
                elif kind == 'rename': recipe['units'][0]['rename_main'] = 1
                elif kind == 'link': recipe['link']['flags'].append('@foreign')
                elif kind == 'group': groups = ()
                elif kind == 'missing-source': groups = ((intent.project / 'state.h',), *groups[1:])
                elif kind == 'policy': policy['lifetimes']['enabled'] = True
                else: output = intent.output
                with self.assertRaises(ValueError):
                    units.freeze(intent.sdk, intent.project, output, 'cpp', recipe, groups, policy)


if __name__ == '__main__':
    unittest.main()
