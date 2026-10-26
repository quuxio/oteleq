"""Bounded staging retains pinned original ZIPs and cleans only new working copies."""

from pathlib import Path
import os
import stat
import tempfile
from types import SimpleNamespace
import unittest
from unittest.mock import patch
import warnings
import zipfile

import qualification_archive_selection as selection
import qualification_temporary_selection as temporary


class TemporarySelectionTests(unittest.TestCase):
    def setUp(self) -> None:
        self.folder = tempfile.TemporaryDirectory()
        self.addCleanup(self.folder.cleanup)
        self.root = Path(self.folder.name).resolve()
        self.archive = self.root / 'original.zip'
        self.members = [('native-metric-evidence/qualification.json', b'{"case":1}'),
                        ('native-metric-evidence/run/observation', b'outcome'),
                        ('native-metric-evidence/consumer-cli', b'not executed')]
        self.write(self.members)

    def write(self, members: list) -> str:
        with warnings.catch_warnings():
            warnings.simplefilter('ignore', UserWarning)
            with zipfile.ZipFile(self.archive, 'w') as bundle:
                for name, raw in members: bundle.writestr(name, raw)
        return selection.sha256(self.archive)

    def stage(self, digest: str | None = None):
        return temporary.staged(self.archive, digest or selection.sha256(self.archive),
                                namespace='native-metric', directory=self.root)

    def test_complete_selection_is_private_original_and_removed_after_success(self) -> None:
        sentinel = self.root / 'unrelated'; sentinel.write_text('preserve')
        digest = selection.sha256(self.archive)
        with self.stage(digest) as index:
            root = Path(index['root'])
            self.assertEqual(stat.S_IMODE(root.stat().st_mode), 0o700)
            self.assertEqual(index['selected_members'], 2)
            self.assertEqual(index['archive_members'], 3)
            self.assertIn('Temporary', index['copy_lifetime'])
            for name, raw in self.members[:2]:
                path = root / name
                self.assertEqual(path.read_bytes(), raw)
                self.assertEqual(stat.S_IMODE(path.stat().st_mode), 0o600)
            selection.verify(index, digest, namespace='native-metric')
        self.assertFalse(root.exists())
        self.assertEqual(sentinel.read_text(), 'preserve')
        self.assertEqual(selection.sha256(self.archive), digest)

    def test_digest_namespace_and_original_link_refuse_before_staging(self) -> None:
        for digest in ('0' * 64, 'invalid'):
            with self.subTest(digest=digest), self.assertRaises(ValueError):
                with self.stage(digest): pass
        with self.assertRaises(ValueError):
            with temporary.staged(self.archive, selection.sha256(self.archive), namespace='foreign'): pass
        linked = self.root / 'linked.zip'; linked.symlink_to(self.archive)
        with self.assertRaises(ValueError):
            with temporary.staged(linked, selection.sha256(self.archive), namespace='native-metric'): pass
        self.assertFalse(list(self.root.glob('oteleq-archive-audit-*')))

    def test_identical_copies_keep_independent_private_files_and_all_logical_members(self) -> None:
        digest = self.write([self.members[0], ('native-metric-evidence/copy.json', self.members[0][1])])
        with self.stage(digest) as index:
            root = Path(index['root'])
            first, second = (root / name for name in (self.members[0][0], 'native-metric-evidence/copy.json'))
            self.assertEqual(index['selected_members'], 2)
            self.assertEqual(index['selected_bytes'], 2 * len(self.members[0][1]))
            self.assertEqual(index['working_storage']['unique_contents'], 1)
            self.assertEqual(index['working_storage']['unique_content_bytes'], len(self.members[0][1]))
            self.assertNotEqual(first.stat().st_ino, second.stat().st_ino)
            self.assertEqual((first.stat().st_nlink, second.stat().st_nlink), (1, 1))
            selection.verify(index, digest, namespace='native-metric')
        self.assertFalse(root.exists())

    def test_ordinary_copy_path_preserves_private_files_without_clone_support(self) -> None:
        digest = self.write([self.members[0], ('native-metric-evidence/copy.json', self.members[0][1])])
        with patch.object(temporary, 'copy_on_write', return_value=None):
            with self.stage(digest) as index:
                self.assertEqual(index['working_storage']['kind'], 'Independent ordinary temporary files')
                for name in index['files']:
                    self.assertEqual((Path(index['root']) / name).stat().st_nlink, 1)

    def test_clone_failure_does_not_overwrite_original_or_leave_working_files(self) -> None:
        digest = self.write([self.members[0], ('native-metric-evidence/copy.json', self.members[0][1])])
        def fail(source, target): raise OSError('controlled clone failure')
        with patch.object(temporary, 'copy_on_write', return_value=fail), self.assertRaises(OSError):
            with self.stage(digest): pass
        self.assertFalse(list(self.root.glob('oteleq-archive-audit-*')))
        self.assertEqual(selection.sha256(self.archive), digest)

    def test_a_shared_inode_cannot_be_substituted_for_a_private_clone(self) -> None:
        digest = self.write([self.members[0], ('native-metric-evidence/copy.json', self.members[0][1])])
        def linked(source, target): os.link(source, target)
        with patch.object(temporary, 'copy_on_write', return_value=linked), \
                self.assertRaisesRegex(ValueError, 'not an independent ordinary file'):
            with self.stage(digest): pass
        self.assertFalse(list(self.root.glob('oteleq-archive-audit-*')))

    def test_unsafe_linked_duplicate_and_foreign_members_cannot_create_copies(self) -> None:
        link = zipfile.ZipInfo('native-metric-evidence/link.json')
        link.create_system = 3; link.external_attr = (stat.S_IFLNK | 0o777) << 16
        for members in ([('../escape.json', b'x')], [('/absolute.json', b'x')],
                        [('foreign/file.json', b'x')], [('native-metric-evidence/a\\b.json', b'x')],
                        [self.members[0], self.members[0]], [(link, b'../escape')]):
            digest = self.write(members)
            with self.subTest(members=repr(members)), self.assertRaises(ValueError):
                with self.stage(digest): pass
            self.assertFalse(list(self.root.glob('oteleq-archive-audit-*')))

    def test_empty_member_and_selected_budgets_refuse_without_partial_working_set(self) -> None:
        for setting in ('MAX_MEMBERS', 'MAX_SELECTED_BYTES', 'MAX_MEMBER_BYTES'):
            with patch.object(temporary, setting, 1), self.subTest(setting=setting), self.assertRaises(ValueError):
                with self.stage(): pass
        self.write([self.members[-1]])
        with self.assertRaises(ValueError):
            with self.stage(): pass
        self.assertFalse(list(self.root.glob('oteleq-archive-audit-*')))

    def test_low_disk_refuses_before_copy_and_mid_copy_refusal_removes_only_own_tree(self) -> None:
        digest = selection.sha256(self.archive)
        with patch.object(temporary.shutil, 'disk_usage', return_value=SimpleNamespace(free=0)), \
                self.assertRaisesRegex(ValueError, 'insufficient space'):
            with self.stage(digest): pass
        with patch.object(temporary.shutil, 'disk_usage', side_effect=(SimpleNamespace(free=2**40), SimpleNamespace(free=0))), \
                self.assertRaisesRegex(ValueError, 'storage reserve'):
            with self.stage(digest): pass
        self.assertFalse(list(self.root.glob('oteleq-archive-audit-*')))
        self.assertEqual(selection.sha256(self.archive), digest)

    def test_changed_copy_and_rehashed_index_cannot_replace_original_zip_bytes(self) -> None:
        digest = selection.sha256(self.archive)
        with self.assertRaises(ValueError):
            with self.stage(digest) as index:
                path = Path(index['root']) / self.members[0][0]
                path.write_bytes(b'{"case":2}')
                index['files'][self.members[0][0]]['sha256'] = selection.sha256(path)
        self.assertFalse(list(self.root.glob('oteleq-archive-audit-*')))
        self.assertEqual(selection.sha256(self.archive), digest)

    def test_primary_error_survives_a_preservation_failure_and_copies_are_cleaned(self) -> None:
        error = RuntimeError('original audit failure')
        with self.assertRaisesRegex(RuntimeError, 'original audit failure'):
            with self.stage() as index:
                (Path(index['root']) / self.members[0][0]).write_bytes(b'changed')
                raise error
        self.assertIn('preservation also failed', error.__notes__[0])
        self.assertFalse(list(self.root.glob('oteleq-archive-audit-*')))

    def test_changed_zip_identity_or_invalid_temporary_parent_refuse(self) -> None:
        with self.assertRaises(ValueError):
            with temporary.staged(self.archive, selection.sha256(self.archive),
                                  namespace='native-metric', directory=Path('.')): pass
        original = selection.sha256(self.archive)
        with self.assertRaisesRegex(ValueError, 'identity or write facts'):
            with self.stage(original):
                raw = self.archive.read_bytes(); self.archive.write_bytes(raw)
        self.assertFalse(list(self.root.glob('oteleq-archive-audit-*')))


if __name__ == '__main__':
    unittest.main()
