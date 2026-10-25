"""Reconcile Go metric schedules with owned checkpoints and serial call trees."""

from collections import Counter
import hashlib
from pathlib import Path
import stat

import go_control as control
import go_files as files
import go_health as health
import go_live
from go_provider import policy_digest, require, same
from java_live import metric_bodies
from otelc_collection import serial_trees
import otelc_capture as capture


def checked_status(value: object, record: dict, flags: dict) -> dict:
    value = control.status(value, record["pid"])
    require(all(value[key] is flag for key, flag in flags.items()), "Go live reply differs from the declared metric state")
    return value


def checked_health(value: object, record: dict, completed: int, flags: dict) -> dict:
    value = control.live(value, record["pid"], policy_sha256=record["policy_sha256"],
                         selection_sha256=record["selection_sha256"])
    require(int(value["probe_accounting"]["function_ended"]) == completed
            and all(value["controls"][key] is flag for key, flag in flags.items()),
            "Go live health differs from the completed selected call trees")
    require(int(value["trace_exports"]["exported_spans"]) == completed
            and value["trace_exports"]["queue_pending"] == "0", "Go retained paused trace flush is incomplete")
    if not all(flags.values()):
        exports = value["metric_exports"]
        require(exports["attempts"] == exports["succeeded"], "Go disabled metric window lacks a completed drain")
    return value


def transition(value: object, record: dict, flags: dict, *, initial: bool = False) -> int:
    require(type(value) is list and len(value) == 3, "Go live transition requires both independent setters")
    commands = ["status", "collection " + ("on" if flags["collection"] else "off"),
                "emission " + ("on" if flags["emission"] else "off")]
    previous = None
    for index, (row, command) in enumerate(zip(value, commands)):
        row = health.fields(row, {"command", "response"}, "Go live transition")
        require(row["command"] == command, "Go live setter order differs")
        current = control.status(row["response"], record["pid"])
        if initial and index == 0:
            checked_status(current, record, flags)
        if index:
            key, other = ("collection", "emission") if index == 1 else ("emission", "collection")
            require(current[key] is flags[key] and current[other] is previous[other],
                    "Go live setter changed its independent flag")
        previous = current
    checked_status(previous, record, flags)
    return len(value)


def checkpoint_files(run, phases: list[str]) -> None:
    """Read every private request and acknowledgement without trusting record paths."""
    root, token = run.session.binding.root, run.session.binding.token
    owner = run.session.started.owner
    names = {"start.ready", "start.tmp", "start.resume", "start.resume.tmp"}
    for phase in phases:
        expected = {"schema_version": 1, "kind": "oteleq.go.checkpoint", "phase": phase,
                    "token": token, "pid": owner.application_pid, "parent_pid": owner.pid}
        groups = {}
        for suffix in (".ready", ".tmp", ".resume", ".resume.tmp"):
            name = phase + suffix
            _, facts, raw = files.file(root / name, 1024, keep=True)
            require(stat.S_IMODE(facts[2]) == 0o600 and facts[3] == root.stat().st_uid and facts[8] == 2,
                    "unsafe retained Go live checkpoint")
            if suffix in (".ready", ".tmp"):
                require(same(capture.strict_json(raw), expected), "Go retained checkpoint identity differs")
                group = "ready"
            else:
                require(raw == (token + " " + phase + "\n").encode("ascii"), "Go retained acknowledgement differs")
                group = "resume"
            if group in groups:
                require(groups[group] == facts, "Go retained marker has different publication links")
            groups[group] = facts
            names.add(name)
    require({path.name for path in root.iterdir()} == names, "Go retained checkpoint denominator differs")


def read(folder: Path, run, sequence: list[dict], bodies: list) -> dict:
    """Bind closed schedule metadata to already verified native execution."""
    _, _, raw = files.file(folder / go_live.RECORD, go_live.MAX_RECORD_BYTES, keep=True, private=True)
    record = health.fields(capture.strict_json(raw), {"control_schema_version", "plain", "supervisor_pid", "pid",
        "sdk_pid", "launch_id", "policy_sha256", "selection_sha256", "interval_ms", "steps", "restored"}, "Go live record")
    intent, owner = run.prepared.intent, run.session.started.owner
    expected = {"control_schema_version": 1, "plain": intent.plain, "supervisor_pid": owner.pid,
                "pid": owner.application_pid, "sdk_pid": None if intent.plain else owner.application_pid,
                "launch_id": run.prepared.response["request"]["launch_id"], "policy_sha256": policy_digest(intent.policy),
                "selection_sha256": intent.build.receipt["selection"]["sha256"], "interval_ms": go_live.INTERVAL_MS}
    require(type(sequence) is list and 1 <= len(sequence) <= 32
            and same({key: record[key] for key in expected}, expected), "Go live record differs from owned execution")
    require(type(record["steps"]) is list and len(record["steps"]) == len(sequence), "Go live record is missing declared calls")
    cursor = 0
    for index, (step, declared) in enumerate(zip(record["steps"], sequence)):
        step = health.fields(step, {"id", "requested", "before", "after"}, "Go live step")
        require(step["id"] == "step-" + str(index) and same(step["requested"], declared["metrics"]),
                "Go live requested call state changed")
        before = health.fields(step["before"], {"history", "flush", "health", "cursor"}, "Go live before")
        after = health.fields(step["after"], {"status", "flush", "health", "settled_flush", "settled", "cursor",
                                               "metric_bodies", "held_ns"}, "Go live after")
        start, end = before["cursor"], after["cursor"]
        require(type(start) is int and type(end) is int and cursor <= start <= end <= len(bodies)
                and type(after["held_ns"]) is int and 0 <= after["held_ns"] <= run.session.binding.wait_ms * 1_000_000,
                "Go live receipt cursors or held interval differ")
        indices = metric_bodies(bodies, start, end)
        require(same(after["metric_bodies"], indices)
                and (all(step["requested"].values()) or not indices
                     and after["held_ns"] >= go_live.INTERVAL_MS * 1_000_000),
                "Go disabled interval is missing, too short or received metrics")
        if intent.plain:
            require(before["history"] == [] and before["flush"] is before["health"] is None
                    and all(after[key] is None for key in ("status", "flush", "health", "settled_flush", "settled")),
                    "plain Go live record fabricated SDK replies")
        cursor = end
    restored = health.fields(record["restored"], {"history", "flush", "health", "cursor"}, "Go live restoration")
    require(type(restored["cursor"]) is int and cursor <= restored["cursor"] <= len(bodies),
            "Go live restoration cursor differs")
    if intent.plain:
        require(not bodies and restored["history"] == [] and restored["flush"] is restored["health"] is None,
                "plain Go live record contains SDK evidence")
    phases = [phase + "-" + str(index) for index in range(len(sequence)) for phase in ("before", "after")] + ["finish"]
    checkpoint_files(run, phases)
    record["record_sha256"] = hashlib.sha256(raw).hexdigest()
    return record


