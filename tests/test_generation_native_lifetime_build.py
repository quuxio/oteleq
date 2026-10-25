"""Closed lifetime build recipes reject repaired metadata and missing evidence."""

import copy
from dataclasses import replace
import gzip
import json
from pathlib import Path
import sys
import tempfile
import struct
import unittest
from unittest import mock

ROOT = Path(__file__).resolve().parents[1]
sys.path[:0] = [str(ROOT / 'adapters/generation'), str(ROOT / 'examples')]
import native_lifetime_build as build
import native_lifetime_inventory as inventory
import native_lifetime_fixture as fixture
import native_provider_fixture as fixed
import native_unit_build
import native_inputs


class NativeLifetimeBuildTests(unittest.TestCase):
    def test_Darwin_debug_names_are_fixed_by_the_selected_host_target(self):
        arm = inventory.debug_names('darwin', 'arm64-apple-darwin25.0.0')
        self.assertEqual(len(arm), 3)
        self.assertTrue(arm[-1].endswith('/aarch64/lifetimes.yml'))
        self.assertTrue(inventory.debug_names('darwin', 'x86_64-apple-darwin25.0.0')[-1].endswith(
            '/x86_64/lifetimes.yml'))
        self.assertEqual(inventory.debug_names('linux', None), ())
        for target in (None, '', 'arm64-unknown-linux-gnu', 'foreign-apple-darwin', True):
            with self.subTest(target=target), self.assertRaises(ValueError):
                inventory.debug_names('darwin', target)

    def test_native_Mach_O_debug_UUID_is_typed_bounded_and_unambiguous(self):
        identifier = b'0123456789abcdef'
        command = struct.pack('<2I', 0x1B, 24) + identifier
        def image(cpu=0x0100000C, *, magic=0xFEEDFACF, count=1, size=24, body=command):
            return struct.pack('<8I', magic, cpu, 0, 2, count, size, 0, 0) + body
        self.assertEqual(inventory.debug_uuid(image(), 'arm64-apple-darwin25'), identifier)
        self.assertEqual(inventory.debug_uuid(image(0x01000007), 'x86_64-apple-darwin25'), identifier)
        for raw in (b'', image(magic=0), image(cpu=0), image(count=5000), image(size=999),
                    image(size=23), image(count=2), image(count=2, size=48, body=command*2),
                    image(body=struct.pack('<2I', 0x1B, 16)+identifier),
                    image(body=struct.pack('<2I', 1, 24)+identifier)):
            with self.subTest(raw=raw), self.assertRaises(ValueError):
                inventory.debug_uuid(raw, 'arm64-apple-darwin25')

    def test_repeated_compiler_includes_and_frozen_aliases_bind_each_file_once(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary).resolve(); source = root/'source.h'; source.write_text('header')
            alias = root/'alias.h'; alias.symlink_to(source)
            held = native_inputs.capture(source)
            aliases = native_unit_build.alias_inputs((alias,), (held,))
            raw = ('otelc-inputs: '+str(source)+' '+str(alias)+' '+str(source)+'\n').encode()
            self.assertEqual(inventory.dependencies(raw, root, (held,), aliases), [held.gate_identity()])
            with self.assertRaises(ValueError): inventory.dependencies(raw, root, (held,), ())
            with self.assertRaises(ValueError): inventory.dependencies(b'foreign: data', root, (held,), aliases)

    def test_both_profiles_bind_complete_products_and_original_facts(self):
        for kind, count in (('object', 74), ('resource', 96)):
            with self.subTest(kind=kind), tempfile.TemporaryDirectory() as temporary:
                intent = fixture.build(Path(temporary).resolve(), kind=kind)
                actual = build.read(intent)
                self.assertEqual(len(actual.files), count)
                self.assertEqual(actual.manifest()['schema_version'], intent.version)
                actual.verify()
                actual.manifest()['sdk']['sha256'] = '0' * 64
                actual.verify()
                with self.assertRaises(ValueError): actual.file('foreign')
                with self.assertRaises(ValueError): replace(actual, files=()).verify()

    def test_without_observation_assets_or_main_rename_both_profiles_stay_closed(self):
        for kind in ('object', 'resource'):
            with self.subTest(kind=kind), tempfile.TemporaryDirectory() as temporary:
                intent = fixture.build(Path(temporary).resolve(), kind=kind, tooling=False)
                actual = build.read(intent)
                self.assertIsNone(intent.base.objcopy)
                self.assertFalse(any('rename' in row['label'] for row in build.commands(intent)))
                actual.verify()

    def test_shared_context_cannot_enter_the_function_only_reader_or_build(self):
        with tempfile.TemporaryDirectory() as temporary:
            intent = fixture.build(Path(temporary).resolve())
            with self.assertRaisesRegex(ValueError, 'unit policy'):
                native_unit_build.read(intent.base)
            with self.assertRaisesRegex(ValueError, 'unit policy'):
                native_unit_build.Build(intent.base, ()).verify()
            with self.assertRaises(ValueError): build.read(intent.base)

    def test_compiled_driver_is_neutral_and_mixed_C_units_have_explicit_object_environment(self):
        with tempfile.TemporaryDirectory() as temporary:
            intent = fixture.build(Path(temporary).resolve())
            steps = {row['label']: row for row in build.commands(intent)}
            self.assertEqual(steps['instrumented-state']['environment'], {'OTELC_OBJECT_C_UNIT': '1'})
            self.assertNotIn('environment', steps['instrumented-observer'])
            self.assertNotIn('environment', steps['plain-work'])
            self.assertTrue(steps['instrumented-work']['environment']['OTELC_OBJECT_INVENTORY'].endswith(
                '/lifetimes/work/native-lifetimes.json'))

    def test_C_checks_every_application_and_driver_object_in_both_lanes_after_rename(self):
        with tempfile.TemporaryDirectory() as temporary:
            intent = fixture.build(Path(temporary).resolve(), kind='resource')
            steps = build.commands(intent)
            self.assertEqual(sum(row.get('symbol_check', False) for row in steps), 6)
            labels = [row['label'] for row in steps]
            for lane in ('plain', 'instrumented'):
                self.assertEqual(labels.index(lane + '-work-resource-symbols'),
                                 labels.index(lane + '-work-rename') + 1)
            self.assertNotIn('environment', next(row for row in steps if row['label'] == 'instrumented-observer'))

    def test_every_allocator_name_in_either_lane_or_driver_refuses(self):
        for label in ('plain-work', 'instrumented-state', 'plain-observer', 'instrumented-observer'):
            for symbol in ('free', '_free', 'malloc', '_calloc', 'realloc'):
                with self.subTest(label=label, symbol=symbol), tempfile.TemporaryDirectory() as temporary:
                    intent = fixture.build(Path(temporary).resolve(), kind='resource')
                    (intent.base.output / (label + '-resource-symbols.stdout')).write_text(symbol + '\n')
                    with self.assertRaisesRegex(ValueError, 'interposed'):
                        build.read(intent)

    def test_malformed_symbol_channel_does_not_fall_back_to_metadata(self):
        for raw in (b'free\0', b'\xff'):
            with self.subTest(raw=raw), tempfile.TemporaryDirectory() as temporary:
                intent = fixture.build(Path(temporary).resolve(), kind='resource')
                (intent.base.output / 'plain-work-resource-symbols.stdout').write_bytes(raw)
                with self.assertRaises(ValueError): build.read(intent)

    def test_foreign_empty_directory_links_extra_and_missing_products_refuse(self):
        for change in ('empty', 'nested-empty', 'extra', 'missing', 'link'):
            with self.subTest(change=change), tempfile.TemporaryDirectory() as temporary:
                intent = fixture.build(Path(temporary).resolve())
                output = intent.base.output
                if change == 'empty': (output / 'foreign').mkdir()
                elif change == 'nested-empty': (output / 'lifetimes/work/foreign').mkdir()
                elif change == 'extra': (output / 'lifetime-tool/foreign').write_text('unowned')
                elif change == 'missing': (output / 'plugin/functions.o').unlink()
                else:
                    path = output / 'lifetimes/work/0-semantics.json.gz'
                    path.unlink(); path.symlink_to(output / 'plain')
                with self.assertRaises(ValueError): build.read(intent)

    def test_retained_original_product_identity_cannot_be_repaired(self):
        with tempfile.TemporaryDirectory() as temporary:
            actual = build.read(fixture.build(Path(temporary).resolve()))
            path = actual.intent.base.output / 'plugin/objects.o'
            path.write_bytes(path.read_bytes())
            with self.assertRaises(ValueError): actual.verify()

    def test_rehashed_plugin_ABI_input_or_compiler_commands_refuse(self):
        for kind in ('object', 'resource'):
            for change in ('ABI', 'input', 'profile', 'coverage', 'commands', 'database'):
                with self.subTest(kind=kind, change=change), tempfile.TemporaryDirectory() as temporary:
                    intent = fixture.build(Path(temporary).resolve(), kind=kind)
                    path = intent.base.output / 'plugin/llvm-plugin.json'
                    value = json.loads(path.read_text())
                    if change == 'ABI': value[kind + '_probe_abi'] = 'foreign'
                    elif change == 'input': value[kind + '_inputs'].pop()
                    elif change == 'profile': value['profile'] = 'llvm22-itanium-source-v1'
                    elif change == 'coverage': value['coverage'] = True
                    elif change == 'commands':
                        path = intent.base.output / 'plugin/command.json'; value = json.loads(path.read_text()); value.pop()
                    else:
                        path = intent.base.output / 'plugin/compile_commands.json'; value = json.loads(path.read_text()); value.reverse()
                    fixed.write(path, value); fixture.rebind(intent)
                    with self.assertRaisesRegex(ValueError, 'plugin'):
                        build.read(intent)

    def test_rehashed_unit_commands_environment_tools_and_selection_refuse(self):
        for change in ('commands', 'driver-environment', 'tools', 'selection', 'dependencies', 'inputs', 'files', 'artifacts'):
            with self.subTest(change=change), tempfile.TemporaryDirectory() as temporary:
                intent = fixture.build(Path(temporary).resolve(), kind='resource')
                path = intent.base.output / 'native-build.json'; value = json.loads(path.read_text())
                if change == 'commands': value['commands'][-1]['arguments'].append('-lforeign')
                elif change == 'driver-environment':
                    next(row for row in value['commands'] if row['label'] == 'instrumented-observer')['environment'] = {'OTELC_RESOURCE_INVENTORY': 'foreign'}
                elif change == 'tools': value['tools'].pop('nm')
                elif change == 'selection': value['selection_sha256'] = '0' * 64
                elif change == 'dependencies': value['dependencies']['plain-work'].pop()
                else: value[change].pop()
                fixed.write(path, value); fixture.rebind(intent)
                with self.assertRaises(ValueError): build.read(intent)

    def test_tool_source_library_inputs_commands_and_stdout_channels_refuse_substitution(self):
        for change in ('source', 'library', 'inputs', 'command', 'database', 'stdout', 'dependencies'):
            with self.subTest(change=change), tempfile.TemporaryDirectory() as temporary:
                intent = fixture.build(Path(temporary).resolve(), kind='resource')
                folder = intent.base.output / 'resource-tool'
                path = folder / 'native-lifetime-tool.json'; value = json.loads(path.read_text())
                if change == 'source': value['source']['path'] = str(intent.base.project / 'unit0.c')
                elif change == 'library': value['libraries'].reverse()
                elif change == 'inputs': value['inputs'].pop()
                elif change == 'command': value['command'].append('-DFOREIGN=1')
                elif change == 'database':
                    path = folder / 'compile_commands.json'; value = []; fixed.write(path, value)
                elif change == 'stdout': (folder / 'tool-build.json').write_bytes(b'foreign')
                else: (folder / 'tool.d').write_text('otelc-inputs: /foreign\n')
                if change not in ('stdout', 'dependencies'): fixed.write(path, value)
                with self.assertRaises(ValueError): build.read(intent)

    def test_changed_restored_helper_headers_libraries_and_pass_sources_refuse(self):
        for change in ('source', 'header', 'library', 'pass', 'application'):
            with self.subTest(change=change), tempfile.TemporaryDirectory() as temporary:
                intent = fixture.build(Path(temporary).resolve())
                held = {'source': intent.tool.source, 'header': intent.tool.dependencies[-1],
                        'library': intent.tool.libraries[0], 'pass': intent.pass_inputs[0],
                        'application': intent.base.dependencies[0]}[change]
                held.path.write_bytes(held.path.read_bytes())
                with self.assertRaises(ValueError): build.read(intent)

    def test_semantic_facts_are_checked_against_the_caller_before_inventory_hashes(self):
        for kind in ('object', 'resource'):
            with self.subTest(kind=kind), tempfile.TemporaryDirectory() as temporary:
                intent = fixture.build(Path(temporary).resolve(), kind=kind)
                folder = intent.base.output / ('lifetimes/work' if kind == 'object' else 'resources/work')
                path = folder / ('0-semantics.json.gz' if kind == 'object' else 'semantics.json.gz')
                value = json.loads(gzip.decompress(path.read_bytes()))
                value['types'][0]['name'] = 'Foreign'
                path.write_bytes(gzip.compress(json.dumps(value).encode()))
                with self.assertRaisesRegex(ValueError, 'caller-frozen'):
                    build.read(intent)

    def test_rehashed_semantic_context_or_inventory_selection_cannot_authorise_a_build(self):
        for kind in ('object', 'resource'):
            for change in ('source', 'context', 'policy', 'selection', 'bytes', 'tool', 'inputs'):
                with self.subTest(kind=kind, change=change), tempfile.TemporaryDirectory() as temporary:
                    intent = fixture.build(Path(temporary).resolve(), kind=kind)
                    path = intent.base.output / ('lifetimes/work/native-lifetimes.json' if kind == 'object' else 'resources/work/native-resources.json')
                    value = json.loads(path.read_text()); row = value['translation_units'][0] if kind == 'object' else value
                    if change == 'source': row['source'] = str(intent.base.project / 'foreign.c')
                    elif change == 'context': value['compile_context']['flags'].reverse()
                    elif change == 'policy': value['policy_sha256'] = '0' * 64
                    elif change == 'selection': row['types'].clear()
                    elif change == 'bytes': row['semantic_bytes'] = True
                    elif change == 'tool': value['tool']['product']['sha256'] = '0' * 64
                    else: value['inputs'].pop()
                    fixed.write(path, value); fixture.rebind(intent)
                    with self.assertRaises(ValueError): build.read(intent)

    def test_resource_resolution_keeps_each_emitted_site_including_zero(self):
        for change in ('missing', 'caller', 'file', 'boolean', 'count', 'callee'):
            with self.subTest(change=change), tempfile.TemporaryDirectory() as temporary:
                intent = fixture.build(Path(temporary).resolve(), kind='resource')
                path = intent.base.output / 'resources/work/resolution.json'; value = json.loads(path.read_text())
                if change == 'missing': value['sites'].pop()
                elif change == 'boolean': value['sites'][0]['emitted_calls'] = True
                elif change == 'count': value['sites'][0]['emitted_calls'] = 2
                elif change == 'callee': value['sites'][0]['emitted_callees'] = ['free']
                else: value['sites'][0][change] = 'foreign'
                fixed.write(path, value)
                with self.assertRaises(ValueError): build.read(intent)
        with tempfile.TemporaryDirectory() as temporary:
            intent = fixture.build(Path(temporary).resolve(), kind='resource')
            path = intent.base.output / 'resources/work/resolution.json'; value = json.loads(path.read_text())
            value['sites'][0].update(emitted_calls=0, emitted_callees=[])
            # Rebind the ordinary artifact receipt as a producer could; zero
            # emitted sites are valid observations rather than invented probes.
            fixed.write(path, value)
            outer = intent.base.output / 'native-build.json'; metadata = json.loads(outer.read_text())
            metadata['artifacts'] = [fixed.identity(Path(row['path']), gate=True) if row['path'] == str(path) else row
                                     for row in metadata['artifacts']]
            fixed.write(outer, metadata); fixture.rebind(intent)
            build.read(intent)

    def test_invalid_profile_policy_limits_and_selector_types_refuse(self):
        with tempfile.TemporaryDirectory() as temporary:
            intent = fixture.build(Path(temporary).resolve())
            for change in ('enabled', 'boolean', 'limit', 'include', 'source', 'release'):
                value = intent.base.policy()
                if change == 'enabled': value['lifetimes']['enabled'] = False
                elif change == 'boolean': value['lifetimes']['max_live'] = True
                elif change == 'limit': value['lifetimes']['max_live'] = 1000001
                elif change == 'include': value['lifetimes']['include'] = ['']
                elif change == 'source': value['sources']['exclude'] = None
                else: value['lifetimes']['release_methods'] = [True]
                with self.subTest(change=change), self.assertRaises(ValueError): build.policy(value, 'object')
            with self.assertRaises(ValueError): build.policy(intent.base.policy(), 'foreign')

    def test_semantic_document_is_closed_typed_and_retains_duplicate_row_counts(self):
        source = Path('/application/main.cpp'); original = fixture.facts(source, 'object')
        for change in ('schema', 'extra', 'USR', 'location', 'flag', 'site'):
            value = copy.deepcopy(original)
            if change == 'schema': value['schema_version'] = True
            elif change == 'extra': value['future'] = []
            elif change == 'USR': value['types'].append(value['types'][0])
            elif change == 'location': value['types'][0]['location']['line'] = True
            elif change == 'flag': value['types'][0]['dependent'] = 0
            else: value['variables'][0]['type_usr'] = 'missing'
            with self.subTest(change=change), self.assertRaises(ValueError): inventory.document(value, 'object')
        value = copy.deepcopy(original); value['variables'] *= 2
        self.assertFalse(inventory.equivalent_facts(original, value))
        self.assertTrue(inventory.equivalent_facts(original, copy.deepcopy(original)))
        with mock.patch.object(inventory, 'MAX_AST', 16), self.assertRaises(ValueError):
            inventory.document(original, 'object')

    def test_selectors_are_slash_aware_literal_and_exclusion_first(self):
        policy = {'include': ['**/*.cpp'], 'exclude': ['private/**']}
        self.assertTrue(inventory.selection(policy, 'main.cpp', path=True))
        self.assertTrue(inventory.selection(policy, 'src/main.cpp', path=True))
        self.assertFalse(inventory.selection(policy, 'private/main.cpp', path=True))
        self.assertFalse(inventory.selection({'include': ['*.cpp'], 'exclude': []}, 'src/main.cpp', path=True))
        self.assertTrue(inventory.selection({'include': ['I?em[*]'], 'exclude': []}, 'Item[*]'))
        self.assertFalse(inventory.selection({'include': [], 'exclude': []}, 'Item'))

    def test_independent_resource_selection_rejects_unsupported_or_custom_sites(self):
        source = Path('/application/main.c'); data = fixture.facts(source, 'resource')
        policy = {'sources': {'include': ['**'], 'exclude': []}, 'lifetimes': {'include': ['Item'], 'exclude': []}}
        for change in ('unsupported', 'custom', 'incomplete', 'arguments'):
            value = copy.deepcopy(data)
            if change == 'unsupported': value['unsupported'] = [{**value['allocations'][0], 'reason': 'unsupported'}]
            elif change == 'custom': value['allocations'][0]['standard'] = False
            elif change == 'incomplete': value['types'][0]['complete'] = False
            else: value['releases'][0]['arguments'] = True
            with self.subTest(change=change), self.assertRaises(ValueError):
                inventory.catalogue(value, 'resource', policy, Path('/application'))
        value = copy.deepcopy(data); value['allocations'][0]['observer'] = True
        self.assertEqual(inventory.catalogue(value, 'resource', policy, Path('/application'))['allocations'], [])

    def test_outer_binding_compiler_database_and_dependency_substitution_refuse(self):
        for change in ('outer', 'database', 'dependency'):
            with self.subTest(change=change), tempfile.TemporaryDirectory() as temporary:
                intent = fixture.build(Path(temporary).resolve())
                if change == 'outer':
                    path = intent.base.output / 'native-source-build.json'; value = json.loads(path.read_text())
                    value['schema_version'] = 3; fixed.write(path, value)
                elif change == 'database': fixed.write(intent.base.output / 'compile_commands.json', [])
                else: (intent.base.output / 'lifetimes/work/0.d').write_text('otelc-inputs: /foreign\n')
                with self.assertRaises(ValueError): build.read(intent)


if __name__ == '__main__':
    unittest.main()
