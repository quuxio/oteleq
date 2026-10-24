"""Cache journals keep input bytes distinct from source compilation and admission."""

import copy
from dataclasses import replace
from pathlib import Path
import sys
import tempfile
import unittest
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[1]
sys.path[:0] = [str(ROOT / 'adapters/generation'), str(ROOT / 'examples')]
import python_origin as origin
import python_journal as inputs
from test_generation_python_origin import PID, PATH, fixture, metadata, wire

CACHE = b'/tmp/__pycache__/entry.cpython-312.pyc'


def cache_rows(*, plain: bool = False) -> list:
    rows = metadata(metadata(fixture(plain=plain, loader=True), 1, 5, 3), 1, 9, 3)
    kind, _, payload = rows[0]
    rows[0] = kind, CACHE, payload
    return rows


def cache_wire(rows: list) -> bytes:
    """Change only frame markers; raw payloads are independent fixture bytes."""
    data = bytearray(wire(rows))
    offset = 0
    while offset < len(data):
        _, _, _, _, _, path_size, size = inputs.HEADER.unpack_from(data, offset)
        data[offset:offset + 8] = origin.CACHE_MAGIC
        offset += inputs.HEADER.size + path_size + size
    return bytes(data)


class PythonCacheOriginTests(unittest.TestCase):
    def test_explicit_version_keeps_consumed_cache_and_executing_filename_distinct(self):
        for plain in (False, True):
            with self.subTest(plain=plain), patch('builtins.compile', side_effect=AssertionError('no compiler')):
                value = origin.decode(cache_wire(cache_rows(plain=plain)), PID, version=3)
            source, root, executed, *_ = value.records
            self.assertEqual(value.schema_version, 3)
            self.assertTrue(value.capture_complete)
            self.assertEqual(source.path, CACHE)
            self.assertEqual(root.descriptor.record.path, PATH)
            self.assertEqual((root.input_sequence, root.route, root.compiler_flags, root.optimisation), (1, 3, 0, 3))
            self.assertEqual((executed.root, executed.member, executed.path), (77, 9, PATH))
            self.assertEqual(value.comparison_steps > 0, not plain)

    def test_default_and_explicit_formats_refuse_downgrades_mixed_markers_and_invalid_versions(self):
        cached = cache_wire(cache_rows())
        with self.assertRaises(ValueError):
            origin.decode(cached, PID)
        with self.assertRaises(ValueError):
            origin.decode(wire(fixture()), PID, version=3)
        for version in (True, 1, 0, 4, '3', None):
            with self.subTest(version=version), self.assertRaises(ValueError):
                origin.decode(cached, PID, version=version)
        offset = inputs.HEADER.size + len(CACHE) + len(cache_rows()[0][2])
        with self.assertRaises(ValueError):
            origin.decode(cached[:offset] + origin.MAGIC + cached[offset + 8:], PID, version=3)
        for rows in (fixture(), fixture(loader=True)):
            self.assertTrue(origin.decode(cache_wire(rows), PID, version=3).capture_complete)

    def test_cache_route_requires_exact_roles_flags_unknown_optimisation_and_header_bytes(self):
        rows = cache_rows()
        for field, value in ((3, 0), (4, 0), (5, 4), (8, 1), (9, 0), (9, 1), (9, 2), (9, 4)):
            changed = metadata(rows, 1, field, value)
            with self.subTest(field=field, value=value), self.assertRaises(ValueError):
                origin.decode(cache_wire(changed), PID, version=3)
        for kind, path in ((1, CACHE), (3, PATH), (3, b'/tmp/cache.dat')):
            changed = copy.deepcopy(rows)
            changed[0] = kind, path, rows[0][2]
            with self.subTest(kind=kind, path=path), self.assertRaises(ValueError):
                origin.decode(cache_wire(changed), PID, version=3)
        for count in (0, 15):
            changed = metadata(rows, 0, 3, count)
            changed[0] = 3, CACHE, changed[0][2][:inputs.SOURCE.size] + b'x' * count
            with self.subTest(count=count), self.assertRaises(ValueError):
                origin.decode(cache_wire(changed), PID, version=3)
        with self.assertRaises(ValueError):
            origin.decode(wire(rows), PID)

    def test_private_cache_file_still_requires_owned_regular_metadata(self):
        with tempfile.TemporaryDirectory() as temporary:
            path = Path(temporary) / 'journal'
            path.write_bytes(cache_wire(cache_rows()))
            path.chmod(0o600)
            self.assertEqual(origin.read(path, PID, version=3).schema_version, 3)
            with self.assertRaises(ValueError):
                origin.read(path, PID)
            path.chmod(0o644)
            with self.assertRaises(ValueError):
                origin.read(path, PID, version=3)

    def test_source_only_selection_cannot_silently_admit_a_new_journal_contract(self):
        import python_selection
        from test_generation_python_selection import VERSION, expected

        value = origin.decode(cache_wire(fixture()), PID, version=3)
        for journal in (value, replace(value, schema_version=2.0), replace(value, schema_version=True)):
            with self.subTest(version=journal.schema_version), \
                    self.assertRaisesRegex(ValueError, 'source-only Python selection requires journal2'):
                python_selection.verify(journal, (expected(),), python_version=VERSION,
                                        optimisation=0, plain=False)
