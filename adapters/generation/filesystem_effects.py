"""Bounded independent filesystem fixtures and exact boundary observations."""
from collections.abc import Callable, Iterator
from contextlib import ExitStack, contextmanager
import json
import os
from pathlib import Path
import re
import stat
from typing import Any

PREFIX = "filesystem:"
DEFAULT_LIMITS = {"max_entries": 256, "max_bytes": 65536, "max_depth": 16}
RESERVED = {"PATH", "HOME", "SHELL", "TMPDIR", "TMP", "TEMP", "USER", "LOGNAME", "PWD", "OLDPWD", "LANG"}
RESERVED_PREFIXES = ("OTEL", "OTELEQ", "RUST", "CARGO", "GO", "NODE", "PYTHON", "JAVA", "LD_", "DYLD_", "LC_", "XDG_")


def relative(value: Any) -> str:
    """Accept literal portable relative paths without silently cleaning them."""
    if (type(value) is not str or not value or len(value.encode("utf-8")) > 1024
            or any(char in value for char in ("\\", ":", "\0"))
            or any(part in ("", ".", "..") or len(part.encode("utf-8")) > 255 for part in value.split("/"))):
        raise ValueError("filesystem fixture paths require literal safe relative components")
    return value


def initial_files(value: Any, keys: Callable, integer: Callable) -> list[dict]:
    """Freeze exact binary file contents and permission bits."""
    if type(value) is not list or len(value) > 1023:
        raise ValueError("filesystem.files requires a bounded array")
    result = []
    for item in value:
        keys(item, {"path", "hex", "mode"}, "filesystem.files")
        payload = item.get("hex", "")
        if type(payload) is not str or len(payload) > 131072 or not re.fullmatch(r"(?:[0-9a-fA-F]{2})*", payload):
            raise ValueError("filesystem file hex requires bounded complete byte pairs")
        result.append({"path": relative(item.get("path")), "hex": payload.lower(),
                       "mode": integer(item.get("mode", 0o600), 0, 0o777, "filesystem file mode")})
    return result


def declaration(value: Any, keys: Callable, integer: Callable) -> dict:
    """Validate one named independently reconstructed application fixture."""
    keys(value, {"name", "environment", "path_mode", "files", "directories", *DEFAULT_LIMITS}, "effects.filesystem")
    name, environment = value.get("name"), value.get("environment")
    if type(name) is not str or not re.fullmatch(r"[a-z][a-z0-9_-]{0,63}", name):
        raise ValueError("filesystem fixture name requires a short lowercase identifier")
    if (type(environment) is not str or not re.fullmatch(r"[A-Z][A-Z0-9_]{0,127}", environment)
            or environment in RESERVED or environment.startswith(RESERVED_PREFIXES)):
        raise ValueError("filesystem environment requires a distinct application variable, outside runtime/tool controls")
    path_mode = value.get("path_mode", "absolute")
    if type(path_mode) is not str or path_mode not in ("absolute", "relative"):
        raise ValueError("filesystem.path_mode must be absolute or relative")
    directories = value.get("directories", [])
    if type(directories) is not list or len(directories) > 1023:
        raise ValueError("filesystem.directories requires a bounded array")
    result = {"name": name, "environment": environment, "path_mode": path_mode,
              "files": initial_files(value.get("files", []), keys, integer),
              "directories": [relative(item) for item in directories]}
    for key, maximum in (("max_entries", 1024), ("max_bytes", 65536), ("max_depth", 16)):
        result[key] = integer(value.get(key, DEFAULT_LIMITS[key]), 0 if key == "max_bytes" else 1, maximum, "filesystem." + key)
    validate_layout(result)
    return result


