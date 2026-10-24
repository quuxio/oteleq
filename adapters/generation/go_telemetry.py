"""Join decoded Go OTLP to owned execution and independent final health."""

from collections import Counter
import hashlib
import json
import math
from pathlib import Path

import go_health
import go_control_receipt
from go_provider import policy_digest, require
import otelc_capture as capture

SCOPE = "io.quux.otelc.go"
CALLS = "otelc.function.calls"
ERRORS = "otelc.function.errors"
DURATION = "otelc.function.duration"
LIVE = "otelc.lifetime.live"
ERROR_TYPES = {"panic", "goexit", "returned_error"}
MAX_SPANS = 16384
MAX_POINTS = 65536
WITNESS_FIELDS = ("decoder", "raw_otlp_sha256", "functions", "spans", "losses", "pending")


def attributes(rows) -> dict:
    """Unset, duplicate and non-string attributes cannot hide another identity."""
    result = {}
    for row in rows:
        require(row.key not in result and row.value.WhichOneof("value") == "string_value",
                "invalid Go OTLP attributes")
        result[row.key] = row.value.string_value
    return result


def resource(group, service: str, version: str) -> None:
    """Go resources expose service/SDK identity; they do not expose a launch PID."""
    require(not group.schema_url and group.resource.dropped_attributes_count == 0
            and attributes(group.resource.attributes) == {
                "service.name": service, "telemetry.sdk.language": "go",
                "telemetry.sdk.name": "opentelemetry", "telemetry.sdk.version": version},
            "Go OTLP resource differs from the owned service or compiled SDK")


def scope(value) -> None:
    require(value.scope.name == SCOPE and not value.scope.version and not value.schema_url
            and not value.scope.attributes and value.scope.dropped_attributes_count == 0,
            "unexpected Go instrumentation scope")


def decode(decoder, body: bytes):
    """Malformed wire input is a retained qualification failure."""
    from google.protobuf.message import DecodeError
    try:
        return decoder.FromString(body)
    except DecodeError as error:
        raise ValueError("Go prepared provider: invalid OTLP protobuf") from error


def scoped_spans(group):
    require(bool(group.scope_spans), "empty Go trace resource")
    for instrumentation in group.scope_spans:
        scope(instrumentation)
        require(bool(instrumentation.spans), "empty Go trace scope")
        yield from instrumentation.spans


def trace_spans(bodies: list, run, service: str, decoder):
    for route, body in bodies:
        if route != capture.TRACE_PATH:
            continue
        message = decode(decoder, body)
        require(bool(message.resource_spans), "empty Go trace request")
        for group in message.resource_spans:
            resource(group, service, run.sdk_version)
            yield from scoped_spans(group)


def span_record(span, selected: set[str], nodes: dict) -> tuple:
    key = capture.span_identity(span)
    values = attributes(span.attributes)
    expected = {"function": span.name}
    error_type = None
    if span.status.code == 2:
        error_type = values.get("error.type")
        require(error_type in ERROR_TYPES, "unknown Go unwind boundary")
        expected["error.type"] = error_type
    require(key not in nodes and len(nodes) < MAX_SPANS and span.name in selected and span.kind == 1
            and span.status.code in (0, 2) and not span.status.message
            and values == expected and not span.events and not span.links
            and span.dropped_attributes_count == span.dropped_events_count == span.dropped_links_count == 0,
            "invalid, dropped, excessive or unbound Go function span")
    return key, error_type


def traces(bodies: list, run, service: str, decoder, *, calls: int = 1) -> tuple[dict, list, dict]:
    """Require complete selected call trees, including every declared factory root."""
    selected = {target.name for target in run.caller.targets}
    names, roots, nodes, spans = Counter(), Counter(), {}, []
    errors = Counter()
    for span in trace_spans(bodies, run, service, decoder):
        key, error_type = span_record(span, selected, nodes)
        if error_type is not None:
            errors[span.name, error_type] += 1
        nodes[key] = (span.trace_id, span.parent_span_id) if span.parent_span_id else None
        names[span.name] += 1
        if not span.parent_span_id:
            roots[span.name] += 1
        spans.append(span)
    target_name = run.caller.targets[0].name
    require(type(calls) is int and 1 <= calls <= 32
            and set(names) == selected and roots == Counter({name: calls if name == target_name else 1 for name in selected}),
            "Go invocation roots differ from the generated target/factory calls")
    capture.trace_roots(nodes)
    root_spans = [span for span in spans if not span.parent_span_id]
    targets = sorted((span for span in root_spans if span.name == target_name), key=lambda span: span.start_time_unix_nano)
    require(all(span.end_time_unix_nano <= targets[0].start_time_unix_nano
                for span in root_spans if span.name != target_name),
            "Go source factory did not complete before the selected call")
    require(all(first.end_time_unix_nano <= second.start_time_unix_nano for first, second in zip(targets, targets[1:])),
            "Go selected root calls are not serial")
    by_id = {capture.span_identity(span): span for span in spans}
    for key, parent in nodes.items():
        if parent is not None:
            child, owner = by_id[key], by_id[parent]
            require(owner.start_time_unix_nano <= child.start_time_unix_nano
                    <= child.end_time_unix_nano <= owner.end_time_unix_nano,
                    "Go child span lies outside its selected parent")
    return dict(names), spans, dict(errors)


