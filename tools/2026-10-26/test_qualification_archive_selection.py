"""A rewritten local index cannot authenticate a changed retained byte copy."""
from __future__ import annotations

import copy
import hashlib
from pathlib import Path
import tempfile
import unittest
import zipfile

import qualification_archive_selection as selection


class ArchiveSelectionTests(unittest.TestCase):
    def setUp(self) -> None:
        self.temporary = tempfile.TemporaryDirectory()
        self.addCleanup(self.temporary.cleanup)
        self.root = Path(self.temporary.name).resolve()
        self.copies = self.root / 'copies'
        self.copies.mkdir()
        self.archive = self.root / 'original.zip'
        self.members = {'native-lifetime-evidence/qualification.json': b'{"observed":1}',
                        'native-lifetime-evidence/otlp-0.protobuf': b'\0',
                        'native-lifetime-evidence/consumer-cli': b'never executed'}
        with zipfile.ZipFile(self.archive, 'w') as archive:
            for name, raw in self.members.items():
                archive.writestr(name, raw)
        files = {}
        for name, raw in self.members.items():
            if name.endswith('consumer-cli'):
                continue
            path = self.copies / name
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_bytes(raw)
            files[name] = {'sha256': hashlib.sha256(raw).hexdigest(), 'bytes': len(raw)}
        self.pinned = selection.sha256(self.archive)
        self.index = {'archive': str(self.archive), 'root': str(self.copies),
                      'archive_sha256': self.pinned, 'archive_members': 3,
                      'archive_directories': 0, 'selected_members': 2,
                      'selected_bytes': sum(row['bytes'] for row in files.values()),
                      'files': files}

    def verify(self, index: dict | None = None, digest: str | None = None) -> dict:
        return selection.verify(self.index if index is None else index,
                                self.pinned if digest is None else digest,
                                namespace='native-lifetime')

    def test_complete_original_selection_streams_against_both_index_and_copy(self) -> None:
        value = self.verify()
        self.assertEqual(value['selected_members_streamed'], 2)
        self.assertEqual(value['selected_bytes_streamed'], self.index['selected_bytes'])
        self.assertEqual(selection.sha256(self.archive), self.pinned)

    def test_changed_copy_and_rehashed_local_index_still_refuse_original_zip_mismatch(self) -> None:
        name = 'native-lifetime-evidence/qualification.json'
        path = self.copies / name
        path.write_bytes(b'{"observed":2}')
        changed = copy.deepcopy(self.index)
        changed['files'][name]['sha256'] = selection.sha256(path)
        # The old index-to-copy-only check accepts this self-consistent change.
        self.assertEqual(selection.sha256(path), changed['files'][name]['sha256'])
        with self.assertRaisesRegex(ValueError, 'index differs from original ZIP'):
            self.verify(changed)

    def test_changed_copy_without_index_update_refuses(self) -> None:
        path = self.copies / 'native-lifetime-evidence/otlp-0.protobuf'
        path.write_bytes(b'x')
        with self.assertRaisesRegex(ValueError, 'copy differs from original ZIP'):
            self.verify()

    def test_omitted_or_extra_selected_members_refuse(self) -> None:
        changed = copy.deepcopy(self.index)
        changed['files'].pop('native-lifetime-evidence/otlp-0.protobuf')
        with self.assertRaisesRegex(ValueError, 'incomplete or extra'):
            self.verify(changed)
        changed = copy.deepcopy(self.index)
        changed['files']['native-lifetime-evidence/consumer-cli'] = {'sha256': '0' * 64, 'bytes': 14}
        with self.assertRaisesRegex(ValueError, 'incomplete or extra'):
            self.verify(changed)

    def test_independent_digest_cannot_be_replaced_by_the_local_index(self) -> None:
        with self.assertRaisesRegex(ValueError, 'independently supplied digest'):
            self.verify(digest='0' * 64)

    def test_wrong_count_or_boolean_denominators_refuse(self) -> None:
        for key, value in (('archive_members', 4), ('selected_members', 1),
                           ('selected_bytes', 1), ('archive_directories', False)):
            with self.subTest(key=key), self.assertRaises(ValueError):
                self.verify(self.index | {key: value})

    def test_symlinked_retained_member_refuses_without_reading_its_target(self) -> None:
        path = self.copies / 'native-lifetime-evidence/otlp-0.protobuf'
        target = self.root / 'separate'
        target.write_bytes(path.read_bytes())
        path.unlink()
        path.symlink_to(target)
        with self.assertRaisesRegex(ValueError, 'linked or missing'):
            self.verify()


if __name__ == '__main__':
    unittest.main()
