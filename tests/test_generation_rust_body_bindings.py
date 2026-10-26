"""Original Rust body owners cannot disappear behind equal producer records."""

import copy
from pathlib import Path
import sys
import tempfile
import unittest

ROOT = Path(__file__).resolve().parents[1]
sys.path[:0] = [str(ROOT / 'adapters/generation'), str(ROOT / 'examples')]
import native_inputs
import rust_body_bindings as bindings
import rust_inventory_fixture


def document(fixture):
    """Author one independent literal original body, without running Rust."""
    return {'schema_version': 1, 'kind': 'otelc.rust.body-bindings', 'mode': 'binding-inspect',
        'crate_name': 'otelc_app', 'algorithm': 'rustc-1.98.1-stablehash-128-v1',
        'byte_coordinates': 'original-utf8', 'sources': fixture.sources.hashes(),
        'original_body_count': 1, 'helper_exclusions': [],
        'source_complete': False, 'semantic_complete': False,
        'bodies': [{'function': copy.deepcopy(fixture.function), 'diagnostic_def_index': 7,
            'eligible': True, 'reason': None, 'fingerprints': {'phase': 'Runtime(PostCleanup)',
                'pre_optimization_mir': 'a' * 32, 'typeck': 'b' * 32}}]}


class RustBodyBindingTests(unittest.TestCase):
    def setUp(self):
        temporary = tempfile.TemporaryDirectory()
        self.addCleanup(temporary.cleanup)
        self.base = Path(temporary.name).resolve()
        self.fixture = rust_inventory_fixture.Fixture(self.base)
        self.value = document(self.fixture)

    def check(self, value=None, functions=None):
        return bindings.document(self.value if value is None else value, self.fixture.sources,
            crate_name='otelc_app', functions=self.fixture.inspect if functions is None else functions)

    def test_complete_record_fresh_views_and_diagnostic_index_exclusion(self):
        self.assertEqual(self.check(), self.value)
        changed = copy.deepcopy(self.value)
        changed['bodies'][0]['diagnostic_def_index'] = 99
        options = {'crate_name': 'otelc_app', 'functions': self.fixture.inspect}
        self.assertEqual(bindings.comparison(changed, self.fixture.sources, **options),
                         bindings.comparison(self.value, self.fixture.sources, **options))
        output = self.fixture.output / 'binding-inspect-inventory.json'
        output.write_text(bindings.encoded(self.value))
        held = bindings.read(self.fixture.output, self.fixture.sources, **options)
        held.value()['bodies'].clear()
        self.assertEqual(len(held.value()['bodies']), 1)

    def test_closed_header_versions_denominators_and_algorithm(self):
        for key, value in [('schema_version', True), ('kind', 'other'), ('mode', 'weave'),
                ('crate_name', 'foreign'), ('algorithm', 'sha256'), ('byte_coordinates', 'chars'),
                ('sources', {}), ('original_body_count', True), ('original_body_count', 0),
                ('helper_exclusions', ['new-helper']), ('helper_exclusions', ()),
                ('source_complete', 0), ('semantic_complete', True), ('bodies', ()), ('extra', 1)]:
            with self.subTest(key=key), self.assertRaises(ValueError):
                self.check(self.value | {key: value})
        for key in self.value:
            with self.subTest(missing=key), self.assertRaises(ValueError):
                self.check({name: value for name, value in self.value.items() if name != key})
        with self.assertRaises(ValueError):
            bindings.document(self.value, self.fixture.sources, crate_name='bad-name',
                              functions=self.fixture.inspect)

    def test_body_primitives_fingerprints_and_original_function_join(self):
        for key, value in [('diagnostic_def_index', True), ('diagnostic_def_index', -1),
                ('diagnostic_def_index', 2**32), ('eligible', 1), ('reason', 'foreign'),
                ('fingerprints', None), ('extra', 1)]:
            changed = copy.deepcopy(self.value)
            changed['bodies'][0][key] = value
            with self.subTest(key=key), self.assertRaises(ValueError):
                self.check(changed)
        for key, value in [('phase', ''), ('phase', 'x\0'), ('phase', 'x' * 257),
                ('pre_optimization_mir', 'a' * 64), ('typeck', 'B' * 32), ('typeck', True), ('extra', 1)]:
            changed = copy.deepcopy(self.value)
            changed['bodies'][0]['fingerprints'][key] = value
            with self.subTest(fingerprint=key), self.assertRaises(ValueError):
                self.check(changed)
        changed = copy.deepcopy(self.value)
        changed['bodies'][0]['function']['end'] -= 1
        with self.assertRaises(ValueError): self.check(changed)
        with self.assertRaises(ValueError):
            self.check(self.value | {'bodies': [], 'original_body_count': 0})

    def test_unavailable_owners_remain_visible_with_no_invented_fingerprints(self):
        for reason in ('expanded', 'asynchronous', 'body_kind', 'const_function'):
            changed = copy.deepcopy(self.value)
            body = changed['bodies'][0]
            body.update(eligible=False, reason=reason, fingerprints=None)
            body['function']['expanded'] = reason == 'expanded'
            body['function']['asynchronous'] = reason == 'asynchronous'
            functions = self.fixture.inspect | {'definitions': [copy.deepcopy(body['function'])]}
            self.assertEqual(self.check(changed, functions), changed)
            body['fingerprints'] = copy.deepcopy(self.value['bodies'][0]['fingerprints'])
            with self.assertRaises(ValueError): self.check(changed, functions)
        changed = copy.deepcopy(self.value)
        changed['bodies'][0]['function']['asynchronous'] = True
        with self.assertRaises(ValueError): self.check(changed)
        changed = copy.deepcopy(self.value)
        changed['bodies'][0]['function']['expanded'] = True
        with self.assertRaises(ValueError): self.check(changed)

    def test_extra_nonfunction_owner_is_retained_but_extra_eligible_owner_refuses(self):
        changed = copy.deepcopy(self.value)
        other = copy.deepcopy(changed['bodies'][0])
        other['function'].update(compiler_name='otelc_app::static',
                                identity='main.rs::otelc_app::static')
        other.update(eligible=False, reason='body_kind', fingerprints=None)
        changed['bodies'].append(other)
        changed['original_body_count'] = 2
        self.assertEqual(self.check(changed), changed)
        other.update(eligible=True, reason=None,
                     fingerprints=copy.deepcopy(self.value['bodies'][0]['fingerprints']))
        with self.assertRaises(ValueError): self.check(changed)
        changed['bodies'][1] = copy.deepcopy(changed['bodies'][0])
        with self.assertRaises(ValueError): self.check(changed)

    def test_original_utf8_and_restored_source_facts_remain_required(self):
        path = self.fixture.main
        original = path.read_bytes()
        path.write_bytes(original + b' changed')
        path.write_bytes(original)
        with self.assertRaises(ValueError): self.check()
        # A separate explicitly captured fixture proves physical UTF-8 offsets.
        folder = self.base / 'unicode'
        folder.mkdir()
        fixture = rust_inventory_fixture.Fixture(folder)
        fixture.main.write_bytes(b'\xef\xbb\xbffn run() {}\r\n')
        import rust_inventory
        fixture.sources = rust_inventory.capture_sources(fixture.project, (fixture.main, fixture.types))
        fixture.function.update(start=1, end=5)
        fixture.inspect.update(sources=fixture.sources.hashes(), definitions=[fixture.function])
        with self.assertRaisesRegex(ValueError, 'UTF-8'):
            bindings.document(document(fixture), fixture.sources,
                              crate_name='otelc_app', functions=fixture.inspect)
