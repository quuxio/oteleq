"""Owned, non-following receipt I/O and atomic restoration without overwrites."""

from __future__ import annotations

from contextlib import contextmanager
import ctypes
import hashlib
import os
from pathlib import Path, PurePosixPath
import stat
import sys
from typing import Iterator
import uuid

from ci.evidence_index import MAX_FILE_BYTES, require
from ci import evidence_attributes as attributes


def _directory(descriptor: int) -> None:
    value = os.fstat(descriptor)
    require(stat.S_ISDIR(value.st_mode) and value.st_uid == os.getuid()
            and not value.st_mode & 0o022, "unsafe receipt directory")


@contextmanager
def parent(root: Path, name: str, *, create: bool = False) -> Iterator[tuple[int, str]]:
    """Walk below an opened root through owned directories, refusing symlinks."""
    descriptor = os.open(root, os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW)
    try:
        _directory(descriptor)
        path = PurePosixPath(name)
        for part in path.parts[:-1]:
            if create:
                try:
                    os.mkdir(part, 0o700, dir_fd=descriptor)
                except FileExistsError:
                    pass
            child = os.open(part, os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW,
                            dir_fd=descriptor)
            os.close(descriptor)
            descriptor = child
            _directory(descriptor)
        yield descriptor, path.name
    finally:
        os.close(descriptor)


def stable(value: os.stat_result) -> tuple:
    """Identify changes without treating an access-time update as a mutation."""
    return (value.st_dev, value.st_ino, value.st_size, value.st_mtime_ns,
            value.st_ctime_ns, value.st_mode, value.st_uid, value.st_gid, value.st_nlink)


def _metadata(value: os.stat_result) -> dict:
    require(stat.S_ISREG(value.st_mode) and value.st_nlink == 1
            and value.st_uid == os.getuid() and not value.st_mode & 0o7000
            and not getattr(value, "st_flags", 0), "unsafe receipt file metadata")
    require(0 <= value.st_size <= MAX_FILE_BYTES, "receipt exceeds byte budget")
    return {"size": value.st_size, "mode": stat.S_IMODE(value.st_mode),
            "uid": value.st_uid, "gid": value.st_gid, "mtime_ns": value.st_mtime_ns}


def read(root: Path, name: str) -> tuple[dict, bytes, tuple]:
    """Read one stable file and its attributes; multiple links remain unsupported."""
    with parent(root, name) as (directory, leaf):
        descriptor = os.open(leaf, os.O_RDONLY | os.O_NOFOLLOW | os.O_NONBLOCK,
                             dir_fd=directory)
        try:
            before = os.fstat(descriptor)
            result = _metadata(before)
            result["xattrs"] = attributes.read(descriptor)
            with os.fdopen(descriptor, "rb", closefd=False) as stream:
                content = stream.read(MAX_FILE_BYTES + 1)
            require(len(content) == before.st_size, "receipt size changed during read")
            require(stable(before) == stable(os.fstat(descriptor))
                    == stable(os.stat(leaf, dir_fd=directory, follow_symlinks=False)),
                    "receipt changed during read")
        finally:
            os.close(descriptor)
    result.update(path=name, sha256=hashlib.sha256(content).hexdigest())
    return result, content, stable(before)


def check(root: Path, item: dict) -> tuple:
    """Require original content and all bound metadata, including nanosecond mtime."""
    actual, _, identity = read(root, item["path"])
    require(actual == item, "receipt content/metadata differs: " + item["path"])
    return identity


def _rename(directory: int, temporary: str, destination: str) -> None:
    # Apple sys/stdio.h RENAME_EXCL; Linux renameat2 RENAME_NOREPLACE.
    function_name, flags = (("renameatx_np", 4) if sys.platform == "darwin"
                            else ("renameat2", 1) if sys.platform.startswith("linux")
                            else ("", 0))
    library = ctypes.CDLL(None, use_errno=True)
    function = getattr(library, function_name, None) if function_name else None
    require(function is not None, "atomic no-replace restoration is unsupported")
    function.argtypes = [ctypes.c_int, ctypes.c_char_p, ctypes.c_int,
                         ctypes.c_char_p, ctypes.c_uint]
    function.restype = ctypes.c_int
    if function(directory, os.fsencode(temporary), directory, os.fsencode(destination), flags):
        raise OSError(ctypes.get_errno(), "atomic no-replace restoration failed", destination)


def install(root: Path, item: dict, content: bytes) -> None:
    """Install a fully checked private temporary file; never replace a target."""
    require(len(content) == item["size"]
            and hashlib.sha256(content).hexdigest() == item["sha256"], "restore content differs")
    with parent(root, item["path"], create=True) as (directory, leaf):
        temporary = ".oteleq-restore-" + uuid.uuid4().hex
        descriptor = os.open(temporary, os.O_RDWR | os.O_CREAT | os.O_EXCL
                             | os.O_NOFOLLOW, 0o600, dir_fd=directory)
        try:
            with os.fdopen(descriptor, "wb", closefd=False) as stream:
                stream.write(content)
                stream.flush()
            value = os.fstat(descriptor)
            if value.st_gid != item["gid"]:
                os.fchown(descriptor, item["uid"], item["gid"])
            attributes.write(descriptor, item["xattrs"])
            os.fchmod(descriptor, item["mode"])
            os.utime(descriptor, ns=(item["mtime_ns"], item["mtime_ns"]))
            require(_metadata(os.fstat(descriptor)) == {
                key: item[key] for key in ("size", "mode", "uid", "gid", "mtime_ns")},
                "restore metadata could not be reproduced")
            os.fsync(descriptor)
            os.lseek(descriptor, 0, os.SEEK_SET)
            with os.fdopen(descriptor, "rb", closefd=False) as stream:
                require(hashlib.file_digest(stream, "sha256").hexdigest() == item["sha256"],
                        "staged restore content differs")
            _rename(directory, temporary, leaf)
            os.fsync(directory)
        finally:
            os.close(descriptor)
            try:
                os.unlink(temporary, dir_fd=directory)
            except FileNotFoundError:
                pass
    check(root, item)


def remove(root: Path, item: dict, expected: tuple) -> None:
    """Recheck an idle original immediately before unlinking its explicit path."""
    require(check(root, item) == expected, "receipt identity changed before eviction")
    with parent(root, item["path"]) as (directory, leaf):
        require(stable(os.stat(leaf, dir_fd=directory, follow_symlinks=False)) == expected,
                "receipt identity changed before unlink")
        os.unlink(leaf, dir_fd=directory)
        os.fsync(directory)