def point(metric, value, names: set[str], bounds: list) -> tuple:
    """Check exact labels, kinds, monotonic counters and histogram accounting."""
    labels = attributes(value.attributes)
    function = labels.get("function")
    require(function in names and value.flags == 0
            and 0 < value.start_time_unix_nano <= value.time_unix_nano,
            "invalid Go function metric identity or timestamps")
    expected = {"function": function}
    error_type = ""
    if metric.name == ERRORS:
        error_type = labels.get("error.type")
        require(error_type in ERROR_TYPES, "unknown Go metric unwind boundary")
        expected["error.type"] = error_type
    require(labels == expected, "unexpected Go function metric labels")
    if metric.name == DURATION:
        require(list(value.explicit_bounds) == bounds and len(value.bucket_counts) == len(bounds) + 1
                and sum(value.bucket_counts) == value.count and value.HasField("sum")
                and math.isfinite(value.sum) and value.sum >= 0,
                "invalid Go duration histogram")
        count = value.count
    else:
        require(metric.sum.is_monotonic and value.WhichOneof("value") == "as_int" and value.as_int >= 0,
                "invalid Go cumulative counter")
        count = value.as_int
    return (metric.name, function, error_type), (value.start_time_unix_nano, value.time_unix_nano, count)


def live_gauge(metric) -> int:
    """Disabled lifetime hooks still export two explicit zero SDK gauges."""
    require(metric.WhichOneof("data") == "gauge" and metric.unit == "", "invalid Go lifetime gauge")
    boundaries = set()
    for value in metric.gauge.data_points:
        labels = attributes(value.attributes)
        boundary = labels.get("boundary")
        require(boundary in {"observed_gc", "resource"} and boundary not in boundaries
                and labels == {"type": "all", "boundary": boundary}
                and value.WhichOneof("value") == "as_int" and value.as_int == 0 and value.flags == 0
                and 0 < value.start_time_unix_nano <= value.time_unix_nano,
                "unrequested or incomplete Go lifetime observation")
        boundaries.add(boundary)
    require(boundaries == {"observed_gc", "resource"}, "missing Go lifetime gauge dimension")
    return len(boundaries)


def scoped_metrics(group):
    require(bool(group.scope_metrics), "empty Go metric resource")
    for instrumentation in group.scope_metrics:
        scope(instrumentation)
        require(bool(instrumentation.metrics), "empty Go metric scope")
        yield from instrumentation.metrics


def metric_values(bodies: list, run, service: str):
    from opentelemetry.proto.collector.metrics.v1.metrics_service_pb2 import ExportMetricsServiceRequest
    for route, body in bodies:
        if route != "/v1/metrics":
            continue
        message = decode(ExportMetricsServiceRequest, body)
        require(bool(message.resource_metrics), "empty Go metric request")
        for group in message.resource_metrics:
            resource(group, service, run.sdk_version)
            yield from scoped_metrics(group)


def cumulative_totals(series: dict) -> dict:
    totals = {}
    for key, samples in series.items():
        samples.sort()
        require(len({sample[0] for sample in samples}) == 1
                and len({sample[1] for sample in samples}) == len(samples)
                and all(before[2] <= after[2] for before, after in zip(samples, samples[1:])),
                "reset, duplicated or decreasing Go cumulative samples")
        totals[key] = samples[-1][2]
    return totals


