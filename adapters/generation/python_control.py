"""Independently read Python controls and live health from the owned SDK pair."""

from pathlib import Path
import re

import live_control
import python_health as health
from python_provider import require, same

COMMANDS = {"status", "flush", "health", "collection on", "collection off", "emission on", "emission off"}
MAX_STATUSES = 512
BASE_FIELDS = {"schema_version", "pid", "sdk_pid", "collection", "emission",
               "function_completions", "active_functions", "runtime_losses"}
BARRIER_FIELDS = {"effective_emission_off", "in_flight_exports"}
HEALTH_FIELDS = {"schema_version", "kind", "language", "scope", "pid", "sdk_pid", "launch_id",
                 "policy_sha256", "phase", "sdk_attached", "lifecycle", "metric_flush", "span_accounting",
                 "trace_exports", "metric_exports", "downstream_receipt", "otlp_partial_rejection",
                 "source_complete", "application_exit", "sdk_exit", "failures", "application", "sdk"}
LIVE_SDK_FIELDS = health.SDK_FIELDS - {"sdk_phase", "shutdown_completed", "handoff_incomplete",
                                      "producer_checkpoint_available", "producer"}


def status(value: object, pid: int, command: str) -> dict:
    """Flush replies contain runtime facts; setters/status also expose a barrier."""
    names = BASE_FIELDS if command == "flush" else BASE_FIELDS | BARRIER_FIELDS
    value = health.fields(value, names, "live control")
    require(type(value["schema_version"]) is int and value["schema_version"] == 1
            and type(value["pid"]) is int and value["pid"] == pid and pid > 1
            and type(value["sdk_pid"]) is int and value["sdk_pid"] > 1 and value["sdk_pid"] != pid,
            "live control process identity differs")
    require(all(type(value[key]) is bool for key in ("collection", "emission"))
            and value["runtime_losses"] == {} and type(value["runtime_losses"]) is dict
            and health.count(value["active_functions"], "live active functions") == 0,
            "live control flags, losses or paused calls differ")
    health.count(value["function_completions"], "live completions")
    if command != "flush":
        pending = health.count(value["in_flight_exports"], "live pending exports")
        require(type(value["effective_emission_off"]) is bool
                and value["effective_emission_off"] == (not value["emission"] and pending == 0),
                "live export barrier differs")
    return value


def pipeline(value: object, pid: int, sdk_pid: int, launch_id: str, digest: str) -> dict:
    """Keep running queue counts unavailable and inspect actual API outcomes."""
    value = health.fields(value, LIVE_SDK_FIELDS, "live SDK")
    require(same({key: value[key] for key in ("schema_version", "kind", "pid", "sdk_pid", "launch_id", "policy_sha256")},
                 {"schema_version": 1, "kind": "otelc.python.sdk", "pid": pid, "sdk_pid": sdk_pid,
                  "launch_id": launch_id, "policy_sha256": digest}) and value["phase"] == "running",
            "live SDK identity or phase differs")
    require(all(type(value[key]) is bool for key in ("collection", "emission", "effective_emission_off", "operation_pending"))
            and all(value[key] is False for key in ("closed", "shutdown_complete", "shutdown_failed")),
            "live SDK controls or shutdown differ")
    names = {"export_started", "export_succeeded", "export_failed", "in_flight_exports", "flush_started",
             "flush_failed", "in_flight_flushes", "handoff_received", "protocol_errors", "operation_failures", "reply_lost"}
    totals = health.counts(value, names, "live SDK")
    require(totals["export_started"] == totals["export_succeeded"] + totals["in_flight_exports"]
            and all(totals[key] == 0 for key in ("export_failed", "flush_failed", "protocol_errors", "operation_failures", "reply_lost"))
            and value["effective_emission_off"] == (not value["emission"] and totals["in_flight_exports"] == 0),
            "live SDK exports, controls or handoff failed")
    trace = health.fields(value["traces"], health.TRACE_FIELDS, "live traces")
    counts = health.counts(trace, health.TRACE_FIELDS - {"closed"}, "live traces")
    require(trace["closed"] is False and counts["failed"] == counts["failed_items"] == 0
            and counts["started"] == counts["succeeded"] + counts["pending"]
            and counts["started_items"] == counts["exported_items"] + counts["pending_items"],
            "live trace export failed or disagrees")
    collection = health.fields(value["metric_collection"], health.COLLECTION_FIELDS, "live collection")
    counts = health.counts(collection, {"started", "succeeded", "failed", "pending"}, "live collection")
    require(all(collection[key] is False for key in ("closed", "shutdown_complete", "shutdown_failed"))
            and counts["failed"] == 0 and counts["started"] == counts["succeeded"] + counts["pending"],
            "live metric collection failed or disagrees")
    queue = health.fields(value["span_accounting"], health.QUEUE_FIELDS, "live queue")
    health.counts(queue, {"received", "sdk_exported"}, "live queue")
    require(queue["queue_pending"] is queue["queue_dropped"] is None
            and queue["queue_evidence"] == queue["downstream_receipt"] == queue["otlp_partial_rejection"] == "unavailable"
            and queue["sdk_exported"] == trace["exported_items"] <= queue["received"],
            "live queue availability or accounting differs")
    return value


