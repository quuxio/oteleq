"""Validate final Java SDK health against the actual process and decoded receipt."""
import os
from pathlib import Path
import re
import stat

from otelc_capture import strict_json

MAX_REPORT_BYTES = 4096
EXPORT_COUNTERS = {"batches_started", "batches_succeeded", "batches_failed", "batches_pending",
                   "units_started", "units_succeeded", "units_failed"}
REPORT_FIELDS = {"schema_version", "kind", "language", "pid", "policy_sha256", "selection_sha256",
                 "scope", "phase", "sdk_attached", "lifecycle", "metric_flush", "span_accounting",
                 "trace_exports", "metric_exports", "downstream_receipt", "otlp_partial_rejection"}


def require(condition: bool, reason: str) -> None:
    """Incomplete or unsupported SDK evidence cannot qualify an application run."""
    if not condition:
        raise ValueError("Java health: " + reason)


def read(runtime: Path) -> dict:
    """Read a bounded regular report from the caller's private canonical runtime."""
    require(runtime == runtime.resolve(strict=True), "runtime must be canonical")
    parent = os.open(runtime, os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW)
    try:
        directory = os.fstat(parent)
        require(stat.S_ISDIR(directory.st_mode) and directory.st_uid == os.getuid()
                and stat.S_IMODE(directory.st_mode) == 0o700, "runtime must be an owned 0700 directory")
        descriptor = os.open("health.json", os.O_RDONLY | os.O_NOFOLLOW | os.O_NONBLOCK, dir_fd=parent)
    finally:
        os.close(parent)
    try:
        before = os.fstat(descriptor)
        require(stat.S_ISREG(before.st_mode) and before.st_uid == os.getuid()
                and stat.S_IMODE(before.st_mode) == 0o600 and before.st_size <= MAX_REPORT_BYTES,
                "report must be a bounded owned 0600 regular file")
        with os.fdopen(descriptor, "rb", closefd=False) as stream:
            data = stream.read(MAX_REPORT_BYTES + 1)
        after = os.fstat(descriptor)
    finally:
        os.close(descriptor)
    identity = lambda value: (value.st_dev, value.st_ino, value.st_size, value.st_mtime_ns, value.st_ctime_ns)
    require(len(data) <= MAX_REPORT_BYTES and identity(before) == identity(after), "report changed while reading")
    return strict_json(data)


def counter(value: object, label: str) -> int:
    """Null is unavailable, and decimal counters use ASCII without lost precision."""
    require(type(value) is str and re.fullmatch(r"0|[1-9][0-9]*", value) is not None,
            "missing, unavailable or invalid counter: " + label)
    return int(value)


def exports(value: dict, unit: str, batches: int, units: int) -> dict:
    """Exporter API counts must agree with the independently decoded HTTP bodies."""
    require(type(value) is dict and set(value) == EXPORT_COUNTERS | {"exporters_observed", "unit"}
            and type(value["exporters_observed"]) is int and value["exporters_observed"] == 1
            and value["unit"] == unit, "unsupported exporter observer or shape: " + unit)
    actual = {name: counter(value[name], unit + "." + name) for name in EXPORT_COUNTERS}
    expected = {"batches_started": batches, "batches_succeeded": batches, "batches_failed": 0,
                "batches_pending": 0, "units_started": units, "units_succeeded": units, "units_failed": 0}
    require(actual == expected, "failed, pending or mismatched export receipt: " + unit)
    return actual


def qualify(report: dict, *, pid: int, policy_sha256: str, selection_sha256: str,
            trace_batches: int, spans: int, metric_batches: int, metric_points: int) -> dict:
    """Accept only an attached final supported pipeline with actual decoded receipt."""
    require(type(report) is dict and set(report) == REPORT_FIELDS
            and type(report["schema_version"]) is int and report["schema_version"] == 1
            and report["kind"] == "otelc.runtime-health" and report["language"] == "java"
            and report["scope"] == "sdk_pipeline", "unsupported report shape/version")
    require(type(pid) is int and pid > 0 and type(report["pid"]) is int and report["pid"] == pid,
            "report does not identify the actual launched JVM")
    for key, expected in (("policy_sha256", policy_sha256), ("selection_sha256", selection_sha256)):
        require(type(expected) is str and re.fullmatch(r"[0-9a-f]{64}", expected) is not None
                and report[key] == expected, "launch identity differs: " + key)
    require(report["phase"] == "final" and report["sdk_attached"] is True,
            "missing final attached SDK checkpoint")
    require(report["lifecycle"] == {"flush": "succeeded", "shutdown": "succeeded"},
            "SDK flush/shutdown did not succeed")
    require(all(type(value) is int and value > 0 for value in (trace_batches, spans, metric_batches, metric_points)),
            "required independently decoded receipt is missing")
    flush = report["metric_flush"]
    require(type(flush) is dict and set(flush) == {"attempts", "failed_attempts"}, "missing metric flush history")
    attempts = counter(flush["attempts"], "metric_flush.attempts")
    failed = counter(flush["failed_attempts"], "metric_flush.failed_attempts")
    require(attempts >= 1 and failed == attempts - 1, "metric flush attempt history is inconsistent")
    accounting = report["span_accounting"]
    expected = {"processors_observed": 1, "batch_processors_observed": 1, "sampled_started": str(spans),
                "sampled_ended": str(spans), "sampled_active": "0", "queue_pending": "0",
                "queue_dropped": "0", "queue_evidence": "derived_after_shutdown"}
    require(accounting == expected and all(type(accounting[key]) is int for key in
                ("processors_observed", "batch_processors_observed")),
            "span accounting is unavailable, unsupported, active, lost or inconsistent with receipt")
    trace = exports(report["trace_exports"], "spans", trace_batches, spans)
    metric = exports(report["metric_exports"], "metric_points", metric_batches, metric_points)
    require(report["downstream_receipt"] == report["otlp_partial_rejection"] == "unavailable",
            "SDK cannot establish downstream or partial-rejection evidence")
    return {"pid": pid, "metric_flush": {"attempts": attempts, "failed_attempts": failed},
            "span_accounting": accounting, "trace_exports": trace, "metric_exports": metric}
