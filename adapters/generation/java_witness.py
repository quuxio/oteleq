"""Independent Java action-v2 control and final-evidence reader.

Accepted framing is data, not invocation qualification. Callers must bind the
reply to frozen compiler/launch identities, private harness readiness, actual
process completion and independently decoded OTLP before admitting a result.
"""

from dataclasses import dataclass
import os
from pathlib import Path
import re
import socket
import stat
import time
import uuid

from otelc_capture import strict_json

PROFILE = "java-sync-action-v2"
VERSION = 2
MAX_REPLY = 262144
MAX_FINAL = 4194304
MAX_COUNTER = 2**63 - 1
HASH_FIELDS = ("build_sha256", "selection_sha256", "policy_sha256",
               "tooling_sha256", "envelope_probe_id", "rendezvous_probe_id",
               "wrapper_probe_id", "target_probe_id")
REPLY_FIELDS = {"schema_version", "profile", "runtime_id", "pid", "request_id", "error",
                "rejected_probes", "max_scopes", "max_spans_per_scope", "scope",
                *HASH_FIELDS}
SCOPE_FIELDS = {"cookie", "sequence", "thread_id", "scope_id", "case_id",
                "attempt_id", "phase", "failure", "trace_id", "root_span_id",
                "target_span_id", "root_exited", "envelope_exited", "target_exited",
                "target_entries", "export_failures", "flush_failures", "checkpoint",
                "producer_complete", "receiver_confirmation_required", "started_ids",
                "ended_ids", "exported_ids", "pending_exports", "queue_dropped"}
PHASES = {"entered", "ready", "armed", "consumed", "exited", "expired",
          "cancelled", "complete", "invalidated", "incomplete", "terminated"}
FINAL_FIELDS = {"schema_version", "kind", "phase", "pid", "producer",
                "queue_evidence", "scopes"}


def require(condition: bool, reason: str) -> None:
    """Absent or contradictory evidence cannot select an attribution fallback."""
    if not condition:
        raise ValueError("Java action witness: " + reason)


def hex_id(value: object, width: int, *, nullable: bool = False) -> bool:
    """Opaque identities have a closed ASCII representation without coercion."""
    return ((nullable and value is None) or type(value) is str
            and re.fullmatch(r"[0-9a-f]{" + str(width) + "}", value) is not None)


def counter(value: object, *, positive: bool = False) -> int:
    """Keep exact canonical Java long values, including logical thread IDs."""
    require(type(value) is str and re.fullmatch(r"0|[1-9][0-9]{0,18}", value) is not None,
            "invalid decimal counter")
    number = int(value)
    require(int(positive) <= number <= MAX_COUNTER, "counter outside supported range")
    return number


def failure(value: object) -> bool:
    """Only a bounded machine-readable reason can appear in this protocol."""
    return value is None or (type(value) is str
            and re.fullmatch(r"[a-z][a-z_]{0,63}", value) is not None)


@dataclass(frozen=True)
class Identity:
    """Freeze independently expected build/probe identity with one live runtime."""

    runtime_id: str
    pid: int
    hashes: tuple[tuple[str, str], ...]

    @classmethod
    def bind(cls, value: dict, expected: dict, *, pid: int,
             runtime_id: str | None = None) -> "Identity":
        """A first status can supply runtime freshness, never expected build hashes."""
        require(type(pid) is int and pid > 0 and value["pid"] == pid,
                "producer does not identify the actual JVM")
        require(type(expected) is dict and set(expected) == set(HASH_FIELDS)
                and all(hex_id(expected[key], 64) for key in HASH_FIELDS),
                "incomplete independent launch/probe identity")
        require(all(value[key] == expected[key] for key in HASH_FIELDS),
                "producer build or compiler probe differs")
        require(runtime_id is None or value["runtime_id"] == runtime_id,
                "producer runtime changed")
        return cls(value["runtime_id"], pid, tuple((key, expected[key]) for key in HASH_FIELDS))

    def check(self, value: dict) -> None:
        """Every later acknowledgement and final header belongs to this runtime."""
        require(value["runtime_id"] == self.runtime_id and value["pid"] == self.pid
                and all(value[key] == expected for key, expected in self.hashes),
                "producer runtime, build or probe changed")


def span_sets(scope: dict) -> tuple[set[str], set[str], set[str]]:
    """Require complete distinct bounded sets without inventing missing spans."""
    result = []
    for key in ("started_ids", "ended_ids", "exported_ids"):
        values = scope[key]
        require(type(values) is list and len(values) <= 1024
                and all(hex_id(value, 16) and value != "0" * 16 for value in values)
                and len(set(values)) == len(values), "invalid span ID set")
        result.append(set(values))
    started, ended, exported = result
    require(ended <= started and exported <= started, "span accounting contradicts starts")
    return started, ended, exported


