"""Independent selected-method OTLP receipt and final prepared-Java health."""
from collections import Counter
import hashlib
import json
import math
from pathlib import Path

import java_health
import java_launch
import java_control_receipt
import java_live
import java_provider as provider
import otelc_capture as capture
import sequences

CALLS = "otelc.function.calls"
DURATION = "otelc.function.duration"
METHOD_SCOPE = ("io.opentelemetry.methods", "2.32.0-alpha")
BUCKETS = [1e-6, 1e-5, 1e-4, .001, .01, .1, 1.]


def attributes(rows) -> dict:
    """Require unique typed attributes rather than overwrite duplicate identities."""
    result = {}
    for row in rows:
        kind = row.value.WhichOneof("value")
        provider.require(row.key not in result and kind is not None, "duplicate or missing OTLP attribute")
        result[row.key] = (kind, getattr(row.value, kind))
    return result


def resource(value, service: str) -> None:
    """Receipt belongs to this actual attempt, not another process or service."""
    values = attributes(value.attributes)
    provider.require(values.get("service.name") == ("string_value", service)
                     and values.get("otelc.language") == ("string_value", "java"), "OTLP resource identity differs")


def decode(decoder, body):
    """Translate errors only at the external protobuf decoder boundary."""
    try:
        return decoder(body)
    except Exception as error:
        raise ValueError("Java prepared provider: invalid OTLP protobuf receipt") from error


def trace(message, service: str, owner: str, method: str, nodes: dict, intervals: dict) -> tuple[int, int]:
    """Check each selected method, ID, parent and unambiguous source owner."""
    spans, errors = 0, 0
    for group in message.resource_spans:
        resource(group.resource, service)
        for scope in group.scope_spans:
            count, failed = method_scope(scope, owner, method, nodes, intervals)
            spans += count
            errors += failed
    return spans, errors


def method_scope(scope, owner: str, method: str, nodes: dict, intervals: dict) -> tuple[int, int]:
    """Validate ordinary method spans separately from explicit action-role spans."""
    provider.require((scope.scope.name, scope.scope.version) == METHOD_SCOPE, "unexpected method instrumentation scope")
    errors = 0
    for span in scope.spans:
        key = capture.span_identity(span)
        values = attributes(span.attributes)
        provider.require(key not in nodes and span.kind == 1
                         and values.get("code.namespace") == ("string_value", owner)
                         and values.get("code.function") == ("string_value", method)
                         and span.name == owner.rsplit(".", 1)[-1] + "." + method,
                         "unbound, duplicate or unexpected selected method span")
        provider.require(span.status.code in (0, 2), "unexpected selected span status")
        provider.require(span.dropped_attributes_count == span.dropped_events_count == span.dropped_links_count == 0,
                         "selected span contains dropped observations")
        nodes[key] = (span.trace_id, span.parent_span_id) if span.parent_span_id else None
        intervals[key] = (span.start_time_unix_nano, span.end_time_unix_nano)
        errors += int(span.status.code == 2)
    return len(scope.spans), errors


def metric_point(point, method: str) -> None:
    """A required series needs its real function label, complete value and times."""
    provider.require(attributes(point.attributes) == {"function": ("string_value", method)}
                     and point.flags == 0 and 0 < point.start_time_unix_nano <= point.time_unix_nano,
                     "incomplete or unbound function metric point")


def metric_value(metric, data, point) -> int:
    """Require complete counter or histogram values from the fixed SDK policy."""
    if metric.name == CALLS:
        provider.require(data.is_monotonic and point.WhichOneof("value") == "as_int" and point.as_int >= 0,
                         "function calls lack an integer monotonic value")
        return point.as_int
    provider.require(list(point.explicit_bounds) == BUCKETS
                     and len(point.bucket_counts) == len(BUCKETS) + 1
                     and sum(point.bucket_counts) == point.count
                     and point.HasField("sum") and math.isfinite(point.sum) and point.sum >= 0,
                     "function histogram is incomplete or differs from policy")
    return point.count


def metrics(message, service: str, method: str, recorded: dict) -> int:
    """Count every actual exported point, retaining cumulative function evidence."""
    count = 0
    for group in message.resource_metrics:
        resource(group.resource, service)
        for scope in group.scope_metrics:
            count += scope_metrics(scope, method, recorded)
    return count


def scope_metrics(scope, method: str, recorded: dict) -> int:
    """Validate each scope's required series and count all its exported points."""
    count = 0
    for metric in scope.metrics:
        kind = metric.WhichOneof("data")
        provider.require(kind is not None, "missing metric data")
        data = getattr(metric, kind)
        count += len(data.data_points)
        if metric.name not in (CALLS, DURATION):
            continue
        provider.require((scope.scope.name, scope.scope.version) == METHOD_SCOPE
                         and metric.unit == ("{call}" if metric.name == CALLS else "s"),
                         "unbound function metric scope or unit")
        expected = "sum" if metric.name == CALLS else "histogram"
        provider.require(kind == expected and data.aggregation_temporality == 2,
                         "function metric is not a cumulative counter/histogram")
        for point in data.data_points:
            metric_point(point, method)
            recorded[metric.name].append((point.time_unix_nano, metric_value(metric, data, point)))
    return count


