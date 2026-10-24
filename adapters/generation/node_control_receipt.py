"""Independently verify live source controls against serial traces and metric bytes."""

from collections import Counter
from collections.abc import Iterator
import hashlib
from pathlib import Path

from java_live import metric_bodies, read_owned
from otelc_collection import serial_trees as trees
import node_control as control
import node_live
import node_source as provider
import otelc_capture as capture

EXPORT_COUNTERS = ("export_started", "export_succeeded", "export_failed")


def control_statuses(record: dict) -> Iterator[dict]:
    """Yield actual replies in the same order as the paused host exchanges."""
    for step in record["steps"]:
        yield from (row["status"] for row in step["before"]["history"])
        yield from (step["after"][name] for name in ("status", "flush", "settled"))
    yield from (row["status"] for row in record["restored"]["history"])
    yield record["restored"]["flush"]


def export_timeline(record: dict, final: dict) -> None:
    """A drained off barrier forbids new admissions until explicit re-enable."""
    previous = dict.fromkeys(EXPORT_COUNTERS, 0)
    drained_started = None
    for current in control_statuses(record):
        provider.require(all(current[key] >= previous[key] for key in EXPORT_COUNTERS),
                         "live Node exporter counters moved backwards")
        if drained_started is not None and not current["emission"]:
            provider.require(current["export_started"] == drained_started,
                             "live Node export admitted during a drained emission-off window")
        if current["emission"]:
            drained_started = None
        elif current["effective_emission_off"]:
            drained_started = current["export_started"]
        previous = current
    provider.require(all(type(final.get(key)) is int and final[key] >= previous[key]
                         for key in EXPORT_COUNTERS), "live Node exporter counters exceed the final SDK report")

def count(value: object, maximum: int) -> bool:
    return type(value) is int and 0 <= value <= maximum


def read(folder: Path, entry: dict, bodies: list, *, plain: bool) -> dict:
    """Bind the retained schedule to all three actual completed process identities."""
    raw = read_owned(folder / node_live.RECORD, node_live.MAX_RECORD_BYTES)
    record = capture.strict_json(raw)
    process = capture.strict_json((folder / "process.json").read_bytes())
    application = capture.strict_json((folder / "node-source-application.json").read_bytes())
    completion = capture.strict_json((folder / "node-source-completion.json").read_bytes())
    fields = {"control_schema_version", "plain", "language", "supervisor_pid", "pid", "sdk_pid", "launch_id", "interval_ms", "steps", "restored"}
    provider.require(type(record) is dict and set(record) == fields
                     and type(record["control_schema_version"]) is int and record["control_schema_version"] == 1
                     and record["plain"] is plain and record["language"] == entry["language"]
                     and type(record["pid"]) is int and record["pid"] == application["pid"]
                     and type(record["supervisor_pid"]) is int and record["supervisor_pid"] == process["pid"]
                     and completion["application_pid"] == record["pid"] and completion["sdk_pid"] == record["sdk_pid"]
                     and type(record["interval_ms"]) is int and record["interval_ms"] == node_live.INTERVAL_MS,
                     "live Node record or process identity differs")
    declared = entry["sequence_configuration"]
    provider.require(type(record["steps"]) is list and len(record["steps"]) == len(declared), "missing live Node calls")
    cursor = 0
    for index, (step, expected) in enumerate(zip(record["steps"], declared)):
        provider.require(type(step) is dict and set(step) == {"id", "requested", "before", "after"}
                         and step["id"] == "step-" + str(index) and type(step["requested"]) is dict
                         and set(step["requested"]) == {"collection", "emission"}
                         and all(type(flag) is bool for flag in step["requested"].values())
                         and step["requested"] == expected["metrics"], "live Node schedule differs")
        cursor = dimensions(step, cursor, len(bodies))
        if plain:
            provider.require(step["before"]["history"] == []
                             and all(step["after"][key] is None for key in ("status", "flush", "settled"))
                             and step["after"]["metric_bodies"] == [], "plain Node lane fabricated SDK replies")
    restored = record["restored"]
    provider.require(type(restored) is dict and set(restored) == {"history", "flush", "cursor"}
                     and count(restored["cursor"], len(bodies)) and restored["cursor"] >= cursor,
                     "missing live Node restoration")
    if plain:
        provider.require(record["sdk_pid"] is None and record["launch_id"] is None and not bodies
                         and restored["history"] == [] and restored["flush"] is None, "plain Node lane contains SDK evidence")
    else:
        final = capture.strict_json((folder / "node-runtime/node-status.json").read_bytes())
        provider.require(record["sdk_pid"] == final["sdk_pid"] and record["launch_id"] == final["launch_id"],
                         "live Node SDK differs from final completed SDK")
    record["record_sha256"] = hashlib.sha256(raw).hexdigest()
    return record