def read_scope(scope: object) -> dict:
    """Validate incomplete data as incomplete, preserving recoverable flush history."""
    require(type(scope) is dict and set(scope) == SCOPE_FIELDS, "unsupported scope fields")
    require(hex_id(scope["cookie"], 32) and type(scope["phase"]) is str and scope["phase"] in PHASES
            and failure(scope["failure"]), "invalid context identity or phase")
    counter(scope["sequence"], positive=True)
    counter(scope["thread_id"], positive=True)
    for key in ("target_entries", "export_failures", "flush_failures", "pending_exports"):
        counter(scope[key])
    for key in ("root_exited", "envelope_exited", "target_exited", "checkpoint",
                "producer_complete", "receiver_confirmation_required"):
        require(type(scope[key]) is bool, "invalid scope flag")
    require(scope["receiver_confirmation_required"], "missing independent receiver requirement")
    for key, width in (("scope_id", 32), ("case_id", 64), ("attempt_id", 64),
                       ("trace_id", 32), ("root_span_id", 16), ("target_span_id", 16)):
        require(hex_id(scope[key], width, nullable=True), "invalid scoped identity")
    armed = [scope[key] is not None for key in ("scope_id", "case_id", "attempt_id")]
    require(all(armed) or not any(armed), "partial arm identity")
    if scope["queue_dropped"] is not None:
        counter(scope["queue_dropped"])
    started, ended, exported = span_sets(scope)
    if scope["producer_complete"]:
        require(scope["phase"] == "complete" and scope["failure"] is None
                and all(armed) and bool(started) and started == ended == exported
                and all(scope[key] for key in ("checkpoint", "root_exited", "envelope_exited", "target_exited"))
                and scope["pending_exports"] == "0" and scope["target_entries"] != "0"
                and scope["queue_dropped"] in (None, "0")
                and scope["trace_id"] is not None and scope["trace_id"] != "0" * 32
                and scope["root_span_id"] in started and scope["target_span_id"] in started
                and scope["root_span_id"] != scope["target_span_id"],
                "producer completion lacks matching evidence")
    else:
        require(scope["phase"] != "complete", "complete phase contradicts completion flag")
    return scope


def reply(value: object, request_id: str | None) -> dict:
    """Read only the explicit v2 schema; old optional profiles stay unavailable."""
    require(request_id is None or hex_id(request_id, 32), "invalid expected request identity")
    require(type(value) is dict and set(value) == REPLY_FIELDS,
            "unsupported reply fields")
    require(type(value["schema_version"]) is int and value["schema_version"] == VERSION
            and value["profile"] == PROFILE and value["request_id"] == request_id
            and hex_id(value["runtime_id"], 32)
            and type(value["pid"]) is int and value["pid"] > 0
            and all(hex_id(value[key], 64) for key in HASH_FIELDS)
            and type(value["max_scopes"]) is int and value["max_scopes"] == 64
            and type(value["max_spans_per_scope"]) is int and value["max_spans_per_scope"] == 1024
            and failure(value["error"]), "unsupported or uncorrelated reply identity")
    counter(value["rejected_probes"])
    if value["scope"] is not None:
        read_scope(value["scope"])
    return value


def context(value: dict, identity: Identity, *, thread_id: str, cookie: str,
            sequence: str, case_id: str | None = None, attempt_id: str | None = None,
            scope_id: str | None = None) -> dict:
    """Bind actual harness readiness; first-ready or an OS thread cannot substitute."""
    identity.check(value)
    require(value["error"] is None and value["scope"] is not None,
            "producer refused or omitted the intended action")
    counter(thread_id, positive=True)
    counter(sequence, positive=True)
    require(hex_id(cookie, 32), "invalid expected context cookie")
    scope = value["scope"]
    expected = {"thread_id": thread_id, "cookie": cookie, "sequence": sequence}
    for key, actual, width in (("case_id", case_id, 64), ("attempt_id", attempt_id, 64),
                                ("scope_id", scope_id, 32)):
        if actual is not None:
            require(hex_id(actual, width), "invalid expected action identity")
            expected[key] = actual
    require(all(scope[key] == actual for key, actual in expected.items()),
            "logical thread, context or action differs")
    return scope


def endpoint(path: Path) -> tuple[int, int]:
    """Only an owned private runtime's fixed witness socket can be queried."""
    directory, info = path.parent.lstat(), path.lstat()
    require(path.name == "witness.sock" and path.parent == path.parent.resolve(strict=True)
            and stat.S_ISDIR(directory.st_mode) and directory.st_uid == os.getuid()
            and stat.S_IMODE(directory.st_mode) == 0o700, "unsafe witness runtime")
    require(stat.S_ISSOCK(info.st_mode) and info.st_uid == os.getuid()
            and stat.S_IMODE(info.st_mode) == 0o600, "unsafe witness socket")
    return info.st_dev, info.st_ino