def live(value: object, pid: int) -> dict:
    """Reconstruct the common health view from its separately present raw SDK."""
    value = health.fields(value, HEALTH_FIELDS, "live report")
    sdk_pid, launch, digest = value["sdk_pid"], value["launch_id"], value["policy_sha256"]
    require(type(sdk_pid) is int and sdk_pid > 1 and sdk_pid != pid
            and type(launch) is str and re.fullmatch("[a-f0-9]{32}", launch)
            and type(digest) is str and re.fullmatch("[a-f0-9]{64}", digest), "invalid live SDK binding")
    app = health.fields(value["application"], BASE_FIELDS | {"lifetime_events_pending"}, "live application")
    require(app["lifetime_events_pending"] is None, "live generated lifetimes must be disabled")
    status({key: app[key] for key in BASE_FIELDS}, pid, "flush")
    require(app["sdk_pid"] == sdk_pid, "live application SDK changed")
    sdk = pipeline(value["sdk"], pid, sdk_pid, launch, digest)
    require(all(app[key] is sdk[key] for key in ("collection", "emission")), "live application and SDK flags disagree")
    completed = app["function_completions"]
    require(sdk["span_accounting"]["received"] == completed, "live selected spans were not handed to the SDK")
    expected = {"schema_version": 2, "kind": "otelc.runtime-health", "language": "python",
                "scope": "application_sdk_pair", "pid": pid, "sdk_pid": sdk_pid, "launch_id": launch,
                "policy_sha256": digest, "phase": "running", "sdk_attached": True,
                "lifecycle": {"flush": "unavailable", "shutdown": "unavailable"},
                "metric_flush": {"scope": "exporter", "attempts": str(sdk["flush_started"]),
                                 "failed_attempts": str(sdk["flush_failed"])},
                "span_accounting": {"processors_observed": 1, "batch_processors_observed": 1,
                    "sampled_started": str(completed), "sampled_ended": str(completed), "sampled_active": "0",
                    "queue_pending": None, "queue_dropped": None, "queue_evidence": "unavailable"},
                "trace_exports": health.exporter(sdk, traces=True), "metric_exports": health.exporter(sdk, traces=False),
                "downstream_receipt": "unavailable", "otlp_partial_rejection": "unavailable", "source_complete": False,
                "application_exit": None, "sdk_exit": None, "failures": {}, "application": app, "sdk": sdk}
    require(same(value, expected), "live public health differs from independently checked SDK facts")
    return value


def request(path: Path, command: str, pid: int, deadline: float) -> dict:
    """Read the common transport and apply Python's exact command-specific view."""
    require(command in COMMANDS, "unsupported live Python control command")
    value = live_control.exchange(path, command, pid, deadline, maximum=262144 if command == "health" else 4096)
    return live(value, pid) if command == "health" else status(value, pid, command)
