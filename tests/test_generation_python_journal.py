"""Native journal framing, identities, terminal counts and explicit losses."""

import hashlib
import os
from pathlib import Path
import stat
import struct
import sys
import tempfile
import unittest
from unittest.mock import patch

REPO = Path(__file__).resolve().parents[1]
sys.path[:0] = [str(REPO / "adapters/generation"), str(REPO / "examples")]
import python_journal as journal

PID = 501
PATH = b"/tmp/entry.py"


def frame(record_kind: int, record_sequence: int, payload: bytes, path: bytes = PATH, **options) -> bytes:
    header = [b"OTLCPY1\0", record_kind, 0, 0, record_sequence, len(path), len(payload)]
    for name, index in (("magic", 0), ("kind", 1), ("flags", 2), ("reserved", 3),
                        ("sequence", 4), ("path_size", 5), ("size", 6)):
        if name in options:
            header[index] = options[name]
    return struct.pack("!8sBBHQQQ", *header) + path + payload


def source(content: bytes = b"source", pid: int = PID, **options) -> bytes:
    values = [pid, 11, 12, len(content), -1, 2, stat.S_IFREG | 0o644]
    for name, index in (("size", 3), ("nanos", 5), ("mode", 6)):
        if name in options:
            values[index] = options[name]
    return struct.pack("!QQQQqQQ", *values) + content


def code(identity: int = 1, **options) -> bytes:
    values = [PID, identity, 0, 0x030c0ff0, 2, 2, 0]
    for name, index in (("pid", 0), ("offset", 2), ("version", 3), ("descriptor", 4), ("size", 5), ("reserved", 6)):
        if name in options:
            values[index] = options[name]
    return struct.pack("!7Q", *values) + b"{}"


def final(sequence: int = 2, count: int = 1, size: int = 6, **options) -> bytes:
    values = [PID, count, size, 0, 0, 1, 1]
    for name, index in (("pid", 0), ("capture", 3), ("journal", 4), ("finalized", 5), ("expected", 6)):
        if name in options:
            values[index] = options[name]
    return frame(2, sequence, struct.pack("!7Q", *values), path=b"")


