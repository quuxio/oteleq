"""Metric gates cannot hide traces or borrow another call's error/exemplar."""

from collections import Counter
from pathlib import Path
import sys
import tempfile
import unittest

REPO = Path(__file__).resolve().parents[1]
sys.path[:0] = [str(REPO / "adapters/generation"), str(REPO / "examples")]
from opentelemetry.proto.collector.metrics.v1.metrics_service_pb2 import ExportMetricsServiceRequest
from opentelemetry.proto.collector.trace.v1.trace_service_pb2 import ExportTraceServiceRequest
import python_execution
import python_telemetry as telemetry
from test_generation_python_execution import fixture
from test_generation_python_telemetry import traces, metrics


class PythonControlledTelemetryTests(unittest.TestCase):
    def setUp(self):
        temporary = tempfile.TemporaryDirectory()
        self.addCleanup(temporary.cleanup)
        intent, launch, owner, catalogue = fixture(Path(temporary.name))
        self.execution = python_execution.read(intent, launch, owner, catalogue)

    def decode(self, trace, metric, measured):
        bodies = [("/v1/traces", trace.SerializeToString()), ("/v1/metrics", metric.SerializeToString())]
        return telemetry.decode(bodies, self.execution, "case", {1: "entry.workload"},
                                ExportTraceServiceRequest, ExportMetricsServiceRequest, measured=measured)

    def two_calls(self, *, second_error=False):
        result = traces()
        other = traces(error=second_error).resource_spans[0].scope_spans[0].spans[0]
        appended = result.resource_spans[0].scope_spans[0].spans.add()
        appended.CopyFrom(other)
        appended.trace_id, appended.span_id = b"u" * 16, b"r" * 8
        appended.start_time_unix_nano, appended.end_time_unix_nano = 4, 5
        for event in appended.events:
            event.time_unix_nano = 4
        return result

    def test_only_collected_span_counts_allow_metrics_while_every_trace_remains_required(self):
        chosen = {(b"t" * 16, b"s" * 8): 1}
        result = self.decode(self.two_calls(), metrics(), (Counter({1: 1}), Counter(), chosen))
        self.assertEqual(result["code_calls"], {1: 2})
        self.assertEqual(result["received"]["spans"], 2)
        with self.assertRaises(ValueError):
            self.decode(self.two_calls(), metrics(), None)
        for invalid in ((), ({}, {}, {}), ({1: True}, {}, chosen),
                        ({1: 2}, {}, chosen), ({1: 1}, {}, {(b"x" * 16, b"s" * 8): 1}),
                        ({1: 1}, {1: 1}, chosen)):
            with self.subTest(invalid=invalid), self.assertRaises(ValueError):
                self.decode(self.two_calls(), metrics(), invalid)

    def test_an_uncollected_exception_cannot_supply_a_collected_error_counter(self):
        measured = (Counter({1: 1}), Counter({1: 1}), {(b"t" * 16, b"s" * 8): 1})
        with self.assertRaises(ValueError):
            self.decode(self.two_calls(second_error=True), metrics(error=True), measured)

    def test_an_uncollected_span_cannot_supply_an_exemplar_for_the_same_code(self):
        value = metrics()
        for metric in value.resource_metrics[0].scope_metrics[0].metrics:
            points = metric.histogram.data_points if metric.name == telemetry.DURATION else metric.sum.data_points
            for point in points:
                for exemplar in point.exemplars:
                    exemplar.trace_id, exemplar.span_id = b"u" * 16, b"r" * 8
        with self.assertRaises(ValueError):
            self.decode(self.two_calls(), value, (Counter({1: 1}), Counter(), {(b"t" * 16, b"s" * 8): 1}))


if __name__ == "__main__":
    unittest.main()
