"""Prepared Java requires independent complete OTLP receipt and actual JVM health."""
import copy
import hashlib
import json
from pathlib import Path
import sys
import tempfile
from types import SimpleNamespace as NS
import unittest
from unittest.mock import patch

REPO = Path(__file__).resolve().parents[1]
sys.path[:0] = [str(REPO / "adapters/generation"), str(REPO / "examples")]
import java_telemetry as telemetry
from test_generation_java_health import report


def attribute(key: str, value: str):
    return NS(key=key, value=NS(string_value=value, WhichOneof=lambda _: "string_value"))


def resource():
    return NS(attributes=[attribute("service.name", "case"), attribute("otelc.language", "java")])


def span(identity=b"a" * 8, parent=b"", status=0):
    return NS(name="App.selected", trace_id=b"t" * 16, span_id=identity, parent_span_id=parent,
              start_time_unix_nano=10, end_time_unix_nano=20, kind=1, status=NS(code=status),
              dropped_attributes_count=0, dropped_events_count=0, dropped_links_count=0,
              attributes=[attribute("code.namespace", "sample.App"), attribute("code.function", "selected")])


def traces(nodes=None):
    scope = NS(name=telemetry.METHOD_SCOPE[0], version=telemetry.METHOD_SCOPE[1])
    return NS(resource_spans=[NS(resource=resource(), scope_spans=[NS(scope=scope, spans=nodes or [span()])])])


def point(count=1, timestamp=20):
    return NS(attributes=[attribute("function", "selected")], flags=0, start_time_unix_nano=10,
              time_unix_nano=timestamp, as_int=count, WhichOneof=lambda _: "as_int", count=count,
              explicit_bounds=list(telemetry.BUCKETS), bucket_counts=[count] + [0] * len(telemetry.BUCKETS),
              sum=.001 * count, HasField=lambda name: name == "sum")


def metrics(count=1):
    rows = []
    for name, kind, unit in ((telemetry.CALLS, "sum", "{call}"), (telemetry.DURATION, "histogram", "s")):
        data = NS(data_points=[point(count)], aggregation_temporality=2, is_monotonic=True)
        rows.append(NS(name=name, unit=unit, WhichOneof=lambda _, kind=kind: kind, **{kind: data}))
    scope = NS(name=telemetry.METHOD_SCOPE[0], version=telemetry.METHOD_SCOPE[1])
    return NS(resource_metrics=[NS(resource=resource(), scope_metrics=[NS(scope=scope, metrics=rows)])])


