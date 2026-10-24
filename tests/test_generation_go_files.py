"""Go input snapshots reject incomplete reads and keep original file facts."""

import os
from pathlib import Path
import sys
import tempfile
import unittest
from unittest.mock import patch

REPO = Path(__file__).resolve().parents[1]
sys.path[:0] = [str(REPO / "adapters/generation"), str(REPO / "examples")]
import go_files as files


class GoInputFileTests(unittest.TestCase):
    def setUp(self):
        self.temporary = tempfile.TemporaryDirectory()
        self.addCleanup(self.temporary.cleanup)
        self.root = Path(self.temporary.name).resolve()
        self.path = self.root / "source.go"; self.path.write_bytes(b"source bytes")

    def test_snapshot_keeps_all_bytes_file_facts_and_ignores_only_git_metadata(self):
        (self.root / ".git").write_text("git metadata")
        original = files.freeze(self.root); original.verify()
        self.assertEqual(set(original.identities), {"source.go"})
        self.assertEqual(files.content(original)["source.go"]["size"], 12)
        self.path.write_bytes(b"same length!")
        with self.assertRaises(ValueError): original.verify()

    def test_arrays_duplicates_nonfinite_links_fifo_and_nonprivate_metadata_refuse(self):
        self.path.write_text('{"ok":true}'); self.path.chmod(0o600)
        self.assertEqual(files.read(self.path, private=True)[0], {"ok": True})
        for data in ("[]", '{"ok":1,"ok":2}', '{"number":NaN}'):
            self.path.write_text(data)
            with self.assertRaises(ValueError): files.read(self.path)
        self.path.chmod(0o644)
        with self.assertRaises(ValueError): files.read(self.path, private=True)
        alias = self.root / "alias"; alias.symlink_to(self.path)
        with self.assertRaises(ValueError): files.freeze(self.root)
        alias.unlink(); self.path.unlink(); os.mkfifo(self.path, 0o600)
        with self.assertRaises(ValueError): files.file(self.path)

    def test_invalid_relative_names_byte_budgets_and_incomplete_walks_refuse(self):
        for name in (None, "", ".", "../outside", "/absolute", "a//b", "a\\b", "bad\0name"):
            with self.subTest(name=name), self.assertRaises(ValueError): files.relative(name)
        for limit in (0, True, 2):
            with self.assertRaises(ValueError): files.file(self.path, limit)
        with patch.object(files, "MAX_FILES", 0), self.assertRaises(ValueError): files.freeze(self.root)
        with patch.object(files, "MAX_TREE_BYTES", 1), self.assertRaises(ValueError): files.freeze(self.root)
        with patch.object(files.capture, "tree_paths", side_effect=PermissionError("unreadable")), \
                self.assertRaises(PermissionError): files.freeze(self.root)

    def test_replaced_or_grown_file_cannot_reuse_pre_read_facts(self):
        original = files.os.fstat; reads = []
        def changed(descriptor):
            info = original(descriptor); reads.append(descriptor)
            if len(reads) == 2:
                self.path.write_bytes(b"a different and longer input")
                return original(descriptor)
            return info
        with patch.object(files.os, "fstat", side_effect=changed), self.assertRaises(ValueError):
            files.file(self.path)

    def test_parent_replacement_cannot_reuse_the_same_open_inode_through_a_link(self):
        parent = self.root / "parent"
        parent.mkdir()
        path = parent / "input.go"
        path.write_bytes(b"unchanged inode and bytes")
        original = files.os.fstat
        replaced = False

        def changed(descriptor):
            nonlocal replaced
            info = original(descriptor)
            if not replaced:
                replaced = True
                moved = self.root / "moved"
                parent.rename(moved)
                parent.symlink_to(moved, target_is_directory=True)
            return info

        with patch.object(files.os, "fstat", side_effect=changed), self.assertRaisesRegex(ValueError, "changed while reading"):
            files.file(path)


if __name__ == "__main__":
    unittest.main()