def phase(indices: list[int], series: dict, calls: Counter, errors: Counter, *, required: bool) -> None:
    """Every sample is bounded by only the completed collection-enabled trees."""
    import go_telemetry as telemetry

    expected = {(metric, name, ""): count for name, count in calls.items()
                for metric in (telemetry.CALLS, telemetry.DURATION)}
    expected.update({(telemetry.ERRORS, name, error_type): errors[name, error_type]
                     for name in calls for error_type in telemetry.ERROR_TYPES})
    observed = {}
    for index in indices:
        for key, count in series[index].items():
            require(key in expected and count <= expected[key], "Go metrics contain uncollected or future calls")
            observed[key] = max(observed.get(key, 0), count)
    if required:
        require(all(observed.get(key) == count for key, count in expected.items() if count),
                "Go positive or retained measurements are missing")


def qualify(record: dict, run, bodies: list, spans: list, series: dict) -> tuple[Counter, Counter]:
    """Join creation and each declared call to exact live replies and metric windows."""
    groups = serial_trees(spans)
    target, factory = run.caller.targets
    require(all(span.name in {target.name, factory.name} for span in spans), "Go live tree contains an unselected function")
    require(len(groups) == len(record["steps"]) + 1, "Go live trace tree denominator differs")
    for index, group in enumerate(groups):
        root, = (span for span in group if not span.parent_span_id)
        require(root.name == (factory.name if index == 0 else target.name), "Go live factory/call tree order differs")
    calls = Counter({target.name: 0, factory.name: 0})
    errors, completed, cursor, statuses = Counter(), 0, 0, 0
    snapshots = []

    def collect(group: list, enabled: bool) -> None:
        if enabled:
            for span in group:
                calls[span.name] += 1
                if span.status.code == 2:
                    values = {item.key: item.value.string_value for item in span.attributes}
                    errors[span.name, values["error.type"]] += 1

    for index, (step, group) in enumerate(zip(record["steps"], groups[1:])):
        flags, before, after = step["requested"], step["before"], step["after"]
        phase(metric_bodies(bodies, cursor, before["cursor"]), series, calls, errors, required=False)
        statuses += transition(before["history"], record, flags, initial=index == 0)
        checked_status(before["flush"], record, flags)
        snapshots.append(checked_health(before["health"], record, completed, flags))
        if index == 0:
            completed += len(groups[0])
            collect(groups[0], flags["collection"])
        completed += len(group)
        collect(group, flags["collection"])
        for name in ("status", "flush", "settled_flush"):
            checked_status(after[name], record, flags)
        snapshots.extend(checked_health(after[name], record, completed, flags) for name in ("health", "settled"))
        statuses += 7
        phase(after["metric_bodies"], series, calls, errors, required=all(flags.values()))
        cursor = after["cursor"]
    restored, flags = record["restored"], {"collection": True, "emission": True}
    statuses += transition(restored["history"], record, flags)
    checked_status(restored["flush"], record, flags)
    snapshots.append(checked_health(restored["health"], record, completed, flags))
    require(statuses + 2 <= control.MAX_STATUSES, "Go live reply denominator exceeds its budget")
    phase(metric_bodies(bodies, cursor, restored["cursor"]), series, calls, errors, required=True)
    phase(metric_bodies(bodies, restored["cursor"], len(bodies)), series, calls, errors, required=False)
    require(int(run.session.execution.health["probe_accounting"]["function_ended"]) == completed,
            "Go final health differs from its complete live call trees")
    last_flushes = 0
    for snapshot in snapshots:
        flushes = int(snapshot["metric_flush"]["attempts"])
        require(flushes > last_flushes, "Go live flush replies lack advancing SDK counters")
        last_flushes = flushes
    previous = None
    for snapshot in [*snapshots, run.session.execution.health]:
        if previous is not None:
            for section, keys in (("metric_exports", ("attempts", "succeeded", "failed")),
                                  ("trace_exports", ("attempts", "succeeded", "failed", "exported_spans")),
                                  ("metric_flush", ("attempts", "failed_attempts"))):
                require(all(int(snapshot[section][key]) >= int(previous[section][key]) for key in keys),
                        "Go live exporter or flush counters moved backwards")
            if not previous["controls"]["emission"] and not snapshot["controls"]["emission"]:
                require(snapshot["metric_exports"]["attempts"] == previous["metric_exports"]["attempts"],
                        "Go SDK exported after the emission-off barrier")
        previous = snapshot
    return calls, errors
