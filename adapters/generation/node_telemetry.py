"""Decoded source-profile function/lifetime telemetry and actual final SDK health."""

from collections import Counter
import hashlib
import math
from pathlib import Path

import node_source as provider
import otelc_capture as capture
import sequences

FUNCTION_SCOPE = ("io.quux.otelc.functions", "0.2.0")
LIFETIME_SCOPE = ("io.quux.otelc.lifetimes", "0.2.0")
BOUNDS = [1e-6, 1e-5, 1e-4, .001, .01, .1, 1.]
RUNTIME_LOSSES = {"function_capacity", "active_call_capacity", "invalid", "async_origin", "incomplete"}
DURATION = "otelc.function.duration"
LIFETIME_SUFFIX = " lifetime"


def attributes(rows) -> dict:
    """Keep duplicate and unset resource/point attributes visible as errors."""
    result = {}
    for row in rows:
        kind = row.value.WhichOneof("value")
        provider.require(row.key not in result and kind is not None, "duplicate or missing OTLP attribute")
        result[row.key] = (kind, getattr(row.value, kind))
    return result


def resource(value, entry: dict, service: str, launch: str) -> None:
    """Bind decoded receipt to this selected service, language and launch."""
    values = attributes(value.attributes)
    provider.require(values.get("service.name") == ("string_value", service)
                     and values.get("service.instance.id") == ("string_value", launch)
                     and values.get("otelc.language") == ("string_value", entry["language"]),
                     "OTLP resource belongs to another attempt")


def counters(value: dict, names: set[str], label: str) -> dict:
    """Unavailable, boolean and negative values cannot become zero counters."""
    provider.require(type(value) is dict and names <= set(value)
                     and all(type(value[name]) is int and value[name] >= 0 for name in names),
                     "missing or invalid " + label + " counters")
    return {name: value[name] for name in names}


def health(report: dict, entry: dict) -> tuple[dict, int]:
    """Only the actual closed source1 report can establish final drain/loss state."""
    provider.require(type(report) is dict and type(report.get("schema_version")) is int
                     and report["schema_version"] == 1 and report.get("language") == entry["language"]
                     and report.get("phase") == report.get("sdk_phase") == "closed"
                     and report.get("collection") is True and report.get("emission") is True
                     and report.get("effective_emission_off") is False
                     and report.get("producer_checkpoint_available") is True,
                     "source SDK final report is missing or unfinished")
    losses = counters(report.get("runtime_losses"), RUNTIME_LOSSES, "runtime")
    provider.require(set(report["runtime_losses"]) == RUNTIME_LOSSES, "unknown runtime loss dimension")
    top = counters(report, {"function_completions", "active_functions", "native_callback_failures", "lifetime_lost",
                           "handoff_incomplete", "in_flight_exports", "export_started", "export_succeeded", "export_failed"}, "source")
    handoff = counters(report.get("handoff"), {"attempted", "accepted", "lost", "deadline_ms"}, "handoff")
    provider.require(report["handoff"].get("sdk_process_failed") is False
                     and handoff["attempted"] == handoff["accepted"] and handoff["deadline_ms"] == 50,
                     "incomplete source-to-SDK handoff")
    traces = counters(report.get("traces"), {"started", "succeeded", "failed", "pending", "exported_items"}, "trace exporter")
    metrics = counters(report.get("metric_collection"), {"started", "failed", "pending"}, "metric collection")
    observed = counters(report.get("span_observation"), {"sampled_started", "sampled_ended", "sampled_active", "handed_off"}, "span observation")
    queue = counters(report.get("span_accounting"), {"received", "sdk_exported", "queue_pending", "queue_dropped"}, "SDK span queue")
    provider.require(report["span_accounting"].get("queue_evidence") == "derived_after_shutdown"
                     and report["span_accounting"].get("downstream_receipt") == "unavailable"
                     and report["span_accounting"].get("otlp_partial_rejection") == "unavailable",
                     "unknown final queue evidence or unsupported downstream claim")
    provider.require(top["export_started"] == top["export_succeeded"] > 0
                     and traces["started"] == traces["succeeded"] > 0 and metrics["started"] > 0
                     and observed["sampled_started"] == observed["sampled_ended"] == observed["handed_off"]
                     and queue["received"] == queue["sdk_exported"] == traces["exported_items"] == observed["handed_off"],
                     "final exporter and observed span accounting differ")
    losses.update({"native.callback": top["native_callback_failures"], "lifetime.lost": top["lifetime_lost"],
                   "handoff.lost": handoff["lost"], "handoff.incomplete": top["handoff_incomplete"],
                   "export.metrics": top["export_failed"], "export.traces": traces["failed"],
                   "collection.failed": metrics["failed"], "queue.dropped": queue["queue_dropped"]})
    pending = top["active_functions"] + top["in_flight_exports"] + traces["pending"] + metrics["pending"] + observed["sampled_active"] + queue["queue_pending"]
    provider.require(not any(losses.values()) and pending == 0, "lossy or pending source SDK observations")
    return losses, pending


