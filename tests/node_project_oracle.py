"""Independent fixed-fixture values, module receipts and raw Node OTLP checks."""
import bisect
import hashlib
import json
import math
from pathlib import Path
import struct

LOSSES = {"function_capacity", "active_call_capacity", "incomplete", "invalid", "async_origin"}
CONTEXT_FIELDS = {"schema_version", "format", "loader_hint", "source_sha256", "package", "node_version"}


def require(condition: bool, message: str) -> None:
    if not condition:
        raise ValueError("Node qualification: " + message)


def digest(path: Path) -> str:
    with path.open("rb") as handle:
        return hashlib.file_digest(handle, "sha256").hexdigest()


def number(language: str, value: float) -> dict:
    return {"kind": "float", "type": language + ".float64", "bits": struct.pack(">d", value).hex()}


def text(language: str, value: str) -> dict:
    return {"kind": "string", "type": language + ".string", "encoding": "utf16_be", "value": value.encode("utf-16-be").hex()}


def reference(node_id: str) -> dict:
    return {"kind": "reference", "node_id": node_id}


def object_node(language: str, node_id: str, type_name: str, properties: dict, *, array: bool = False) -> dict:
    fields = {"meta:extensible": {"kind": "boolean", "value": True}}
    for index, (name, value) in enumerate(properties.items()):
        key = "property:" + name
        fields["order:" + str(index)] = text(language, name)
        fields[key] = value
        for flag in ("writable", "enumerable", "configurable"):
            fields[flag + ":" + key] = {"kind": "boolean", "value": not (array and name == "length" and flag != "writable")}
    return {"id": node_id, "type": type_name, "fields": fields}


def expected_graph(spec: dict, argument: float, state: float, result: float | None = None) -> dict:
    language = spec["language"]
    nodes = [object_node(language, "n0", "ecmascript.array.prototype:Array",
                         {"0": number(language, argument), "length": number(language, 1.0)}, array=True)]
    roots = {"arguments": reference("n0")}
    if spec.get("receiver"):
        roots["receiver"] = reference("n1")
        nodes.append(object_node(language, "n1", "ecmascript.object.prototype:declared:sample.Counter",
                                 {"value": number(language, state), "alias": reference("n1")}))
    else:
        roots["global:state"] = number(language, state)
    if result is not None:
        roots["result"] = number(language, result)
    return {"roots": roots, "nodes": nodes}


def check_observation(value: dict, spec: dict, lane: str, argument: float) -> None:
    initial = 10.0 if spec.get("receiver") else 2.0
    final = initial + argument + int(spec.get("different", False) and lane == "instrumented_on")
    result = 7.0 if spec.get("different") else final if spec.get("receiver") else final + argument
    require(value["gaps"] == [], "missing captured dimensions")
    require(value["before"] == expected_graph(spec, argument, initial), "complete initial graph differs")
    require(value["after"] == expected_graph(spec, argument, final), "complete final graph differs")
    require(value["outcome"] == {"kind": "return", "graph": expected_graph(spec, argument, final, result)}, "complete outcome graph differs")


def check_context(folder: Path, spec: dict, entry: dict) -> None:
    value = json.loads((folder / "node-context.json").read_text())
    require(set(value) == {"original", "caller"}, "context receipt fields differ")
    for label in ("original", "caller"):
        receipt = value[label]
        require(set(receipt) == CONTEXT_FIELDS and type(receipt["schema_version"]) is int and receipt["schema_version"] == 1,
                "closed context schema differs")
        require(receipt["format"] == spec["format"] and receipt["package"] == spec["package"], "module/package receipt differs")
        require(receipt["node_version"] == spec["node_version"], "Node version differs")
    require(value["original"] == entry["node_context"] == entry["node_original_context"], "original/private source binding differs")
    require(value["original"]["source_sha256"] == spec["source_sha256"], "original source digest differs")
    require(value["caller"]["source_sha256"] == digest(folder / "project" / spec["filename"]), "caller source digest differs")
    probe = json.loads((folder / "node-context-probe/stdout").read_bytes())
    require(probe == value["caller"], "actual loader stdout differs from retained receipt")


def check_health(value: dict, spec: dict) -> int:
    require(set(value) == {"schema_version", "language", "pid", "export_finished", "function_calls", "functions", "losses", "export_loss", "traces"}, "health schema differs")
    require(value["schema_version"] == 1 and value["language"] == spec["language"], "health identity differs")
    require(type(value["pid"]) is int and value["pid"] > 0, "missing application PID")
    require(value["export_finished"] is True and value["function_calls"] == 1 and value["export_loss"] == 0, "runtime export/call counters differ")
    require(value["functions"] == {spec["function"]: {"count": 1, "unwinds": 0}}, "selected runtime function differs")
    require(value["losses"] == dict.fromkeys(LOSSES, 0), "runtime losses differ")
    require(value["traces"] == {"completed_trees": 1, "sampled_out_roots": 0, "active_trees": 0, "queued_trees": 0, "losses": {}}, "trace completion differs")
    return value["pid"]


