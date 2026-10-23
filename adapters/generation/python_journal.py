"""Independent native Python journal-1 framing; input reads are not code origin."""

from dataclasses import dataclass
import hashlib
from pathlib import Path
import stat
import struct

import python_prepared
from python_provider import require

HEADER = struct.Struct("!8sBBHQQQ")
SOURCE = struct.Struct("!QQQQqQQ")
CODE = struct.Struct("!7Q")
FINAL = struct.Struct("!7Q")
MAGIC = b"OTLCPY1\0"
MAX_BYTES = 64 * 1024 * 1024
MAX_PAYLOAD = 16 * 1024 * 1024
MAX_RECORDS = 4096
MAX_PATH = 65535


@dataclass(frozen=True)
class SourceRecord:
    """Preserve the actual record order and complete consumed input bytes."""

    sequence: int
    kind: int
    path: bytes
    content: bytes
    device: int
    inode: int
    mtime_ns: int
    mode: int

    @property
    def sha256(self) -> str:
        """Hash the captured bytes, without reopening application source paths."""
        return hashlib.sha256(self.content).hexdigest()


@dataclass(frozen=True)
class CodeRecord:
    """A code ID and graph payload need separate graph and origin validation."""

    sequence: int
    path: bytes
    content: bytes
    identity: int
    offset: int
    python_version: int
    descriptor_version: int

    @property
    def sha256(self) -> str:
        """Bind the exact retained descriptor bytes."""
        return hashlib.sha256(self.content).hexdigest()


@dataclass(frozen=True)
class Journal:
    """Final capture counts remain distinct from application/SDK exit success."""

    pid: int
    records: tuple[SourceRecord | CodeRecord, ...]
    capture_failures: int
    journal_failures: int
    python_finalized: bool
    entry_expected: bool

    @property
    def complete(self) -> bool:
        """Only the declared entry capture is complete; source origin stays open."""
        return (self.python_finalized and self.entry_expected and not self.capture_failures
                and not self.journal_failures and any(type(row) is SourceRecord and row.kind == 1 for row in self.records))


def source_record(sequence: int, kind: int, path: bytes, payload: bytes, pid: int) -> SourceRecord:
    """Decode opened-file facts without treating a filename as consumed evidence."""
    actual, device, inode, size, seconds, nanos, mode = SOURCE.unpack_from(payload)
    require(actual == pid and nanos < 10 ** 9 and stat.S_ISREG(mode)
            and size == len(payload) - SOURCE.size, "invalid native Python source input")
    return SourceRecord(sequence, kind, path, payload[SOURCE.size:], device, inode, seconds * 10 ** 9 + nanos, mode)


def code_record(sequence: int, path: bytes, payload: bytes, pid: int) -> CodeRecord:
    """Read only the advertised descriptor-2 envelope; no application code runs."""
    actual, identity, offset, version, descriptor, size, reserved = CODE.unpack_from(payload)
    require(actual == pid and identity > 0 and offset < MAX_PAYLOAD and offset % 2 == 0
            and version <= 0xffffffff and version >> 24 == 3 and (version >> 16 & 255) >= 12
            and descriptor == 2 and 0 < size == len(payload) - CODE.size and reserved == 0,
            "invalid native Python code input")
    return CodeRecord(sequence, path, payload[CODE.size:], identity, offset, version, descriptor)


def final_record(payload: bytes, records: list, pid: int) -> Journal:
    """Terminal counts must cover every preceding entry, import and code record."""
    actual, count, size, capture, journal, finalized, expected = FINAL.unpack(payload)
    require(actual == pid and count == len(records) and size == sum(len(row.content) for row in records)
            and finalized in (0, 1) and expected in (0, 1), "native Python terminal counts differ")
    identities = [row.identity for row in records if type(row) is CodeRecord]
    require(len(set(identities)) == len(identities), "duplicate native Python code identity")
    if capture == journal == 0:
        require(set(identities) == set(range(1, len(identities) + 1)), "native Python code identities are incomplete")
    return Journal(pid, tuple(records), capture, journal, bool(finalized), bool(expected))


def decode(data: bytes, pid: int) -> Journal:
    """Validate bounded exact framing, order, actual PID and terminal EOF."""
    require(type(data) is bytes and len(data) <= MAX_BYTES and type(pid) is int and pid > 0,
            "invalid native Python journal size or PID")
    position, sequence = 0, 0
    records = []
    while position < len(data):
        require(len(data) - position >= HEADER.size, "truncated native Python record header")
        magic, kind, flags, reserved, current, path_size, size = HEADER.unpack_from(data, position)
        position += HEADER.size
        require(magic == MAGIC and kind in (1, 2, 3, 4) and flags == reserved == 0
                and current == sequence + 1 and current <= MAX_RECORDS and path_size <= MAX_PATH
                and SOURCE.size <= size <= MAX_PAYLOAD + SOURCE.size
                and path_size + size <= len(data) - position, "invalid native Python record framing")
        path = data[position:position + path_size]
        position += path_size
        payload = data[position:position + size]
        position += size
        sequence = current
        if kind == 2:
            require(not path and size == FINAL.size and position == len(data), "native Python final record is not terminal")
            return final_record(payload, records, pid)
        require(bool(path) and b"\0" not in path, "invalid native Python record path")
        records.append(code_record(sequence, path, payload, pid) if kind == 4
                       else source_record(sequence, kind, path, payload, pid))
    raise ValueError("Python prepared provider: native journal lacks finalization evidence")


def read(path: Path, pid: int) -> Journal:
    """The caller must wait for its owned supervisor and SDK before this snapshot."""
    return decode(python_prepared.read_bytes(path, MAX_BYTES), pid)
