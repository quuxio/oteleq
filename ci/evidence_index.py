"""Validate explicit cold-receipt selections and sealed archive indexes."""

from __future__ import annotations

import hashlib
import json
import os
from pathlib import Path, PurePosixPath
import stat
from typing import Any

MAX_FILES = 100_000
MAX_FILE_BYTES = 64 * 1024 * 1024
MAX_TOTAL_BYTES = 128 * 1024**3
MAX_INDEX_BYTES = 64 * 1024 * 1024
KIND = "oteleq.cold-receipts"
FILE_KEYS = {"path", "sha256", "size", "mode", "uid", "gid", "mtime_ns", "xattrs"}


class ArchiveError(ValueError):
    """The requested archive operation cannot preserve its evidence contract."""


def require(condition: bool, message: str) -> None:
    """Keep safety checks active independently of Python assertion settings."""
    if not condition:
        raise ArchiveError(message)


def canonical(value: Any) -> bytes:
    """Encode a deterministic index seal, without non-finite JSON numbers."""
    return json.dumps(value, sort_keys=True, separators=(",", ":"),
                      ensure_ascii=True, allow_nan=False).encode("ascii")


def digest(content: bytes) -> str:
    """Return the SHA256 identity of a bounded encoded record."""
    return hashlib.sha256(content).hexdigest()


def _pairs(values: list[tuple[str, Any]]) -> dict:
    result = {}
    for key, value in values:
        require(key not in result, "duplicate JSON key")
        result[key] = value
    return result


def load(path: Path) -> tuple[dict, bytes]:
    """Read bounded, unambiguous JSON from one private regular file."""
    descriptor = os.open(path, os.O_RDONLY | os.O_NOFOLLOW | os.O_NONBLOCK)
    try:
        value = os.fstat(descriptor)
        require(stat.S_ISREG(value.st_mode) and value.st_nlink == 1
                and value.st_uid == os.getuid(), "unsafe index/selection file")
        with os.fdopen(descriptor, "rb", closefd=False) as stream:
            content = stream.read(MAX_INDEX_BYTES + 1)
    finally:
        os.close(descriptor)
    require(len(content) <= MAX_INDEX_BYTES, "index/selection exceeds byte budget")
    try:
        result = json.loads(content, object_pairs_hook=_pairs,
                            parse_constant=lambda _: require(False, "non-finite JSON"))
    except (UnicodeError, RecursionError) as error:
        raise ArchiveError("invalid index/selection encoding or depth") from error
    require(type(result) is dict, "index/selection must be an object")
    return result, content


def root_path(path: Path) -> Path:
    """Require an explicit canonical directory owned by the current user."""
    require(path.is_absolute() and path == path.resolve(strict=True),
            "root must be an existing canonical absolute path")
    value = path.stat()
    require(stat.S_ISDIR(value.st_mode) and value.st_uid == os.getuid(),
            "root must be an owned directory")
    return path


def relative_path(name: Any) -> str:
    """Restrict this format to generated Node launch receipts and Java logs."""
    require(type(name) is str and 0 < len(name.encode("utf-8")) <= 4096
            and "\\" not in name and all(ord(c) >= 32 for c in name),
            "invalid receipt path")
    path = PurePosixPath(name)
    require(not path.is_absolute() and ".." not in path.parts
            and path.as_posix() == name and len(path.parts) >= 2,
            "receipt path must be normalised and relative")
    allowed = ((path.name in ("node-launch.json", "node-plain-launch.json")
                and path.parent.name == "node-runtime")
               or (path.name == "class-load.log" and path.parent.name == "sdk-runtime"))
    require(allowed, "unsupported receipt role")
    require(not any(p in {"provider", "snapshot", ".git", ".venv", "node_modules"}
                    or p.startswith("source-") for p in path.parts),
            "source/provider roles cannot be archived")
    return name


def selection(path: Path, root: Path) -> list[str]:
    """Validate a deliberately supplied file list; never scan or execute inputs."""
    value, _ = load(path)
    require(set(value) == {"schema_version", "kind", "root", "paths"}
            and type(value["schema_version"]) is int and value["schema_version"] == 1
            and value["kind"] == KIND and value["root"] == str(root),
            "selection schema/root differs")
    paths = value["paths"]
    require(type(paths) is list and 0 < len(paths) <= MAX_FILES, "invalid selection count")
    names = [relative_path(name) for name in paths]
    require(len(set(names)) == len(names), "duplicate selected path")
    return sorted(names)


def index(path: Path, expected_sha256: str, root: Path) -> dict:
    """Require the caller's trust anchor and the index's canonical payload seal."""
    value, content = load(path)
    require(digest(content) == expected_sha256, "index SHA256 differs")
    require(set(value) == {"schema_version", "kind", "root", "archive_sha256",
                           "files", "seal_sha256"}
            and type(value["schema_version"]) is int and value["schema_version"] == 1
            and value["kind"] == KIND and value["root"] == str(root), "index schema/root differs")
    payload = {key: item for key, item in value.items() if key != "seal_sha256"}
    require(digest(canonical(payload)) == value["seal_sha256"], "index seal differs")
    require(type(value["archive_sha256"]) is str and len(value["archive_sha256"]) == 64
            and all(c in "0123456789abcdef" for c in value["archive_sha256"]), "invalid archive hash")
    files = value["files"]
    require(type(files) is list and 0 < len(files) <= MAX_FILES, "invalid indexed file count")
    names = []
    for item in files:
        require(type(item) is dict and set(item) == FILE_KEYS, "invalid indexed file fields")
        names.append(relative_path(item["path"]))
        require(all(type(item[k]) is int for k in ("size", "mode", "uid", "gid", "mtime_ns")),
                "invalid indexed metadata types")
        require(0 <= item["size"] <= MAX_FILE_BYTES and 0 <= item["mode"] <= 0o777
                and item["uid"] == os.getuid() and 0 <= item["gid"] < 2**32
                and 0 <= item["mtime_ns"] < 2**63, "invalid indexed metadata")
        require(type(item["sha256"]) is str and len(item["sha256"]) == 64
                and all(c in "0123456789abcdef" for c in item["sha256"]), "invalid content hash")
        attributes = item["xattrs"]
        require(type(attributes) is dict and len(attributes) <= 64, "invalid indexed attributes")
        total = 0
        for name, content in attributes.items():
            require(type(name) is str and type(content) is str
                    and 0 < len(name) <= 510 and len(name) % 2 == len(content) % 2 == 0
                    and all(c in "0123456789abcdef" for c in name + content), "invalid indexed attribute bytes")
            require(b"\0" not in bytes.fromhex(name), "invalid indexed attribute name")
            total += (len(name) + len(content)) // 2
        require(total <= 65536, "indexed attributes exceed byte budget")
    require(names == sorted(set(names)), "duplicate or unordered indexed paths")
    require(sum(item["size"] for item in files) <= MAX_TOTAL_BYTES, "indexed byte budget exceeded")
    return value
