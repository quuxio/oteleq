"""Reconcile frozen Python metric schedules with actual controls and OTLP."""

from collections import Counter
import hashlib
from pathlib import Path

from java_live import metric_bodies, read_owned
from otelc_collection import serial_trees as trees
import otelc_capture as capture
import python_control as control
import python_health as health
import python_live
import python_provider as provider
import python_telemetry as telemetry


def checked_status(value: object, record: dict, completed: int, flags: dict, command: str) -> dict:
    actual = control.status(value, record["pid"], command)
    provider.require(actual["sdk_pid"] == record["sdk_pid"]
                     and actual["function_completions"] == completed
                     and all(actual[key] is flag for key, flag in flags.items()),
                     "live Python reply disagrees with the actual call schedule")
    if command != "flush" and not flags["emission"]:
        provider.require(actual["effective_emission_off"], "live Python emission-off barrier is incomplete")
    return actual


def checked_health(value: object, record: dict, completed: int, flags: dict) -> dict:
    actual = control.live(value, record["pid"])
    provider.require(actual["sdk_pid"] == record["sdk_pid"] and actual["launch_id"] == record["launch_id"]
                     and actual["policy_sha256"] == record["policy_sha256"]
                     and actual["application"]["function_completions"] == completed
                     and all(actual["sdk"][key] is flag for key, flag in flags.items()),
                     "live Python health identity or selected-call count differs")
    provider.require(all(flags.values()) or actual["sdk"]["in_flight_exports"] == 0,
                     "disabled Python window began before exports drained")
    return actual["sdk"]


def transition(value: object, record: dict, completed: int, flags: dict, *, initial: bool = False) -> int:
    """Read each independent setter without treating its preceding state as new."""
    provider.require(type(value) is list and 3 <= len(value) <= control.MAX_STATUSES,
                     "missing Python live transition replies")
    commands = ["status", "collection " + ("on" if flags["collection"] else "off"),
                "emission " + ("on" if flags["emission"] else "off")]
    previous = None
    for index, row in enumerate(value):
        row = health.fields(row, {"command", "response"}, "live transition")
        provider.require(row["command"] == (commands[index] if index < 3 else "status"),
                         "Python live command order differs")
        current = control.status(row["response"], record["pid"], row["command"])
        provider.require(current["sdk_pid"] == record["sdk_pid"] and current["function_completions"] == completed,
                         "Python calls or SDK changed during a live transition")
        if initial and index == 0:
            provider.require(all(current[key] is flag for key, flag in flags.items()),
                             "Python startup flags differ from the first declared call")
        if index:
            key, other = ("collection", "emission") if index == 1 else ("emission", "collection")
            provider.require(current[key] is flags[key] and current[other] is previous[other],
                             "Python live setter changed its independent flag")
        previous = current
    checked_status(previous, record, completed, flags, "status")
    return len(value)


def read(folder: Path, entry: dict, execution, policy: dict, bodies: list, *, plain: bool) -> dict:
    """Bind closed retained metadata to independently verified actual execution."""
    raw = read_owned(folder / python_live.RECORD, python_live.MAX_RECORD_BYTES)
    record = health.fields(capture.strict_json(raw), {
        "control_schema_version", "plain", "profile", "supervisor_pid", "pid", "sdk_pid", "launch_id",
        "policy_sha256", "interval_ms", "steps", "restored"}, "live record")
    expected = {"control_schema_version": 1, "plain": plain, "profile": entry["python_profile"],
                "supervisor_pid": execution.owner.pid, "pid": execution.application_pid,
                "sdk_pid": execution.sdk_pid, "launch_id": execution.launch_id,
                "policy_sha256": health.policy_digest(policy), "interval_ms": python_live.INTERVAL_MS}
    provider.require(provider.same({key: record[key] for key in expected}, expected),
                     "Python live record differs from actual prepared process identities")
    provider.require(type(record["steps"]) is list and len(record["steps"]) == len(entry["sequence_configuration"]),
                     "Python live record is missing declared calls")
    cursor = 0
    for index, (step, declared) in enumerate(zip(record["steps"], entry["sequence_configuration"])):
        step = health.fields(step, {"id", "requested", "before", "after"}, "live step")
        provider.require(step["id"] == "step-" + str(index) and provider.same(step["requested"], declared["metrics"]),
                         "Python live requested schedule changed")
        before = health.fields(step["before"], {"history", "flush", "health", "cursor"}, "live before")
        after = health.fields(step["after"], {"status", "flush", "health", "settled_flush", "settled", "cursor", "metric_bodies", "held_ns"}, "live after")
        start, end = before["cursor"], after["cursor"]
        provider.require(type(start) is int and type(end) is int and cursor <= start <= end <= len(bodies)
                         and type(after["held_ns"]) is int and 0 <= after["held_ns"] <= 3600000 * 1000000,
                         "Python live receipt cursors or interval differ")
        received = metric_bodies(bodies, start, end)
        provider.require(provider.same(after["metric_bodies"], received)
                         and (all(step["requested"].values()) or not received
                              and after["held_ns"] >= python_live.INTERVAL_MS * 1000000),
                         "Python disabled metric interval is missing, too short or received data")
        if plain:
            provider.require(before["history"] == [] and before["flush"] is before["health"] is None
                             and all(after[key] is None for key in ("status", "flush", "health", "settled_flush", "settled")),
                             "plain Python live record fabricated SDK replies")
        cursor = end
    restored = health.fields(record["restored"], {"history", "flush", "health", "cursor"}, "live restoration")
    provider.require(type(restored["cursor"]) is int and cursor <= restored["cursor"] <= len(bodies),
                     "Python live restoration cursor differs")
    if plain:
        provider.require(not bodies and restored["history"] == [] and restored["flush"] is restored["health"] is None,
                         "plain Python live lane contains SDK evidence")
    record["record_sha256"] = hashlib.sha256(raw).hexdigest()
    return record