def span_record(span, identity: tuple, entry: dict, allowed: set[str], nodes: dict) -> tuple:
    """Validate one span before adding it to the independent trace graph."""
    key = capture.span_identity(span)
    values = attributes(span.attributes)
    provider.require(key not in nodes and span.kind == 1 and span.status.code in (0, 2)
                     and span.dropped_attributes_count == span.dropped_events_count == span.dropped_links_count == 0,
                     "invalid or dropped source span")
    if identity == FUNCTION_SCOPE:
        provider.require(span.name in allowed and values.get("code.function.name") == ("string_value", span.name)
                         and values.get("otelc.language") == ("string_value", entry["language"]),
                         "unbound source function span")
    else:
        provider.require(span.name == entry["node_class_label"] + LIFETIME_SUFFIX
                         and values.get("type") == ("string_value", entry["node_class_label"])
                         and values.get("boundary") == ("string_value", "observed_gc"),
                         "unrequested lifetime boundary")
    return key


def trace_group(group, entry: dict, service: str, launch: str, allowed: set[str],
                nodes: dict, spans: list) -> None:
    """Bind a resource and each declared scope before accepting its spans."""
    resource(group.resource, entry, service, launch)
    permitted = {FUNCTION_SCOPE, LIFETIME_SCOPE} if sequences.collects(entry) else {FUNCTION_SCOPE}
    for scope in group.scope_spans:
        identity = (scope.scope.name, scope.scope.version)
        provider.require(identity in permitted, "unexpected source trace scope")
        for span in scope.spans:
            key = span_record(span, identity, entry, allowed, nodes)
            nodes[key] = (span.trace_id, span.parent_span_id) if span.parent_span_id else None
            spans.append(span)


def collection_receipt(spans: list, report: dict, entry: dict, creator: str | None) -> None:
    """A collected receiver needs its actual lifetime and optional creation link."""
    lifetime = [span for span in spans if span.name == entry["node_class_label"] + LIFETIME_SUFFIX]
    provider.require(len(lifetime) == 1, "collection did not yield one complete lifetime")
    state = counters(report.get("lifetimes"), {"admitted", "gc_completed", "resource_completed", "current_live", "censored"}, "lifetime")
    provider.require(state == {"admitted": 1, "gc_completed": 1, "resource_completed": 0, "current_live": 0, "censored": 0},
                     "source collection is missing or incomplete")
    if creator:
        parent = next(span for span in spans if span.name == creator)
        provider.require(len(lifetime[0].links) == 1 and lifetime[0].links[0].trace_id == parent.trace_id
                         and lifetime[0].links[0].span_id == parent.span_id, "collection lost its creation link")


