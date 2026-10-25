"""Literal public lifetime selection, fixture, source and prebuild type contracts."""

import copy
from dataclasses import replace
import json
from pathlib import Path
import subprocess
import sys
import tempfile
import tomllib
import unittest
from unittest.mock import Mock, patch

ROOT = Path(__file__).resolve().parents[1]
sys.path[:0] = [str(ROOT / 'adapters/generation'), str(ROOT / 'examples')]
import generation
import native_lifetime_fixture
import native_lifetime_policy as life
import native_prepared
import native_source
import policy
from test_generation_native_lifetime_negotiation import descriptor


def observation(language='cpp'):
    return {'type': 'Item', 'creation_path': [0], 'release_path': [0], 'complete': True,
            **({'exception_exit': False} if language == 'cpp' else {})}


def entry(language='cpp'):
    profile = life.OBJECT if language == 'cpp' else life.RESOURCE
    options = native_source.settings({'backend': 'prepared', 'profile': profile,
                                     'lifetimes': {'include': ['Item']}})
    value = {'language': language, 'path': 'src/work.cpp' if language == 'cpp' else 'src/work.c',
             'otelc_function': 'work(int)' if language == 'cpp' else 'work', 'reason': '',
             'id': 'work', 'parameters': ['int'], 'expected_baseline': {'kind': 'return'}}
    native_source.configure(value, options)
    return value


