"""Read Go health-4 independently and bind final accounting to actual receipt."""

import os
from pathlib import Path
import re
import stat
from typing import cast

from go_provider import require
from otelc_capture import strict_json

MAX_REPORT_BYTES = 64 * 1024
MAX_COUNTER = (1 << 64) - 1
FIELDS = {"schema_version", "kind", "language", "scope", "pid", "policy_sha256",
          "selection_sha256", "phase", "sdk_attached", "source_complete", "controls",
          "lifecycle", "metric_flush", "probe_accounting", "metric_exports", "trace_exports",
          "downstream_receipt", "otlp_partial_rejection", "http_spans"}
PROBES = {"function_started", "function_ended", "function_active", "function_lost",
          "observer_started", "observer_ended", "observer_active", "observer_lost", "unwind_unknown",
          "object_admitted", "gc_observed", "resource_released", "objects_pending",
          "resources_unreleased", "lifetime_lost", "duplicate_objects"}
OUTCOMES = ("not_started", "pending", "succeeded", "failed", "timed_out")


def fields(value: object, expected: set[str], label: str) -> dict:
    """New fields require an explicit supported schema, never a partial view."""
    require(type(value) is dict and set(value) == expected, "invalid health " + label + " fields")
    return value


def count(value: object, label: str) -> int:
    """Unknown values and inexact decimal encodings cannot become zero."""
    # Wire counters use ASCII digits, including every digit after the first.
    require(type(value) is str and re.fullmatch(r"0|[1-9][0-9]{0,19}", value) is not None
            and int(value) <= MAX_COUNTER, "invalid health counter: " + label)
    return int(value)


def counters(value: object, expected: set[str], label: str, *, closed: bool = False) -> dict:
    """Normalise the named counters while retaining closed as a real boolean."""
    value = fields(value, expected | ({"closed"} if closed else set()), label)
    result = {name: count(value[name], label + "." + name) for name in expected}
    if closed:
        require(type(value["closed"]) is bool, "invalid health closed flag: " + label)
        result["closed"] = value["closed"]
    return result


def exporter(value: object, *, traces: bool) -> dict | None:
    """An absent trace exporter has no invented queue or delivery counters."""
    require(type(value) is dict and type(value.get("observed")) is bool, "invalid exporter observation")
    value = cast(dict, value)
    if not value["observed"]:
        require(set(value) == {"observed"} and traces, "missing exporter or invented unobserved counters")
        return None
    expected = {"attempts", "succeeded", "failed"}
    if traces:
        expected |= {"exported_spans", "queue_pending", "queue_dropped"}
    return counters({name: item for name, item in value.items() if name != "observed"},
                    expected, "trace exports" if traces else "metric exports", closed=True)


def http_spans(value: object) -> dict | None:
    """HTTP operation boundaries stay separate from probes and resource release."""
    require(type(value) is dict and type(value.get("observed")) is bool, "invalid HTTP span observation")
    value = cast(dict, value)
    if not value["observed"]:
        require(set(value) == {"observed"}, "invented unobserved HTTP span counters")
        return None
    return counters({name: item for name, item in value.items() if name != "observed"},
                    {"started", "ended", "active"}, "HTTP spans", closed=True)


def read(runtime: Path) -> dict:
    """Read only a completed owned private checkpoint without following links."""
    require(runtime == runtime.resolve(strict=True), "health runtime must be canonical")
    parent = os.open(runtime, os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW)
    descriptor = None
    try:
        directory = os.fstat(parent)
        require(stat.S_ISDIR(directory.st_mode) and directory.st_uid == os.getuid()
                and stat.S_IMODE(directory.st_mode) == 0o700, "health runtime must be owned and mode0700")
        descriptor = os.open("health.json", os.O_RDONLY | os.O_NOFOLLOW | os.O_NONBLOCK, dir_fd=parent)
        before = os.fstat(descriptor)
        require(stat.S_ISREG(before.st_mode) and before.st_uid == os.getuid() and before.st_nlink == 1
                and stat.S_IMODE(before.st_mode) == 0o600 and before.st_size <= MAX_REPORT_BYTES,
                "health checkpoint must be a bounded owned mode0600 ordinary file")
        with os.fdopen(descriptor, "rb", closefd=False) as stream:
            data = stream.read(MAX_REPORT_BYTES + 1)
        after = os.fstat(descriptor)
        current = os.stat("health.json", dir_fd=parent, follow_symlinks=False)
        identity = lambda info: (info.st_dev, info.st_ino, info.st_size, info.st_mtime_ns,
                                 info.st_ctime_ns, info.st_mode, info.st_uid, info.st_nlink)
        require(len(data) == before.st_size and identity(before) == identity(after) == identity(current),
                "health checkpoint changed while reading")
        current_directory = runtime.lstat()
        require(runtime.resolve(strict=True) == runtime
                and (directory.st_dev, directory.st_ino, directory.st_mode, directory.st_uid, directory.st_gid)
                == (current_directory.st_dev, current_directory.st_ino, current_directory.st_mode,
                    current_directory.st_uid, current_directory.st_gid), "health runtime changed while reading")
        return strict_json(data)
    finally:
        if descriptor is not None:
            os.close(descriptor)
        os.close(parent)


