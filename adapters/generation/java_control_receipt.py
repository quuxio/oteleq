"""Bind serial call trees, recorded controls and direct cumulative metric receipt."""
import hashlib
from pathlib import Path

import java_control as control
import java_live
from otelc_capture import strict_json


def counter(value: object, maximum: int) -> bool:
    return type(value) is int and 0 <= value <= maximum


def read(folder: Path, entry: dict, pid: int, bodies: list, *, plain: bool) -> dict:
    """Both lanes retain real process identity; plain mode fabricates no SDK reply."""
    raw = java_live.read_owned(folder / java_live.RECORD, java_live.MAX_RECORD_BYTES)
    record = strict_json(raw)
    control.require(type(record) is dict and set(record) == {"control_schema_version", "plain", "pid", "interval_ms", "steps", "restored"}
                    and type(record["control_schema_version"]) is int and record["control_schema_version"] == 1
                    and record["plain"] is plain and type(record["pid"]) is int and record["pid"] == pid
                    and type(record["interval_ms"]) is int and record["interval_ms"] == java_live.INTERVAL_MS,
                    "control record identity differs")
    declared = entry["sequence_configuration"]
    control.require(type(record["steps"]) is list and len(record["steps"]) == len(declared), "missing control call records")
    cursor = 0
    for index, (step, expected) in enumerate(zip(record["steps"], declared)):
        control.require(type(step) is dict and set(step) == {"id", "requested", "before", "after"}
                        and step["id"] == "step-" + str(index)
                        and type(step["requested"]) is dict and set(step["requested"]) == {"collection", "emission"}
                        and all(type(flag) is bool for flag in step["requested"].values())
                        and step["requested"] == expected["metrics"],
                        "control call identity or requested state differs")
        cursor = dimensions(step, cursor, len(bodies))
        if plain:
            control.require(step["before"]["history"] == [] and all(step["after"][key] is None for key in ("status", "flush", "settled"))
                            and step["after"]["metric_bodies"] == [], "plain lane contains fabricated SDK controls")
    restored = record["restored"]
    control.require(type(restored) is dict and set(restored) == {"history", "flush", "cursor"}
                    and counter(restored["cursor"], len(bodies)) and restored["cursor"] >= cursor,
                    "missing final control restoration")
    if plain:
        control.require(restored["history"] == [] and restored["flush"] is None and not bodies, "plain lane contains SDK control receipt")
    record["record_sha256"] = hashlib.sha256(raw).hexdigest()
    return record


def dimensions(step: dict, previous: int, maximum: int) -> int:
    before, after = step["before"], step["after"]
    control.require(type(before) is dict and set(before) == {"history", "cursor"}
                    and type(after) is dict and set(after) == {"status", "flush", "settled", "cursor", "metric_bodies", "held_ns"},
                    "incomplete call checkpoint receipt")
    control.require(counter(before["cursor"], maximum) and counter(after["cursor"], maximum)
                    and previous <= before["cursor"] <= after["cursor"]
                    and counter(after["held_ns"], 900000 * 1000000)
                    and type(after["metric_bodies"]) is list
                    and all(counter(index, maximum - 1) for index in after["metric_bodies"]), "invalid control observation window")
    if not step["requested"]["emission"]:
        control.require(after["held_ns"] >= java_live.INTERVAL_MS * 1000000, "emission-off window is shorter than one export interval")
    return after["cursor"]


def history(rows: list, pid: int, requested: dict, completed: int) -> int:
    """Each independent setter must preserve the other actual control and counter."""
    control.require(type(rows) is list and 3 <= len(rows) <= control.MAX_STATUS_RECORDS, "missing bounded control history")
    commands = ["status", "collection " + ("on" if requested["collection"] else "off"),
                "emission " + ("on" if requested["emission"] else "off")]
    previous = None
    for index, row in enumerate(rows):
        control.require(type(row) is dict and set(row) == {"command", "status"}
                        and row["command"] == (commands[index] if index < 3 else "status"), "unexpected control acknowledgement")
        current = control.status(row["status"], pid)
        control.require(current["completed"] == completed, "selected measurements changed during a control transition")
        if index > 0:
            independent_transition(index, current, previous, requested)
        previous = current
    control.require(all(previous[key] == value for key, value in requested.items())
                    and (requested["emission"] or previous["effective_emission_off"]), "requested export barrier was not reached")
    return len(rows)


def independent_transition(index: int, current: dict, previous: dict, requested: dict) -> None:
    """A setter acknowledges only its own flag; polls preserve both flags."""
    key, other = ("collection", "emission") if index == 1 else ("emission", "collection")
    control.require(current[key] == requested[key] and current[other] == previous[other],
                    "control transition altered an independent state")


def trees(nodes: dict, intervals: dict) -> list[int]:
    """Serial complete named trees qualify call order, not invocation cookies."""
    roots = [key for key, parent in nodes.items() if parent is None]
    roots.sort(key=lambda key: intervals[key])
    control.require(all(intervals[left][1] <= intervals[right][0] and intervals[left] != intervals[right]
                        for left, right in zip(roots, roots[1:])), "selected call trees overlap or have ambiguous order")
    positions = {key: index for index, key in enumerate(roots)}
    counts = [0] * len(roots)
    for key in nodes:
        root = key
        while nodes[root] is not None:
            root = nodes[root]
        control.require(intervals[root][0] <= intervals[key][0] <= intervals[key][1] <= intervals[root][1],
                        "selected child span escapes its synchronous call tree")
        counts[positions[root]] += 1
    return counts


def qualify(record: dict, pid: int, bodies: list, sizes: list[int], series: dict) -> int:
    """Direct receipt must include collected calls and exclude uncollected calls."""
    control.require(len(record["steps"]) == len(sizes), "control calls and selected roots differ")
    completed, statuses = 0, 0
    for step, size in zip(record["steps"], sizes):
        requested, before, after = step["requested"], step["before"], step["after"]
        statuses += history(before["history"], pid, requested, completed)
        completed += size if requested["collection"] else 0
        for name in ("status", "flush", "settled"):
            value = control.status(after[name], pid)
            statuses += 1
            control.require(value["completed"] == completed and all(value[key] == flag for key, flag in requested.items())
                            and (requested["emission"] or value["effective_emission_off"]), "per-call recording or emission state differs")
        received = java_live.metric_bodies(bodies, before["cursor"], after["cursor"])
        control.require(after["metric_bodies"] == received and (requested["emission"] or not received), "emission-off window received metrics")
        phase_series(received, series, completed, required=requested["collection"] and requested["emission"])
    restored = record["restored"]
    statuses += history(restored["history"], pid, {"collection": True, "emission": True}, completed)
    final = control.status(restored["flush"], pid)
    control.require(final["completed"] == completed and final["collection"] and final["emission"], "final restored controls differ")
    control.require(statuses + 1 <= java_live.MAX_STATUSES, "control history exceeds its aggregate budget")
    received = java_live.metric_bodies(bodies, record["steps"][-1]["after"]["cursor"], restored["cursor"])
    phase_series(received, series, completed, required=True)
    return completed


def phase_series(indices: list[int], series: dict, expected: int, *, required: bool) -> None:
    """A live positive/export-restoration control needs both actual metric series."""
    for name in ("otelc.function.calls", "otelc.function.duration"):
        values = [point for index in indices for point in series[index][name]]
        control.require(all(value <= expected for _, value in values), "phase metric includes uncollected calls")
        if required:
            control.require(values and max(values)[1] == expected, "missing positive or retained emission-off measurements")
