"""Independent final Python health-2/SDK-1 accounting and local receipt checks."""

import hashlib
import json
from pathlib import Path
import re

import python_execution
import python_prepared
from python_provider import require, same

MAX_COUNTER = 2 ** 64 - 1
SDK_FIELDS = {"schema_version", "kind", "pid", "sdk_pid", "launch_id", "policy_sha256", "phase", "sdk_phase",
              "collection", "emission", "effective_emission_off", "closed", "shutdown_complete", "shutdown_failed",
              "shutdown_completed", "export_started", "export_succeeded", "export_failed", "in_flight_exports",
              "flush_started", "flush_failed", "in_flight_flushes", "metric_collection", "traces", "span_accounting",
              "handoff_received", "handoff_incomplete", "producer_checkpoint_available", "producer", "protocol_errors",
              "operation_failures", "operation_pending", "reply_lost"}
TRACE_FIELDS = {"closed", "started", "succeeded", "failed", "pending", "started_items", "exported_items",
                "failed_items", "pending_items"}
COLLECTION_FIELDS = {"closed", "started", "succeeded", "failed", "pending", "shutdown_complete", "shutdown_failed"}
QUEUE_FIELDS = {"received", "sdk_exported", "queue_pending", "queue_dropped", "queue_evidence",
                "downstream_receipt", "otlp_partial_rejection"}
PRODUCER_FIELDS = {"pid", "launch_id", "function_completions", "active_functions", "runtime_losses", "handoff", "span_observation"}
EXPORT_FIELDS = ("batches_started", "batches_succeeded", "batches_failed", "batches_pending",
                 "units_started", "units_succeeded", "units_failed")
RECEIVED = {"trace_batches", "spans", "metric_batches", "metric_points"}


def policy_digest(policy: dict) -> str:
    """SDK policy hashes use compact JSON, separately from prepared-file hashes."""
    return hashlib.sha256(json.dumps(policy, sort_keys=True, separators=(",", ":"), allow_nan=False).encode()).hexdigest()


def fields(value: object, names: set[str], label: str) -> dict:
    """Unknown or missing dimensions need a new qualified health profile."""
    require(type(value) is dict and set(value) == names, "invalid Python health " + label + " fields")
    return value


def count(value: object, label: str) -> int:
    """Unavailable, boolean, negative and oversized values cannot become zero."""
    require(type(value) is int and 0 <= value <= MAX_COUNTER, "invalid Python health counter: " + label)
    return value


def counts(value: dict, names: set[str], label: str) -> dict[str, int]:
    """Check each required integer while preserving the complete original data."""
    require(type(value) is dict and names <= set(value), "missing Python health " + label + " counters")
    return {name: count(value[name], label + "." + name) for name in names}


def producer(value: object, execution: python_execution.Execution, spans: int, received: int) -> dict:
    """Bind final application completion and handoff to the SDK's actual EOF."""
    value = fields(value, PRODUCER_FIELDS, "producer")
    require(same({key: value[key] for key in ("pid", "launch_id")},
                 {"pid": execution.application_pid, "launch_id": execution.launch_id}), "Python producer identity differs")
    totals = counts(value, {"function_completions", "active_functions"}, "producer")
    require(totals == {"function_completions": spans, "active_functions": 0}, "Python producer calls are active or incomplete")
    losses = value["runtime_losses"]
    require(type(losses) is dict and "incomplete" in losses and len(losses) <= 32
            and all(type(name) is str and 0 < len(name) <= 128 and "\0" not in name for name in losses),
            "Python runtime loss dimensions are unavailable")
    require(not any(count(number, "runtime loss " + name) for name, number in losses.items()), "Python runtime reported lost observations")
    handoff = fields(value["handoff"], {"attempted", "accepted", "lost", "deadline_ms"}, "handoff")
    transfer = counts(handoff, {"attempted", "accepted", "lost"}, "handoff")
    require(transfer["attempted"] == transfer["accepted"] == received - 1 and transfer["lost"] == 0
            and type(handoff["deadline_ms"]) in (int, float)
            and handoff["deadline_ms"] == 50, "Python final handoff/EOF accounting differs")
    observation = fields(value["span_observation"], {"sampled_started", "sampled_ended", "handed_off"}, "span observation")
    require(counts(observation, set(observation), "span observation") == dict.fromkeys(observation, spans),
            "Python application spans are missing, active or lost")
    return value


def sdk_pipeline(sdk: dict, received: dict) -> None:
    """Exporter API counts and final queue/collection state must match receipt."""
    traces = fields(sdk["traces"], TRACE_FIELDS, "trace exporter")
    expected_trace = {"started": received["trace_batches"], "succeeded": received["trace_batches"],
                      "failed": 0, "pending": 0, "started_items": received["spans"],
                      "exported_items": received["spans"], "failed_items": 0, "pending_items": 0}
    require(traces["closed"] is True and counts(traces, set(expected_trace), "trace exporter") == expected_trace,
            "Python trace exporter receipt, loss or pending counts differ")
    collection = fields(sdk["metric_collection"], COLLECTION_FIELDS, "metric collection")
    totals = counts(collection, {"started", "succeeded", "failed", "pending"}, "metric collection")
    require(collection["closed"] is collection["shutdown_complete"] is True and collection["shutdown_failed"] is False
            and totals["started"] == totals["succeeded"] >= received["metric_batches"]
            and totals["failed"] == totals["pending"] == 0, "Python metric collection is failed or pending")
    queue = fields(sdk["span_accounting"], QUEUE_FIELDS, "span queue")
    require(counts(queue, {"received", "sdk_exported", "queue_pending", "queue_dropped"}, "span queue")
            == {"received": received["spans"], "sdk_exported": received["spans"], "queue_pending": 0, "queue_dropped": 0}
            and queue["queue_evidence"] == "derived_after_shutdown"
            and queue["downstream_receipt"] == queue["otlp_partial_rejection"] == "unavailable",
            "Python final queue accounting is unavailable, lost or pending")