class NativeLifetimePolicyTests(unittest.TestCase):
    def test_documented_example_is_valid_and_preserves_independent_fixture_expectations(self):
        example = tomllib.loads((ROOT / 'examples/equivalence-native-lifetimes.toml').read_text())
        configuration = policy.validate(example)
        self.assertEqual(configuration['adapters']['cpp']['profile'], life.OBJECT)
        fixture = configuration['fixtures'][0]
        self.assertEqual(fixture['lifetimes'], life.expectations([observation()], 'cpp'))
        selected = entry()
        generation.configure_fixture(selected, {}, fixture)
        self.assertEqual(generation.generation_case(selected, 0, [5])[life.EXPECTATIONS], fixture['lifetimes'])
        with self.assertRaisesRegex(ValueError, 'no selected profile'):
            life.require_expectations({life.EXPECTATIONS: []})

    def test_profiles_and_type_selection_are_explicit_and_round_trip(self):
        for language, kind, version in (('cpp', 'object', 4), ('c', 'resource', 5)):
            with self.subTest(language=language):
                value = entry(language)
                options = value['native_options']
                self.assertEqual(life.kind(value), kind)
                self.assertEqual(native_source.build_version(options), version)
                self.assertEqual(native_source.source_profile(options), 'resource-v1')
                self.assertEqual(policy.validate({'adapters': {language: options}})['adapters'][language], options)
                with self.assertRaises(ValueError):
                    native_source.configure({**value, 'language': 'c' if language == 'cpp' else 'cpp'}, options)
        for change in ({}, {'include': []}, {'include': ['Item'], 'max_live': True},
                       {'include': ['Item'], 'max_live': 0}, {'include': ['Item'], 'unknown': 1},
                       {'include': [None]}, {'include': ['bad\0name']}):
            with self.subTest(change=change), self.assertRaises(ValueError):
                native_source.settings({'backend': 'prepared', 'profile': life.OBJECT, 'lifetimes': change})
        for value in ({'lifetimes': {'include': ['Item']}},
                      {'backend': 'prepared', 'lifetimes': {'include': ['Item']}},
                      {'backend': 'prepared', 'profile': life.OBJECT}):
            with self.subTest(value=value), self.assertRaises(ValueError):
                native_source.settings(value)

    def test_completed_censored_and_zero_expectations_are_closed_and_copied(self):
        for language in ('c', 'cpp'):
            value = observation(language)
            parsed = life.expectations([value], language)
            self.assertEqual(life.expectations(parsed, language), parsed)
            parsed[0]['creation_path'].append(3)
            self.assertEqual(value['creation_path'], [0])
            censored = {'type': 'Item', 'creation_path': [0], 'complete': False}
            self.assertIsNone(life.expectations([censored], language)[0]['release_path'])
            self.assertEqual(life.expectations([], language), [])
        original = observation()
        for changes in ({'type': ''}, {'type': 'bad\0name'}, {'complete': 1}, {'creation_path': [False]},
                        {'creation_path': [1]}, {'creation_path': []}, {'creation_path': [0] * 65},
                        {'creation_path': [0, life.native_telemetry.MAX_SPANS]},
                        {'release_path': None}, {'exception_exit': None}, {'unknown': 1}):
            with self.subTest(changes=changes), self.assertRaises(ValueError):
                life.expectations([{**original, **changes}], 'cpp')
        for language, value in (('python', []), ('cpp', None), ('c', [original]),
                                ('cpp', [{'type': 'Item', 'creation_path': [0], 'complete': False,
                                          'release_path': [0]}])):
            with self.subTest(language=language, value=value), self.assertRaises(ValueError):
                life.expectations(value, language)
        with patch.object(life, 'MAX_OBSERVATIONS', 0), self.assertRaises(ValueError):
            life.expectations([original], 'cpp')

    def test_policy_fixtures_retain_expectations_and_refuse_other_callable_modes(self):
        raw = {'language': 'cpp', 'source': 'src/**', 'function': 'work(int)',
               'cases': [[2]], 'lifetimes': [observation()]}
        parsed = policy.fixture(raw, 0)
        self.assertEqual(policy.fixture(parsed, 0), parsed)
        for changes in ({'language': None}, {'language': 'rust'},
                        {'receiver': {'factory': 'Item', 'arguments': []}}, {'sequence': {}}):
            with self.subTest(changes=changes), self.assertRaises(ValueError):
                policy.fixture({**raw, **changes}, 0)
        selected = entry()
        generation.configure_fixture(selected, {}, parsed)
        self.assertEqual(selected[life.EXPECTATIONS], parsed['lifetimes'])
        case = generation.generation_case(selected, 0, [2])
        selected[life.EXPECTATIONS][0]['creation_path'].append(9)
        self.assertEqual(case[life.EXPECTATIONS][0]['creation_path'], [0])
        ordinary = {**entry(), 'native_options': {'profile': 'native-owned-v1'}}
        generation.configure_fixture(ordinary, {}, parsed)
        self.assertIn('explicit native lifetime profile', ordinary['reason'])

    def test_missing_expectations_and_unbound_sources_cannot_become_ready_policy(self):
        selected = entry()
        with self.assertRaisesRegex(ValueError, 'requires declared'):
            native_source.configuration(selected, 'http://127.0.0.1:4318', 'service')
        life.bind(selected, [])
        with self.assertRaises(ValueError):
            native_source.configuration(selected, 'http://127.0.0.1:4318', 'service')
        profile = {'local_inputs': {'src/work.cpp': 'hash', 'include/item.h': 'hash', 'unused.txt': 'hash'}}
        life.bind_sources(selected, profile, {'include': ['**'], 'exclude': ['*.txt']}, policy.selected)
        configured = native_source.configuration(selected, 'http://127.0.0.1:4318', 'service')
        self.assertTrue(configured['lifetimes']['enabled'])
        self.assertEqual(configured['sources'], {'include': ['include/item.h', 'src/work.cpp'], 'exclude': []})
        self.assertEqual(configured['functions']['include'], ['work(int)'])
        self.assertEqual(configured['resource']['service_name'], 'service')
        configured['sources']['include'].clear()
        self.assertEqual(len(selected[life.SOURCES]['include']), 2)
        with self.assertRaises(ValueError):
            life.bind_sources(selected, profile, {'include': ['include/**'], 'exclude': []}, policy.selected)
        with self.assertRaises(ValueError):
            life.source_selection({'local_inputs': {'src/bad*.cpp': 'hash'}},
                                  {'include': ['**'], 'exclude': []}, policy.selected)

    def test_inventory_readiness_refuses_absent_declarations_and_accepts_explicit_zero(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary).resolve()
            selected = {**entry('c'), 'name': 'work', 'output': 'int', 'globals': [], 'input_cases': [[5]]}
            path = root / selected['path']; path.parent.mkdir()
            path.write_text('int work(int value){return value;}\n')
            self.assertEqual(generation.qualify_entry(selected, root, 1), 'blocked')
            self.assertIn('requires declared fixture observations', selected['reason'])
            selected['reason'] = ''
            life.bind(selected, [])
            self.assertEqual(generation.qualify_entry(selected, root, 1), 'ready')

    def test_names_resolve_only_from_earlier_caller_semantics_and_remain_immutable(self):
        for kind, language in (('object', 'cpp'), ('resource', 'c')):
            with self.subTest(kind=kind), tempfile.TemporaryDirectory() as temporary:
                intent = native_lifetime_fixture.build(Path(temporary).resolve(), kind=kind)
                values = [observation(language)]
                resolved = life.resolve(intent, values)
                self.assertEqual(resolved[0].type_usr, 'c:@S@Item')
                values[0]['creation_path'].append(8)
                self.assertEqual(resolved[0].creation_path, (0,))
                with self.assertRaisesRegex(ValueError, 'absent or ambiguous'):
                    life.resolve(intent, [{**observation(language), 'type': 'unknown'}])
                name, raw = intent.semantics[0]
                value = life.capture.strict_json(raw)
                value['types'].append({**value['types'][0], 'usr': 'another:Item'})
                ambiguous = replace(intent, semantics=((name, life.encoded(value)), *intent.semantics[1:]))
                with self.assertRaisesRegex(ValueError, 'absent or ambiguous'):
                    life.resolve(ambiguous, [observation(language)])
        with self.assertRaises(ValueError):
            life.resolve(object(), [])

    def test_same_name_in_another_selected_source_blocks_before_sdk_build(self):
        selected = {**entry('c'), 'target': 'application', 'source_offset': 4, 'symbol': 'work'}
        selected[life.SOURCES] = {'include': ['src/work.c', 'src/other.c', 'include/item.h'], 'exclude': []}
        function = {'name': 'work', 'source_file': 'src/work.c', 'source_offset': 4, 'symbol': 'work'}
        original = {'target': 'application', 'function': function}
        life.unique_target(selected, [original, original], generation.entry_identity)
        other = {'target': 'application', 'function': {**function, 'source_file': 'src/other.c', 'symbol': 'local_work'}}
        with self.assertRaisesRegex(ValueError, 'ambiguous across selected source'):
            life.unique_target(selected, [original, other], generation.entry_identity)
        life.unique_target(selected, [original, {**other, 'target': 'other'}], generation.entry_identity)
        life.unique_target(selected, [original, {**other, 'function': {**other['function'], 'source_file': 'unused.c'}}],
                           generation.entry_identity)
        life.unique_target(selected, [original, {**other, 'function': {**other['function'], 'name': 'unselected'}}],
                           generation.entry_identity)
        life.unique_target({'native_backend': 'legacy'}, [], generation.entry_identity)

    def test_public_profiles_negotiate_their_descriptor_and_recheck_retained_source_selection(self):
        for language, version in (('cpp', 4), ('c', 5)):
            with self.subTest(language=language), tempfile.TemporaryDirectory() as temporary:
                root = Path(temporary).resolve()
                selected = entry(language)
                selected.update(status='ready', native_context={'language': language})
                life.bind(selected, [])
                profile = {'local_inputs': {selected['path']: 'hash', 'include/item.h': 'hash'}}
                selection = {'include': ['**'], 'exclude': []}
                life.bind_sources(selected, profile, selection, policy.selected)
                tools = {'python-host': root / 'python'}
                execute = Mock(return_value=subprocess.CompletedProcess([], 0, json.dumps(descriptor(version)).encode(), b''))
                with patch.object(native_source, 'sdk'):
                    native_source.negotiate(generation, root, root, language, tools, selected['native_options'], execute)
                self.assertEqual(execute.call_args.args[0][-2:], ['--build-version', str(version)])
                data = {'inventory': [selected], 'native_projects': {language: profile}, 'otelc_root': str(root),
                    'tools': {language: {name: str(path) for name, path in tools.items()}},
                    'configuration': {'adapters': {language: selected['native_options']}, 'sources': selection},
                    'native_provider_manifest': generation.manifest(root / native_source.DIRECTORY)}
                native_source.verify_probes(generation, root, data)
                for field in (life.EXPECTATIONS, life.SOURCES):
                    changed = copy.deepcopy(data); changed['inventory'][0].pop(field)
                    with self.subTest(field=field), self.assertRaises(ValueError):
                        native_source.verify_probes(generation, root, changed)
                changed = copy.deepcopy(data)
                changed['inventory'][0][life.SOURCES]['include'].append('unselected.h')
                with self.assertRaisesRegex(ValueError, 'source selection differs'):
                    native_source.verify_probes(generation, root, changed)

    def test_pass_helper_abi_and_symbol_tool_inputs_are_bound_before_metadata(self):
        for kind, language in (('object', 'cpp'), ('resource', 'c')):
            with self.subTest(kind=kind), tempfile.TemporaryDirectory() as temporary:
                intent = native_lifetime_fixture.build(Path(temporary).resolve(), kind=kind)
                sdk = intent.base.sdk
                producer = sdk.root / 'otelc'; producer.mkdir()
                for name in native_prepared.REQUIRED:
                    (producer / name).write_text('literal producer ' + name)
                options = {**entry(language)['native_options'], 'sdk_build': str(sdk.directory)}
                tools = {'cmake': sdk.cmake.path, 'ninja': sdk.ninja.path, 'llvm-config': sdk.toolchain.config.path,
                         'clang': sdk.toolchain.directory / 'clang', 'clang++': sdk.toolchain.directory / 'clang++'}
                if kind == 'resource':
                    nm = sdk.toolchain.directory / 'llvm-nm'
                    actual = nm.with_name('symbol-tool'); nm.rename(actual); nm.symlink_to(actual)
                with patch.object(native_source.sys, 'platform', 'linux'):
                    expected = native_source.artefacts(sdk.root, language, tools, options)
                    names = set(expected['files'])
                    self.assertIn(str(intent.tool.source.path), names)
                    self.assertIn(str(sdk.root / 'native/llvm/resource_abi.h'), names)
                    self.assertIn(str(sdk.root / 'native/llvm/object_abi.h'), names)
                    self.assertIn(str(sdk.root / 'native/llvm' / ('ObjectPass.cpp' if kind == 'object' else 'ResourcePass.cpp')), names)
                    if kind == 'resource':
                        self.assertIn(str(nm), names)
                        self.assertEqual(expected['files'][str(nm)]['identity']['resolved_path'], str(actual))
                    native_source.stable(sdk.root, language, tools, options, expected)
                    intent.tool.source.path.write_bytes(intent.tool.source.path.read_bytes())
                    with self.assertRaises(ValueError):
                        native_source.stable(sdk.root, language, tools, options, expected)
                with patch.object(native_source.native_toolchain, 'capture', return_value=sdk.toolchain), \
                        patch.object(native_source.native_sdk, 'capture', return_value=sdk) as capture_sdk:
                    native_source.sdk(sdk.root, language, tools, options, sdk.root, Mock())
                self.assertEqual(capture_sdk.call_args.kwargs['source_profile'], 'resource-v1')


if __name__ == '__main__':
    unittest.main()
