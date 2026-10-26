"""Run a qualification, then compress all owned outputs, including failures."""

from __future__ import annotations

import argparse
from contextlib import ExitStack
import fcntl
import json
import os
from pathlib import Path
import signal
import shutil
import stat
import subprocess
import sys
import tarfile
import uuid
import zlib

from ci import qualification_bundle as bundle
from ci.qualification_paths import checked


def _marker(root: Path) -> Path:
    return root.with_name(root.name + ".compressed.json")


def _publish(root: Path, value: dict) -> None:
    """Publish and sync the archive trust anchor before retiring raw data."""
    marker = _marker(root)
    temporary = marker.with_name(marker.name + ".pending-" + uuid.uuid4().hex)
    with temporary.open("xb") as stream:
        stream.write(bundle.canonical(value))
        stream.flush()
        os.fsync(stream.fileno())
    os.replace(temporary, marker)
    descriptor = os.open(marker.parent, os.O_RDONLY | os.O_DIRECTORY)
    try:
        os.fsync(descriptor)
    finally:
        os.close(descriptor)


def _previous(root: Path, command: list[str]) -> dict | None:
    marker = _marker(root)
    if not root.exists() and not marker.exists():
        return None
    bundle.require(not root.is_symlink() and (not root.exists()
                   or (root.is_dir() and root.resolve() == root)),
                   "existing output is not a canonical directory")
    bundle.require("--retained-only" in command and marker.is_file()
                   and not marker.is_symlink(),
                   "output already exists; use a new path or explicit retained-only replay")
    previous = json.loads(marker.read_text())
    bundle.require(previous.get("root") == str(root)
                   and previous.get("state") == "compressed",
                   "previous qualification is not a complete compressed bundle")
    return previous


def _prepare(roots: list[Path], command: list[str]) -> None:
    """Refuse pre-existing unrelated trees before any qualification command starts."""
    bundle.require(len(set(roots)) == len(roots), "duplicate qualification output")
    previous_roots = {}
    for root in roots:
        bundle.require(not root.is_symlink(), "qualification output is a symbolic link")
        bundle.require(root.parent.is_dir() and root.parent == root.parent.resolve()
                       and not Path.cwd().resolve().is_relative_to(root),
                       "qualification output needs a canonical existing external parent")
        bundle.require(not any(root != other and (root.is_relative_to(other)
                       or other.is_relative_to(root)) for other in roots),
                       "qualification outputs overlap")
        previous_roots[root] = _previous(root, command)
    for root, previous in previous_roots.items():
        if previous is None:
            with _marker(root).open("x") as output:
                json.dump({"root": str(root), "state": "running"}, output)
        elif not root.exists():
            bundle.restore(Path(previous["store"]), previous["receipt_sha256"], root)


def _archive_root(root: Path, command: list[str], code: int, pid: int) -> None:
    root = checked(root)
    root.mkdir(mode=0o700, exist_ok=True)
    record = root / ("qualification-process-" + uuid.uuid4().hex + ".json")
    record.write_bytes(bundle.canonical({"command": command, "exit_code": code, "pid": pid}))
    store = root.with_name(root.name + ".bundle-" + uuid.uuid4().hex)
    result = bundle.pack(root, store)
    state = {**result, "state": "compressed", "command_exit_code": code}
    _publish(root, state)
    bundle.check_originals(root, store, closed_links=True)
    shutil.rmtree(root)
    result["raw_removed"] = True
    _publish(root, {**state, "raw_removed": True})
    print(json.dumps({"qualification_bundle": result}, sort_keys=True))


def _compress(roots: list[Path], command: list[str], code: int, pid: int) -> bool:
    errors = []
    for root in roots:
        try:
            _archive_root(root, command, code, pid)
        except (OSError, ValueError, EOFError, tarfile.TarError, zlib.error) as error:
            errors.append(str(error))
            print("qualification compression refused; preserve raw outputs: " + str(error),
                  file=sys.stderr)
    return not errors


def _run(roots: list[Path], command: list[str]) -> int:
    """Keep command failure primary; never remove data after failed compression."""
    _prepare(roots, command)
    process = subprocess.Popen(command, start_new_session=True)
    interrupted = None
    handlers = {}

    def stop(signum: int, _frame: object) -> None:
        nonlocal interrupted
        interrupted = signum
        try:
            os.killpg(process.pid, signum)
        except ProcessLookupError:
            pass

    for signum in (signal.SIGINT, signal.SIGTERM):
        handlers[signum] = signal.signal(signum, stop)
    try:
        code = process.wait()
    finally:
        for signum, handler in handlers.items():
            signal.signal(signum, handler)
    signalled = code < 0 or code in (130, 137, 143)
    if interrupted:
        code = 128 + interrupted
    elif code < 0:
        code = 128 - code
    # The maintained qualifiers own exporter/child cleanup. A signal can
    # interrupt that cleanup, so keep raw evidence for an explicit cold retry.
    if interrupted or signalled:
        print("qualification interrupted; raw evidence retained; compress only after all children stop",
              file=sys.stderr)
        return code
    compressed = _compress(roots, command, code, process.pid)
    if code:
        return code
    return 0 if compressed else 2


def run(roots: list[Path], command: list[str]) -> int:
    """Hold exclusive leases for every output until its final archive is published."""
    with ExitStack() as stack:
        for root in sorted(set(roots)):
            path = root.with_name(root.name + ".qualification.lock")
            descriptor = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_NOFOLLOW
                                 | os.O_NONBLOCK, 0o600)
            stack.callback(os.close, descriptor)
            value = os.fstat(descriptor)
            bundle.require(stat.S_ISREG(value.st_mode)
                           and value.st_uid == os.getuid() and value.st_nlink == 1,
                           "unsafe qualification output lease")
            fcntl.flock(descriptor, fcntl.LOCK_EX | fcntl.LOCK_NB)
        return _run(roots, command)


def main(argv: list[str] | None = None) -> int:
    """Wrap a fixed caller-selected command; archive metadata never selects execution."""
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--root", type=Path, action="append", required=True)
    parser.add_argument("command", nargs=argparse.REMAINDER)
    args = parser.parse_args(argv)
    command = args.command[1:] if args.command[:1] == ["--"] else args.command
    if not command:
        parser.error("a qualification command is required after --")
    try:
        roots = [checked(path.absolute(), new=True) for path in args.root]
        return run(roots, command)
    except (OSError, ValueError, EOFError, tarfile.TarError, zlib.error) as error:
        print("qualification did not start: " + str(error), file=sys.stderr)
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
