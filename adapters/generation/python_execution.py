"""Bind execution-1 records to the caller's actual owned supervisor and inputs."""

from dataclasses import dataclass
import os
from pathlib import Path
import re
import stat

import python_code
import python_journal
import python_prepared as prepared
import python_provider as provider

SHARED = {"schema_version", "kind", "supervisor_pid", "parent_pid", "process_group",
          "request_sha256", "plan_sha256", "prepared_sha256"}


@dataclass(frozen=True)
class Owner:
    """Known Popen/kernel facts supplied by the consumer, not producer metadata."""

    pid: int
    parent_pid: int
    argv: tuple[str, ...]
    returncode: int
    python_version: int


@dataclass(frozen=True)
class Execution:
    """Transport/input facts remain separate from selected-source admission."""

    owner: Owner
    application_pid: int
    sdk_pid: int | None
    launch_id: str | None
    journal: python_journal.Journal
    descriptors: tuple[python_code.Descriptor, ...]
    final: dict


def pid(value: object) -> bool:
    """PID zero, booleans and unavailable values do not identify a process."""
    return type(value) is int and value > 0


def shared(owner: Owner, launch: dict) -> dict:
    """Reproduce only fixed supervisor identity and complete prepared digests."""
    return {"schema_version": 1, "supervisor_pid": owner.pid, "parent_pid": owner.parent_pid,
            "process_group": owner.pid, "request_sha256": prepared.digest(launch["request"]),
            "plan_sha256": prepared.digest(launch["plan"]), "prepared_sha256": prepared.digest(launch["prepared"])}


def verify_shared(value: dict, expected: dict, kind: str, fields: set[str]) -> None:
    """A stale record, altered lane or different process cannot share this run."""
    provider.require(type(value) is dict and set(value) == SHARED | fields
                     and provider.same({key: value[key] for key in SHARED}, {**expected, "kind": kind}),
                     "Python execution process identity or closed record fields differ")


def native_command(value: object, launch: dict) -> None:
    """The recorded native recipe verifies fixed inputs; it never chooses argv."""
    provider.require(type(value) is list and all(type(item) is str for item in value)
                     and len(value) == 4 + len(launch["plan"]["native_arguments"]), "invalid native Python command fields")
    provider.require(re.fullmatch("[1-9][0-9]{0,9}", value[1]) is not None and 3 <= int(value[1]) <= 0x7fffffff,
                     "invalid inherited Python journal descriptor")
    expected = [launch["prepared"]["driver"]["path"], value[1], launch["plan"]["python"],
                launch["plan"]["argv0"], *launch["plan"]["native_arguments"]]
    provider.require(value == expected, "native Python executable, flags or literal arguments differ")


def sdk_identity(runtime: Path, app: dict, expected: dict, plain: bool) -> tuple[int | None, str | None]:
    """SDK readiness/spawn evidence belongs to this owner and one fresh launch."""
    if plain:
        provider.require(app["sdk_ready"] is False and app["sdk_pid"] is app["sdk_launch_id"] is None
                         and not (runtime / "sdk").exists() and not (runtime / "sdk").is_symlink()
                         and not (runtime / "health.json").exists() and not (runtime / "health.json").is_symlink(),
                         "plain Python lane contains SDK or health evidence")
        return None, None
    identity, launch = app["sdk_pid"], app["sdk_launch_id"]
    provider.require(app["sdk_ready"] is True and pid(identity)
                     and identity not in (app["application_pid"], expected["supervisor_pid"], expected["parent_pid"])
                     and type(launch) is str and re.fullmatch("[0-9a-f]{32}", launch) is not None,
                     "Python SDK process or launch identity is unavailable")
    directory = runtime / "sdk"
    info = directory.lstat()
    provider.require(directory.is_dir() and not directory.is_symlink() and info.st_uid == os.getuid()
                     and stat.S_IMODE(info.st_mode) == 0o700, "Python SDK directory is not private")
    spawned, _ = prepared.read(directory / "python-sdk-spawned.json")
    ready, _ = prepared.read(directory / "python-sdk-ready.json")
    provider.require(provider.same(spawned, {"schema_version": 1, "pid": identity,
                                           "parent_pid": expected["supervisor_pid"], "launch_id": launch})
                     and provider.same(ready, {"schema_version": 1, "pid": identity, "launch_id": launch}),
                     "Python SDK spawn/readiness differs from the owning application launch")
    return identity, launch


def source_summary(row: python_journal.SourceRecord) -> dict:
    """Bind producer summaries to every actual ordered input record."""
    return {"path_hex": row.path.hex(), "sha256": row.sha256, "device": row.device,
            "inode": row.inode, "mtime_ns": row.mtime_ns}


