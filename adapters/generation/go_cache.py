"""Bound a private SDK compiler cache without touching retained caller exports."""

from contextlib import contextmanager
import json
import os
from pathlib import Path
import re
import stat
from typing import Iterator

from go_provider import require, same
import go_files as files
import otelc_capture as capture

MARKER = "owner.json"
PROFILE = "oteleq.go.sdk-cache-v1"
DEFAULT_MAX_BYTES = 1024 ** 3
MAX_ENTRIES = 100000
DIRECTORY_FLAGS = os.O_RDONLY | getattr(os, "O_DIRECTORY", 0) | getattr(os, "O_NOFOLLOW", 0)


def settings(value: object) -> dict:
    """Only an explicit external directory can enable bounded SDK cache reuse."""
    require(type(value) is dict and set(value) <= {"directory", "max_bytes"}, "invalid Go build_cache fields")
    name = value.get("directory")
    require(type(name) is str and "\0" not in name and "\\" not in name, "invalid Go build_cache directory")
    path = Path(name)
    require(path.is_absolute() and str(path) == name and ".." not in path.parts and path != Path("/"),
            "Go build_cache directory must be a canonical absolute path")
    maximum = value.get("max_bytes", DEFAULT_MAX_BYTES)
    require(type(maximum) is int and 1024 ** 2 <= maximum <= 2 ** 63 - 1,
            "Go build_cache max_bytes must be an integer from 1048576 to 9223372036854775807")
    return {"directory": name, "max_bytes": maximum}


def ordinary(info) -> tuple:
    """A disposable cache file cannot be a link to retained input or another user."""
    require(stat.S_ISREG(info.st_mode) and info.st_uid == os.getuid() and info.st_nlink == 1,
            "Go SDK cache contains a foreign, linked or special file")
    return files.signature(info)


def location(options: dict, protected: list[Path]) -> Path:
    """Refuse source and retained-input overlap before creating cache files."""
    root = Path(settings(options)["directory"])
    for path in protected:
        require(path.is_absolute() and path.resolve() == path, "Go SDK cache protection needs canonical paths")
        require(not capture.path_within(root, path) and not capture.path_within(path, root),
                "Go SDK cache overlaps source, retained inputs or execution evidence")
    return root


def directory(descriptor: int) -> tuple[int, int]:
    """Anchor directory operations to an owned real directory descriptor."""
    info = os.fstat(descriptor)
    require(stat.S_ISDIR(info.st_mode) and info.st_uid == os.getuid(), "invalid Go SDK cache directory")
    return info.st_dev, info.st_ino


def entry_members(descriptor: int, name: str, info) -> dict:
    """Bind one ordinary cache file or a bounded cached executable directory."""
    if not stat.S_ISDIR(info.st_mode):
        return {"": ordinary(info)}
    require(name.endswith("-d"), "invalid Go SDK executable cache key")
    child = os.open(name, DIRECTORY_FLAGS, dir_fd=descriptor)
    try:
        directory(child)
        names = os.listdir(child)
        require(0 < len(names) <= 16, "invalid Go SDK executable cache denominator")
        return {member: ordinary(os.stat(member, dir_fd=child, follow_symlinks=False)) for member in names}
    finally:
        os.close(child)


def entries(root: int) -> list[dict]:
    """Inspect the pinned Go cache layout, including its cached executable folders."""
    result = []
    for shard in sorted(os.listdir(root)):
        if shard in ("README", "trim.txt"):
            info = os.stat(shard, dir_fd=root, follow_symlinks=False)
            ordinary(info)
            require(info.st_size <= 4096, "oversized Go SDK cache control file")
            continue
        require(re.fullmatch(r"[0-9a-f]{2}", shard) is not None, "unexpected Go SDK cache entry")
        descriptor = os.open(shard, DIRECTORY_FLAGS, dir_fd=root)
        try:
            directory(descriptor)
            for name in sorted(os.listdir(descriptor)):
                require(re.fullmatch(shard + r"[0-9a-f]{62}-[ad]", name) is not None,
                        "unexpected Go SDK cache key")
                info = os.stat(name, dir_fd=descriptor, follow_symlinks=False)
                members = entry_members(descriptor, name, info)
                result.append({"shard": shard, "name": name, "directory": bool("" not in members),
                               "inode": (info.st_dev, info.st_ino), "members": members,
                               "bytes": sum(row[5] for row in members.values()), "mtime_ns": info.st_mtime_ns})
                require(len(result) <= MAX_ENTRIES, "Go SDK cache entry budget exceeded")
        finally:
            os.close(descriptor)
    return result


def remove(root: int, entry: dict) -> None:
    """Unlink only the inspected cache members through held directory descriptors."""
    shard = os.open(entry["shard"], DIRECTORY_FLAGS, dir_fd=root)
    child = None
    try:
        directory(shard)
        info = os.stat(entry["name"], dir_fd=shard, follow_symlinks=False)
        require((info.st_dev, info.st_ino) == entry["inode"], "Go SDK cache key changed before eviction")
        descriptor = shard
        if entry["directory"]:
            child = os.open(entry["name"], DIRECTORY_FLAGS, dir_fd=shard)
            directory(child)
            require(set(os.listdir(child)) == set(entry["members"]), "Go SDK executable cache changed")
            descriptor = child
        for member, expected in entry["members"].items():
            name = member or entry["name"]
            observed = os.stat(name, dir_fd=descriptor, follow_symlinks=False)
            require(ordinary(observed) == expected, "Go SDK cache file changed before eviction")
            os.unlink(name, dir_fd=descriptor)
        if child is not None:
            os.rmdir(entry["name"], dir_fd=shard)
    finally:
        if child is not None:
            os.close(child)
        os.close(shard)


