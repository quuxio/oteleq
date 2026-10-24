"""Bind Go execution records to a native application observed before its call."""

from dataclasses import dataclass

import go_files as files
import go_health
import go_prepared as prepared
from go_provider import PROFILE, data_seal, metadata_digest, policy_digest, require, same
from otelc_capture import strict_json

EXECUTION_FILE = "go-execution.json"
HEALTH_FILE = "health.json"

START_FILES = ("go-supervisor-start.json", "go-application-start.json")


@dataclass(frozen=True)
class Owner:
    """Actual Popen/kernel facts supplied by the consumer before releasing work."""

    pid: int
    parent_pid: int
    application_pid: int
    command: tuple[str, ...]


def record(path, maximum: int = files.MAX_METADATA_BYTES) -> tuple[dict, tuple]:
    """Keep decoded metadata bound to its one stable private-file read."""
    identity, facts, raw = files.file(path, maximum, keep=True, private=True)
    value = strict_json(raw)
    require(type(value) is dict, "Go execution metadata must be an object")
    return value, (identity, facts)


def owner_record(launch: prepared.Prepared, owner: Owner) -> dict:
    """Only caller-owned process facts and complete prepared documents select IDs."""
    response = launch.response
    return {"schema_version": 1, "kind": "otelc.go.supervisor", "profile": PROFILE,
            "supervisor_pid": owner.pid, "parent_pid": owner.parent_pid, "process_group": owner.pid,
            "launch_id": response["request"]["launch_id"],
            "request_sha256": metadata_digest(response["request"]),
            "plan_sha256": metadata_digest(response["plan"]),
            "prepared_sha256": metadata_digest(response["prepared"])}


def application_record(launch: prepared.Prepared, owner: Owner) -> dict:
    """The observed native process must run the fixed lane's retained binary."""
    return {"schema_version": 1, "kind": "otelc.go.application", "profile": PROFILE,
            "launch_id": launch.response["request"]["launch_id"], "pid": owner.application_pid,
            "supervisor_pid": owner.pid, "process_group": owner.pid, "plain": launch.intent.plain,
            "argv": launch.response["plan"]["argv"], "binary": launch.response["plan"]["binary"]}


def start_state(launch: prepared.Prepared, owner: Owner, evidence: dict) -> dict:
    return {"prepared": launch.accepted_seal, "owner": vars(owner), "evidence": evidence}


def verify_evidence(launch: prepared.Prepared, evidence: dict) -> None:
    for name, expected in evidence.items():
        require(same(files.file(launch.intent.runtime / name, max(1, expected[0]["size"]), private=True)[:2], expected),
                "Go execution record changed: " + name)


@dataclass(frozen=True)
class Started:
    """Pre-call process records cannot be replaced by a post-exit PID claim."""

    prepared: prepared.Prepared
    owner: Owner
    evidence: dict
    seal: str

    def verify(self) -> None:
        require(data_seal(start_state(self.prepared, self.owner, self.evidence)) == self.seal,
                "accepted Go start metadata changed")
        self.prepared.verify()
        verify_evidence(self.prepared, self.evidence)


def bind(launch: prepared.Prepared, owner: Owner) -> Started:
    """Check actual caller/kernel identities while the generated worker is paused."""
    require(type(launch) is prepared.Prepared and type(owner) is Owner
            and all(type(pid) is int and 1 < pid <= 0x7fffffff
                    for pid in (owner.pid, owner.application_pid))
            and type(owner.parent_pid) is int and 1 <= owner.parent_pid <= 0x7fffffff
            and len({owner.pid, owner.parent_pid, owner.application_pid}) == 3
            and type(owner.command) is tuple and all(type(value) is str for value in owner.command)
            and same(list(owner.command), prepared.command(launch.intent)),
            "invalid caller-owned Go process binding")
    launch.verify()
    path = launch.intent.runtime / EXECUTION_FILE
    require(not path.exists() and not path.is_symlink(), "Go application already completed before binding")
    values = {name: record(launch.intent.runtime / name) for name in START_FILES}
    expected = (owner_record(launch, owner), application_record(launch, owner))
    require(all(same(values[name][0], value) for name, value in zip(START_FILES, expected)),
            "Go actual owner/application differs from prepared start records")
    evidence = {name: value[1] for name, value in values.items()}
    result = Started(launch, owner, evidence, data_seal(start_state(launch, owner, evidence)))
    result.verify()
    return result


@dataclass(frozen=True)
class Execution:
    """Successful ownership/final health; independent OTLP qualification is separate."""

    started: Started
    value: dict
    health: dict | None
    evidence: dict
    seal: str

    def verify(self) -> None:
        require(data_seal({"start": self.started.seal, "value": self.value,
                           "health": self.health, "evidence": self.evidence}) == self.seal,
                "accepted Go completion metadata changed")
        self.started.verify()
        verify_evidence(self.started.prepared, self.evidence)


def finish(started: Started, returncode: int) -> Execution:
    """Join a completed successful diagnostic to the same pre-call application."""
    require(type(started) is Started and type(returncode) is int and returncode == 0,
            "Go diagnostic supervisor did not complete successfully")
    started.verify()
    launch, owner = started.prepared, started.owner
    runtime = launch.intent.runtime
    value, identity = record(runtime / EXECUTION_FILE)
    evidence = {EXECUTION_FILE: identity}
    health = None
    if launch.intent.plain:
        require(not any((runtime / name).exists() or (runtime / name).is_symlink()
                        for name in (HEALTH_FILE, "control.json")), "plain Go execution has SDK evidence")
    else:
        _, evidence[HEALTH_FILE] = record(runtime / HEALTH_FILE, go_health.MAX_REPORT_BYTES)
        health = go_health.read(runtime)
        go_health.validate(health, pid=owner.application_pid, policy_sha256=policy_digest(launch.intent.policy),
                           selection_sha256=launch.intent.build.receipt["selection"]["sha256"])
        require(health["phase"] == "final"
                and same(health["lifecycle"], {"flush": "succeeded", "shutdown": "succeeded"})
                and health["probe_accounting"]["closed"] is True,
                "Go execution lacks a completed final SDK lifecycle")
        verify_evidence(launch, {HEALTH_FILE: evidence[HEALTH_FILE]})
    expected = {"schema_version": 1, "kind": "otelc.go.execution", "profile": PROFILE,
                "launch_id": launch.response["request"]["launch_id"], "supervisor": owner_record(launch, owner),
                "application_pid": owner.application_pid, "sdk_pid": None if launch.intent.plain else owner.application_pid,
                "application_exit_code": 0, "interrupted_by": None, "inputs_rechecked": True, "sdk_health": health,
                "failures": {}, "source_complete": False, "downstream_receipt": "unavailable"}
    require(same(value, expected), "Go completion differs from actual owner, lane, exit or final SDK report")
    result = Execution(started, value, health, evidence,
                       data_seal({"start": started.seal, "value": value, "health": health, "evidence": evidence}))
    result.verify()
    return result