def receipt(bodies: list, service: str, entry: dict, trace_decoder, metric_decoder, *, controls: dict | None = None) -> dict:
    """Require the declared call roots and complete matching cumulative metrics."""
    owner, method = entry["otelc_function"].split("(", 1)[0].rsplit(".", 1)
    nodes, intervals, by_body, batches = {}, {}, {}, Counter()
    recorded = {CALLS: [], DURATION: []}
    spans, errors, points = 0, 0, 0
    for index, (path, body) in enumerate(bodies):
        provider.require(path in (capture.TRACE_PATH, "/v1/metrics"), "unexpected OTLP route")
        batches[path] += 1
        if path == capture.TRACE_PATH:
            calls, failed = trace(decode(trace_decoder, body), service, owner, method, nodes, intervals)
            spans += calls;errors += failed
        else:
            current = {CALLS: [], DURATION: []}
            points += metrics(decode(metric_decoder, body), service, method, current)
            by_body[index] = current
            for name, values in current.items():
                recorded[name].extend(values)
    provider.require(spans > 0 and capture.trace_roots(nodes) == sequences.call_count(entry),
                     "missing complete selected invocation tree(s) for declared calls")
    expected = spans
    if sequences.controls(entry):
        provider.require(controls is not None, "missing required live metric-control receipt")
        sizes = java_control_receipt.trees(nodes, intervals)
        expected = java_control_receipt.qualify(controls, controls["pid"], bodies, sizes, by_body)
    for name, values in recorded.items():
        ordered = [value for _, value in sorted(values)]
        provider.require(ordered and all(0 <= value <= expected for value in ordered)
                         and ordered == sorted(ordered) and ordered[-1] == expected,
                         "missing, reset or mismatched direct function metric: " + name)
    return {"trace_batches": batches[capture.TRACE_PATH], "spans": spans,
            "metric_batches": batches["/v1/metrics"], "metric_points": points, "errors": errors}


def witness(runtime: Path, folder: Path, entry: dict, bodies: list, service: str, trace_decoder) -> dict:
    """Qualify real health directly without fabricating the legacy runtime report."""
    from opentelemetry.proto.collector.metrics.v1.metrics_service_pb2 import ExportMetricsServiceRequest
    launch = capture.strict_json((folder / java_launch.LAUNCH_FILE).read_bytes())
    process = capture.strict_json((folder / "process.json").read_bytes())
    provider.require(type(process) is dict and set(process) == {"pid", "argv"} and process["argv"] == launch["argv"],
                     "missing actual JVM process identity")
    controls = java_control_receipt.read(folder, entry, process["pid"], bodies, plain=False) if sequences.controls(entry) else None
    received = receipt(bodies, service, entry, trace_decoder.FromString, ExportMetricsServiceRequest.FromString, controls=controls)
    if controls is not None:
        (folder / "verified-controls.json").write_text(json.dumps({"control_record_sha256": controls["record_sha256"],
                  "pid": process["pid"], "selected_spans": received["spans"],
                  "collected_spans": controls["restored"]["flush"]["completed"], "source": java_live.RECORD}, indent=2) + "\n")
    health = java_health.read(runtime)
    verified = java_health.qualify(health, pid=process["pid"], policy_sha256=launch["policy_sha256"],
                                   selection_sha256=launch["selection_sha256"],
                                   **{name: value for name, value in received.items() if name != "errors"})
    (folder / "verified-health.json").write_text(json.dumps(verified, indent=2) + "\n")
    raw = hashlib.sha256()
    for _, body in bodies:
        raw.update(body)
    decoder = "opentelemetry-proto traces/metrics and Java SDK health1" + ("; bounded live metric controls1" if controls is not None else "")
    return {"decoder": decoder, "raw_otlp_sha256": raw.hexdigest(),
            "functions": {entry["otelc_function"]: received["spans"]}, "spans": received["spans"],
            "losses": {"sdk.queue_dropped": int(health["span_accounting"]["queue_dropped"]),
                       "sdk.trace_export_failed": int(health["trace_exports"]["units_failed"]),
                       "sdk.metric_export_failed": int(health["metric_exports"]["units_failed"])},
            "pending": int(health["span_accounting"]["queue_pending"]) + int(health["span_accounting"]["sampled_active"])
                       + int(health["trace_exports"]["batches_pending"]) + int(health["metric_exports"]["batches_pending"])}