def metric_series(bodies: list, run, service: str, names: set[str]) -> tuple[dict, dict, int]:
    """Retain each receiver position as well as complete cumulative sample histories."""
    series, windows, points = {}, {}, 0
    kinds = {CALLS: ("sum", "{call}"), ERRORS: ("sum", "{error}"), DURATION: ("histogram", "s")}
    bounds = run.prepared.intent.policy["metrics"]["histogram_boundaries_seconds"]
    for index, (route, body) in enumerate(bodies):
        if route != "/v1/metrics":
            continue
        windows[index] = {}
        for metric in metric_values([(route, body)], run, service):
            if metric.name == LIVE:
                points += live_gauge(metric)
                require(points <= MAX_POINTS, "Go metric point budget exceeded")
                continue
            require(metric.name in kinds and (metric.WhichOneof("data"), metric.unit) == kinds[metric.name],
                    "unknown Go metric or value kind")
            data = getattr(metric, kinds[metric.name][0])
            require(data.aggregation_temporality == 2 and bool(data.data_points), "non-cumulative or empty Go metric")
            for value in data.data_points:
                key, sample = point(metric, value, names, bounds)
                series.setdefault(key, []).append(sample)
                windows[index][key] = max(windows[index].get(key, 0), sample[2])
                points += 1
                require(points <= MAX_POINTS, "Go metric point budget exceeded")
    return series, windows, points


def metric_totals(totals: dict, names: dict, errors: dict) -> None:
    """Require positive measurements and permit absent genuinely suppressed series."""
    for name, count in names.items():
        default = 0 if count == 0 else None
        require(totals.get((CALLS, name, ""), default) == totals.get((DURATION, name, ""), default) == count,
                "Go function metrics differ from decoded spans")
        for error_type in ERROR_TYPES:
            require(totals.get((ERRORS, name, error_type), 0) == errors.get((name, error_type), 0),
                    "Go error metric differs from decoded unwind spans")


def metrics(bodies: list, run, service: str, names: dict, errors: dict) -> int:
    """Compare every cumulative sample with independently decoded function spans."""
    series, _, points = metric_series(bodies, run, service, set(names))
    metric_totals(cumulative_totals(series), names, errors)
    return points


def witness(run, bodies: list, service: str, decoder, *, folder: Path | None = None, calls: int = 1,
            sequence: list[dict] | None = None) -> dict | None:
    """Keep actual owned SDK health separate from local downstream receipt."""
    run.verify()
    controls = None
    if sequence is not None:
        require(folder is not None, "Go live witness requires its retained control record")
        controls = go_control_receipt.read(folder, run, sequence, bodies)
    if run.prepared.intent.plain:
        require(not bodies and run.session.execution.health is None, "plain Go worker emitted SDK evidence")
        return None
    require(all(route in (capture.TRACE_PATH, "/v1/metrics") and type(body) is bytes and bool(body)
                for route, body in bodies), "unknown Go telemetry route or empty body")
    names, spans, errors = traces(bodies, run, service, decoder, calls=calls)
    if controls is None:
        points = metrics(bodies, run, service, names, errors)
    else:
        series, windows, points = metric_series(bodies, run, service, set(names))
        collected, collected_errors = go_control_receipt.qualify(controls, run, bodies, spans, windows)
        metric_totals(cumulative_totals(series), collected, collected_errors)
    received = {"trace_batches": sum(route == capture.TRACE_PATH for route, _ in bodies),
                "metric_batches": sum(route == "/v1/metrics" for route, _ in bodies),
                "spans": len(spans), "metric_points": points}
    intent = run.prepared.intent
    health = go_health.qualify(run.session.execution.health, pid=run.session.started.owner.application_pid,
                               policy_sha256=policy_digest(intent.policy), selection_sha256=intent.build.receipt["selection"]["sha256"],
                               received=received, function_spans=len(spans), observer_completions=0, received_http_spans=0)
    require(not any(health["probe_accounting"][name] for name in (
        "object_admitted", "gc_observed", "resource_released", "objects_pending", "resources_unreleased", "duplicate_objects")),
        "unrequested Go lifetime observations in the call-only profile")
    raw = hashlib.sha256()
    for route, body in bodies:
        raw.update(len(route).to_bytes(8, "big") + route.encode() + len(body).to_bytes(8, "big") + body)
    receipt = {"decoder": "opentelemetry-proto Go traces/metrics with independent owned health4",
            "raw_otlp_sha256": raw.hexdigest(), "functions": names, "spans": len(spans),
            "losses": {name: health["probe_accounting"][name] for name in (
                "function_lost", "observer_lost", "unwind_unknown", "lifetime_lost")},
            "pending": health["probe_accounting"]["function_active"] + health["probe_accounting"]["observer_active"],
            "sdk_pid": health["sdk_pid"], "received": received, "health": health}
    if controls is not None:
        receipt["controls"] = {"record_sha256": controls["record_sha256"], "steps": len(controls["steps"]),
                                "metric_functions": dict(collected), "interval_ms": controls["interval_ms"]}
    if folder is not None:
        (folder / "go-verified-telemetry.json").write_text(json.dumps(receipt, indent=2, allow_nan=False) + "\n")
    return {name: receipt[name] for name in WITNESS_FIELDS}
