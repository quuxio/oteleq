"""Bounded original/private Go input snapshots independent of provider readers."""

from dataclasses import dataclass
import hashlib
import json
import os
from pathlib import Path, PurePosixPath
import stat

import otelc_capture as capture
from go_provider import require

MAX_FILE_BYTES = 256 * 1024 * 1024
MAX_METADATA_BYTES = 32 * 1024 * 1024
MAX_FILES = 4096
MAX_TREE_BYTES = 256 * 1024 * 1024


def signature(info) -> tuple:
    """Byte identity alone cannot establish that an original file was untouched."""
    return (info.st_dev, info.st_ino, info.st_mode, info.st_uid, info.st_gid,
            info.st_size, info.st_mtime_ns, info.st_ctime_ns, info.st_nlink)


def relative(name: object) -> str:
    """Input metadata cannot escape a fixed root or change path spelling."""
    require(type(name) is str and bool(name) and "\0" not in name and "\\" not in name,
            "invalid Go input name")
    path = PurePosixPath(name)
    require(not path.is_absolute() and str(path) == name and name != "." and ".." not in path.parts,
            "noncanonical Go input name")
    return name


def file(path: Path, maximum: int = MAX_FILE_BYTES, *, keep: bool = False,
         private: bool = False) -> tuple[dict, tuple, bytes]:
    """Hash one stable ordinary input without following links or waiting on a FIFO."""
    require(type(maximum) is int and 0 < maximum <= MAX_FILE_BYTES, "invalid Go input byte budget")
    require(path.is_absolute() and path.resolve(strict=True) == path, "Go input must have a canonical absolute path")
    descriptor = os.open(path, os.O_RDONLY | os.O_NOFOLLOW | os.O_NONBLOCK)
    try:
        before = os.fstat(descriptor)
        require(stat.S_ISREG(before.st_mode) and before.st_size <= maximum, "Go input is special or oversized")
        if private:
            require(before.st_uid == os.getuid() and stat.S_IMODE(before.st_mode) == 0o600 and before.st_nlink == 1,
                    "Go launch metadata must be an owned mode0600 single-link file")
        digest, size, chunks = hashlib.sha256(), 0, []
        with os.fdopen(descriptor, "rb", closefd=False) as stream:
            while block := stream.read(1024 * 1024):
                size += len(block)
                require(size <= maximum, "Go input grew beyond its byte budget")
                digest.update(block)
                if keep:
                    chunks.append(block)
        require(size == before.st_size
                and path.resolve(strict=True) == path
                and signature(before) == signature(os.fstat(descriptor)) == signature(path.lstat()),
                "Go input changed while reading")
    finally:
        os.close(descriptor)
    identity = {"path": str(path), "resolved_path": str(path), "sha256": digest.hexdigest(), "size": size}
    return identity, signature(before), b"".join(chunks)


def identity(path: Path, maximum: int = MAX_FILE_BYTES) -> dict:
    """Observe the actual fixed path; producer metadata never chooses it."""
    return file(path, maximum)[0]


def read(path: Path, *, private: bool = False) -> tuple[dict, dict]:
    """Read finite closed-format JSON while keeping its actual file identity."""
    observed, _, raw = file(path, MAX_METADATA_BYTES, keep=True, private=private)
    value = capture.strict_json(raw)
    require(type(value) is dict, "Go metadata must be a JSON object")
    json.dumps(value, allow_nan=False)
    return value, observed


@dataclass(frozen=True)
class Snapshot:
    """Caller-owned complete file identities and stable original file facts."""

    root: Path
    identities: dict[str, dict]
    facts: dict[str, tuple]

    def verify(self) -> None:
        """Additions, removals, replacements and metadata changes all refuse reuse."""
        require(freeze(self.root) == self, "frozen Go inputs or original file facts changed")


def freeze(root: Path) -> Snapshot:
    """Enumerate every ordinary input, refusing incomplete directory inspection."""
    require(root.is_absolute() and root.resolve(strict=True) == root and root.is_dir(),
            "Go input root must be a canonical directory")
    identities, facts, total = {}, {}, 0
    for path in capture.tree_paths(root, excluded={".git"}):
        name = path.relative_to(root).as_posix()
        if ".git" in Path(name).parts:
            continue
        require(not path.is_symlink(), "linked Go input is unsupported")
        if path.is_dir():
            continue
        relative(name)
        observed, stable, _ = file(path)
        total += observed["size"]
        require(len(identities) < MAX_FILES and total <= MAX_TREE_BYTES, "Go input tree exceeds its file/byte budget")
        identities[name], facts[name] = observed, stable
    return Snapshot(root, identities, facts)


def content(snapshot: Snapshot) -> dict:
    """Compare private copies without conflating their distinct paths and inodes."""
    return {name: {key: value[key] for key in ("sha256", "size")}
            for name, value in snapshot.identities.items()}