def attributes(values) -> dict:
    result = {}
    for item in values:
        require(item.key not in result, "duplicate OTLP attribute")
        kind = item.value.WhichOneof("value")
        require(kind in ("string_value", "int_value", "bool_value", "double_value"), "unsupported OTLP attribute kind")
        result[item.key] = getattr(item.value, kind)
    return result


def resource_scope(resource, scope) -> dict:
    require(resource.dropped_attributes_count == scope.dropped_attributes_count == 0, "dropped resource/scope attributes")
    return {"resource": attributes(resource.attributes), "scope": [scope.name, scope.version]}


def trace_records(request) -> list[dict]:
    result = []
    for resource in request.resource_spans:
        for scope in resource.scope_spans:
            identity = resource_scope(resource.resource, scope.scope)
            for span in scope.spans:
                result.append({**identity, "name": span.name, "attributes": attributes(span.attributes),
                    "trace_id": span.trace_id.hex(), "span_id": span.span_id.hex(), "parent": span.parent_span_id.hex(),
                    "start": span.start_time_unix_nano, "end": span.end_time_unix_nano, "status": span.status.code,
                    "drops": span.dropped_attributes_count + span.dropped_events_count + span.dropped_links_count,
                    "events": len(span.events), "links": len(span.links)})
    return result


def metric_point(point, kind: str) -> dict:
    value = {"attributes": attributes(point.attributes), "start": point.start_time_unix_nano,
             "end": point.time_unix_nano, "flags": point.flags, "exemplars": len(point.exemplars)}
    if kind == "sum":
        value.update(value_type=point.WhichOneof("value"), value=point.as_int)
    else:
        value.update(count=point.count, sum=point.sum, minimum=point.min, maximum=point.max,
                     has_min=point.HasField("min"), has_max=point.HasField("max"),
                     bounds=list(point.explicit_bounds), buckets=list(point.bucket_counts))
    return value


def metric_records(request) -> list[dict]:
    result = []
    for resource in request.resource_metrics:
        for scope in resource.scope_metrics:
            identity = resource_scope(resource.resource, scope.scope)
            for metric in scope.metrics:
                kind = metric.WhichOneof("data")
                require(kind in ("sum", "histogram"), "unexpected metric data kind")
                data = getattr(metric, kind)
                result.append({**identity, "name": metric.name, "kind": kind,
                    "temporality": data.aggregation_temporality, "monotonic": data.is_monotonic if kind == "sum" else None,
                    "points": [metric_point(point, kind) for point in data.data_points]})
    return result


def decode(folder: Path, capture: dict) -> dict:
    # The unit verifier does not require the provider's protobuf dependency.
    from opentelemetry.proto.collector.metrics.v1.metrics_service_pb2 import ExportMetricsServiceRequest
    from opentelemetry.proto.collector.trace.v1.trace_service_pb2 import ExportTraceServiceRequest
    result = {"spans": [], "metrics": []}
    decoders = {"/v1/traces": (ExportTraceServiceRequest, "spans", trace_records),
                "/v1/metrics": (ExportMetricsServiceRequest, "metrics", metric_records)}
    for body in capture["bodies"]:
        require(body["path"] in decoders and Path(body["file"]).name == body["file"], "unknown/escaping OTLP body")
        factory, field, extract = decoders[body["path"]]
        result[field].extend(extract(factory.FromString((folder / body["file"]).read_bytes())))
    return result


def check_identity(record: dict, pid: int) -> str:
    require(record["scope"] == ["quux.otelc", "0.1.0"], "instrumentation scope differs")
    resource = record["resource"]
    require(resource.get("service.instance.id") == str(pid), "raw OTLP application PID differs")
    service = resource.get("service.name", "")
    suffix = service.removeprefix("oteleq-gen-")
    require(service.startswith("oteleq-gen-") and len(suffix) == 32 and all(c in "0123456789abcdef" for c in suffix), "raw OTLP service differs")
    return service


def check_span(span: dict, function: str) -> None:
    require(span["name"] == function and span["attributes"] == {"code.function.name": function}, "raw selected span differs")
    for key, length in (("trace_id", 32), ("span_id", 16)):
        value = span[key]
        require(len(value) == length and all(c in "0123456789abcdef" for c in value) and int(value, 16) != 0, "invalid span identity")
    require(span["parent"] == "" and span["status"] in (0, 1), "root/return status differs")
    require(span["start"] > 0 and span["end"] >= span["start"], "span timestamps differ")
    require(span["drops"] == span["events"] == span["links"] == 0, "unexpected span payload/loss")


def check_histogram(point: dict) -> None:
    require(point["count"] == 1 and point["has_min"] and point["has_max"], "histogram count/extrema missing")
    value = point["sum"]
    require(math.isfinite(value) and value >= 0 and point["minimum"] == point["maximum"] == value, "histogram values differ")
    bounds, buckets = point["bounds"], point["buckets"]
    require(all(math.isfinite(v) for v in bounds) and all(a < b for a, b in zip(bounds, bounds[1:])), "histogram bounds differ")
    require(len(buckets) == len(bounds) + 1 and all(type(v) is int and v >= 0 for v in buckets) and sum(buckets) == 1, "histogram buckets differ")
    require(buckets[bisect.bisect_left(bounds, value)] == 1, "histogram placement differs")


