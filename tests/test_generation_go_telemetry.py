"""Independent literal Go protobuf, causal-tree and final-health falsifiers."""

import json
from pathlib import Path
import sys
import tempfile
from types import SimpleNamespace
import unittest
from unittest.mock import Mock, patch

REPO = Path(__file__).resolve().parents[1]
sys.path[:0] = [str(REPO / "adapters/generation"), str(REPO / "examples")]
from opentelemetry.proto.collector.metrics.v1.metrics_service_pb2 import ExportMetricsServiceRequest
from opentelemetry.proto.collector.trace.v1.trace_service_pb2 import ExportTraceServiceRequest
import go_build
import go_source
import go_telemetry as telemetry
from go_provider import policy_digest
from test_generation_go_health import report as health_report

FUNCTION = "example.test/app.Add"
FACTORY = "example.test/app.New"
SERVICE = "independent-go-case"
VERSION = "1.47.0"
PID = 2468
SELECTION = "b" * 64


def labels(target, values):
    for name, value in values.items():
        item = target.add(key=name)
        item.value.string_value = value


def resource(target):
    labels(target.attributes, {"service.name": SERVICE, "telemetry.sdk.language": "go",
                               "telemetry.sdk.name": "opentelemetry", "telemetry.sdk.version": VERSION})


def fixture(*, recursive=False, factory=False, failed=False):
    entry = {"language": "go", "go_backend": "source-v1", "path": "api.go", "name": "Add",
             "go_context": {"module_root": ".", "import_path": "example.test/app"}}
    policy = go_source.configuration(entry, "http://127.0.0.1:1", SERVICE)
    traces, metrics = ExportTraceServiceRequest(), ExportMetricsServiceRequest()
    trace_group = traces.resource_spans.add()
    resource(trace_group.resource)
    trace_scope = trace_group.scope_spans.add()
    trace_scope.scope.name = telemetry.SCOPE
    root = trace_scope.spans.add(name=FUNCTION, trace_id=b"t" * 16, span_id=b"r" * 8,
                                  start_time_unix_nano=100, end_time_unix_nano=200, kind=1)
    labels(root.attributes, {"function": FUNCTION})
    if failed:
        root.status.code = 2
        labels(root.attributes, {"error.type": "panic"})
    names = {FUNCTION: 1}
    targets = [go_build.Target(FUNCTION, "api.go", 1, 1)]
    if recursive:
        child = trace_scope.spans.add(name=FUNCTION, trace_id=b"t" * 16, span_id=b"c" * 8,
                                      parent_span_id=b"r" * 8, start_time_unix_nano=120,
                                      end_time_unix_nano=150, kind=1)
        labels(child.attributes, {"function": FUNCTION})
        names[FUNCTION] += 1
    if factory:
        made = trace_scope.spans.add(name=FACTORY, trace_id=b"f" * 16, span_id=b"n" * 8,
                                     start_time_unix_nano=10, end_time_unix_nano=50, kind=1)
        labels(made.attributes, {"function": FACTORY})
        names[FACTORY] = 1
        targets.append(go_build.Target(FACTORY, "factory.go", 1, 1))
    metric_group = metrics.resource_metrics.add()
    resource(metric_group.resource)
    metric_scope = metric_group.scope_metrics.add()
    metric_scope.scope.name = telemetry.SCOPE
    calls = metric_scope.metrics.add(name=telemetry.CALLS, unit="{call}")
    calls.sum.aggregation_temporality = 2
    calls.sum.is_monotonic = True
    duration = metric_scope.metrics.add(name=telemetry.DURATION, unit="s")
    duration.histogram.aggregation_temporality = 2
    for name, count in names.items():
        point = calls.sum.data_points.add(start_time_unix_nano=1, time_unix_nano=1000, as_int=count)
        labels(point.attributes, {"function": name})
        point = duration.histogram.data_points.add(start_time_unix_nano=1, time_unix_nano=1000,
                                                    count=count, sum=.005 * count)
        point.explicit_bounds.extend(policy["metrics"]["histogram_boundaries_seconds"])
        point.bucket_counts.extend([0, 0, 0, 0, count, 0, 0, 0])
        labels(point.attributes, {"function": name})
    if failed:
        errors = metric_scope.metrics.add(name=telemetry.ERRORS, unit="{error}")
        errors.sum.aggregation_temporality = 2
        errors.sum.is_monotonic = True
        point = errors.sum.data_points.add(start_time_unix_nano=1, time_unix_nano=1000, as_int=1)
        labels(point.attributes, {"function": FUNCTION, "error.type": "panic"})
    live = metric_scope.metrics.add(name=telemetry.LIVE)
    for boundary in ("observed_gc", "resource"):
        point = live.gauge.data_points.add(start_time_unix_nano=1, time_unix_nano=1000, as_int=0)
        labels(point.attributes, {"type": "all", "boundary": boundary})
    health = health_report()
    health["policy_sha256"] = policy_digest(policy)
    health["probe_accounting"].update({key: "0" for key in health["probe_accounting"] if key != "closed"})
    for key in ("function_started", "function_ended"):
        health["probe_accounting"][key] = str(sum(names.values()))
    for section in ("trace_exports", "metric_exports"):
        health[section].update(attempts="1", succeeded="1")
    health["trace_exports"]["exported_spans"] = str(sum(names.values()))
    run = SimpleNamespace(verify=Mock(), sdk_version=VERSION, caller=SimpleNamespace(targets=tuple(targets)),
                          prepared=SimpleNamespace(intent=SimpleNamespace(plain=False, policy=policy,
                              build=SimpleNamespace(receipt={"selection": {"sha256": SELECTION}}))),
                          session=SimpleNamespace(execution=SimpleNamespace(health=health),
                                                  started=SimpleNamespace(owner=SimpleNamespace(application_pid=PID))))
    return run, traces, metrics