def trace_counts(names: Counter, spans: list, report: dict, entry: dict, allowed: set[str]) -> None:
    """Compare declared selected roots and every decoded completion with SDK totals."""
    target_roots = sum(not span.parent_span_id and span.name == entry["otelc_function"] for span in spans)
    extra = {entry["node_class_label"] + LIFETIME_SUFFIX} if sequences.collects(entry) else set()
    provider.require(target_roots == sequences.call_count(entry) and set(names) == allowed | extra,
                     "selected source calls were not independently witnessed")
    provider.require(sum(names.values()) == report["span_accounting"]["received"], "decoded span count differs from final SDK receipt")
    function_count = sum(count for name, count in names.items() if name in allowed)
    provider.require(function_count == report["function_completions"], "source completion count differs from decoded functions")
    creator = sequences.creator(entry)
    if creator:
        provider.require(names[creator] == 1, "source creation factory was not called once")
    if sequences.collects(entry):
        collection_receipt(spans, report, entry, creator)


def decode_traces(bodies, entry: dict, service: str, report: dict, decoder) -> tuple[dict, list, dict]:
    """Validate actual graph identities and selected original function attributes."""
    nodes, spans = {}, []
    allowed = {entry["otelc_function"]}
    creator = sequences.creator(entry)
    if creator:
        allowed.add(creator)
    for route, body in bodies:
        if route != capture.TRACE_PATH:
            continue
        try:
            message = decoder.FromString(body)
        except Exception as error:
            raise ValueError("Node source provider: invalid trace protobuf") from error
        for group in message.resource_spans:
            trace_group(group, entry, service, report["launch_id"], allowed, nodes, spans)
    roots = capture.trace_roots(nodes)
    names = Counter(span.name for span in spans)
    trace_counts(names, spans, report, entry, allowed)
    return dict(names), spans, {"roots": roots, "allowed": allowed}


def metric_point(metric, point, entry: dict, allowed: set[str]) -> tuple[str, int]:
    """Validate source labels, timestamps and the selected metric's exact value kind."""
    values = attributes(point.attributes)
    name = values.get("function", (None, None))[1]
    provider.require(name in allowed and values == {"function": ("string_value", name), "language": ("string_value", entry["language"])}
                     and point.flags == 0 and 0 < point.start_time_unix_nano <= point.time_unix_nano,
                     "incomplete or unbound source metric point")
    if metric.name == DURATION:
        provider.require(list(point.explicit_bounds) == BOUNDS and len(point.bucket_counts) == len(BOUNDS) + 1
                         and sum(point.bucket_counts) == point.count and math.isfinite(point.sum) and point.sum >= 0,
                         "invalid source duration histogram")
        return name, point.count
    provider.require(metric.sum.is_monotonic and point.WhichOneof("value") == "as_int" and point.as_int >= 0,
                     "source counter lacks a monotonic integer value")
    return name, point.as_int


def auxiliary_metric_scope(scope, entry: dict) -> None:
    """SDK queue samples and requested lifetimes are separate from function totals."""
    identity = (scope.scope.name, scope.scope.version)
    permitted = {("@opentelemetry/sdk-trace", "")} | ({LIFETIME_SCOPE} if sequences.collects(entry) else set())
    provider.require(identity in permitted, "unknown or unrequested source metric scope")
    names = ({"otelc.lifetime.admitted", "otelc.lifetime.completed", "otelc.lifetime.incomplete", "otelc.lifetime.lost",
              "otelc.lifetime.duration", "otelc.lifetime.live"} if identity == LIFETIME_SCOPE
             else {"otel.sdk.processor.span.queue.capacity", "otel.sdk.processor.span.queue.size"})
    provider.require(all(metric.name in names for metric in scope.metrics), "unknown SDK or lifetime metric")