def entry_evidence(runtime: Path, intent: prepared.Intent, application: int, python_version: int) -> tuple:
    """Recompute the native entry summary and validate code graphs independently."""
    path = runtime / "python-inputs.journal"
    journal = python_journal.read(path, application)
    entries = [row for row in journal.records if type(row) is python_journal.SourceRecord and row.kind == 1]
    imports = [row for row in journal.records if type(row) is python_journal.SourceRecord and row.kind == 3]
    codes = [row for row in journal.records if type(row) is python_journal.CodeRecord]
    provider.require(journal.complete and len(entries) == 1, "native Python entry input is incomplete")
    entry = intent.entry if intent.entry.is_absolute() else intent.project / intent.entry
    entry = entry.resolve(strict=True)
    actual = Path(os.fsdecode(entries[0].path))
    actual = actual if actual.is_absolute() else intent.project / actual
    captured = entries[0]
    metadata = entry.stat()
    provider.require(actual.resolve(strict=True) == entry and captured.content == entry.read_bytes()
                     and (captured.device, captured.inode, captured.mtime_ns, captured.mode)
                     == (metadata.st_dev, metadata.st_ino, metadata.st_mtime_ns, metadata.st_mode),
                     "native Python entry bytes or opened-file identity differ")
    provider.require(all(row.python_version == python_version for row in codes), "native Python code interpreter differs")
    descriptors = tuple(python_code.decode(row) for row in codes)
    summary = {"phase": "complete", "python_finalized": journal.python_finalized,
               "capture_failures": journal.capture_failures, "journal_failures": journal.journal_failures,
               "journal": prepared.file_identity(path), "sources": list(map(source_summary, entries)),
               "imports": list(map(source_summary, imports)), "codes": [
                   {"id": row.identity, "path_hex": row.path.hex(), "sha256": row.sha256,
                    "offset": row.offset, "python_version": row.python_version, "descriptor_version": row.descriptor_version}
                   for row in codes]}
    return journal, descriptors, summary


def read(intent: prepared.Intent, launch: dict, owner: Owner, catalogue: dict) -> Execution:
    """Only a completed matched supervisor/SDK pair can supply final evidence."""
    provider.require(type(owner) is Owner and pid(owner.pid) and pid(owner.parent_pid)
                     and owner.pid != owner.parent_pid and type(owner.returncode) is int and owner.returncode == 0
                     and type(owner.argv) is tuple and all(type(item) is str for item in owner.argv)
                     and list(owner.argv) == prepared.expected_command(intent)
                     and type(owner.python_version) is int and owner.python_version >> 24 == 3
                     and (owner.python_version >> 16 & 255) >= 12, "actual Python supervisor exit or identity differs")
    prepared.verify(launch, intent, catalogue)
    runtime = intent.runtime.resolve(strict=True)
    start, _ = prepared.read(runtime / "python-supervisor-start.json")
    app, _ = prepared.read(runtime / "python-application-start.json")
    final, _ = prepared.read(runtime / "python-execution.json")
    expected = shared(owner, launch)
    verify_shared(start, expected, "otelc.python.supervisor", set())
    verify_shared(app, expected, "otelc.python.application", {
        "application_pid", "sdk_pid", "sdk_ready", "sdk_launch_id", "native_command"})
    provider.require(pid(app["application_pid"]) and app["application_pid"] not in (owner.pid, owner.parent_pid),
                     "Python application PID is unavailable or is the supervisor")
    native_command(app["native_command"], launch)
    sdk, token = sdk_identity(runtime, app, expected, intent.plain)
    verify_shared(final, expected, "otelc.python.execution", {
        "phase", "application", "sdk", "plain", "entry_evidence", "input_recheck", "bootstrap_recheck", "source_complete", "failures"})
    actual_sdk = None if intent.plain else {"pid": sdk, "returncode": 0, "launch_id": token, "phase": "closed"}
    provider.require(final["phase"] == "closed" and final["plain"] is intent.plain
                     and final["source_complete"] is False and final["input_recheck"] is True
                     and final["bootstrap_recheck"] is (None if intent.plain else True)
                     and type(final["failures"]) is dict and not final["failures"]
                     and provider.same(final["application"], {"pid": app["application_pid"], "returncode": 0})
                     and provider.same(final["sdk"], actual_sdk), "Python application/SDK completion or input recheck failed")
    journal, descriptors, summary = entry_evidence(runtime, intent, app["application_pid"], owner.python_version)
    provider.require(provider.same(final["entry_evidence"], summary), "Python entry summary differs from the native journal")
    provider.require(not descriptors if intent.plain else bool(descriptors), "Python lane code-observer evidence differs")
    return Execution(owner, app["application_pid"], sdk, token, journal, descriptors, final)
