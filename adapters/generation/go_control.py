"""Read live Go controls independently of the producer's runtime readers."""

from pathlib import Path

import go_health as health
from go_provider import require
import live_control

COMMANDS = {"status", "health", "flush", "collection on", "collection off", "emission on", "emission off"}
MAX_STATUSES = 512
STATUS_FIELDS = {"schema_version", "pid", "collection", "emission", "effective_emission_off"}


def status(value: object, pid: int) -> dict:
    """An emission-off reply acknowledges the SDK's completed export barrier."""
    value = health.fields(value, STATUS_FIELDS, "Go live control")
    require(type(pid) is int and 1 < pid <= 0x7fffffff
            and type(value["schema_version"]) is int and value["schema_version"] == 1
            and type(value["pid"]) is int and value["pid"] == pid,
            "Go live control differs from the owned application/embedded SDK")
    require(all(type(value[key]) is bool for key in ("collection", "emission", "effective_emission_off"))
            and value["effective_emission_off"] is (not value["emission"]),
            "Go live flags or completed emission-off barrier differ")
    return value


def live(value: object, pid: int, *, policy_sha256: str, selection_sha256: str) -> dict:
    """Validate a paused call-only workload without inventing atomic export counts."""
    value = health.validate(value, pid=pid, policy_sha256=policy_sha256, selection_sha256=selection_sha256)
    require(value["phase"] == "running" and value["lifecycle"] == {"flush": "not_started", "shutdown": "not_started"},
            "Go live schedule has entered final shutdown")
    status(value["controls"], pid)
    probes = health.counters(value["probe_accounting"], health.PROBES, "Go live probes", closed=True)
    require(probes["closed"] is False and probes["function_started"] == probes["function_ended"]
            and all(probes[key] == 0 for key in health.PROBES - {"function_started", "function_ended"}),
            "Go live call boundary has active, lost or unrequested probes")
    flush = health.counters(value["metric_flush"], {"attempts", "failed_attempts"}, "Go live flush")
    require(flush["failed_attempts"] == 0, "Go live metric flush failed")
    for name, traces in (("metric_exports", False), ("trace_exports", True)):
        exports = health.exporter(value[name], traces=traces)
        require(exports is not None and exports["closed"] is False and exports["failed"] == 0,
                "Go live exporter is missing, closed or failed")
        if traces:
            require(exports["queue_dropped"] == 0, "Go live trace queue lost spans")
    http = health.http_spans(value["http_spans"])
    require(http is not None and http["closed"] is False
            and all(http[key] == 0 for key in ("started", "ended", "active")),
            "Go live call-only schedule contains HTTP operations")
    return value


def request(path: Path, command: str, pid: int, deadline: float, *,
            policy_sha256: str, selection_sha256: str) -> dict:
    """Bind authenticated bounded replies to the original process and policy."""
    require(type(command) is str and command in COMMANDS, "unsupported live Go control command")
    value = live_control.exchange(path, command, pid, deadline,
                                  maximum=health.MAX_REPORT_BYTES if command == "health" else 4096)
    return (live(value, pid, policy_sha256=policy_sha256, selection_sha256=selection_sha256)
            if command == "health" else status(value, pid))


def switch(path: Path, pid: int, requested: dict, deadline: float, *,
           policy_sha256: str, selection_sha256: str) -> list[dict]:
    """Set both flags independently; never substitute combined on/off commands."""
    require(type(requested) is dict and set(requested) == {"collection", "emission"}
            and all(type(flag) is bool for flag in requested.values()), "invalid Go live metric state")
    options = {"policy_sha256": policy_sha256, "selection_sha256": selection_sha256}
    previous = request(path, "status", pid, deadline, **options)
    history = [{"command": "status", "response": previous}]
    for key, other in (("collection", "emission"), ("emission", "collection")):
        command = key + (" on" if requested[key] else " off")
        current = request(path, command, pid, deadline, **options)
        require(current[key] is requested[key] and current[other] is previous[other],
                "Go live setter changed the independent metric flag")
        history.append({"command": command, "response": current})
        previous = current
    return history