class PythonJournalTests(unittest.TestCase):
    def test_complete_records_retain_actual_order_bytes_and_opened_file_metadata(self) -> None:
        data = frame(1, 1, source()) + frame(3, 2, source(b"import")) + frame(4, 3, code()) + final(4, 3, 14)
        value = journal.decode(data, PID)
        self.assertTrue(value.complete)
        self.assertEqual([row.sequence for row in value.records], [1, 2, 3])
        entry, imported, native = value.records
        self.assertEqual((entry.kind, imported.kind), (1, 3))
        self.assertEqual((entry.path, entry.content, entry.device, entry.inode, entry.mtime_ns, entry.mode),
                         (PATH, b"source", 11, 12, -999999998, stat.S_IFREG | 0o644))
        self.assertEqual(entry.sha256, hashlib.sha256(b"source").hexdigest())
        self.assertEqual(native.sha256, hashlib.sha256(b"{}").hexdigest())
        self.assertEqual((native.identity, native.python_version, native.descriptor_version), (1, 0x030c0ff0, 2))

    def test_losses_and_unfinished_or_unexpected_entry_stay_explicitly_incomplete(self) -> None:
        for options in ({"capture": 1}, {"journal": 1}, {"finalized": 0}, {"expected": 0}):
            with self.subTest(options=options):
                value = journal.decode(frame(1, 1, source()) + final(**options), PID)
                self.assertFalse(value.complete)
        self.assertFalse(journal.decode(final(1, 0, 0), PID).complete)

    def test_empty_truncated_and_unterminated_or_trailing_data_refuse(self) -> None:
        entry = frame(1, 1, source())
        for data in (b"", entry[:10], entry[:-1], entry, entry + final()[:-1], entry + final() + b"x"):
            with self.subTest(size=len(data)), self.assertRaises(ValueError):
                journal.decode(data, PID)
        for pid in (True, 0, -1, "501"):
            with self.subTest(pid=pid), self.assertRaises(ValueError):
                journal.decode(entry + final(), pid)
        with self.assertRaises(ValueError):
            journal.decode(bytearray(entry + final()), PID)

    def test_unknown_versions_flags_record_order_and_sizes_refuse(self) -> None:
        variants = ({"magic": b"OTLCPY2\0"}, {"kind": 5}, {"flags": 1}, {"reserved": 1},
                    {"sequence": 2}, {"path_size": 65536}, {"size": 55}, {"size": journal.MAX_PAYLOAD + 57})
        for options in variants:
            with self.subTest(options=options), self.assertRaises(ValueError):
                journal.decode(frame(1, 1, source(), **options) + final(), PID)
        with patch.object(journal, "MAX_BYTES", 1), self.assertRaises(ValueError):
            journal.decode(frame(1, 1, source()) + final(), PID)
        with patch.object(journal, "MAX_RECORDS", 1), self.assertRaises(ValueError):
            journal.decode(frame(1, 1, source()) + final(), PID)

    def test_missing_nul_paths_source_pid_mode_times_and_length_refuse(self) -> None:
        for path in (b"", b"bad\0path"):
            with self.subTest(path=path), self.assertRaises(ValueError):
                journal.decode(frame(1, 1, source(), path=path) + final(), PID)
        for options in ({"pid": 502}, {"mode": stat.S_IFDIR}, {"nanos": 10 ** 9}, {"size": 7}):
            with self.subTest(options=options), self.assertRaises(ValueError):
                journal.decode(frame(1, 1, source(**options)) + final(), PID)

    def test_code_envelopes_require_advertised_version_identity_width_and_position(self) -> None:
        variants = ({"identity": 0}, {"pid": 502}, {"offset": 1}, {"offset": journal.MAX_PAYLOAD},
                    {"version": 0x030b0ff0}, {"version": 0x04000000}, {"version": 2 ** 32},
                    {"descriptor": 1}, {"descriptor": 3}, {"size": 0}, {"size": 1}, {"reserved": 1})
        for options in variants:
            with self.subTest(options=options), self.assertRaises(ValueError):
                journal.decode(frame(4, 1, code(**options)) + final(2, 1, 2), PID)

    def test_final_pid_counts_bytes_status_width_and_nonterminal_record_refuse(self) -> None:
        entry = frame(1, 1, source())
        for options in ({"pid": 502}, {"count": 2}, {"size": 7}, {"finalized": 2}, {"expected": 2}):
            with self.subTest(options=options), self.assertRaises(ValueError):
                journal.decode(entry + final(**options), PID)
        payload = struct.pack("!7Q", PID, 1, 6, 0, 0, 1, 1)
        for terminal in (frame(2, 2, payload, path=PATH), frame(2, 2, payload + b"x", path=b"")):
            with self.assertRaises(ValueError):
                journal.decode(entry + terminal, PID)

    def test_duplicate_code_ids_always_refuse_and_missing_ids_disclose_losses(self) -> None:
        duplicate = frame(4, 1, code()) + frame(4, 2, code()) + final(3, 2, 4, capture=1)
        with self.assertRaisesRegex(ValueError, "duplicate"):
            journal.decode(duplicate, PID)
        with self.assertRaisesRegex(ValueError, "incomplete"):
            journal.decode(frame(4, 1, code(2)) + final(2, 1, 2), PID)
        value = journal.decode(frame(4, 1, code(2)) + final(2, 1, 2, capture=1), PID)
        self.assertEqual(value.capture_failures, 1)
        self.assertFalse(value.complete)

    def test_private_reader_rejects_permissions_links_special_files_and_bad_byte_budgets(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            path = Path(temporary) / "input.journal"
            path.write_bytes(frame(1, 1, source()) + final())
            path.chmod(0o600)
            self.assertTrue(journal.read(path, PID).complete)
            for maximum in (True, 0, -1, journal.MAX_BYTES + 1):
                with self.subTest(maximum=maximum), self.assertRaises(ValueError):
                    journal.python_prepared.read_bytes(path, maximum)
            path.chmod(0o644)
            with self.assertRaises(ValueError):
                journal.read(path, PID)
            path.chmod(0o600)
            linked = path.with_name("link")
            os.link(path, linked)
            with self.assertRaises(ValueError):
                journal.read(path, PID)
            linked.unlink()
            linked.symlink_to(path)
            with self.assertRaises(OSError):
                journal.read(linked, PID)
            linked.unlink(); os.mkfifo(linked)
            with self.assertRaises(ValueError):
                journal.read(linked, PID)
