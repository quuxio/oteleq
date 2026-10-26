"""Alter copied actual receipts and require the frozen product witness to refuse."""
import copy
import json
from pathlib import Path
import shutil
import sys
import tomllib

ROOT = Path(__file__).resolve().parent
sys.path[:0] = [str(ROOT / "source/adapters/generation"), str(ROOT / "source/examples")]
import java_telemetry
from opentelemetry.proto.collector.trace.v1.trace_service_pb2 import ExportTraceServiceRequest
from opentelemetry.proto.collector.metrics.v1.metrics_service_pb2 import ExportMetricsServiceRequest

report = json.loads((ROOT / "qualification/corpus/comparison/report.json").read_text())
case = next(row for row in report["cases"] if row["function"] == "Counter.identity(int)")
entry = next(row for row in report["inventory"] if row["otelc_function"] == case["function"])
original = ROOT / "qualification/corpus/comparison" / case["case"] / "instrumented_on-0"
http = json.loads((original / "http-capture.json").read_text())
bodies = [(row["path"], (original / row["file"]).read_bytes()) for row in http["bodies"]]
service = tomllib.loads((original / "policy.toml").read_text())["resource"]["service_name"]
controls = json.loads((original / "java-controls.json").read_text())
destination = ROOT / "negative-controls"
destination.mkdir(mode=0o700)


def witness(folder, receipt):
    return java_telemetry.witness(folder / "sdk-runtime", folder, entry, receipt, service, ExportTraceServiceRequest)


positive = destination / "positive"
shutil.copytree(original, positive)
witness(positive, bodies)
edits = [
    ("wrong-pid", lambda row: row.update(pid=row["pid"] + 1), "control record identity"),
    ("collection-off-recorded", lambda row: row["steps"][1]["after"]["status"].update(completed=2), "per-call recording"),
    ("short-off-window", lambda row: row["steps"][2]["after"].update(held_ns=0), "shorter than"),
    ("unpaused-call", lambda row: row["steps"][0]["before"]["history"][0]["status"].update(completed=1), "during a control transition"),
    ("restoration-count", lambda row: row["restored"]["flush"].update(completed=3), "final restored controls"),
    ("coerced-counter", lambda row: row["steps"][0]["after"]["status"].update(completed=True), "invalid control counters"),
]
results = []
for name, change, message in edits:
    folder = destination / name
    shutil.copytree(original, folder)
    value = copy.deepcopy(controls)
    change(value)
    (folder / "java-controls.json").write_text(json.dumps(value))
    try:
        witness(folder, bodies)
    except ValueError as error:
        assert message in str(error), str(error)
        results.append({"control": name, "refused": True, "reason": str(error)})
    else:
        raise AssertionError(name + " qualified altered evidence")

folder = destination / "missing-retained-measurement"
shutil.copytree(original, folder)
changed = list(bodies)
start = controls["steps"][-1]["after"]["cursor"]
for index in range(start, len(changed)):
    route, raw = changed[index]
    if route != "/v1/metrics":
        continue
    request = ExportMetricsServiceRequest.FromString(raw)
    for resource in request.resource_metrics:
        for scope in resource.scope_metrics:
            for metric in scope.metrics:
                if metric.name == "otelc.function.calls":
                    for point in metric.sum.data_points:
                        point.as_int = 1
                if metric.name == "otelc.function.duration":
                    for point in metric.histogram.data_points:
                        point.count = 1
                        for bucket in range(len(point.bucket_counts)):
                            point.bucket_counts[bucket] = int(bucket == 0)
    changed[index] = route, request.SerializeToString()
try:
    witness(folder, changed)
except ValueError as error:
    assert "retained emission-off measurements" in str(error), str(error)
    results.append({"control": "missing-retained-measurement", "refused": True, "reason": str(error)})
else:
    raise AssertionError("missing retained measurements qualified")
(destination / "results.json").write_text(json.dumps({"positive_actual_receipt": True, "negative_controls": results}, indent=2) + "\n")
print(json.dumps({"positive_actual_receipt": True, "refused_controls": len(results)}))
