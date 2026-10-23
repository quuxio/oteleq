"""Pack, verify, materialise and explicitly evict idle diagnostic receipts."""

from __future__ import annotations

from contextlib import contextmanager
import fcntl
import gzip
import hashlib
import io
import os
from pathlib import Path
import stat
import sys
import tarfile
import tempfile
from typing import Iterator
import uuid

from ci import evidence_files as files
from ci import evidence_index as records

ARCHIVE = "receipts.tar.gz"
INDEX = "index.json"
CHUNK = 1024 * 1024


def _guard(root: Path, store: Path) -> None:
    records.require(not sys.flags.optimize, "optimised Python is unsupported")
    records.root_path(root)
    records.require(store.is_absolute() and not store.is_relative_to(root)
                    and not root.is_relative_to(store), "archive storage must be separate from the corpus")


def _write(path: Path, content: bytes, mode: int = 0o400) -> None:
    descriptor = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_EXCL | os.O_NOFOLLOW, 0o600)
    try:
        with os.fdopen(descriptor, "wb", closefd=False) as stream:
            stream.write(content)
            stream.flush()
        os.fchmod(descriptor, mode)
        os.fsync(descriptor)
    finally:
        os.close(descriptor)


@contextmanager
def _locked(store: Path) -> Iterator[None]:
    records.root_path(store)
    records.require(stat.S_IMODE(store.stat().st_mode) == 0o700, "archive directory must have mode 0700")
    descriptor = os.open(store / "operation.lock", os.O_WRONLY | os.O_CREAT | os.O_NOFOLLOW, 0o600)
    try:
        value = os.fstat(descriptor)
        records.require(stat.S_ISREG(value.st_mode) and value.st_nlink == 1
                        and value.st_uid == os.getuid(), "unsafe archive operation lock")
        fcntl.flock(descriptor, fcntl.LOCK_EX | fcntl.LOCK_NB)
        yield
    finally:
        os.close(descriptor)


def pack(root: Path, selection: Path, store: Path) -> dict:
    """Create and fully verify a new archive; this operation never removes originals."""
    _guard(root, store)
    names = records.selection(selection, root)
    records.root_path(store.parent)
    records.require(store.parent / store.name == store and store.name not in (".", ".."),
                    "invalid archive directory")
    store.mkdir(mode=0o700)
    entries, total = [], 0
    with _locked(store):
        with (store / ARCHIVE).open("xb") as output:
            os.chmod(store / ARCHIVE, 0o600)
            with gzip.GzipFile(filename="", mode="wb", fileobj=output, mtime=0) as compressed, \
                 tarfile.open(fileobj=compressed, mode="w|", format=tarfile.PAX_FORMAT) as archive:
                for name in names:
                    item, content, _ = files.read(root, name)
                    entries.append(item)
                    total += item["size"]
                    records.require(total <= records.MAX_TOTAL_BYTES, "selected byte budget exceeded")
                    member = tarfile.TarInfo(name)
                    member.size, member.mode = len(content), 0o600
                    archive.addfile(member, io.BytesIO(content))
            output.flush()
            os.fsync(output.fileno())
        with (store / ARCHIVE).open("rb") as stream:
            archive_sha256 = hashlib.file_digest(stream, "sha256").hexdigest()
        payload = {"schema_version": 1, "kind": records.KIND, "root": str(root),
                   "archive_sha256": archive_sha256, "files": entries}
        payload["seal_sha256"] = records.digest(records.canonical(payload))
        content = records.canonical(payload) + b"\n"
        _write(store / INDEX, content)
        os.chmod(store / ARCHIVE, 0o400)
        directory = os.open(store, os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW)
        try:
            os.fsync(directory)
        finally:
            os.close(directory)
        index_sha256 = records.digest(content)
        with _verified(root, store, index_sha256) as (verified, _):
            records.require(len(verified["files"]) == len(entries), "verified file count differs")
        for item in entries:
            files.check(root, item)
    return {"index_sha256": index_sha256, "archive_sha256": archive_sha256,
            "files": len(entries), "original_bytes": sum(item["size"] for item in entries),
            "archive_bytes": (store / ARCHIVE).stat().st_size, "originals_removed": 0}