def phase(indices: list[int], series: dict, calls: Counter, errors: Counter, *, required: bool) -> None:
    """Count only collected trees; successful export is checked through receipt."""
    expected = {(metric, code): count for code, count in calls.items() if count
                for metric in (telemetry.CALLS, telemetry.DURATION)}
    expected.update({(telemetry.EXCEPTIONS, code): errors[code] for code, count in calls.items() if count})
    observed = {}
    for index in indices:
        for key, count in series[index].items():
            provider.require(key in expected and count <= expected[key], "Python metrics contain uncollected calls")
            observed[key] = max(observed.get(key, 0), count)
    if required:
        provider.require(all(observed.get(key) == count for key, count in expected.items()
                             if key[0] != telemetry.EXCEPTIONS or count),
                         "Python positive or retained live measurements are missing")


def qualify(record: dict, entry: dict, bodies: list, execution, service: str, functions: dict,
            trace_decoder, metric_decoder, final: dict) -> tuple[Counter, Counter, dict]:
    """Use full selected serial trees and literal code IDs as the denominator."""
    spans, series = [], {}
    for index, (route, body) in enumerate(bodies):
        if route == capture.TRACE_PATH:
            for resource in trace_decoder.FromString(body).resource_spans:
                telemetry.trace_group(resource, execution, service, functions, {}, {}, Counter(), Counter())
                spans.extend(span for scope in resource.scope_spans for span in scope.spans)
        else:
            observed = {}
            for resource in metric_decoder.FromString(body).resource_metrics:
                telemetry.metric_group(resource, execution, service, functions, observed, [])
            series[index] = telemetry.cumulative(observed)
    groups = trees(spans)
    creator = provider.creator(entry)
    prefix = int(creator is not None)
    provider.require(len(groups) == len(record["steps"]) + prefix, "Python live trace tree denominator differs")
    for index, group in enumerate(groups):
        root, = (span for span in group if not span.parent_span_id)
        provider.require(root.name == (creator if index < prefix else entry["otelc_function"]),
                         "Python creation or selected call tree order differs")
    calls, errors, completed, collected = Counter(), Counter(), 0, {}

    def collect(group: list, enabled: bool) -> None:
        for span in group:
            code, _ = telemetry.label(span.attributes, functions, span=True)
            if enabled:
                collected[capture.span_identity(span)] = code
                calls[code] += 1
                errors[code] += int(span.status.code == 2)

    if prefix:
        completed = len(groups[0])
        collect(groups[0], record["steps"][0]["requested"]["collection"])
    snapshots, statuses = [], 0
    for index, (step, group) in enumerate(zip(record["steps"], groups[prefix:])):
        flags, before, after = step["requested"], step["before"], step["after"]
        statuses += transition(before["history"], record, completed, flags, initial=index == 0)
        checked_status(before["flush"], record, completed, flags, "flush")
        snapshots.append(checked_health(before["health"], record, completed, flags))
        completed += len(group)
        for name, command in (("status", "status"), ("flush", "flush"), ("settled_flush", "flush")):
            checked_status(after[name], record, completed, flags, command)
        snapshots.extend(checked_health(after[name], record, completed, flags) for name in ("health", "settled"))
        statuses += 7
        collect(group, flags["collection"])
        phase(after["metric_bodies"], series, calls, errors, required=all(flags.values()))
    restored, flags = record["restored"], {"collection": True, "emission": True}
    statuses += transition(restored["history"], record, completed, flags)
    checked_status(restored["flush"], record, completed, flags, "flush")
    snapshots.append(checked_health(restored["health"], record, completed, flags))
    provider.require(statuses + 2 <= control.MAX_STATUSES, "Python live status budget exceeded")
    phase(metric_bodies(bodies, record["steps"][-1]["after"]["cursor"], restored["cursor"]), series, calls, errors, required=True)
    names = ("export_started", "export_succeeded", "export_failed")
    previous, drained = dict.fromkeys(names, 0), None
    for sdk in [*snapshots, final]:
        provider.require(all(type(sdk[key]) is int and sdk[key] >= previous[key] for key in previous),
                         "Python live exporter counters moved backwards")
        if drained is not None and not sdk["emission"]:
            provider.require(sdk["export_started"] == drained, "Python SDK admitted exports after emission-off drained")
        drained = sdk["export_started"] if not sdk["emission"] and sdk["effective_emission_off"] else None
        previous = {key: sdk[key] for key in names}
    return calls, errors, collected
