"""Source SDK telemetry requires actual selected calls, metrics and final drain."""

import json
from pathlib import Path
import sys
import tempfile
import unittest

from opentelemetry.proto.collector.metrics.v1.metrics_service_pb2 import ExportMetricsServiceRequest
from opentelemetry.proto.collector.trace.v1.trace_service_pb2 import ExportTraceServiceRequest

REPO = Path(__file__).resolve().parents[1]
sys.path[:0] = [str(REPO / "adapters/generation"), str(REPO / "examples")]
import node_telemetry as telemetry


def report():
    """Unit protocol fixture based on a completed single-call source SDK report."""
    return {"schema_version": 1, "pid": 101, "sdk_pid": 102, "language": "javascript", "launch_id": "a" * 32,
            "phase": "closed", "sdk_phase": "closed", "producer_checkpoint_available": True,
            "collection": True, "emission": True, "effective_emission_off": False,
            "runtime_losses": dict.fromkeys(telemetry.RUNTIME_LOSSES, 0), "function_completions": 1,
            "active_functions": 0, "native_callback_failures": 0, "lifetime_lost": 0, "handoff_incomplete": 0,
            "in_flight_exports": 0, "export_started": 1, "export_succeeded": 1, "export_failed": 0,
            "handoff": {"attempted": 4, "accepted": 4, "lost": 0, "deadline_ms": 50, "sdk_process_failed": False},
            "traces": {"started": 1, "succeeded": 1, "failed": 0, "pending": 0, "exported_items": 1},
            "metric_collection": {"started": 1, "failed": 0, "pending": 0},
            "span_observation": {"sampled_started": 1, "sampled_ended": 1, "sampled_active": 0, "handed_off": 1},
            "span_accounting": {"received": 1, "sdk_exported": 1, "queue_pending": 0, "queue_dropped": 0,
                                "queue_evidence": "derived_after_shutdown", "downstream_receipt": "unavailable", "otlp_partial_rejection": "unavailable"}}


def attributes(rows, values):
    for key, value in values.items():
        item = rows.add(key=key)
        item.value.string_value = value


def resource(value):
    attributes(value.attributes, {"service.name": "case", "service.instance.id": "a" * 32, "otelc.language": "javascript"})


def traces(error=False):
    message = ExportTraceServiceRequest()
    group = message.resource_spans.add()
    resource(group.resource)
    scope = group.scope_spans.add()
    scope.scope.name, scope.scope.version = telemetry.FUNCTION_SCOPE
    span = scope.spans.add(name="app.add", trace_id=b"t" * 16, span_id=b"s" * 8, kind=1,
                           start_time_unix_nano=1, end_time_unix_nano=2)
    span.status.code = 2 if error else 0
    attributes(span.attributes, {"code.function.name": "app.add", "otelc.language": "javascript"})
    return message


def metrics(error=False):
    message = ExportMetricsServiceRequest()
    group = message.resource_metrics.add()
    resource(group.resource)
    scope = group.scope_metrics.add()
    scope.scope.name, scope.scope.version = telemetry.FUNCTION_SCOPE
    names = ["otelc.function.calls", "otelc.function.duration"] + (["otelc.function.unwinds"] if error else [])
    for name in names:
        metric = scope.metrics.add(name=name)
        if name.endswith("duration"):
            metric.histogram.aggregation_temporality = 2
            point = metric.histogram.data_points.add(count=1, sum=.0001)
            point.explicit_bounds.extend(telemetry.BOUNDS)
            point.bucket_counts.extend([0, 0, 1, 0, 0, 0, 0, 0])
        else:
            metric.sum.aggregation_temporality = 2
            metric.sum.is_monotonic = True
            point = metric.sum.data_points.add(as_int=1)
        point.start_time_unix_nano, point.time_unix_nano = 1, 2
        attributes(point.attributes, {"function": "app.add", "language": "javascript"})
    return message


