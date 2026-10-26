"""Rehashed compiler inventories cannot replace independent Rust source intent."""

import copy
from dataclasses import replace
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[1]
sys.path[:0] = [str(ROOT / 'adapters/generation'), str(ROOT / 'examples')]
import native_inputs
import rust_inventory as inventory
import rust_lifetimes
from rust_inventory_fixture import Fixture


class RustInventoryTests(unittest.TestCase):
    def setUp(self) -> None:
        temporary = tempfile.TemporaryDirectory()
        self.addCleanup(temporary.cleanup)
        self.fixture = Fixture(Path(temporary.name).resolve())

    def test_literal_inspection_and_weave_are_closed_fresh_and_compiler_free(self) -> None:
        f = self.fixture
        with patch.object(subprocess, 'Popen', side_effect=AssertionError('must not execute')):
            for mode in ('inspect', 'weave'):
                value = f.inspect | {'mode': mode}
                f.write(mode + '-inventory.json', value)
                record = inventory.read_functions(f.output, f.sources, mode)
                self.assertEqual(record.value(), value)
                record.value()['definitions'].clear()
                self.assertEqual(len(record.value()['definitions']), 1)
                record.verify()

    def test_closed_inventory_fields_versions_sources_and_order_refuse(self) -> None:
        f = self.fixture
        for key, changed in [('schema_version', True), ('kind', 'foreign'), ('mode', 'weave'),
                             ('sources', {}), ('source_complete', 0), ('definitions', {}), ('extra', False)]:
            with self.subTest(key=key), self.assertRaises(ValueError):
                inventory.function_document(f.inspect | {key: changed}, f.sources, 'inspect')
        for key in f.inspect:
            with self.subTest(missing=key), self.assertRaises(ValueError):
                inventory.function_document({k: v for k, v in f.inspect.items() if k != key}, f.sources, 'inspect')
        second = f.declaration(f.main, 'otelc_app::another')
        for definitions in ([f.function, f.function], [f.function, second]):
            with self.subTest(definitions=definitions), self.assertRaises(ValueError):
                inventory.function_document(f.inspect | {'definitions': definitions}, f.sources, 'inspect')

    def test_all_declaration_fields_and_original_byte_ranges_are_checked(self) -> None:
        f = self.fixture
        for key, changed in [('identity', 'wrong'), ('file', str(f.output / 'never-read.rs')),
                             ('compiler_name', ''), ('asynchronous', 0), ('expanded', 1),
                             ('start', True), ('end', 24.0), ('start', 25), ('end', 9999), ('extra', False)]:
            value = copy.deepcopy(f.inspect)
            value['definitions'][0][key] = changed
            with self.subTest(key=key, changed=changed), self.assertRaises(ValueError):
                inventory.function_document(value, f.sources, 'inspect')
        for key in f.function:
            value = copy.deepcopy(f.inspect)
            del value['definitions'][0][key]
            with self.subTest(missing=key), self.assertRaises(ValueError):
                inventory.function_document(value, f.sources, 'inspect')
        # Ordinary function declarations retain the SDK's allowed empty range;
        # a lifetime body/type requires the separate nonempty source range.
        value = copy.deepcopy(f.inspect)
        value['definitions'][0]['end'] = 0
        inventory.function_document(value, f.sources, 'inspect')

    def test_source_paths_are_caller_owned_and_original_facts_cannot_be_repaired(self) -> None:
        f = self.fixture
        expected = f.sources.hashes()
        expected.clear()
        self.assertEqual(len(f.sources.hashes()), 2)
        with self.assertRaises(ValueError):
            replace(f.sources, files=tuple(reversed(f.sources.files))).verify()
        with self.assertRaises(ValueError):
            inventory.capture_sources(f.project, (f.main, f.main))
        with self.assertRaises(ValueError):
            inventory.capture_sources(f.project, (f.output / 'never-read.rs',))
        with self.assertRaises(ValueError):
            inventory.capture_sources(f.project, (f.project / 'Cargo.toml',))
        original = f.main.read_bytes()
        f.main.write_bytes(original + b' changed')
        with self.assertRaises(ValueError):
            inventory.function_document(f.inspect, f.sources, 'inspect')
        f.main.write_bytes(original)
        with self.assertRaises(ValueError):
            f.sources.verify()

    def test_linked_source_and_changed_fixed_record_refuse(self) -> None:
        f = self.fixture
        path = f.write('inspect-inventory.json', f.inspect)
        record = inventory.read_functions(f.output, f.sources, 'inspect')
        original = path.read_bytes()
        path.write_bytes(original + b' ')
        with self.assertRaises(ValueError):
            record.verify()
        path.unlink()
        path.symlink_to(f.main)
        with self.assertRaises(ValueError):
            inventory.read_functions(f.output, f.sources, 'inspect')
        alias = f.project / 'alias.rs'
        alias.symlink_to(f.main)
        with self.assertRaises(ValueError):
            inventory.capture_sources(f.project, (alias,))

    def test_selection_uses_literal_brackets_paths_and_exclusion_precedence(self) -> None:
        f = self.fixture
        self.assertEqual(inventory.selected_functions(f.policy, f.sources, f.inspect), [f.function['identity']])
        for changed in ({'sources': {'include': ['**/*.rs'], 'exclude': ['**/main.rs']}},
                        {'functions': {'include': ['otelc_app::*'], 'exclude': ['*run']}}):
            self.assertEqual(inventory.selected_functions(f.policy | changed, f.sources, f.inspect), [])
        row = f.declaration(f.main, 'otelc_app::array[0]')
        value = f.inspect | {'definitions': [row]}
        policy = f.policy | {'functions': {'include': ['otelc_app::array[0]'], 'exclude': []}}
        self.assertEqual(inventory.selected_functions(policy, f.sources, value), [row['identity']])
        policy['functions']['include'] = ['otelc_app::array0']
        self.assertEqual(inventory.selected_functions(policy, f.sources, value), [])
        for bad in ({}, {'include': (), 'exclude': []}, {'include': [''], 'exclude': []},
                    {'include': ['*'], 'exclude': [], 'extra': False}):
            with self.subTest(bad=bad), self.assertRaises(ValueError):
                inventory.patterns(bad)

    def test_unsupported_selected_bodies_refuse_and_excluded_bodies_stay_in_inventory(self) -> None:
        f = self.fixture
        for changed in ({'asynchronous': True}, {'expanded': True},
                        {'compiler_name': 'otelc_app::{closure#0}'}, {'compiler_name': 'x' * 4097}):
            row = f.function | changed
            row['identity'] = 'main.rs::' + row['compiler_name']
            value = f.inspect | {'definitions': [row]}
            policy = f.policy | {'functions': {'include': ['*'], 'exclude': []}}
            with self.subTest(changed=changed), self.assertRaises(ValueError):
                inventory.selected_functions(policy, f.sources, value)
            policy['functions']['exclude'] = ['*']
            self.assertEqual(inventory.selected_functions(policy, f.sources, value), [])

    def test_woven_drop_bindings_require_complete_original_body_fingerprints(self) -> None:
        f = self.fixture
        request = rust_lifetimes.request(f.lifetime, f.sources, f.policy, target=f.target)
        value = f.inspect | request | {'kind': 'otelc.rust.lifetime-weave', 'mode': 'lifetime-weave',
                                       'instrumentation_complete': False}
        inventory.function_document(value, f.sources, 'lifetime-weave', lifetime_request=request)
        for key, changed in [('lifetimes', {}), ('lifetime_bodies', {}), ('instrumentation_complete', True)]:
            with self.subTest(key=key), self.assertRaises(ValueError):
                inventory.function_document(value | {key: changed}, f.sources, 'lifetime-weave', lifetime_request=request)
        for changed in ({'schema_version': True}, {'lifetime_bodies': {}},
                        {'lifetimes': {f.function['identity']: {'01': 'type'}}},
                        {'lifetime_bodies': {f.function['identity']: 'not-a-digest'}}):
            with self.subTest(changed=changed), self.assertRaises(ValueError):
                inventory.bindings(request | changed)
        with self.assertRaises(ValueError):
            inventory.function_document(f.inspect, f.sources, 'inspect', lifetime_request=request)
        with self.assertRaises(ValueError):
            inventory.read_functions(f.output, f.sources, '../redirect')
        with self.assertRaises(ValueError):
            inventory.function_document(f.inspect, None, 'inspect')


if __name__ == '__main__':
    unittest.main()