def command(operation: str, arguments: tuple[str, ...], request_id: str) -> bytes:
    """Build the closed producer command vocabulary before opening a socket."""
    require(hex_id(request_id, 32), "invalid request identity")
    require(type(operation) is str and all(type(value) is str for value in arguments),
            "invalid command types")
    widths = {"status": (32, 32), "end": (32, 32), "cancel": (32, 32)}
    if operation == "arm":
        require(len(arguments) == 11, "arm requires the expected Java thread ID")
        for value, width in zip(arguments, (32, 32, 0, 64, 64, 64, 64, 64, 64, 64, 0)):
            counter(value, positive=True) if width == 0 else require(hex_id(value, width), "invalid arm identity")
    else:
        require(operation in widths and (operation == "status" and not arguments or len(arguments) == 2),
                "unsupported operation or argument count")
        require(all(hex_id(value, width) for value, width in zip(arguments, widths[operation])),
                "invalid command identity")
    return (" ".join((str(VERSION), request_id, operation, *arguments)) + "\n").encode("ascii")


def request(path: Path, operation: str, *arguments: str, deadline: float) -> dict:
    """Retain a common deadline and exactly one bounded correlated wire frame."""
    request_id = uuid.uuid4().hex
    wire = command(operation, arguments, request_id)
    original = endpoint(path)
    with socket.socket(socket.AF_UNIX) as client:
        remaining = min(4., deadline - time.monotonic())
        require(remaining > 0, "control deadline exceeded")
        client.settimeout(remaining)
        client.connect(str(path))
        require(endpoint(path) == original, "witness socket changed during connection")
        client.sendall(wire)
        data = bytearray()
        while not data.endswith(b"\n"):
            remaining = min(4., deadline - time.monotonic())
            require(remaining > 0, "control deadline exceeded")
            client.settimeout(remaining)
            piece = client.recv(MAX_REPLY + 1 - len(data))
            require(bool(piece) and len(data) + len(piece) <= MAX_REPLY,
                    "incomplete or oversized witness reply")
            data.extend(piece)
        require(data.count(b"\n") == 1 and endpoint(path) == original,
                "extra witness frames or replaced socket")
    return reply(strict_json(bytes(data)), request_id)


def read_final(runtime: Path, *, pid: int, identity: Identity) -> dict:
    """Read a stable owned report and bind final evidence to the launched JVM."""
    require(type(pid) is int and pid > 0, "missing actual JVM PID")
    require(pid == identity.pid, "actual JVM PID differs from frozen producer identity")
    require(runtime == runtime.resolve(strict=True), "runtime is not canonical")
    parent = os.open(runtime, os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW)
    try:
        directory = os.fstat(parent)
        require(directory.st_uid == os.getuid() and stat.S_IMODE(directory.st_mode) == 0o700,
                "unsafe final report directory")
        fd = os.open("witness-health.json", os.O_RDONLY | os.O_NOFOLLOW | os.O_NONBLOCK, dir_fd=parent)
        try:
            before = os.fstat(fd)
            require(stat.S_ISREG(before.st_mode) and before.st_uid == os.getuid()
                    and stat.S_IMODE(before.st_mode) == 0o600 and before.st_size <= MAX_FINAL,
                    "unsafe or oversized final report")
            with os.fdopen(fd, "rb", closefd=False) as stream:
                raw = stream.read(MAX_FINAL + 1)
            after = os.fstat(fd)
            linked = os.stat("witness-health.json", dir_fd=parent, follow_symlinks=False)
        finally:
            os.close(fd)
    finally:
        os.close(parent)
    signature = lambda info: (info.st_dev, info.st_ino, info.st_size, info.st_mtime_ns,
                              info.st_ctime_ns, info.st_mode, info.st_uid)
    require(len(raw) == before.st_size <= MAX_FINAL and signature(before) == signature(after) == signature(linked),
            "final report changed while reading")
    value = strict_json(raw)
    require(type(value) is dict and set(value) == FINAL_FIELDS
            and type(value["schema_version"]) is int and value["schema_version"] == VERSION
            and value["kind"] == "otelc.java-witness-final" and value["phase"] == "final"
            and type(value["pid"]) is int and value["pid"] == pid
            and value["queue_evidence"] in ("derived_after_shutdown", "unavailable")
            and type(value["scopes"]) is list and len(value["scopes"]) <= 64,
            "unsupported final report identity")
    header = reply(value["producer"], None)
    identity.check(header)
    require(header["scope"] is None, "final header hides an action")
    cookies, scope_ids, previous = set(), set(), 0
    for scope in value["scopes"]:
        read_scope(scope)
        require(scope["cookie"] not in cookies and (scope["scope_id"] is None or scope["scope_id"] not in scope_ids)
                and int(scope["sequence"]) > previous, "duplicate or unordered final context")
        require(value["queue_evidence"] != "unavailable" or scope["queue_dropped"] is None,
                "queue observation lacks a supported drain")
        cookies.add(scope["cookie"])
        scope_ids.add(scope["scope_id"])
        previous = int(scope["sequence"])
    return value