class NodeTelemetryTests(unittest.TestCase):
    entry = {"language": "javascript", "otelc_function": "app.add"}

    def bodies(self, trace=None, metric=None):
        return [("/v1/traces", (trace if trace is not None else traces()).SerializeToString()),
                ("/v1/metrics", (metric if metric is not None else metrics()).SerializeToString())]

    def test_closed_source_report_and_decoded_receipt_form_a_witness(self):
        with tempfile.TemporaryDirectory() as temporary:
            folder = Path(temporary)
            (folder / "node-runtime").mkdir()
            (folder / "node-runtime/node-status.json").write_text(json.dumps(report()))
            witness = telemetry.witness(folder, self.entry, self.bodies(), "case", ExportTraceServiceRequest)
            self.assertEqual(witness["functions"], {"app.add": 1})
            self.assertEqual(witness["spans"], 1)
            self.assertEqual(witness["pending"], 0)
            self.assertFalse(any(witness["losses"].values()))

    def test_missing_boolean_nonzero_and_unavailable_health_counters_refuse(self):
        for path, changed in [("schema_version", True), ("phase", "failed"), ("collection", False), ("emission", False),
                              ("effective_emission_off", True), ("active_functions", 1), ("export_started", 0),
                              ("runtime_losses.invalid", 1), ("runtime_losses.invalid", False),
                              ("handoff.accepted", 3), ("handoff.sdk_process_failed", True),
                              ("span_accounting.queue_pending", 1), ("span_accounting.downstream_receipt", 0),
                              ("metric_collection.started", 0), ("traces.started", 0)]:
            value = report()
            fields = path.split(".")
            target = value if len(fields) == 1 else value[fields[0]]
            target[fields[-1]] = changed
            with self.subTest(path=path, changed=changed), self.assertRaises(ValueError):
                telemetry.health(value, self.entry)
        value = report()
        del value["runtime_losses"]["invalid"]
        with self.assertRaises(ValueError):
            telemetry.health(value, self.entry)

    def test_trace_resource_scope_function_roots_and_count_are_bound(self):
        for field, changed in [("name", "foreign"), ("kind", 2), ("dropped_attributes_count", 1),
                               ("trace_id", b""), ("start_time_unix_nano", 0)]:
            message = traces()
            setattr(message.resource_spans[0].scope_spans[0].spans[0], field, changed)
            with self.subTest(field=field):
                self.assertRaises(ValueError, telemetry.decode_traces, self.bodies(trace=message),
                                  self.entry, "case", report(), ExportTraceServiceRequest)
        message = traces()
        message.resource_spans[0].resource.attributes[0].value.string_value = "foreign"
        self.assertRaises(ValueError, telemetry.decode_traces, self.bodies(trace=message),
                          self.entry, "case", report(), ExportTraceServiceRequest)
        self.assertRaises(ValueError, telemetry.decode_traces, [], self.entry, "case", report(), ExportTraceServiceRequest)
        self.assertRaises(ValueError, telemetry.decode_traces, [("/v1/traces", b"\xff")],
                          self.entry, "case", report(), ExportTraceServiceRequest)

    def test_function_calls_unwinds_histograms_and_cumulative_values_are_checked(self):
        for error in (False, True):
            bodies = self.bodies(traces(error), metrics(error))
            _, spans, graph = telemetry.decode_traces(bodies, self.entry, "case", report(), ExportTraceServiceRequest)
            telemetry.function_metrics(bodies, self.entry, "case", report(), spans, graph["allowed"])
        _, spans, graph = telemetry.decode_traces(self.bodies(), self.entry, "case", report(), ExportTraceServiceRequest)
        for field, changed in [("as_int", 0), ("flags", 1), ("time_unix_nano", 0)]:
            message = metrics()
            setattr(message.resource_metrics[0].scope_metrics[0].metrics[0].sum.data_points[0], field, changed)
            with self.subTest(field=field):
                self.assertRaises(ValueError, telemetry.function_metrics, self.bodies(metric=message),
                                  self.entry, "case", report(), spans, graph["allowed"])
        message = metrics()
        message.resource_metrics[0].scope_metrics[0].metrics[1].histogram.data_points[0].sum = float("nan")
        self.assertRaises(ValueError, telemetry.function_metrics, self.bodies(metric=message),
                          self.entry, "case", report(), spans, graph["allowed"])
        self.assertRaises(ValueError, telemetry.function_metrics, [], self.entry, "case", report(), spans, graph["allowed"])
        self.assertRaises(ValueError, telemetry.function_metrics, [("/v1/metrics", b"\xff")],
                          self.entry, "case", report(), spans, graph["allowed"])

    def test_sdk_queue_samples_are_separate_from_final_drain_and_unknown_metrics_refuse(self):
        message = metrics()
        scope = message.resource_metrics[0].scope_metrics.add()
        scope.scope.name = "@opentelemetry/sdk-trace"
        scope.metrics.add(name="otel.sdk.processor.span.queue.size").sum.data_points.add(as_double=1)
        bodies = self.bodies(metric=message)
        _, spans, graph = telemetry.decode_traces(bodies, self.entry, "case", report(), ExportTraceServiceRequest)
        telemetry.function_metrics(bodies, self.entry, "case", report(), spans, graph["allowed"])
        scope.metrics[0].name = "unrequested"
        self.assertRaises(ValueError, telemetry.function_metrics, self.bodies(metric=message),
                          self.entry, "case", report(), spans, graph["allowed"])
        scope.scope.name, scope.scope.version = telemetry.LIFETIME_SCOPE
        scope.metrics[0].name = "otelc.lifetime.admitted"
        self.assertRaises(ValueError, telemetry.function_metrics, self.bodies(metric=message),
                          self.entry, "case", report(), spans, graph["allowed"])

    def cumulative(self, count, timestamp, *, start=1):
        message = metrics()
        values = message.resource_metrics[0].scope_metrics[0].metrics
        call = values[0].sum.data_points[0]
        call.as_int, call.start_time_unix_nano, call.time_unix_nano = count, start, timestamp
        duration = values[1].histogram.data_points[0]
        duration.count, duration.sum = count, count * .0001
        duration.start_time_unix_nano, duration.time_unix_nano = start, timestamp
        duration.bucket_counts[:] = [0, 0, count, 0, 0, 0, 0, 0]
        return message

    def cumulative_witness(self, messages):
        spans = [traces().resource_spans[0].scope_spans[0].spans[0]] * 2
        bodies = [("/v1/metrics", message.SerializeToString()) for message in messages]
        telemetry.function_metrics(bodies, self.entry, "case", report(), spans, {"app.add"})

    def test_cumulative_points_preserve_order_and_allow_repeated_or_reordered_delivery(self):
        first, last = self.cumulative(1, 100), self.cumulative(2, 200)
        for messages in ([first, last], [last, first], [first, last, last]):
            with self.subTest(messages=len(messages)):
                self.cumulative_witness(messages)

    def test_later_counter_histogram_bucket_and_start_resets_cannot_hide_behind_a_maximum(self):
        for fault in ("counter", "histogram", "bucket", "sum", "start", "same-time"):
            first, last = self.cumulative(1, 100), self.cumulative(2, 200)
            values = last.resource_metrics[0].scope_metrics[0].metrics
            if fault == "counter":
                first.resource_metrics[0].scope_metrics[0].metrics[0].sum.data_points[0].as_int = 2
                values[0].sum.data_points[0].as_int = 1
            elif fault == "histogram":
                first = self.cumulative(2, 100)
                values[1].histogram.data_points[0].count = 1
                values[1].histogram.data_points[0].bucket_counts[:] = [0, 0, 1, 0, 0, 0, 0, 0]
            elif fault == "bucket":
                values[1].histogram.data_points[0].bucket_counts[:] = [0, 0, 0, 2, 0, 0, 0, 0]
            elif fault == "sum":
                values[1].histogram.data_points[0].sum = 0
            elif fault == "start":
                values[0].sum.data_points[0].start_time_unix_nano = 2
            else:
                last = self.cumulative(2, 100)
            with self.subTest(fault=fault), self.assertRaisesRegex(ValueError, "cumulative"):
                self.cumulative_witness([first, last])

    def test_duplicate_and_unset_attributes_refuse(self):
        message = traces()
        values = message.resource_spans[0].resource.attributes
        values.add(key="unset")
        with self.assertRaises(ValueError):
            telemetry.attributes(values)
        del values[-1]
        values.add().CopyFrom(values[0])
        with self.assertRaises(ValueError):
            telemetry.attributes(values)

    def test_collection_requires_its_actual_lifetime_and_source_factory_link(self):
        entry = {"language": "javascript", "name": "Counter.add", "otelc_function": "app.Counter.add",
                 "node_class_label": "app.Counter", "receiver_fixture": {"kind": "function", "source_function": "make"},
                 "sequence_configuration": [{"action": "call"}, {"action": "release"}, {"action": "collect"}]}
        message = traces()
        scope = message.resource_spans[0].scope_spans[0]
        selected = scope.spans[0]
        selected.name = "app.Counter.add"
        selected.attributes[0].value.string_value = selected.name
        creator = scope.spans.add(name="app.make", trace_id=b"m" * 16, span_id=b"p" * 8,
                                 kind=1, start_time_unix_nano=1, end_time_unix_nano=2)
        attributes(creator.attributes, {"code.function.name": "app.make", "otelc.language": "javascript"})
        lifetime_scope = message.resource_spans[0].scope_spans.add()
        lifetime_scope.scope.name, lifetime_scope.scope.version = telemetry.LIFETIME_SCOPE
        lifetime = lifetime_scope.spans.add(name="app.Counter lifetime", trace_id=b"l" * 16, span_id=b"z" * 8,
                                            kind=1, start_time_unix_nano=1, end_time_unix_nano=2)
        attributes(lifetime.attributes, {"type": "app.Counter", "boundary": "observed_gc"})
        lifetime.links.add(trace_id=creator.trace_id, span_id=creator.span_id)
        state = report()
        state["function_completions"] = 2
        state["span_accounting"]["received"] = 3
        state["lifetimes"] = {"admitted": 1, "gc_completed": 1, "resource_completed": 0, "current_live": 0, "censored": 0}
        names, spans, graph = telemetry.decode_traces(self.bodies(trace=message), entry, "case", state, ExportTraceServiceRequest)
        self.assertEqual(names, {"app.Counter.add": 1, "app.make": 1, "app.Counter lifetime": 1})
        self.assertEqual(graph["allowed"], {"app.Counter.add", "app.make"})
        lifetime.links[0].span_id = b"x" * 8
        self.assertRaisesRegex(ValueError, "creation link", telemetry.decode_traces,
                               self.bodies(trace=message), entry, "case", state, ExportTraceServiceRequest)
        state["lifetimes"]["gc_completed"] = 0
        with self.assertRaisesRegex(ValueError, "collection is missing"):
            telemetry.collection_receipt(spans, state, entry, "app.make")

    def test_actual_censored_lifetime_remains_incomplete_without_a_fabricated_gc_span(self):
        entry = {**self.entry, "node_class_label": "app.Counter",
                 "sequence_configuration": [{"action": "call"}, {"action": "release"}, {"action": "collect"}]}
        state = report()
        state["lifetimes"] = {"admitted": 1, "gc_completed": 0, "resource_completed": 0,
                              "current_live": 1, "censored": 1}
        with tempfile.TemporaryDirectory() as temporary:
            folder = Path(temporary)
            (folder / "node-runtime").mkdir()
            path = folder / "node-runtime/node-status.json"
            path.write_text(json.dumps(state))
            witness = telemetry.witness(folder, entry, self.bodies(), "case", ExportTraceServiceRequest)
            self.assertEqual(witness["functions"], {"app.add": 1})
            self.assertEqual(witness["spans"], 1)
            self.assertEqual(witness["losses"]["lifetime.censored"], 1)
            self.assertEqual(witness["pending"], 0)
            state["lifetimes"].update(gc_completed=1, current_live=0, censored=0)
            path.write_text(json.dumps(state))
            bodies = self.bodies()
            with self.assertRaisesRegex(ValueError, "independently witnessed"):
                telemetry.witness(folder, entry, bodies, "case", ExportTraceServiceRequest)


if __name__ == "__main__":
    unittest.main()