def dimensions(step: dict, previous: int, maximum: int) -> int:
    before, after = step["before"], step["after"]
    provider.require(type(before) is dict and set(before) == {"history", "cursor"}
                     and type(after) is dict and set(after) == {"status", "flush", "settled", "cursor", "metric_bodies", "held_ns"},
                     "incomplete live Node window")
    provider.require(count(before["cursor"], maximum) and count(after["cursor"], maximum)
                     and previous <= before["cursor"] <= after["cursor"]
                     and count(after["held_ns"], 3600000 * 1000000)
                     and type(after["metric_bodies"]) is list
                     and all(count(index, maximum - 1) for index in after["metric_bodies"]), "invalid live Node window")
    if not all(step["requested"].values()):
        provider.require(after["held_ns"] >= node_live.INTERVAL_MS * 1000000, "disabled metric window is too short")
    return after["cursor"]


def status(value: object, record: dict, completed: int, requested: dict) -> dict:
    actual = control.status(value, record["pid"])
    provider.require(actual["sdk_pid"] == record["sdk_pid"] and actual["launch_id"] == record["launch_id"]
                     and actual["language"] == record["language"]
                     and actual["function_completions"] == completed
                     and all(actual[key] is flag for key, flag in requested.items())
                     and (requested["emission"] or actual["effective_emission_off"]),
                     "live Node acknowledgement disagrees with actual call/control state")
    return actual


def history(rows: list, record: dict, requested: dict, completed: int) -> int:
    """Every actual setter must preserve its independent flag and all calls."""
    provider.require(type(rows) is list and 3 <= len(rows) <= control.MAX_STATUSES, "missing live Node transition history")
    commands = ["status", "collection " + ("on" if requested["collection"] else "off"),
                "emission " + ("on" if requested["emission"] else "off")]
    previous = None
    for index, row in enumerate(rows):
        provider.require(type(row) is dict and set(row) == {"command", "status"}
                         and row["command"] == (commands[index] if index < 3 else "status"), "unexpected live Node command")
        current = control.status(row["status"], record["pid"])
        provider.require(current["sdk_pid"] == record["sdk_pid"] and current["launch_id"] == record["launch_id"]
                         and current["language"] == record["language"]
                         and current["function_completions"] == completed, "live Node transition changed process or calls")
        provider.require(index != 0 or completed != 0
                         or all(current[key] is flag for key, flag in requested.items()),
                         "live Node initial metric state differs from the requested startup state")
        if index:
            key, other = ("collection", "emission") if index == 1 else ("emission", "collection")
            provider.require(current[key] is requested[key] and current[other] is previous[other],
                             "live Node setter changed an independent flag")
        previous = current
    status(previous, record, completed, requested)
    return len(rows)


def phase(indices: list[int], series: dict, totals: Counter, unwinds: Counter, *, required: bool) -> None:
    """Direct cumulative receipt distinguishes suppressed recording from transport."""
    expected = {(metric, name): value for name, value in totals.items()
                for metric in ("otelc.function.calls", "otelc.function.duration")}
    expected.update({("otelc.function.unwinds", name): unwinds[name] for name in totals})
    observed = {}
    for index in indices:
        for key, value in series[index].items():
            provider.require(key in expected and value <= expected[key], "live metric includes uncollected calls")
            observed[key] = max(observed.get(key, 0), value)
    if required:
        provider.require(all(observed.get(key) == value for key, value in expected.items()
                             if key[0] != "otelc.function.unwinds" or value), "missing positive or retained live measurements")


def qualify(record: dict, bodies: list, spans: list, series: dict, final: dict) -> tuple[Counter, Counter]:
    """Metrics count collection-enabled trees; traces retain every declared call."""
    groups = trees(spans)
    provider.require(len(groups) == len(record["steps"]), "live Node calls and serial roots differ")
    completed = statuses = 0
    totals, unwinds = Counter(), Counter()
    for step, group in zip(record["steps"], groups):
        requested, before, after = step["requested"], step["before"], step["after"]
        statuses += history(before["history"], record, requested, completed)
        completed += len(group)
        for name in ("status", "flush", "settled"):
            status(after[name], record, completed, requested)
            statuses += 1
        if requested["collection"]:
            for span in group:
                totals[span.name] += 1
                unwinds[span.name] += int(span.status.code == 2)
        received = metric_bodies(bodies, before["cursor"], after["cursor"])
        provider.require(after["metric_bodies"] == received and (all(requested.values()) or not received),
                         "live Node disabled window received metrics")
        phase(received, series, totals, unwinds, required=all(requested.values()))
    restored = record["restored"]
    statuses += history(restored["history"], record, {"collection": True, "emission": True}, completed)
    status(restored["flush"], record, completed, {"collection": True, "emission": True})
    provider.require(statuses + 1 <= control.MAX_STATUSES, "aggregate live Node status budget exceeded")
    received = metric_bodies(bodies, record["steps"][-1]["after"]["cursor"], restored["cursor"])
    phase(received, series, totals, unwinds, required=True)
    export_timeline(record, final)
    return totals, unwinds
