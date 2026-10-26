"""Rust lifetime selection retains unavailable values and complete original MIR."""

import copy
import hashlib
import json
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[1]
sys.path[:0] = [str(ROOT / 'adapters/generation'), str(ROOT / 'examples')]
import rust_lifetimes as lifetimes
from rust_inventory_fixture import Fixture


class RustLifetimeInventoryTests(unittest.TestCase):
    def setUp(self) -> None:
        temporary = tempfile.TemporaryDirectory()
        self.addCleanup(temporary.cleanup)
        self.fixture = Fixture(Path(temporary.name).resolve())

    def parse(self, value: dict) -> dict:
        f = self.fixture
        return lifetimes.document(value, f.sources, target=f.target)

    def request(self, value: dict | None = None, policy: dict | None = None) -> dict:
        f = self.fixture
        return lifetimes.request(f.lifetime if value is None else value, f.sources,
                                 f.policy if policy is None else policy, target=f.target)

    def test_literal_v2_record_is_compiler_free_and_keeps_original_record_facts(self) -> None:
        f = self.fixture
        path = f.write('lifetime-inspect-inventory.json', f.lifetime)
        with patch.object(subprocess, 'Popen', side_effect=AssertionError('must not execute')):
            record = lifetimes.read(f.output, f.sources, target=f.target)
            self.assertEqual(record.value(), f.lifetime)
            record.verify()
        result = self.parse(f.lifetime)
        result['bodies'].clear()
        self.assertEqual(len(self.parse(f.lifetime)['bodies']), 1)
        path.write_text(path.read_text() + ' ')
        with self.assertRaises(ValueError):
            record.verify()

    def test_complete_unfiltered_body_hash_matches_utf8_wire_encoding(self) -> None:
        f = self.fixture
        request = self.request()
        raw = json.dumps(f.body, sort_keys=True, separators=(',', ':'), ensure_ascii=False).encode()
        expected = hashlib.sha256(raw).hexdigest()
        self.assertEqual(request, {'schema_version': 2,
            'lifetimes': {f.function['identity']: {'2': f.type_source['compiler_name']}},
            'lifetime_bodies': {f.function['identity']: expected}})
        self.assertNotEqual(expected, hashlib.sha256(json.dumps(f.body, sort_keys=True, separators=(',', ':')).encode()).hexdigest())
        changed = copy.deepcopy(f.lifetime)
        changed['bodies'][0]['sites'][1]['cleanup'] = True
        self.assertEqual(self.request(changed)['lifetimes'], request['lifetimes'])
        self.assertNotEqual(self.request(changed)['lifetime_bodies'], request['lifetime_bodies'])

    def test_every_closed_header_field_and_selected_target_is_checked(self) -> None:
        f = self.fixture
        for key, changed in [('schema_version', True), ('schema_version', 1), ('kind', 'foreign'),
                             ('sources', {}), ('target', 'wrong-host'), ('pointer_width', 64.0),
                             ('source_complete', 0), ('instrumentation_complete', True),
                             ('bodies', {}), ('skipped', {}), ('extra', False)]:
            with self.subTest(key=key, changed=changed), self.assertRaises(ValueError):
                self.parse(f.lifetime | {key: changed})
        for key in f.lifetime:
            with self.subTest(missing=key), self.assertRaises(ValueError):
                self.parse({k: v for k, v in f.lifetime.items() if k != key})
        with self.assertRaises(ValueError):
            lifetimes.document(f.lifetime, f.sources, target=True)

    def test_all_body_metadata_is_validated_before_selection(self) -> None:
        f = self.fixture
        changes = [('phase', 'Built'), ('local_count', True), ('block_count', 0),
                   ('argument_count', 4), ('locals', {}), ('unavailable_locals', {}), ('sites', {}),
                   ('extra', None), ('function', f.function | {'asynchronous': True}),
                   ('function', f.function | {'expanded': True}), ('function', f.function | {'end': 0})]
        policy = f.policy | {'lifetimes': {'enabled': False, 'include': [], 'exclude': []}}
        for key, changed in changes:
            value = copy.deepcopy(f.lifetime)
            value['bodies'][0][key] = changed
            with self.subTest(key=key, changed=changed), self.assertRaises(ValueError):
                self.request(value, policy)
        value = f.lifetime | {'bodies': [f.body, f.body]}
        with self.assertRaises(ValueError):
            self.parse(value)

    def test_type_role_layout_and_original_declaration_are_checked(self) -> None:
        f = self.fixture
        changes = [('local', True), ('role', 'argument'), ('kind', 'array'), ('needs_drop', 1),
                   ('rendered_type', ''), ('compiler_type', 'wrong'), ('size', -1),
                   ('alignment', 0), ('alignment', 3), ('alignment', True),
                   ('layout_error', ''), ('layout_error', 'unavailable'), ('extra', False)]
        for key, changed in changes:
            value = copy.deepcopy(f.lifetime)
            value['bodies'][0]['locals'][0][key] = changed
            with self.subTest(key=key, changed=changed), self.assertRaises(ValueError):
                self.parse(value)
        for key in f.body['locals'][0]:
            value = copy.deepcopy(f.lifetime)
            del value['bodies'][0]['locals'][0][key]
            with self.subTest(missing=key), self.assertRaises(ValueError):
                self.parse(value)
        value = copy.deepcopy(f.lifetime)
        value['bodies'][0]['locals'].append(copy.deepcopy(value['bodies'][0]['locals'][0]))
        with self.assertRaises(ValueError):
            self.parse(value)

    def test_argument_return_and_unavailable_layout_shapes_are_not_silently_dropped(self) -> None:
        f = self.fixture
        value = copy.deepcopy(f.lifetime)
        original = value['bodies'][0]['locals'][0]
        value['bodies'][0]['locals'] += [original | {'local': 0, 'role': 'return'},
                                       original | {'local': 1, 'role': 'argument', 'layout_error': 'unavailable',
                                                   'size': None, 'alignment': None}]
        self.assertEqual(set(self.request(value)['lifetimes'][f.function['identity']]), {'0', '1', '2'})
        # These remain requests for the compiler to accept or explicitly refuse;
        # metadata selection does not claim support for argument/return weaving.

    def test_ownership_site_kinds_indices_flags_and_unwind_are_checked(self) -> None:
        f = self.fixture
        for kind in lifetimes.SITE_KINDS:
            value = copy.deepcopy(f.lifetime)
            value['bodies'][0]['sites'] = [f.body['sites'][0] | {
                'kind': kind, 'other': 3, 'unwind': 'Continue' if kind == 'drop' else None}]
            self.parse(value)
        for key, changed in [('kind', 'foreign'), ('local', 3), ('local', True), ('block', 3),
                             ('statement', -1), ('other', 4), ('projected', 0), ('cleanup', 1),
                             ('unwind', 'Continue'), ('extra', False)]:
            value = copy.deepcopy(f.lifetime)
            value['bodies'][0]['sites'][0][key] = changed
            with self.subTest(key=key, changed=changed), self.assertRaises(ValueError):
                self.parse(value)
        value = copy.deepcopy(f.lifetime)
        value['bodies'][0]['sites'][1]['unwind'] = None
        with self.assertRaises(ValueError):
            self.parse(value)

    def test_selected_unavailable_types_refuse_and_explicit_exclusions_apply_to_both_names(self) -> None:
        f = self.fixture
        value = copy.deepcopy(f.lifetime)
        value['bodies'][0]['unavailable_locals'] = [f.unavailable()]
        policy = f.policy | {'lifetimes': {'enabled': True, 'include': ['*'], 'exclude': []}}
        with self.assertRaisesRegex(ValueError, 'unavailable'):
            self.request(value, policy)
        for name in ('foreign::Value', 'foreign::Value<Wrapper>'):
            selected = policy | {'lifetimes': policy['lifetimes'] | {'exclude': [name]}}
            result = self.request(value, selected)
            self.assertEqual(result['lifetimes'], self.request()['lifetimes'])
            self.assertNotEqual(result['lifetime_bodies'], self.request()['lifetime_bodies'])
        self.assertEqual(self.request(value, f.policy | {
            'lifetimes': {'enabled': False, 'include': ['*'], 'exclude': []}})['lifetimes'], {})

    def test_unavailable_locals_are_closed_unique_and_disjoint_from_source_bound_types(self) -> None:
        f = self.fixture
        for kind in ('foreign_adt', 'array', 'tuple', 'opaque'):
            value = copy.deepcopy(f.lifetime)
            value['bodies'][0]['unavailable_locals'] = [f.unavailable() | {'kind': kind}]
            self.parse(value)
        for key, changed in [('local', True), ('local', 0), ('role', 'return'), ('needs_drop', 1),
                             ('kind', 'struct'), ('compiler_type', ''), ('rendered_type', ''), ('extra', False)]:
            value = copy.deepcopy(f.lifetime)
            value['bodies'][0]['unavailable_locals'] = [f.unavailable() | {key: changed}]
            with self.subTest(key=key, changed=changed), self.assertRaises(ValueError):
                self.parse(value)
        for rows in ([f.unavailable(), f.unavailable()], [f.unavailable(local=2)]):
            value = copy.deepcopy(f.lifetime)
            value['bodies'][0]['unavailable_locals'] = rows
            with self.assertRaises(ValueError):
                self.parse(value)

    def test_skipped_bodies_are_explicit_unique_and_never_replace_original_bodies(self) -> None:
        f = self.fixture
        skipped = f.declaration(f.main, 'otelc_app::other')
        for reason in ('const', 'async', 'closure', 'expanded'):
            self.parse(f.lifetime | {'skipped': [{'function': skipped, 'reason': reason}]})
        for rows in ([{'function': skipped, 'reason': 'unknown'}],
                     [{'function': f.function, 'reason': 'const'}],
                     [{'function': skipped, 'reason': 'const'}] * 2,
                     [{'function': skipped, 'reason': 'const', 'extra': False}]):
            with self.subTest(rows=rows), self.assertRaises(ValueError):
                self.parse(f.lifetime | {'skipped': rows})

    def test_selection_flags_source_patterns_and_original_source_mutation_stay_visible(self) -> None:
        f = self.fixture
        self.assertEqual(self.request(policy=f.policy | {
            'sources': {'include': ['*.rs'], 'exclude': ['main.rs']}})['lifetimes'], {})
        for flag in (0, None, 'true'):
            with self.subTest(flag=flag), self.assertRaises(ValueError):
                self.request(policy=f.policy | {'lifetimes': f.policy['lifetimes'] | {'enabled': flag}})
        original = f.types.read_bytes()
        f.types.write_bytes(original + b' changed')
        with self.assertRaises(ValueError):
            self.parse(f.lifetime)
        f.types.write_bytes(original)
        with self.assertRaises(ValueError):
            self.parse(f.lifetime)


if __name__ == '__main__':
    unittest.main()