def validate_layout(value: dict) -> None:
    """Reject duplicate/conflicting or over-budget initial fixture requests."""
    files = [item["path"] for item in value["files"]]
    paths = [*files, *value["directories"]]
    if len(paths) != len(set(paths)):
        raise ValueError("filesystem initial paths must be distinct")
    parents = {str(parent) for name in paths for parent in Path(name).parents if str(parent) != "."}
    if set(files) & parents:
        raise ValueError("filesystem file cannot also be a directory")
    if (len(set(paths) | parents) + 1 > value["max_entries"]
            or sum(len(item["hex"]) // 2 for item in value["files"]) > value["max_bytes"]
            or any(len(name.split("/")) > value["max_depth"] for name in paths)):
        raise ValueError("filesystem initial fixture exceeds its declared limits")


def settings(value: Any, keys: Callable, integer: Callable) -> dict:
    """Unknown effects remain rejected; requested fixture names and bindings are unique."""
    keys(value, {"filesystem"}, "effects")
    selected = value.get("filesystem", [])
    if type(selected) is not list or len(selected) > 8:
        raise ValueError("effects.filesystem requires at most eight declarations")
    result = [declaration(item, keys, integer) for item in selected]
    for key in ("name", "environment"):
        if len({item[key] for item in result}) != len(result):
            raise ValueError("filesystem fixture names and environments must be distinct")
    return {"filesystem": result}


def selected(configuration: dict) -> list[dict]:
    return configuration.get("effects", {}).get("filesystem", [])


def channels(configuration: dict) -> list[str]:
    return [PREFIX + item["name"] for item in selected(configuration)]


def unavailable(configuration: dict) -> str | None:
    """A requested unsupported host remains a named blocker before application launch."""
    if selected(configuration) and not (all(hasattr(os, name) for name in ("O_NOFOLLOW", "O_NONBLOCK", "O_DIRECTORY"))
                                         and os.scandir in os.supports_fd and {os.open, os.stat, os.mkdir} <= os.supports_dir_fd):
        return "filesystem effects require descriptor-based POSIX capture on the selected host"
    return None


def bind(entry: dict, configuration: dict) -> None:
    reason = unavailable(configuration)
    if entry["status"] == "ready" and reason:
        entry["reason"], entry["status"] = reason, "blocked"


def stamp(value: os.stat_result) -> tuple:
    """Use volatile metadata only to refuse changed-during-read observations."""
    return (value.st_dev, value.st_ino, value.st_mode, value.st_size, value.st_mtime_ns, value.st_ctime_ns, value.st_nlink)


class Reader:
    """Never follow links or block on special files while walking one owned root."""
    def __init__(self, limits: dict, budget: int = 262144):
        self.limits = limits
        self.budget = budget
        self.encoded = 64
        self.entries: list[dict] = []
        self.bytes = 0

    def visit(self, parent: int, name: str, relative_name: bytes, depth: int) -> None:
        if len(self.entries) >= self.limits["max_entries"] or depth > self.limits["max_depth"] or len(relative_name) > 1024:
            raise ValueError("filesystem entry/depth limit exceeded")
        before = os.stat(name, dir_fd=parent, follow_symlinks=False)
        if not (stat.S_ISDIR(before.st_mode) or stat.S_ISREG(before.st_mode)):
            raise ValueError("filesystem symlink or special file requires a separate observation profile")
        flags = os.O_RDONLY | os.O_NOFOLLOW | os.O_NONBLOCK
        if stat.S_ISDIR(before.st_mode):
            flags |= os.O_DIRECTORY
        descriptor = os.open(name, flags, dir_fd=parent)
        try:
            if stamp(os.fstat(descriptor)) != stamp(before):
                raise ValueError("filesystem entry changed before capture")
            record = {"path_hex": relative_name.hex(), "mode": stat.S_IMODE(before.st_mode)}
            if stat.S_ISDIR(before.st_mode):
                record["kind"] = "directory"
                self.record(record)
                for child in self.names(descriptor):
                    child_name = relative_name + (b"/" if relative_name else b"") + os.fsencode(child)
                    self.visit(descriptor, child, child_name, depth + 1)
            else:
                record.update(kind="file", hex=self.read_file(descriptor).hex())
                self.record(record)
            if stamp(os.fstat(descriptor)) != stamp(before) or stamp(os.stat(name, dir_fd=parent, follow_symlinks=False)) != stamp(before):
                raise ValueError("filesystem entry changed during capture")
        finally:
            os.close(descriptor)

    def record(self, value: dict) -> None:
        self.encoded += len(json.dumps(value, ensure_ascii=True, separators=(",", ":"))) + 1
        if self.encoded > self.budget:
            raise ValueError("filesystem encoded observation budget exceeded")
        self.entries.append(value)

    def names(self, descriptor: int) -> list[str]:
        names = []
        with os.scandir(descriptor) as stream:
            for item in stream:
                if len(names) >= self.limits["max_entries"] - len(self.entries):
                    raise ValueError("filesystem entry limit exceeded")
                names.append(item.name)
        return sorted(names, key=os.fsencode)

    def read_file(self, descriptor: int) -> bytes:
        result = bytearray()
        while True:
            chunk = os.read(descriptor, min(65536, self.limits["max_bytes"] - self.bytes + 1))
            if not chunk:
                return bytes(result)
            self.bytes += len(chunk)
            if self.bytes > self.limits["max_bytes"]:
                raise ValueError("filesystem byte limit exceeded")
            result.extend(chunk)


def snapshot(root: Path, limits: dict, *, budget: int = 262144) -> dict:
    """An inaccessible or unsupported requested observation is an explicit gap."""
    reader = Reader(limits, budget)
    parent = None
    try:
        try:
            parent = os.open(root.parent, os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW)
            reader.visit(parent, root.name, b"", 0)
            return {"complete": True, "entries": reader.entries, "gaps": []}
        except FileNotFoundError as error:
            if error.filename == root.name and not reader.entries:
                return {"complete": True, "entries": [{"path_hex": "", "kind": "absent"}], "gaps": []}
            return {"complete": False, "entries": reader.entries, "gaps": ["filesystem entry disappeared during capture"]}
        except (ValueError, OSError) as error:
            return {"complete": False, "entries": reader.entries, "gaps": [str(error)]}
    finally:
        if parent is not None:
            os.close(parent)


@contextmanager
def directory(name: str | Path, parent: int | None = None) -> Iterator[int]:
    descriptor = os.open(name, os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW, dir_fd=parent)
    try:
        yield descriptor
    finally:
        os.close(descriptor)


def mkdir(parent: int, name: str) -> None:
    try:
        os.mkdir(name, mode=0o700, dir_fd=parent)
    except FileExistsError:
        pass  # The following no-follow directory open still verifies the entry.


@contextmanager
def subdirectories(root: int, parts: list[str]) -> Iterator[int]:
    with ExitStack() as stack:
        descriptor = root
        for part in parts:
            mkdir(descriptor, part)
            descriptor = stack.enter_context(directory(part, descriptor))
            os.fchmod(descriptor, 0o700)
        yield descriptor


def seed(folder: Path, item: dict) -> Path:
    """Create exclusively through owned descriptors so setup cannot follow a link."""
    folder.mkdir(parents=True, exist_ok=True)
    with directory(folder) as base:
        mkdir(base, "filesystem-fixtures")
        with directory("filesystem-fixtures", base) as parent:
            os.mkdir(item["name"], mode=0o700, dir_fd=parent)
            with directory(item["name"], parent) as root:
                os.fchmod(root, 0o700)
                for name in item["directories"]:
                    with subdirectories(root, name.split("/")):
                        pass
                seed_files(root, item["files"])
    return folder / "filesystem-fixtures" / item["name"]


def seed_files(root: int, files: list[dict]) -> None:
    for item in files:
        parts = item["path"].split("/")
        with subdirectories(root, parts[:-1]) as parent:
            descriptor = os.open(parts[-1], os.O_WRONLY | os.O_CREAT | os.O_EXCL | os.O_NOFOLLOW, 0o600, dir_fd=parent)
            with os.fdopen(descriptor, "wb") as stream:
                stream.write(bytes.fromhex(item["hex"]))
                os.fchmod(stream.fileno(), item["mode"])


def prepare(folder: Path, configuration: dict, *, working_directory: Path | None = None) -> tuple[list[dict], dict[str, str]]:
    """Reconstruct declared data independently after compilation, before worker launch."""
    reason = unavailable(configuration)
    if reason:
        raise ValueError(reason)
    states, environment = [], {}
    for item in selected(configuration):
        if item["path_mode"] == "relative" and working_directory is None:
            raise ValueError("relative filesystem binding requires the declared worker directory")
        root = seed(folder, item)
        budget = configuration["limits"]["max_capture_bytes"]
        before = snapshot(root, item, budget=budget)
        if not before["complete"]:
            raise ValueError("filesystem initial fixture capture is incomplete: " + "; ".join(before["gaps"]))
        states.append({"settings": item, "root": root, "before": before, "budget": budget})
        environment[item["environment"]] = os.path.relpath(root, working_directory) if item["path_mode"] == "relative" else str(root)
    return states, environment


def finish(states: list[dict], folder: Path) -> tuple[dict[str, list[int]], bool]:
    """Keep raw boundary records and exact named byte channels, with no silent truncation."""
    result, complete = {}, True
    for state in states:
        after = snapshot(state["root"], state["settings"], budget=state["budget"])
        value = {"filesystem_schema_version": 1, "before": state["before"], "after": after}
        raw = json.dumps(value, sort_keys=True, ensure_ascii=True, separators=(",", ":")).encode()
        (folder / ("filesystem-" + state["settings"]["name"] + ".json")).write_bytes(raw)
        result[PREFIX + state["settings"]["name"]] = list(raw)
        complete &= after["complete"]
    return result, complete
