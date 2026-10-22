"""Independent literal single-call SDK observations for Node project qualification."""

import json
from pathlib import Path
import tomllib

import node_project_oracle as common

BOUNDS = [1e-6, 1e-5, 1e-4, .001, .01, .1, 1.]
FUNCTION_SCOPE = ["io.quux.otelc.functions", "0.2.0"]
LOSS_NAMES = {"function_capacity", "active_call_capacity", "invalid", "async_origin", "incomplete"}


def check_health(value: dict, spec: dict, pid: int) -> None:
    """One known call must finish, with actual SDK drain and no recorded losses."""
    common.require(type(value["schema_version"]) is int and value["schema_version"] == 1
                   and type(value["pid"]) is int and value["pid"] == pid
                   and value["language"] == spec["language"], "source SDK identity differs")
    common.require(value["phase"] == value["sdk_phase"] == "closed"
                   and value["collection"] is True and value["emission"] is True
                   and value["effective_emission_off"] is False
                   and value["producer_checkpoint_available"] is True, "source SDK is not closed and enabled")
    expected = {"function_completions": 1, "active_functions": 0, "in_flight_exports": 0,
                "export_failed": 0, "native_callback_failures": 0, "lifetime_lost": 0, "handoff_incomplete": 0}
    common.require(all(type(value[key]) is int and value[key] == count for key, count in expected.items())
                   and type(value["export_started"]) is int
                   and type(value["export_succeeded"]) is int
                   and value["export_started"] == value["export_succeeded"] > 0, "source SDK completion/loss differs")
    common.require(set(value["runtime_losses"]) == LOSS_NAMES
                   and all(type(count) is int and count == 0 for count in value["runtime_losses"].values()),
                   "source runtime losses differ")
    common.require(json.dumps(value["span_observation"], sort_keys=True) == json.dumps(
                   {"sampled_started": 1, "sampled_ended": 1, "sampled_active": 0, "handed_off": 1}, sort_keys=True),
                   "source SDK observed call count differs")
    common.require(json.dumps(value["span_accounting"], sort_keys=True) == json.dumps(
                   {"received": 1, "sdk_exported": 1, "queue_pending": 0, "queue_dropped": 0,
                    "queue_evidence": "derived_after_shutdown", "downstream_receipt": "unavailable", "otlp_partial_rejection": "unavailable"}, sort_keys=True),
                   "source SDK final queue differs")
    for field in ("traces", "metric_collection"):
        counts = value[field]
        common.require(type(counts["started"]) is int and counts["started"] > 0
                       and all(type(counts[key]) is int and counts[key] == 0 for key in ("failed", "pending")),
                       "source exporter/reader incomplete")
    common.require(type(value["traces"]["succeeded"]) is int
                   and value["traces"]["started"] == value["traces"]["succeeded"]
                   and type(value["traces"]["exported_items"]) is int
                   and value["traces"]["exported_items"] == 1, "source trace export count differs")
    handoff = value["handoff"]
    common.require(all(type(handoff[key]) is int for key in ("attempted", "accepted", "lost", "deadline_ms"))
                   and handoff["attempted"] == handoff["accepted"] > 0 and handoff["lost"] == 0
                   and handoff["deadline_ms"] == 50 and handoff["sdk_process_failed"] is False,
                   "source handoff differs")


def resource_identity(resource: dict, spec: dict, launch: str, service: str) -> None:
    """Bind actual decoded resource values, without treating launch IDs as PIDs."""
    common.require(resource.get("service.name") == service
                   and resource.get("service.instance.id") == launch
                   and resource.get("otelc.language") == spec["language"], "source OTLP resource/scope differs")


def identity(record: dict, spec: dict, launch: str, service: str) -> None:
    """Check the function scope separately from the resource identity."""
    common.require(record["scope"] == FUNCTION_SCOPE, "source OTLP function scope differs")
    resource_identity(record["resource"], spec, launch, service)