def validate(value: object, *, pid: int, policy_sha256: str, selection_sha256: str) -> dict:
    """Bind raw live/final fields to caller-owned identities without assuming quiescence."""
    value = fields(value, FIELDS, "report")
    require(type(value["schema_version"]) is int and value["schema_version"] == 4
            and value["kind"] == "otelc.runtime-health" and value["language"] == "go"
            and value["scope"] == "sdk_pipeline" and value["sdk_attached"] is True
            and value["source_complete"] is False and value["phase"] in ("running", "final"),
            "unsupported health identity or scope")
    require(type(pid) is int and pid > 1 and type(value["pid"]) is int and value["pid"] == pid,
            "health differs from actual application/embedded SDK process")
    for name, expected in (("policy_sha256", policy_sha256), ("selection_sha256", selection_sha256)):
        require(type(expected) is str and re.fullmatch(r"[0-9a-f]{64}", expected) is not None
                and value[name] == expected, "health differs from caller-owned " + name)
    state = fields(value["controls"], {"schema_version", "pid", "collection", "emission", "effective_emission_off"}, "controls")
    require(type(state["schema_version"]) is int and state["schema_version"] == 1
            and type(state["pid"]) is int and state["pid"] == pid
            and all(type(state[name]) is bool for name in ("collection", "emission", "effective_emission_off"))
            and state["effective_emission_off"] is (not state["emission"]), "invalid health live controls")
    lifecycle = fields(value["lifecycle"], {"flush", "shutdown"}, "lifecycle")
    require(all(type(item) is str and item in OUTCOMES for item in lifecycle.values()), "invalid health lifecycle outcome")
    counters(value["metric_flush"], {"attempts", "failed_attempts"}, "metric flush")
    counters(value["probe_accounting"], PROBES, "probes", closed=True)
    exporter(value["metric_exports"], traces=False)
    exporter(value["trace_exports"], traces=True)
    http_spans(value["http_spans"])
    require(value["http_spans"]["observed"] is value["trace_exports"]["observed"],
            "HTTP span observation differs from the owned trace SDK")
    require(value["downstream_receipt"] == value["otlp_partial_rejection"] == "unavailable",
            "SDK cannot claim downstream delivery or partial-rejection knowledge")
    return value


def qualify(value: object, *, pid: int, policy_sha256: str, selection_sha256: str,
            received: dict, function_spans: int, observer_completions: int, received_http_spans: int) -> dict:
    """Require closed clean SDK accounting and complete diagnostic trace receipt."""
    value = validate(value, pid=pid, policy_sha256=policy_sha256, selection_sha256=selection_sha256)
    received = fields(received, {"trace_batches", "spans", "metric_batches", "metric_points"}, "received")
    require(all(type(number) is int and 0 <= number <= MAX_COUNTER
                for number in (*received.values(), function_spans, observer_completions, received_http_spans)),
            "invalid independent receipt counts")
    require(received_http_spans <= received["spans"], "HTTP receipt exceeds the complete decoded trace count")
    require(value["phase"] == "final" and value["lifecycle"] == {"flush": "succeeded", "shutdown": "succeeded"},
            "missing final successful SDK flush/shutdown")
    probes = counters(value["probe_accounting"], PROBES, "probes", closed=True)
    require(probes["closed"] and probes["function_started"] == probes["function_ended"] == function_spans
            and probes["observer_started"] == probes["observer_ended"] == observer_completions
            and not any(probes[name] for name in ("function_active", "function_lost", "observer_active",
                        "observer_lost", "unwind_unknown", "lifetime_lost")), "active, lost or mismatched probe completions")
    flush = counters(value["metric_flush"], {"attempts", "failed_attempts"}, "metric flush")
    require(flush["attempts"] >= 1 and flush["failed_attempts"] == 0, "missing or failed final metric flush")
    http = http_spans(value["http_spans"])
    if http is None:
        require(received_http_spans == 0, "received HTTP spans without a recording observer")
    else:
        require(http["closed"] and http["active"] == 0
                and http["started"] == http["ended"] == received_http_spans,
                "active, unclosed or mismatched HTTP span completions")
    exports = export_receipts(value, received)
    return {"pid": pid, "sdk_pid": pid, "received": received.copy(), "probe_accounting": probes,
            "metric_flush": flush, "http_spans": http, **exports, "metric_exported_points": None, "source_complete": False}


def export_receipts(value: dict, received: dict) -> dict:
    """Join final export/queue accounting to independently decoded batches."""
    exports = {}
    for name, traces, batches in (("metric_exports", False, "metric_batches"), ("trace_exports", True, "trace_batches")):
        actual = exporter(value[name], traces=traces)
        if actual is None:
            require(received[batches] == received["spans"] == 0, "received traces from an unobserved exporter")
        else:
            require(actual["closed"] and actual["attempts"] == actual["succeeded"] == received[batches]
                    and actual["failed"] == 0, "export failure, incomplete drain or receiver batch mismatch")
            if traces:
                require(actual["exported_spans"] == received["spans"]
                        and actual["queue_pending"] == actual["queue_dropped"] == 0,
                        "trace receipt, queue or loss differs")
        exports[name] = actual
    return exports
