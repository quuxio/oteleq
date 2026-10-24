"""Cache selection needs caller-owned consumed bytes and keeps compilation distinct."""

from dataclasses import replace
from pathlib import Path
import sys
import unittest
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[1]
sys.path[:0] = [str(ROOT / 'adapters/generation'), str(ROOT / 'examples')]
import python_origin as origin
import python_selection as selection
from test_generation_python_cache_origin import CACHE, cache_rows, cache_wire
from test_generation_python_origin import PID, VERSION, fixture, metadata
from test_generation_python_selection import expected


def cached(plain=False):
    rows = metadata(cache_rows(plain=plain), 1, 4, 2)
    rows.insert(0, (1, b'/tmp/caller.py', rows[0][2]))
    return origin.decode(cache_wire(rows), PID, version=3)


class PythonCacheSelectionTests(unittest.TestCase):
    def check(self, journal=None, *, plain=False, caches=None, chosen=None):
        return selection.verify(cached(plain) if journal is None else journal,
            (expected(),) if chosen is None else chosen, python_version=VERSION, optimisation=0, plain=plain,
            caches=(replace(expected().source, path=CACHE),) if caches is None else caches)

    def test_both_lanes_bind_actual_cache_input_and_selected_descendant_without_claiming_source_compilation(self):
        for plain in (False, True):
            with self.subTest(plain=plain):
                result, = self.check(plain=plain)
                match, = result.matches
                self.assertEqual((match.root, match.execution, match.member, match.sdk, match.binding),
                                 (77, 91, 9, None if plain else 1, 'cache-read'))
                changed_source = replace(expected(), source=replace(expected().source, content=b'current source may differ'))
                self.assertEqual(self.check(plain=plain, chosen=(changed_source,))[0].matches, result.matches)

    def test_cache_profile_can_observe_a_real_source_fallback_with_no_caches(self):
        for plain in (False, True):
            journal = origin.decode(cache_wire(fixture(plain=plain)), PID, version=3)
            result, = self.check(journal, plain=plain, caches=())
            self.assertEqual(result.matches[0].binding, 'source-compiler')

    def test_source_only_and_cache_contracts_cannot_be_substituted(self):
        with self.assertRaises(ValueError):
            selection.verify(cached(), (expected(),), python_version=VERSION, optimisation=0, plain=False)
        source = replace(cached(), schema_version=2)
        with self.assertRaises(ValueError):
            self.check(source)
        with self.assertRaises(ValueError):
            self.check(caches=())

    def test_cache_bytes_and_every_opened_file_fact_are_frozen_before_capture(self):
        source = replace(expected().source, path=CACHE)
        variants = {name: replace(source, **{name: value}) for name, value in {
            'path': b'/tmp/__pycache__/other.cpython-312.pyc', 'content': b'equal label different bytes',
            'device': 99, 'inode': 88, 'mtime_ns': 0, 'mode': source.mode ^ 0o040}.items()}
        for name, value in variants.items():
            with self.subTest(name=name), self.assertRaises(ValueError):
                self.check(caches=(value,))
        for value in ([source], (source, source), (replace(source, path=b'/tmp/entry.py'),), (None,)):
            with self.subTest(caches=value), self.assertRaises(ValueError):
                self.check(caches=value)

    def test_equal_foreign_cache_path_cannot_bind_a_different_source_filename(self):
        rows = metadata(cache_rows(), 1, 4, 2)
        foreign = b'/tmp/__pycache__/foreign.cpython-312.pyc'
        rows[0] = 3, foreign, rows[0][2]
        rows.insert(0, (1, b'/tmp/caller.py', rows[0][2]))
        journal = origin.decode(cache_wire(rows), PID, version=3)
        with self.assertRaises(ValueError):
            self.check(journal, caches=(replace(expected().source, path=foreign),))

    def test_unexecuted_cache_roots_also_need_their_own_frozen_input(self):
        rows = fixture()
        extra = metadata(metadata(metadata(cache_rows(plain=True), 1, 1, 78), 1, 2, 91), 1, 4, 6)
        journal = origin.decode(cache_wire([*rows, *extra[:2]]), PID, version=3)
        with self.assertRaises(ValueError):
            self.check(journal, caches=())
        self.assertEqual(self.check(journal)[0].matches[0].binding, 'source-compiler')

    def test_source_cache_name_rules_and_total_cache_budget_are_explicit(self):
        self.assertTrue(selection.cache_for_source(b'/app/foo.bar.py', b'/app/__pycache__/foo.bar.cpython-312.opt-2.pyc'))
        for name in (b'/app/__pycache__/foo.bar.cpython-312.pyc', b'/app/foo.cpython-312.pyc',
                     b'/app/__pycache__/foo..pyc', b'/app/__pycache__/foo.cpython-312.opt-.pyc'):
            with self.subTest(name=name):
                self.assertFalse(selection.cache_for_source(b'/app/foo.py', name))
        with patch.object(selection.inputs, 'MAX_BYTES', 1), self.assertRaises(ValueError):
            self.check(chosen=(replace(expected(), source=replace(expected().source, content=b'')),))