def function_metric_scope(scope, entry: dict, allowed: set[str], observed: dict) -> None:
    """Retain every cumulative sample; arrival order need not be timestamp order."""
    for metric in scope.metrics:
        provider.require(metric.name in {"otelc.function.calls", "otelc.function.unwinds", DURATION},
                         "unexpected source function metric")
        histogram = metric.name == DURATION
        provider.require(metric.WhichOneof("data") == ("histogram" if histogram else "sum"), "source metric kind differs")
        data = metric.histogram if histogram else metric.sum
        provider.require(data.aggregation_temporality == 2, "source metrics must be cumulative")
        for point in data.data_points:
            name, count = metric_point(metric, point, entry, allowed)
            key = (metric.name, name)
            sample = (point.start_time_unix_nano, point.time_unix_nano, count,
                      tuple(point.bucket_counts) if histogram else (), point.sum if histogram else 0)
            observed.setdefault(key, []).append(sample)


def cumulative_step(previous: tuple, sample: tuple) -> None:
    """One later measurement cannot reset an established cumulative stream."""
    provider.require(sample[0] == previous[0], "cumulative metric start time changed")
    if sample[1] == previous[1]:
        provider.require(sample == previous, "conflicting cumulative snapshots share a timestamp")
        return
    provider.require(sample[2] >= previous[2] and sample[4] >= previous[4]
                     and all(current >= old for current, old in zip(sample[3], previous[3])),
                     "cumulative metric count, bucket or sum regressed")


def cumulative_counts(observed: dict) -> dict:
    """Reject resets and conflicting snapshots before using final cumulative totals."""
    result = {}
    for key, samples in observed.items():
        ordered = sorted(samples, key=lambda sample: sample[1])
        previous = ordered[0]
        for sample in ordered[1:]:
            cumulative_step(previous, sample)
            previous = sample
        result[key] = previous[2]
    return result


def metric_group(group, entry: dict, service: str, launch: str, allowed: set[str], observed: dict) -> None:
    """Validate resource identity and route each scope to its own measurement contract."""
    resource(group.resource, entry, service, launch)
    for scope in group.scope_metrics:
        if (scope.scope.name, scope.scope.version) == FUNCTION_SCOPE:
            function_metric_scope(scope, entry, allowed, observed)
        else:
            auxiliary_metric_scope(scope, entry)


def function_metrics(bodies, entry: dict, service: str, report: dict, spans: list, allowed: set[str]) -> None:
    """Cumulative call/unwind/histogram samples must reach the decoded call totals."""
    from opentelemetry.proto.collector.metrics.v1.metrics_service_pb2 import ExportMetricsServiceRequest
    totals, unwinds = Counter(), Counter()
    for span in spans:
        if span.name in allowed:
            totals[span.name] += 1
            unwinds[span.name] += int(span.status.code == 2)
    observed = {}
    for route, body in bodies:
        if route != "/v1/metrics":
            continue
        try:
            message = ExportMetricsServiceRequest.FromString(body)
        except Exception as error:
            raise ValueError("Node source provider: invalid metric protobuf") from error
        for group in message.resource_metrics:
            metric_group(group, entry, service, report["launch_id"], allowed, observed)
    counts = cumulative_counts(observed)
    for name, count in totals.items():
        provider.require(counts.get(("otelc.function.calls", name)) == count
                         and counts.get((DURATION, name)) == count
                         and counts.get(("otelc.function.unwinds", name), 0) == unwinds[name],
                         "decoded source function metrics differ from actual traced calls")


def witness(folder: Path, entry: dict, bodies: list, service: str, decoder) -> dict:
    """Use direct source health and local OTLP receipt without a legacy report shim."""
    report = capture.strict_json((folder / "node-runtime/node-status.json").read_bytes())
    losses, pending = health(report, entry)
    names, spans, graph = decode_traces(bodies, entry, service, report, decoder)
    function_metrics(bodies, entry, service, report, spans, graph["allowed"])
    raw = hashlib.sha256()
    for route, body in bodies:
        if route == capture.TRACE_PATH:
            raw.update(body)
    return {"decoder": "opentelemetry-proto ExportTraceServiceRequest + ExportMetricsServiceRequest",
            "raw_otlp_sha256": raw.hexdigest(), "functions": names, "spans": len(spans), "losses": losses, "pending": pending}