def trim(root: Path, maximum: int, receipt: Path, *, expected: tuple[int, int] | None = None) -> None:
    """Retain an eviction receipt and keep compiler cache bytes below the limit."""
    require(type(maximum) is int and maximum >= 0, "invalid Go SDK cache byte budget")
    descriptor = os.open(root, DIRECTORY_FLAGS)
    value = {"schema_version": 1, "kind": "oteleq.go.sdk-cache-maintenance", "directory": str(root),
             "max_bytes": maximum, "removed": [], "complete": False}
    try:
        actual = directory(descriptor)
        require(expected is None or expected == actual, "Go SDK compiler cache identity changed")
        require(root.resolve(strict=True) == root, "Go SDK compiler cache has aliases")
        expected = actual
        candidates = entries(descriptor)
        total = sum(row["bytes"] for row in candidates)
        value["before_bytes"] = total
        for entry in sorted(candidates, key=lambda row: (row["mtime_ns"], row["shard"], row["name"])):
            if total <= maximum:
                break
            info = root.lstat()
            require((info.st_dev, info.st_ino) == expected and not root.is_symlink(), "Go SDK cache directory changed")
            remove(descriptor, entry)
            value["removed"].append(entry)
            total -= entry["bytes"]
        removed = {(row["shard"], row["name"]) for row in value["removed"]}
        remaining = [row for row in candidates if (row["shard"], row["name"]) not in removed]
        require(entries(descriptor) == remaining, "Go SDK cache changed during eviction")
        info = root.lstat()
        require((info.st_dev, info.st_ino) == expected and root.resolve(strict=True) == root,
                "Go SDK compiler cache identity changed")
        value.update(after_bytes=total, complete=True)
    finally:
        os.close(descriptor)
        with receipt.open("x") as stream:
            json.dump(value, stream, sort_keys=True, indent=2)
            stream.write("\n")


@contextmanager
def lease(options: dict, protected: list[Path], evidence: Path) -> Iterator[dict[str, str]]:
    """Serialise SDK builds in a marked cache; failed builds retain their cache."""
    import fcntl

    selected = settings(options)
    root = location(selected, protected)
    require(root.parent.resolve(strict=True) == root.parent, "Go SDK cache parent has aliases")
    try:
        root.mkdir(mode=0o700)
        info = root.stat()
        marker = {"schema_version": 1, "kind": PROFILE, "directory": str(root), "uid": os.getuid(),
                  "device": info.st_dev, "inode": info.st_ino}
        descriptor = os.open(root / MARKER, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
        with os.fdopen(descriptor, "w") as stream:
            json.dump(marker, stream, sort_keys=True)
            stream.write("\n")
    except FileExistsError:
        pass
    info = root.lstat()
    require(stat.S_ISDIR(info.st_mode) and info.st_uid == os.getuid() and stat.S_IMODE(info.st_mode) == 0o700
            and root.resolve(strict=True) == root, "Go SDK cache must be an owned private real directory")
    marker, _ = files.read(root / MARKER, private=True)
    require(same(marker, {"schema_version": 1, "kind": PROFILE, "directory": str(root), "uid": os.getuid(),
                          "device": info.st_dev, "inode": info.st_ino}), "foreign Go SDK cache marker")
    require(set(os.listdir(root)) <= {MARKER, "lock", "build"}, "foreign Go SDK cache contents")
    root_descriptor = os.open(root, DIRECTORY_FLAGS)
    lock = None
    try:
        root_identity = directory(root_descriptor)
        require(root_identity == (info.st_dev, info.st_ino), "Go SDK cache root changed")
        lock = os.open("lock", os.O_RDWR | os.O_CREAT | os.O_NOFOLLOW, 0o600, dir_fd=root_descriptor)
        ordinary(os.fstat(lock))
        try:
            fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
        except BlockingIOError as error:
            raise ValueError("Go SDK cache is already in use by another build") from error
        cache = root / "build"
        try:
            os.mkdir("build", mode=0o700, dir_fd=root_descriptor)
        except FileExistsError:
            pass
        current = root.lstat()
        require((current.st_dev, current.st_ino) == root_identity and not root.is_symlink(),
                "Go SDK cache root changed")
        require(not cache.is_symlink() and cache.resolve(strict=True) == cache, "linked Go SDK compiler cache")
        cache_descriptor = os.open("build", DIRECTORY_FLAGS, dir_fd=root_descriptor)
        try:
            cache_identity = directory(cache_descriptor)
        finally:
            os.close(cache_descriptor)
        trim(cache, selected["max_bytes"], evidence / "sdk-cache-before.json", expected=cache_identity)
        yield {"GOCACHE": str(cache), "GOCACHEPROG": ""}
        current = root.lstat()
        require((current.st_dev, current.st_ino) == root_identity and not root.is_symlink(),
                "Go SDK cache root changed during compilation")
        trim(cache, selected["max_bytes"], evidence / "sdk-cache-after.json", expected=cache_identity)
    finally:
        if lock is not None:
            os.close(lock)
        os.close(root_descriptor)