def check_telemetry(value: dict, spec: dict, launch: str, service: str) -> None:
    """Compare decoded single-call trace and cumulative measurements to fixed facts."""
    common.require(len(value["spans"]) == 1, "source fixture needs exactly one selected span")
    span = value["spans"][0]
    identity(span, spec, launch, service)
    common.require(span["attributes"] == {"code.function.name": spec["function"], "otelc.language": spec["language"]},
                   "source function attributes differ")
    common.check_span({**span, "attributes": {"code.function.name": spec["function"]}}, spec["function"])
    totals = {}
    for metric in value["metrics"]:
        identity(metric, spec, launch, service)
        common.require(metric["name"] in {"otelc.function.calls", "otelc.function.duration", "otelc.function.unwinds"}
                       and metric["temporality"] == 2 and metric["points"], "source metric schema differs")
        histogram = metric["name"] == "otelc.function.duration"
        common.require(metric["kind"] == ("histogram" if histogram else "sum")
                       and (histogram or metric["monotonic"] is True), "source metric data kind differs")
        for point in metric["points"]:
            common.require(point["attributes"] == {"function": spec["function"], "language": spec["language"]}
                           and 0 < point["start"] <= point["end"] and point["flags"] == point["exemplars"] == 0,
                           "source metric point labels/time differ")
            if histogram:
                common.require(point["bounds"] == BOUNDS, "source duration bounds differ")
                common.check_histogram(point)
                count = point["count"]
            else:
                count = point["value"]
                common.require(point["value_type"] == "as_int" and type(count) is int
                               and count == int(metric["name"] == "otelc.function.calls"), "source counter differs")
            totals[metric["name"]] = max(totals.get(metric["name"], 0), count)
    common.require(totals.get("otelc.function.calls") == totals.get("otelc.function.duration") == 1
                   and totals.get("otelc.function.unwinds", 0) == 0, "source function metric totals differ")


def decode(folder: Path, capture: dict, spec: dict, launch: str, service: str) -> dict:
    """Decode retained bodies; SDK queue samples remain separate from final drain."""
    from opentelemetry.proto.collector.metrics.v1.metrics_service_pb2 import ExportMetricsServiceRequest
    from opentelemetry.proto.collector.trace.v1.trace_service_pb2 import ExportTraceServiceRequest
    result = {"spans": [], "metrics": []}
    for body in capture["bodies"]:
        common.require(Path(body["file"]).name == body["file"], "escaping source OTLP body")
        raw = (folder / body["file"]).read_bytes()
        if body["path"] == "/v1/traces":
            result["spans"].extend(common.trace_records(ExportTraceServiceRequest.FromString(raw)))
            continue
        common.require(body["path"] == "/v1/metrics", "unknown source OTLP route")
        request = ExportMetricsServiceRequest.FromString(raw)
        for resource in request.resource_metrics:
            for scope in resource.scope_metrics:
                record = common.resource_scope(resource.resource, scope.scope)
                if record["scope"] != FUNCTION_SCOPE:
                    resource_identity(record["resource"], spec, launch, service)
                    common.require(record["scope"] == ["@opentelemetry/sdk-trace", ""]
                                   and all(metric.name in {"otel.sdk.processor.span.queue.capacity", "otel.sdk.processor.span.queue.size"}
                                           for metric in scope.metrics), "unknown source SDK metric scope/name")
                    continue
                for metric in scope.metrics:
                    kind = metric.WhichOneof("data")
                    common.require(kind in ("sum", "histogram"), "unknown source metric data")
                    data = getattr(metric, kind)
                    result["metrics"].append({**record, "name": metric.name, "kind": kind,
                        "temporality": data.aggregation_temporality,
                        "monotonic": data.is_monotonic if kind == "sum" else None,
                        "points": [common.metric_point(point, kind) for point in data.data_points]})
    return result


def check_attempt(folder: Path, spec: dict, capture: dict) -> None:
    """Use actual app receipts, direct SDK status and independent raw decoding."""
    actual = json.loads((folder / "node-source-application.json").read_text())
    report = json.loads((folder / "node-runtime/node-status.json").read_text())
    completion = json.loads((folder / "node-source-completion.json").read_text())
    manifest = json.loads((folder / "node-runtime/node-launch.json").read_text())
    common.require(report["sdk_pid"] == completion["sdk_pid"] and report["launch_id"] == manifest["launch_id"],
                   "source SDK process/launch binding differs")
    check_health(report, spec, actual["pid"])
    # The common policy is TOML; its service identity is an original consumer input.
    policy = tomllib.loads((folder / "policy.toml").read_text())
    service = policy["resource"]["service_name"]
    check_telemetry(decode(folder, capture, spec, report["launch_id"], service), spec, report["launch_id"], service)