def sdk_report(value: object, execution: python_execution.Execution, digest: str, received: dict) -> dict:
    """Closed SDK shutdown alone cannot establish a clean export or delivery."""
    value = fields(value, SDK_FIELDS, "SDK")
    identity = {key: value[key] for key in ("schema_version", "kind", "pid", "sdk_pid", "launch_id", "policy_sha256")}
    require(same(identity, {"schema_version": 1, "kind": "otelc.python.sdk", "pid": execution.application_pid,
                            "sdk_pid": execution.sdk_pid, "launch_id": execution.launch_id, "policy_sha256": digest}),
            "Python final SDK identity differs")
    require(value["phase"] == value["sdk_phase"] == "closed"
            and all(value[name] is True for name in ("collection", "emission", "closed", "shutdown_complete",
                                                     "shutdown_completed", "producer_checkpoint_available"))
            and all(value[name] is False for name in ("effective_emission_off", "shutdown_failed", "operation_pending")),
            "Python final SDK is detached, suppressed or unfinished")
    integer_names = {"export_started", "export_succeeded", "export_failed", "in_flight_exports", "in_flight_flushes",
                     "flush_started", "flush_failed", "handoff_received", "handoff_incomplete", "protocol_errors",
                     "operation_failures", "reply_lost"}
    totals = counts(value, integer_names, "SDK")
    require(totals["export_started"] == totals["export_succeeded"] == received["metric_batches"]
            and all(totals[name] == 0 for name in integer_names - {"export_started", "export_succeeded", "flush_started", "handoff_received"}),
            "Python SDK export, control, handoff or pending counters failed")
    producer(value["producer"], execution, received["spans"], totals["handoff_received"])
    sdk_pipeline(value, received)
    return value


def exporter(sdk: dict, *, traces: bool) -> dict:
    """Metric-point units stay null; only the independent collector counts them."""
    if traces:
        raw = sdk["traces"]
        names = ("started", "succeeded", "failed", "pending", "started_items", "exported_items", "failed_items")
        values = [str(raw[name]) for name in names]
    else:
        values = [str(sdk[name]) for name in ("export_started", "export_succeeded", "export_failed", "in_flight_exports")]
        values.extend((None, None, None))
    return {"exporters_observed": 1, "unit": "spans" if traces else "metric_points", **dict(zip(EXPORT_FIELDS, values, strict=True))}


def qualify(report: object, sdk: object, execution: python_execution.Execution, digest: str, receipt: dict) -> dict:
    """Verify final pipeline facts and preserve every explicitly unavailable field."""
    require(type(execution) is python_execution.Execution and python_execution.pid(execution.sdk_pid)
            and type(digest) is str and re.fullmatch("[0-9a-f]{64}", digest) is not None,
            "Python health requires the actual instrumented execution identity")
    received = counts(fields(receipt, RECEIVED, "independent receipt"), RECEIVED, "independent receipt")
    require(all(number > 0 for number in received.values()), "Python health lacks a positive decoded receipt")
    sdk = sdk_report(sdk, execution, digest, received)
    expected = {"schema_version": 2, "kind": "otelc.runtime-health", "language": "python",
                "scope": "application_sdk_pair", "pid": execution.application_pid, "sdk_pid": execution.sdk_pid,
                "launch_id": execution.launch_id, "policy_sha256": digest, "phase": "final", "sdk_attached": True,
                "lifecycle": {"flush": "unavailable", "shutdown": "succeeded"},
                "metric_flush": {"scope": "exporter", "attempts": str(sdk["flush_started"]), "failed_attempts": str(sdk["flush_failed"])},
                "span_accounting": {"processors_observed": 1, "batch_processors_observed": 1,
                    "sampled_started": str(received["spans"]), "sampled_ended": str(received["spans"]),
                    "sampled_active": "0", "queue_pending": "0", "queue_dropped": "0", "queue_evidence": "derived_after_shutdown"},
                "trace_exports": exporter(sdk, traces=True), "metric_exports": exporter(sdk, traces=False),
                "downstream_receipt": "unavailable", "otlp_partial_rejection": "unavailable", "source_complete": False,
                "application_exit": 0, "sdk_exit": 0, "failures": {}, "application": sdk["producer"], "sdk": sdk}
    require(type(report) is dict and same(report, expected), "Python public health differs from independently checked final SDK facts")
    return {"pid": execution.application_pid, "sdk_pid": execution.sdk_pid, "launch_id": execution.launch_id,
            "received": received, "runtime_losses": sdk["producer"]["runtime_losses"], "pending": 0,
            "aggregate_flush": "unavailable", "sdk_metric_points": None, "source_origin": "unavailable"}


def read(runtime: Path, execution: python_execution.Execution, digest: str, receipt: dict) -> dict:
    """Compare the public health view with its separately retained SDK report."""
    report, _ = python_prepared.read(runtime / "health.json")
    sdk, _ = python_prepared.read(runtime / "sdk/python-sdk-status.json")
    return qualify(report, sdk, execution, digest, receipt)
