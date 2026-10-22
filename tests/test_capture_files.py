"""Hashing rejects special inputs before a blocking read and closes descriptors."""
import hashlib
import os
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[1]
sys.path[:0] = [str(ROOT / "examples"), str(ROOT / "adapters/generation")]
import otelc_capture as capture
import capture_otelc_tasks as tasks
import java_build


class FileDigestTests(unittest.TestCase):
    def setUp(self):
        temporary = tempfile.TemporaryDirectory(prefix="oteleq hash inputs ")
        self.addCleanup(temporary.cleanup)
        self.root = Path(temporary.name)
        self.source = self.root / "input.bin"
        self.data = bytes(range(256)) * 8193
        self.source.write_bytes(self.data)

    def readers(self):
        return (capture.file_digest, tasks.file_digest, java_build.digest)

    def test_regular_binary_inputs_preserve_the_complete_sha256(self):
        expected = hashlib.sha256(self.data).hexdigest()
        for reader in self.readers():
            with self.subTest(reader=reader.__module__):
                self.assertEqual(reader(self.source), expected)

    def test_empty_regular_input_has_the_standard_digest(self):
        self.source.write_bytes(b"")
        self.assertEqual(capture.file_digest(self.source), hashlib.sha256(b"").hexdigest())

    def test_declared_tool_symlinks_can_still_hash_a_regular_target(self):
        linked = self.root / "selected-tool"
        linked.symlink_to(self.source)
        for reader in self.readers():
            with self.subTest(reader=reader.__module__):
                self.assertEqual(reader(linked), hashlib.sha256(self.data).hexdigest())

    def test_directory_input_is_rejected_as_a_non_regular_file(self):
        for reader in self.readers():
            with self.subTest(reader=reader.__module__):
                with self.assertRaisesRegex(ValueError, "regular file"):
                    reader(self.root)

    def test_missing_input_retains_the_original_operating_system_error(self):
        missing = self.root / "missing"
        for reader in self.readers():
            with self.subTest(reader=reader.__module__):
                with self.assertRaises(FileNotFoundError):
                    reader(missing)

    @unittest.skipUnless(hasattr(os, "mkfifo"), "requires POSIX named pipes")
    def test_fifo_inputs_are_rejected_without_waiting_for_a_writer(self):
        fifo = self.root / "input.fifo"
        os.mkfifo(fifo)
        linked = self.root / "selected-pipe"
        linked.symlink_to(fifo)
        code = ("import sys;sys.path[:0]=sys.argv[1:3];from pathlib import Path;"
                "import importlib;reader=getattr(importlib.import_module(sys.argv[3]),sys.argv[4]);"
                "\ntry:reader(Path(sys.argv[5]))"
                "\nexcept ValueError as error:"
                "\n assert 'regular file' in str(error),str(error)"
                "\nelse:raise AssertionError('FIFO accepted')")
        for target in (fifo, linked):
            for reader in self.readers():
                with self.subTest(reader=reader.__module__, target=target.name):
                    result = subprocess.run([sys.executable, "-c", code, str(ROOT / "examples"),
                        str(ROOT / "adapters/generation"), reader.__module__, reader.__name__, str(target)],
                        capture_output=True, text=True, timeout=3, check=False)
                    self.assertEqual(result.returncode, 0, result.stderr)

    @unittest.skipUnless(hasattr(os, "pipe"), "requires descriptor pipes")
    def test_rejected_descriptor_is_closed_without_reading(self):
        descriptor, writer = os.pipe()
        self.addCleanup(os.close, writer)
        try:
            with patch.object(capture.os, "open", return_value=descriptor), \
                 patch.object(capture.hashlib, "file_digest", side_effect=AssertionError("must reject before reading")):
                with self.assertRaisesRegex(ValueError, "regular file"):
                    capture.file_digest(self.source)
            with self.assertRaises(OSError):
                os.fstat(descriptor)
        finally:
            try:
                os.close(descriptor)
            except OSError:
                pass

    def test_regular_descriptor_is_blocking_before_hashing(self):
        def check(stream, algorithm):
            self.assertTrue(os.get_blocking(stream.fileno()))
            self.assertEqual(algorithm, "sha256")
            return hashlib.sha256(self.data)

        with patch.object(capture.hashlib, "file_digest", side_effect=check):
            self.assertEqual(capture.file_digest(self.source), hashlib.sha256(self.data).hexdigest())

    def test_hash_failure_closes_the_owned_descriptor(self):
        opened = []
        original = os.open

        def remember(*args, **kwargs):
            descriptor = original(*args, **kwargs)
            opened.append(descriptor)
            return descriptor

        with patch.object(capture.os, "open", side_effect=remember), \
             patch.object(capture.hashlib, "file_digest", side_effect=OSError("read failed")):
            with self.assertRaisesRegex(OSError, "read failed"):
                capture.file_digest(self.source)
        self.assertEqual(len(opened), 1)
        with self.assertRaises(OSError):
            os.fstat(opened[0])


if __name__ == "__main__":
    unittest.main()