@contextmanager
def _verified(root: Path, store: Path, expected: str) -> Iterator[tuple[dict, tarfile.TarFile]]:
    """Validate gzip through its trailer, every unique member and all payload hashes."""
    value = records.index(store / INDEX, expected, root)
    limit = sum((item["size"] + 511) // 512 * 512 for item in value["files"])
    limit += len(value["files"]) * 16384 + 10240
    descriptor = os.open(store / ARCHIVE, os.O_RDONLY | os.O_NOFOLLOW | os.O_NONBLOCK)
    try:
        before = os.fstat(descriptor)
        records.require(stat.S_ISREG(before.st_mode) and before.st_nlink == 1
                        and before.st_uid == os.getuid() and before.st_size <= limit,
                        "unsafe or oversized archive file")
        with os.fdopen(descriptor, "rb", closefd=False) as source, tempfile.TemporaryFile() as plain:
            records.require(hashlib.file_digest(source, "sha256").hexdigest() == value["archive_sha256"],
                            "archive SHA256 differs")
            source.seek(0)
            total = 0
            with gzip.GzipFile(fileobj=source, mode="rb") as compressed:
                while chunk := compressed.read(CHUNK):
                    total += len(chunk)
                    records.require(total <= limit, "archive expansion exceeds indexed budget")
                    plain.write(chunk)
            records.require(files.stable(before) == files.stable(os.fstat(descriptor)),
                            "archive changed during verification")
            plain.seek(0)
            with tarfile.open(fileobj=plain, mode="r:") as archive:
                count, tail = 0, 0
                for member in archive:
                    records.require(count < len(value["files"]), "extra archive member")
                    item = value["files"][count]
                    records.require(member.name == item["path"] and member.type == tarfile.REGTYPE
                                    and member.sparse is None and member.size == item["size"]
                                    and set(member.pax_headers) <= {"path"}
                                    and member.mode == 0o600 and member.uid == member.gid == member.mtime == 0
                                    and not member.linkname and not member.uname and not member.gname,
                                    "archive member identity/type differs")
                    stream = archive.extractfile(member)
                    records.require(stream is not None, "archive member has no payload")
                    with stream:
                        records.require(hashlib.file_digest(stream, "sha256").hexdigest() == item["sha256"],
                                        "archive member content differs")
                    tail = member.offset_data + (member.size + 511) // 512 * 512
                    count += 1
                records.require(count == len(value["files"]), "archive members are missing")
                plain.seek(tail)
                while chunk := plain.read(CHUNK):
                    records.require(not any(chunk), "nonzero data after the final archive member")
                yield value, archive
    finally:
        os.close(descriptor)


def verify(root: Path, store: Path, expected: str) -> dict:
    """Check the sealed representation without starting applications or changing raw files."""
    _guard(root, store)
    with _locked(store), _verified(root, store, expected) as (value, _):
        return {"files": len(value["files"]), "index_sha256": expected, "archive_verified": True}


def _present(root: Path, value: dict) -> dict[str, tuple]:
    result = {}
    for item in value["files"]:
        try:
            result[item["path"]] = files.check(root, item)
        except FileNotFoundError:
            pass
    return result


def materialise(root: Path, store: Path, expected: str) -> dict:
    """Preflight every conflict before restoring any missing file at its original path."""
    _guard(root, store)
    with _locked(store), _verified(root, store, expected) as (value, archive):
        existing = _present(root, value)
        count = 0
        for item, member in zip(value["files"], archive.getmembers(), strict=True):
            if item["path"] not in existing:
                stream = archive.extractfile(member)
                records.require(stream is not None, "missing verified archive member")
                with stream:
                    files.install(root, item, stream.read(item["size"] + 1))
                count += 1
        for item in value["files"]:
            files.check(root, item)
        return {"restored": count, "already_present": len(existing), "index_sha256": expected}


def evict(root: Path, store: Path, expected: str, *, cold: bool = False) -> dict:
    """Remove checked materialised copies only after the caller establishes quiescence."""
    _guard(root, store)
    records.require(cold is True, "eviction requires explicit confirmation that all readers/writers are stopped")
    with _locked(store), _verified(root, store, expected) as (value, _):
        existing = _present(root, value)
        receipt = store / ("eviction-" + uuid.uuid4().hex + ".jsonl")
        _write(receipt, records.canonical({"root": str(root), "index_sha256": expected,
                                          "present_before": len(existing)}) + b"\n", 0o600)
        count = 0
        with receipt.open("ab") as journal:
            for item in value["files"]:
                if item["path"] in existing:
                    files.remove(root, item, existing[item["path"]])
                    journal.write(records.canonical({"archived": item["path"]}) + b"\n")
                    journal.flush()
                    os.fsync(journal.fileno())
                    count += 1
        return {"evicted": count, "already_archived": len(value["files"]) - len(existing),
                "index_sha256": expected, "receipt": str(receipt)}


def status(root: Path, store: Path, expected: str) -> dict:
    """Disclose archived paths explicitly; a frozen manifest still describes original bytes."""
    _guard(root, store)
    with _locked(store), _verified(root, store, expected) as (value, _):
        present = _present(root, value)
        return {"index_sha256": expected, "present": sorted(present),
                "archived": [item["path"] for item in value["files"] if item["path"] not in present]}