class JavaTelemetryTests(unittest.TestCase):
    def setUp(self):
        self.entry = {"otelc_function": "sample.App.selected(int)"}
        self.trace = traces()
        self.metric = metrics()
        self.bodies = [("/v1/traces", b"trace"), ("/v1/metrics", b"metric")]

    def receipt(self, **changes):
        arguments = dict(bodies=self.bodies, service="case", entry=self.entry,
                         trace_decoder=lambda _: self.trace, metric_decoder=lambda _: self.metric)
        return telemetry.receipt(**{**arguments, **changes})

    def test_direct_receipt_counts_all_points_and_selected_error_tree(self):
        self.trace = traces([span(), span(b"b" * 8, b"a" * 8, status=2)])
        self.metric = metrics(2)
        # Non-function SDK metrics still contribute to the health export accounting.
        self.metric.resource_metrics[0].scope_metrics[0].metrics.append(
            NS(name="other", WhichOneof=lambda _: "gauge", gauge=NS(data_points=[point()])))
        self.assertEqual(self.receipt(), {"trace_batches": 1, "spans": 2, "metric_batches": 1,
                                          "metric_points": 3, "errors": 1})

    def test_incomplete_unknown_duplicate_or_wrongly_typed_attributes_refuse(self):
        for rows in ([attribute("name", "x"), attribute("name", "y")],
                     [NS(key="name", value=NS(WhichOneof=lambda _: None))]):
            with self.assertRaises(ValueError):telemetry.attributes(rows)
        for message in (self.trace, self.metric):
            groups = message.resource_spans if hasattr(message, "resource_spans") else message.resource_metrics
            groups[0].resource.attributes[0].value.string_value = "other"
            with self.assertRaisesRegex(ValueError, "resource identity"):self.receipt()
            groups[0].resource.attributes[0].value.string_value = "case"

    def test_decoder_errors_and_unsupported_routes_refuse(self):
        def broken(_):
            raise RuntimeError("external decoder")
        with self.assertRaisesRegex(ValueError, "invalid OTLP protobuf"):self.receipt(trace_decoder=broken)
        with self.assertRaisesRegex(ValueError, "unexpected OTLP route"):
            self.receipt(bodies=[("/unknown", b"x")])

    def test_span_identity_scope_status_and_dropped_observations_refuse(self):
        original = copy.deepcopy(self.trace)
        changes = (("name", "other"), ("kind", 2), ("span_id", b"short"), ("trace_id", b"\0" * 16),
                   ("parent_span_id", b"missing!"), ("start_time_unix_nano", 0),
                   ("dropped_attributes_count", 1), ("dropped_events_count", 1), ("dropped_links_count", 1))
        for key, value in changes:
            self.trace = copy.deepcopy(original)
            setattr(self.trace.resource_spans[0].scope_spans[0].spans[0], key, value)
            with self.subTest(key=key), self.assertRaises(ValueError):self.receipt()
        for change in (lambda scope: setattr(scope.scope, "version", "other"),
                       lambda scope: setattr(scope.spans[0].status, "code", 1),
                       lambda scope: setattr(scope.spans[0].attributes[1].value, "string_value", "other"),
                       lambda scope: scope.spans.append(copy.deepcopy(scope.spans[0]))):
            self.trace = copy.deepcopy(original);change(self.trace.resource_spans[0].scope_spans[0])
            with self.assertRaises(ValueError):self.receipt()
        for nodes in ([span(), span(b"b" * 8)],
                      [span(parent=b"b" * 8), span(b"b" * 8, b"a" * 8)]):
            self.trace = traces(nodes)
            with self.assertRaises(ValueError):self.receipt()

    def test_required_metrics_need_complete_scope_type_value_buckets_and_times(self):
        original = copy.deepcopy(self.metric)
        edits = [lambda scope: setattr(scope.scope, "version", "other"),
                 lambda scope: setattr(scope.metrics[0], "unit", "other"),
                 lambda scope: setattr(scope.metrics[0], "WhichOneof", lambda _: None),
                 lambda scope: setattr(scope.metrics[0].sum, "aggregation_temporality", 1),
                 lambda scope: setattr(scope.metrics[0].sum, "is_monotonic", False)]
        for name, value in (("as_int", -1), ("flags", 1), ("start_time_unix_nano", 21),
                            ("time_unix_nano", 0), ("WhichOneof", lambda _: "as_double"),
                            ("attributes", [])):
            edits.append(lambda scope, name=name, value=value: setattr(scope.metrics[0].sum.data_points[0], name, value))
        for name, value in (("explicit_bounds", []), ("bucket_counts", []), ("count", 2),
                            ("sum", float("nan")), ("sum", -1.), ("HasField", lambda _: False)):
            edits.append(lambda scope, name=name, value=value: setattr(scope.metrics[1].histogram.data_points[0], name, value))
        for index, edit in enumerate(edits):
            self.metric = copy.deepcopy(original);edit(self.metric.resource_metrics[0].scope_metrics[0])
            with self.subTest(index=index), self.assertRaises(ValueError):self.receipt()

    def test_cumulative_series_allow_earlier_snapshots_and_refuse_resets_missing_or_extra_calls(self):
        rows = self.metric.resource_metrics[0].scope_metrics[0].metrics
        for row, kind in zip(rows, ("sum", "histogram")):
            getattr(row, kind).data_points[:] = [point(1, 30), point(0, 20)]
        self.assertEqual(self.receipt()["spans"], 1)
        for values in ([point(1, 20), point(0, 30)], [], [point(2)]):
            rows[0].sum.data_points[:] = values
            with self.subTest(values=values), self.assertRaises(ValueError):self.receipt()
        with self.assertRaises(ValueError):self.receipt(bodies=[("/v1/metrics", b"metric")])

    def test_witness_binds_real_process_health_and_all_raw_bodies(self):
        module = NS(ExportMetricsServiceRequest=NS(FromString=lambda _: self.metric))
        with tempfile.TemporaryDirectory() as temporary:
            folder = Path(temporary).resolve();runtime = folder / "r";runtime.mkdir(mode=0o700)
            health = report()
            health["metric_exports"].update(batches_started="1", batches_succeeded="1", units_started="2", units_succeeded="2")
            (runtime / "health.json").write_text(json.dumps(health));(runtime / "health.json").chmod(0o600)
            argv = ["/selected/java", "App"]
            (folder / "prepared-launch.json").write_text(json.dumps(dict(argv=argv, policy_sha256="a" * 64,
                                                                         selection_sha256="b" * 64)))
            (folder / "process.json").write_text(json.dumps(dict(pid=123, argv=argv)))
            with patch.dict(sys.modules, {"opentelemetry.proto.collector.metrics.v1.metrics_service_pb2": module}):
                result = telemetry.witness(runtime, folder, self.entry, self.bodies, "case", NS(FromString=lambda _: self.trace))
                self.assertEqual(result["raw_otlp_sha256"], hashlib.sha256(b"tracemetric").hexdigest())
                self.assertEqual(result["functions"], {self.entry["otelc_function"]: 1})
                self.assertEqual(result["pending"], 0)
                self.assertEqual(set(result["losses"].values()), {0})
                self.assertEqual(json.loads((folder / "verified-health.json").read_text())["pid"], 123)
                for process in ({"pid": 123, "argv": ["/other/java"]}, {"pid": 124, "argv": argv}, {}):
                    (folder / "process.json").write_text(json.dumps(process))
                    with self.subTest(process=process), self.assertRaises(ValueError):
                        telemetry.witness(runtime, folder, self.entry, self.bodies, "case", NS(FromString=lambda _: self.trace))


if __name__ == "__main__":
    unittest.main()
