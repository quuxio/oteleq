"""Original physical Rust module routes cannot be replaced by rehashed metadata."""

import copy
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[1]
sys.path[:0] = [str(ROOT / 'adapters/generation'), str(ROOT / 'examples')]
import rust_inventory
import rust_modules as modules


class RustModuleTests(unittest.TestCase):
    def setUp(self) -> None:
        temporary = tempfile.TemporaryDirectory()
        self.addCleanup(temporary.cleanup)
        self.base = Path(temporary.name).resolve()
        self.project, self.output = self.base / 'app', self.base / 'output'
        self.project.mkdir()
        self.output.mkdir()
        self.entry, self.external = self.project / 'main.rs', self.project / 'hidden.rs'
        self.entry.write_bytes('\ufeffmod caf\u00e9 {}\r\nmod hidden;\r\nfn main() {}\r\n'.encode())
        self.external.write_bytes(b'')
        self.sources = rust_inventory.capture_sources(self.project, (self.entry, self.external))
        root = self.location(self.entry, 3, self.entry.stat().st_size)
        inline = self.location(self.entry, 3, 15)
        external = self.location(self.entry, 17, 28)
        self.value = {'schema_version': 1, 'kind': 'otelc.rust.module-inventory',
                      'mode': 'module-inspect', 'crate_name': 'fixture',
                      'byte_coordinates': 'original-utf8', 'sources': self.sources.hashes(),
                      'source_complete': False, 'modules': [
                          self.row('', None, 'crate', root, root),
                          self.row('caf\u00e9', '', 'inline', inline, inline),
                          self.row('hidden', '', 'external', external, self.location(self.external, 0, 0))]}

    @staticmethod
    def location(path: Path, start: int, end: int) -> dict:
        return {'file': str(path), 'start': start, 'end': end, 'expanded': False}

    @staticmethod
    def row(name: str, parent: str | None, kind: str, declaration: dict, body: dict) -> dict:
        return {'compiler_name': name, 'parent': parent, 'kind': kind,
                'declaration': copy.deepcopy(declaration), 'body': copy.deepcopy(body),
                'eligible': True, 'reason': None}

    def check(self, value=None) -> dict:
        return modules.document(self.value if value is None else value, self.sources,
                                self.entry, crate_name='fixture')

    def test_physical_unicode_crlf_empty_module_and_fresh_values_need_no_compiler(self) -> None:
        with patch.object(subprocess, 'Popen', side_effect=AssertionError('must not execute')):
            result = self.check()
            self.assertEqual(result, self.value)
            result['modules'].clear()
            self.assertEqual(len(self.check()['modules']), 3)
            path = self.output / 'module-inventory.json'
            path.write_text(modules.encoded(self.value))
            record = modules.read(self.output, self.sources, self.entry, crate_name='fixture')
            self.assertEqual(record.value(), self.value)
            record.verify()

    def test_closed_header_caller_crate_entry_and_original_denominator_refuse(self) -> None:
        for field, value in [('schema_version', True), ('kind', 'foreign'), ('mode', 'inspect'),
                             ('crate_name', 'foreign'), ('byte_coordinates', 'characters'),
                             ('sources', {}), ('source_complete', 0), ('modules', []),
                             ('modules', ()), ('extra', True)]:
            with self.subTest(field=field), self.assertRaises(ValueError):
                self.check(self.value | {field: value})
        for field in self.value:
            with self.subTest(missing=field), self.assertRaises(ValueError):
                self.check({k: v for k, v in self.value.items() if k != field})
        for crate in ('', True, None, 'x\0', 'x' * 4097):
            with self.subTest(crate=crate), self.assertRaises(ValueError):
                modules.document(self.value, self.sources, self.entry, crate_name=crate)
        for sources, entry in ((None, self.entry), (self.sources, self.base / 'foreign.rs')):
            with self.assertRaises(ValueError):
                modules.document(self.value, sources, entry, crate_name='fixture')

    def test_module_fields_location_primitives_and_foreign_paths_refuse(self) -> None:
        for field, value in [('compiler_name', True), ('compiler_name', 'x' * 4097),
                             ('compiler_name', 'x\0'), ('kind', 'foreign'), ('eligible', 1),
                             ('reason', False), ('reason', 'foreign'), ('extra', 1)]:
            changed = copy.deepcopy(self.value)
            changed['modules'][1][field] = value
            with self.subTest(field=field), self.assertRaises(ValueError):
                self.check(changed)
        for field, value in [('file', str(self.output / 'never-read.rs')), ('start', True),
                             ('end', 15.0), ('start', -1), ('end', 1000), ('expanded', 0), ('extra', 1)]:
            changed = copy.deepcopy(self.value)
            changed['modules'][1]['body'][field] = value
            with self.subTest(location=field), self.assertRaises(ValueError):
                self.check(changed)

    def test_crate_relative_paths_parent_kinds_order_and_missing_roots_refuse(self) -> None:
        for kind in ('root-name', 'root-parent', 'root-file', 'wrong-kind', 'wrong-parent',
                     'no-ancestor', 'duplicate', 'order', 'missing-root', 'empty-child'):
            changed = copy.deepcopy(self.value)
            root, inline, external = changed['modules']
            if kind == 'root-name': root['compiler_name'] = 'fixture'
            elif kind == 'root-parent': root['parent'] = ''
            elif kind == 'root-file': root['body']['file'] = str(self.external)
            elif kind == 'wrong-kind': external['kind'] = 'inline'
            elif kind == 'wrong-parent': inline['parent'] = 'foreign'
            elif kind == 'no-ancestor':
                inline.update(compiler_name='absent::caf\u00e9', parent='absent')
                changed['modules'].sort(key=lambda r: r['compiler_name'])
            elif kind == 'duplicate': changed['modules'].append(copy.deepcopy(external))
            elif kind == 'order': changed['modules'].reverse()
            elif kind == 'missing-root': del changed['modules'][0]
            else: inline['compiler_name'] = ''
            with self.subTest(kind=kind), self.assertRaises(ValueError):
                self.check(changed)

    def test_expanded_and_block_routes_are_visible_and_inherited_but_never_eligible(self) -> None:
        for reason in ('expanded', 'block_module'):
            changed = copy.deepcopy(self.value)
            parent = changed['modules'][1]
            parent.update(eligible=False, reason=reason)
            if reason == 'expanded': parent['body']['expanded'] = True
            else: parent.update(compiler_name='function::caf\u00e9', parent='function')
            child = copy.deepcopy(parent)
            child.update(compiler_name=parent['compiler_name'] + '::nested', parent=parent['compiler_name'])
            child['body']['expanded'] = False
            changed['modules'].append(child)
            changed['modules'].sort(key=lambda r: r['compiler_name'])
            self.assertEqual(self.check(changed), changed)
            child.update(eligible=True, reason=None)
            with self.assertRaises(ValueError):
                self.check(changed)

    def test_unavailable_reasons_cannot_be_added_without_a_matching_ancestor(self) -> None:
        for reason in ('expanded', 'block_module'):
            changed = copy.deepcopy(self.value)
            changed['modules'][1].update(eligible=False, reason=reason)
            with self.subTest(reason=reason), self.assertRaises(ValueError):
                self.check(changed)
        changed = copy.deepcopy(self.value)
        changed['modules'][1]['body']['expanded'] = True
        with self.assertRaises(ValueError):
            self.check(changed)

    def test_original_parent_inline_and_utf8_intervals_cannot_be_rewritten(self) -> None:
        for kind in ('parent-file', 'parent-range', 'inline-range', 'unicode-split'):
            changed = copy.deepcopy(self.value)
            root, inline, external = changed['modules']
            if kind == 'parent-file': external['declaration']['file'] = str(self.external)
            elif kind == 'parent-range': root['body']['end'] = root['declaration']['end'] = 15
            elif kind == 'inline-range': inline['body']['end'] = 16
            else: inline['body']['start'] = 11
            with self.subTest(kind=kind), self.assertRaises(ValueError):
                self.check(changed)

    def test_original_source_restoration_record_repair_and_output_overlap_refuse(self) -> None:
        original = self.entry.read_bytes()
        self.entry.write_bytes(original + b'// changed')
        with self.assertRaises(ValueError): self.check()
        self.entry.write_bytes(original)
        with self.assertRaises(ValueError): self.check()
        self.sources = rust_inventory.capture_sources(self.project, (self.entry, self.external))
        path = self.output / 'module-inventory.json'
        path.write_text(modules.encoded(self.value))
        record = modules.read(self.output, self.sources, self.entry, crate_name='fixture')
        raw = path.read_bytes()
        path.write_bytes(raw + b' ')
        path.write_bytes(raw)
        with self.assertRaises(ValueError): record.verify()
        path.unlink()
        path.symlink_to(self.entry)
        with self.assertRaises(ValueError):
            modules.read(self.output, self.sources, self.entry, crate_name='fixture')
        with self.assertRaises(ValueError):
            modules.read(self.project, self.sources, self.entry, crate_name='fixture')


if __name__ == '__main__':
    unittest.main()