def bodies(traces, metrics):
    return [("/v1/traces", traces.SerializeToString()), ("/v1/metrics", metrics.SerializeToString())]


class GoTelemetryTests(unittest.TestCase):
    def witness(self, run, traces, metrics):
        return telemetry.witness(run, bodies(traces, metrics), SERVICE, ExportTraceServiceRequest)

    def test_exact_normal_recursive_factory_and_error_receipts_join_health(self):
        for options in ({}, {"recursive": True}, {"factory": True}, {"recursive": True, "failed": True}):
            with self.subTest(options=options):
                run, traces, metrics = fixture(**options)
                result = self.witness(run, traces, metrics)
                self.assertEqual(result["spans"], 1 + int(options.get("recursive", False)) + int(options.get("factory", False)))
                self.assertEqual(result["pending"], 0)
                self.assertEqual(set(result), {"decoder", "raw_otlp_sha256", "functions", "spans", "losses", "pending"})
                self.assertEqual(len(result["raw_otlp_sha256"]), 64)
                run.verify.assert_called_once()

    def test_detailed_health_and_receipt_stay_outside_the_closed_comparator_witness(self):
        run, traces, metrics = fixture()
        with tempfile.TemporaryDirectory() as temporary:
            folder = Path(temporary)
            result = telemetry.witness(run, bodies(traces, metrics), SERVICE, ExportTraceServiceRequest, folder=folder)
            receipt = json.loads((folder / "go-verified-telemetry.json").read_text())
            self.assertEqual({name: receipt[name] for name in telemetry.WITNESS_FIELDS}, result)
            self.assertEqual(receipt["sdk_pid"], PID)
            self.assertIsNone(receipt["health"]["metric_exported_points"])
            self.assertEqual(receipt["received"], {"trace_batches": 1, "metric_batches": 1, "spans": 1, "metric_points": 4})
            self.assertNotIn("health", result)

    def test_plain_execution_cannot_emit_or_invent_sdk_evidence(self):
        run, traces, metrics = fixture()
        run.prepared.intent.plain = True
        run.session.execution.health = None
        self.assertIsNone(telemetry.witness(run, [], SERVICE, ExportTraceServiceRequest))
        with self.assertRaisesRegex(ValueError, "plain Go"):
            self.witness(run, traces, metrics)

    def test_foreign_resources_scope_roots_and_dropped_data_refuse(self):
        for field, value in (("name", "foreign"), ("kind", 2), ("dropped_events_count", 1),
                             ("parent_span_id", b"x" * 8), ("span_id", b"")):
            run, traces, metrics = fixture()
            span = traces.resource_spans[0].scope_spans[0].spans[0]
            setattr(span, field, value)
            with self.subTest(field=field), self.assertRaises(ValueError):
                self.witness(run, traces, metrics)
        run, traces, metrics = fixture()
        traces.resource_spans[0].resource.attributes[0].value.string_value = "another service"
        with self.assertRaises(ValueError):
            self.witness(run, traces, metrics)
        run, traces, metrics = fixture()
        traces.resource_spans[0].scope_spans[0].scope.name = "another scope"
        with self.assertRaises(ValueError):
            self.witness(run, traces, metrics)

    def test_missing_parent_duplicate_spans_and_wrong_child_times_refuse(self):
        run, traces, metrics = fixture(recursive=True)
        spans = traces.resource_spans[0].scope_spans[0].spans
        spans[1].start_time_unix_nano = 1
        with self.assertRaisesRegex(ValueError, "outside"):
            self.witness(run, traces, metrics)
        run, traces, metrics = fixture()
        spans = traces.resource_spans[0].scope_spans[0].spans
        spans.add().CopyFrom(spans[0])
        with self.assertRaises(ValueError):
            self.witness(run, traces, metrics)
        run, traces, metrics = fixture(recursive=True)
        with patch.object(telemetry, "MAX_SPANS", 1):
            with self.assertRaises(ValueError):
                self.witness(run, traces, metrics)

    def test_wrong_counts_kinds_histograms_and_live_dimensions_refuse(self):
        for change in ("count", "kind", "bounds", "sum", "live", "labels"):
            run, traces, metrics = fixture()
            values = metrics.resource_metrics[0].scope_metrics[0].metrics
            if change == "count":
                values[0].sum.data_points[0].as_int = 2
            elif change == "kind":
                values[0].sum.is_monotonic = False
            elif change == "bounds":
                values[1].histogram.data_points[0].explicit_bounds[0] = .5
            elif change == "sum":
                values[1].histogram.data_points[0].ClearField("sum")
            elif change == "live":
                values[2].gauge.data_points[0].as_int = 1
            else:
                labels(values[0].sum.data_points[0].attributes, {"function": FUNCTION})
            with self.subTest(change=change), self.assertRaises(ValueError):
                self.witness(run, traces, metrics)
        run, traces, metrics = fixture()
        with patch.object(telemetry, "MAX_POINTS", 3):
            with self.assertRaisesRegex(ValueError, "point budget"):
                self.witness(run, traces, metrics)

    def test_reset_duplicate_or_decreasing_cumulative_series_refuse(self):
        key = (telemetry.CALLS, FUNCTION, "")
        for samples in ([(1, 10, 1), (2, 20, 2)], [(1, 10, 1), (1, 10, 1)], [(1, 10, 2), (1, 20, 1)]):
            with self.assertRaises(ValueError):
                telemetry.cumulative_totals({key: samples})
        self.assertEqual(telemetry.cumulative_totals({key: [(1, 10, 1), (1, 20, 2)]}), {key: 2})

    def test_source_factory_must_finish_before_the_target_root(self):
        run, traces, metrics = fixture(factory=True)
        traces.resource_spans[0].scope_spans[0].spans[1].end_time_unix_nano = 150
        with self.assertRaisesRegex(ValueError, "factory did not complete"):
            self.witness(run, traces, metrics)

    def test_unavailable_malformed_foreign_and_lossy_evidence_cannot_pass(self):
        run, traces, metrics = fixture()
        with self.assertRaisesRegex(ValueError, "invalid OTLP"):
            telemetry.witness(run, [("/v1/traces", b"\xff")], SERVICE, ExportTraceServiceRequest)
        with self.assertRaisesRegex(ValueError, "unknown Go telemetry"):
            telemetry.witness(run, [("/other", b"")], SERVICE, ExportTraceServiceRequest)
        for body in (b"", "invalid", bytearray(b"invalid")):
            with self.assertRaisesRegex(ValueError, "empty body"):
                telemetry.witness(run, [("/v1/traces", body)], SERVICE, ExportTraceServiceRequest)
        run.session.execution.health["trace_exports"]["queue_dropped"] = "1"
        with self.assertRaises(ValueError):
            self.witness(run, traces, metrics)
        run, traces, metrics = fixture()
        run.session.execution.health["probe_accounting"]["object_admitted"] = "1"
        with self.assertRaisesRegex(ValueError, "unrequested"):
            self.witness(run, traces, metrics)


if __name__ == "__main__":
    unittest.main()
