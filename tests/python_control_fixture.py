"""Literal live Python protocol fixtures independent of the consumer readers."""


def status(*, collection=True, emission=True, completed=1, barrier=True):
    value = {"schema_version": 1, "pid": 101, "sdk_pid": 102, "collection": collection,
             "emission": emission, "function_completions": completed, "active_functions": 0,
             "runtime_losses": {}}
    if barrier:
        value.update(effective_emission_off=not emission, in_flight_exports=0)
    return value


def report(*, collection=True, emission=True, completed=1, exports=1):
    sdk = {"schema_version": 1, "kind": "otelc.python.sdk", "pid": 101, "sdk_pid": 102,
           "launch_id": "a" * 32, "policy_sha256": "b" * 64, "phase": "running",
           "collection": collection, "emission": emission, "effective_emission_off": not emission,
           "closed": False, "shutdown_complete": False, "shutdown_failed": False,
           "export_started": exports, "export_succeeded": exports, "export_failed": 0, "in_flight_exports": 0,
           "flush_started": 1, "flush_failed": 0, "in_flight_flushes": 0,
           "metric_collection": {"started": 1, "succeeded": 1, "failed": 0, "pending": 0,
                                 "closed": False, "shutdown_complete": False, "shutdown_failed": False},
           "traces": {"closed": False, "started": int(completed > 0), "succeeded": int(completed > 0),
                      "failed": 0, "pending": 0, "started_items": completed, "exported_items": completed,
                      "failed_items": 0, "pending_items": 0},
           "span_accounting": {"received": completed, "sdk_exported": completed, "queue_pending": None,
                               "queue_dropped": None, "queue_evidence": "unavailable",
                               "downstream_receipt": "unavailable", "otlp_partial_rejection": "unavailable"},
           "handoff_received": 8, "protocol_errors": 0, "operation_failures": 0,
           "operation_pending": False, "reply_lost": 0}
    app = status(collection=collection, emission=emission, completed=completed, barrier=False)
    app["lifetime_events_pending"] = None
    return {"schema_version": 2, "kind": "otelc.runtime-health", "language": "python",
            "scope": "application_sdk_pair", "pid": 101, "sdk_pid": 102, "launch_id": "a" * 32,
            "policy_sha256": "b" * 64, "phase": "running", "sdk_attached": True,
            "lifecycle": {"flush": "unavailable", "shutdown": "unavailable"},
            "metric_flush": {"scope": "exporter", "attempts": "1", "failed_attempts": "0"},
            "span_accounting": {"processors_observed": 1, "batch_processors_observed": 1,
                                "sampled_started": str(completed), "sampled_ended": str(completed),
                                "sampled_active": "0", "queue_pending": None, "queue_dropped": None,
                                "queue_evidence": "unavailable"},
            "trace_exports": {"exporters_observed": 1, "unit": "spans", "batches_started": str(int(completed > 0)),
                              "batches_succeeded": str(int(completed > 0)), "batches_failed": "0", "batches_pending": "0",
                              "units_started": str(completed), "units_succeeded": str(completed), "units_failed": "0"},
            "metric_exports": {"exporters_observed": 1, "unit": "metric_points", "batches_started": str(exports),
                               "batches_succeeded": str(exports), "batches_failed": "0", "batches_pending": "0",
                               "units_started": None, "units_succeeded": None, "units_failed": None},
            "downstream_receipt": "unavailable", "otlp_partial_rejection": "unavailable", "source_complete": False,
            "application_exit": None, "sdk_exit": None, "failures": {}, "application": app, "sdk": sdk}
