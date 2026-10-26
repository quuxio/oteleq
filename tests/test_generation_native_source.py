"""Explicit native selection and preserved public protocol/policy boundaries."""

import copy
import json
from pathlib import Path
import subprocess
import sys
import tempfile
import tomllib
from types import SimpleNamespace
import unittest
from unittest.mock import Mock, patch

ROOT = Path(__file__).resolve().parents[1]
sys.path[:0] = [str(ROOT / 'adapters/generation'), str(ROOT / 'examples')]
import generation
import native_prepared
import native_provider_fixture
import native_protocol
import native_source
import policy


class NativeSourceTests(unittest.TestCase):
    def setUp(self):
        temporary = tempfile.TemporaryDirectory()
        self.addCleanup(temporary.cleanup)
        self.base = Path(temporary.name).resolve()
        self.options = native_source.settings({'backend': 'prepared', 'sdk_build': str(self.base / 'sdk-build')})
        self.entry = {'language': 'cpp', 'path': 'src/one.cpp', 'otelc_function': 'work::selected(short)', 'status': 'ready'}
        native_source.configure(self.entry, self.options)

    def test_selection_is_explicit_closed_and_round_trips_through_project_policy(self):
        self.assertEqual(native_source.settings({}), {'compilation_database': None, 'targets': []})
        self.assertFalse(native_source.enabled({'language': 'cpp'}))
        self.assertEqual(policy.validate({'adapters': {'cpp': self.options}})['adapters']['cpp'], self.options)
        for value in ({'backend': 'other'}, {'backend': 'prepared', 'unknown': True},
                      {'sdk_build': '/tmp/build'}, {'backend': 'prepared', 'profile': 'future'},
                      {'backend': 'prepared', 'sdk_build': 'relative'}, {'backend': 'prepared', 'sdk_build': True},
                      {'backend': 'prepared', 'build_timeout_ms': True}, {'backend': 'prepared', 'build_timeout_ms': 999}):
            with self.subTest(value=value), self.assertRaises(ValueError):
                native_source.settings(value)
        explicit = {'backend': 'prepared', 'compilation_database': 'build/compile_commands.json',
                    'targets': [{'name': 'application', 'units': [{'source': 'src/one.cpp'}]}]}
        self.assertEqual(native_source.settings(explicit)['targets'][0]['name'], 'application')

    def test_sdk_source_closure_is_explicit_and_cannot_weaken_a_lifetime_profile(self):
        self.assertNotIn('sdk_source_profile', self.options)
        self.assertEqual(native_source.source_profile(self.options), 'function-v2')
        for selected in ('function-v2', 'resource-v1'):
            options = native_source.settings({'backend': 'prepared', 'sdk_source_profile': selected})
            self.assertEqual(native_source.source_profile(options), selected)
            self.assertEqual(policy.validate({'adapters': {'cpp': options}})['adapters']['cpp'], options)
        for selected in (True, None, [], 'object-v1', 'future'):
            options = {'backend': 'prepared', 'sdk_source_profile': selected}
            with self.subTest(selected=selected), self.assertRaises(ValueError): native_source.settings(options)
        legacy = {'sdk_source_profile': 'function-v2'}
        with self.assertRaises(ValueError): native_source.settings(legacy)
        lifetime = {'backend': 'prepared', 'profile': 'native-resources-owned-v1',
                    'lifetimes': {'include': ['Item']}, 'sdk_source_profile': 'function-v2'}
        with self.assertRaises(ValueError): native_source.settings(lifetime)
        lifetime['sdk_source_profile'] = 'resource-v1'
        self.assertEqual(native_source.source_profile(native_source.settings(lifetime)), 'resource-v1')

    def test_current_function_sdk_recipe_receives_the_complete_caller_selected_abi_closure(self):
        options = {**self.options, 'sdk_source_profile': 'resource-v1'}
        tools = {key: self.base / key for key in ('llvm-config', 'clang', 'cmake', 'ninja')}
        with patch.object(native_source.native_toolchain, 'capture', return_value='frozen-toolchain'), \
                patch.object(native_source.native_sdk, 'capture', return_value='accepted') as read:
            self.assertEqual(native_source.sdk(self.base, 'c', tools, options, self.base, Mock()), 'accepted')
        self.assertEqual(read.call_args.kwargs['source_profile'], 'resource-v1')

    def test_standalone_recipes_keep_units_independent_and_flags_unaliased(self):
        compiler = self.base / 'clang'
        targets = native_source.standalone_targets('c', compiler, {'b.c': '', 'a.c': '', 'other.cpp': ''})
        self.assertEqual([row['units'][0]['source'] for row in targets], ['a.c', 'b.c'])
        self.assertEqual(len({row['name'] for row in targets}), 2)
        self.assertEqual(targets[0]['units'][0]['compiler'], str(compiler))
        targets[0]['units'][0]['flags'].append('-DCHANGED')
        self.assertNotIn('-DCHANGED', targets[1]['units'][0]['flags'])
        cpp = native_source.standalone_targets('cpp', compiler, {'a.cpp': ''})
        self.assertIn('-std=c++17', cpp[0]['units'][0]['flags'])
        for names in ({}, {str(index) + '.c': '' for index in range(257)}):
            with self.assertRaises(ValueError):
                native_source.standalone_targets('c', compiler, names)

    def test_complete_policy_binds_source_demangled_target_runtime_label_and_service(self):
        resolved = native_source.configuration(self.entry, 'http://127.0.0.1:4318', 'selected-service')
        self.assertEqual(tomllib.loads(native_source.policy(self.entry, 'http://127.0.0.1:4318', 'selected-service')), resolved)
        self.assertEqual(resolved['sources'], {'include': ['src/one.cpp'], 'exclude': []})
        self.assertEqual(resolved['functions'], {'include': ['work::selected(short)'], 'exclude': []})
        self.assertEqual(self.entry['otelc_runtime_function'], 'src/one.cpp::work::selected(short)')
        self.assertEqual(resolved['resource']['service_name'], 'selected-service')
        self.assertEqual(generation.attempt_policy(self.entry, 'http://127.0.0.1:4318', 'selected-service', None),
                         native_source.policy(self.entry, 'http://127.0.0.1:4318', 'selected-service'))
        for field in ('receiver_fixture', 'sequence_configuration'):
            with self.subTest(field=field), self.assertRaises(ValueError):
                native_source.configuration({**self.entry, field: {}}, 'http://127.0.0.1:4318', 'selected-service')
        ordinary = {'language': 'c', 'path': 'main.c', 'otelc_function': 'selected'}
        native_source.configure(ordinary, {})
        self.assertNotIn('native_backend', ordinary)
        with self.assertRaises(ValueError):
            native_source.configuration(ordinary, '', '')

    def test_tools_and_sdk_paths_are_selected_before_metadata(self):
        with patch.object(native_source.capture, 'tool_path', side_effect=lambda name: Path('/tools') / Path(name).name):
            tools = native_source.selected_tools(self.base, 'cpp')
        self.assertEqual(set(tools), {'clang', 'clang++', 'llvm-config', 'llvm-objcopy', 'cpp-demangler', 'python-host', 'cmake', 'ninja'})
        self.assertEqual(native_source.sdk_directory(self.base, {'sdk_build': None}), self.base / 'build/prepared-sdk')
        selected = Mock()
        with patch.object(native_source.native_toolchain, 'capture', return_value=selected) as query, \
                patch.object(native_source.native_sdk, 'capture', return_value='accepted') as read:
            self.assertEqual(native_source.sdk(self.base, 'c', tools, self.options, self.base, Mock()), 'accepted')
        self.assertEqual(query.call_args.args[:3], (tools['llvm-config'], tools['clang'], 'c'))
        self.assertEqual(read.call_args.args, (self.base, Path(self.options['sdk_build']), selected))
        with self.assertRaises(ValueError):
            native_source.selected_tools(self.base, 'rust')

    def test_protocols_and_retained_backend_are_rechecked_without_executing_returned_argv(self):
        tools = {'python-host': self.base / 'python'}
        descriptor = {**native_protocol.PROTOCOLS, 'build': 3, 'unit_recipe': 1}
        execute = Mock(return_value=subprocess.CompletedProcess([], 0, json.dumps(descriptor).encode(), b''))
        workflow = SimpleNamespace(write=generation.write, read=generation.read, manifest=generation.manifest)
        with patch.object(native_source, 'sdk') as accepted:
            native_source.negotiate(workflow, self.base, self.base, 'cpp', tools, self.options, execute)
        accepted.return_value.verify.assert_called_once()
        expected = native_source.cli(self.base, tools) + ['native-protocols', '--build-version', '3']
        self.assertEqual(execute.call_args.args, (expected, self.base))
        self.entry['native_context'] = {'language': 'cpp'}
        data = {'inventory': [self.entry], 'configuration': {'adapters': {'cpp': self.options}},
                'native_projects': {'cpp': {}}, 'tools': {'cpp': {key: str(path) for key, path in tools.items()}},
                'otelc_root': str(self.base), 'native_provider_manifest': generation.manifest(self.base / native_source.DIRECTORY)}
        native_source.verify_probes(workflow, self.base, data)
        for mutate in (lambda value: value['inventory'][0].update(native_backend='legacy'),
                       lambda value: value['inventory'][0].update(otelc_runtime_function='other'),
                       lambda value: value['inventory'][0].pop('native_context')):
            altered = copy.deepcopy(data); mutate(altered)
            with self.assertRaises(ValueError):
                native_source.verify_probes(workflow, self.base, altered)
        (self.base / native_source.DIRECTORY / 'cpp/protocols.json').write_text('{}')
        with self.assertRaises(ValueError):
            native_source.verify_probes(workflow, self.base, data)
        empty = {'inventory': [], 'configuration': {'adapters': {}}}
        with self.assertRaises(ValueError):
            native_source.verify_probes(workflow, self.base, empty)
        with tempfile.TemporaryDirectory() as absent:
            native_source.verify_probes(workflow, Path(absent), empty)

    def test_protocol_failure_remains_visible_and_has_no_legacy_fallback(self):
        for status, document in ((1, {}), (0, native_protocol.PROTOCOLS)):
            with tempfile.TemporaryDirectory() as folder:
                root = Path(folder)
                execute = Mock(return_value=subprocess.CompletedProcess([], status, json.dumps(document).encode(), b''))
                with self.assertRaises(ValueError), patch.object(native_source, 'sdk') as sdk:
                    native_source.negotiate(generation, root, root, 'c', {'python-host': root / 'python'}, self.options, execute)
                sdk.assert_not_called()
                self.assertTrue((root / native_source.DIRECTORY / 'c/protocols.json').is_file())

    def test_fixed_source_product_and_tool_facts_cannot_be_repaired_by_same_bytes(self):
        intent = native_provider_fixture.build(self.base / 'fixture')
        sdk = intent.sdk
        producer = sdk.root / 'otelc'; producer.mkdir()
        for name in native_prepared.REQUIRED:
            (producer / name).write_text('sealed SDK producer ' + name)
        options = native_source.settings({'backend': 'prepared', 'sdk_build': str(sdk.directory)})
        tools = {'cmake': sdk.cmake.path, 'ninja': sdk.ninja.path}
        with patch.object(native_source.sys, 'platform', 'linux'):
            expected = native_source.artefacts(sdk.root, 'c', tools, options)
            native_source.stable(sdk.root, 'c', tools, options, expected)
            path = producer / '__main__.py'
            path.write_bytes(path.read_bytes())
            with self.assertRaisesRegex(ValueError, 'original file facts'):
                native_source.stable(sdk.root, 'c', tools, options, expected)
        with self.assertRaises(ValueError):
            native_source.artefacts(sdk.root, 'rust', tools, options)


if __name__ == '__main__':
    unittest.main()