def check_metric(metric: dict, function: str) -> None:
    require(metric["temporality"] == 2 and metric["points"], "metric aggregation differs")
    require(metric["kind"] == ("histogram" if metric["name"] == "otelc.function.duration" else "sum"), "metric kind differs")
    if metric["kind"] == "sum":
        require(metric["monotonic"] is True, "counter is not monotonic")
    for point in metric["points"]:
        require(point["start"] > 0 and point["end"] >= point["start"] and point["flags"] == point["exemplars"] == 0, "metric time/flags differ")
        check_point_value(point, metric["name"], function)


def check_point_value(point: dict, name: str, function: str) -> None:
    if name in ("otelc.function.calls", "otelc.function.duration", "otelc.function.unwinds"):
        require(point["attributes"] == {"code.function.name": function}, "metric selected function differs")
    if name == "otelc.function.duration":
        check_histogram(point)
        return
    require(point["value_type"] == "as_int" and point["value"] == int(name == "otelc.function.calls"), "counter value differs")
    if name == "otelc.runtime.dropped_observations":
        require(set(point["attributes"]) == {"reason"} and point["attributes"]["reason"] in LOSSES, "loss dimension differs")
    if name == "otelc.export.dropped_batches":
        require(point["attributes"] == {}, "export loss attributes differ")


def check_telemetry(value: dict, function: str, pid: int) -> None:
    require(len(value["spans"]) == 1, "exactly one raw root span required")
    check_span(value["spans"][0], function)
    records = value["spans"] + value["metrics"]
    require(len({check_identity(record, pid) for record in records}) == 1, "raw OTLP services differ")
    names = {m["name"] for m in value["metrics"]}
    required = {"otelc.function.calls", "otelc.function.duration", "otelc.runtime.dropped_observations", "otelc.export.dropped_batches"}
    require(required <= names <= required | {"otelc.function.unwinds"}, "required/unknown raw metrics")
    for metric in value["metrics"]:
        check_metric(metric, function)
    reasons = {point["attributes"]["reason"] for metric in value["metrics"] if metric["name"] == "otelc.runtime.dropped_observations" for point in metric["points"]}
    require(reasons == LOSSES, "raw loss coverage differs")


def check_attempt(folder: Path, attempt: dict, spec: dict, entry: dict, lane: str, argument: float) -> str:
    check_observation(attempt["observation"], spec, lane, argument)
    execution = attempt["execution"]
    require(execution["capture_complete"] is True and execution["termination"] == {"kind": "exit", "code": 0}, "application execution incomplete")
    require(bytes(execution["channels"]["stdout"]) == (spec["format"] + "\n").encode() and execution["channels"]["stderr"] == [], "literal application channels differ")
    require((folder / "stdout").read_bytes() == (spec["format"] + "\n").encode() and (folder / "stderr").read_bytes() == b"", "retained application channels differ")
    check_context(folder, spec, entry)
    capture = json.loads((folder / "http-capture.json").read_text())
    require(capture["errors"] == [], "raw receiver errors")
    if lane == "baseline":
        require(capture["bodies"] == [] and execution["witness"] is None, "baseline emitted telemetry")
    else:
        pid = check_health(json.loads((folder / "runtime.json").read_text()), spec)
        check_telemetry(decode(folder, capture), spec["function"], pid)
        require(execution["witness"]["functions"] == {spec["function"]: 1}, "production witness differs from raw evidence")
    command = json.loads((folder / "command.json").read_text())
    cwd = json.loads((folder / "working-directory.json").read_text())
    return hashlib.sha256(json.dumps([command, cwd], sort_keys=True).encode()).hexdigest()


def check_report(path: Path, spec: dict, workspace: Path, argument: float = 7.0) -> set[str]:
    report = json.loads(path.read_text())
    require(report["source_preserved"] is True and not report["blocked"] and len(report["cases"]) == 1, "inventory/source coverage differs")
    expected = int(spec.get("different", False))
    require(report["exit_code"] == expected and report["cases"][0]["exit_code"] == expected, "comparison verdict differs")
    case = report["cases"][0]
    require(case["function"] == spec["function"] and case["arguments"] == [argument], "case inputs/identity differ")
    plan = json.loads((workspace / "plan.json").read_text())
    entries = [e for e in plan["inventory"] if e["status"] == "ready"]
    require(len(entries) == 1, "selected callable inventory differs")
    entry = entries[0]
    bundle = json.loads((path.parent / case["case"] / "typed-bundle.json").read_text())["cases"][0]
    identities = set()
    for lane in ("baseline", "instrumented_on"):
        require(len(bundle[lane]) == 2, "independent repeats missing")
        for index, attempt in enumerate(bundle[lane]):
            identities.add(check_attempt(path.parent / case["case"] / (lane + "-" + str(index)), attempt, spec, entry, lane, argument))
    require(len(identities) == 4, "application command identities reused")
    return identities
