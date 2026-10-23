"""Both decoded signals bind actual process/code IDs and complete accounting."""

from dataclasses import replace
import math
from pathlib import Path
import random
import sys
import tempfile
import unittest

from opentelemetry.proto.collector.metrics.v1.metrics_service_pb2 import ExportMetricsServiceRequest
from opentelemetry.proto.collector.trace.v1.trace_service_pb2 import ExportTraceServiceRequest

REPO = Path(__file__).resolve().parents[1]
sys.path[:0] = [str(REPO / "adapters/generation"), str(REPO / "examples")]
import python_execution
import python_telemetry as telemetry
from test_generation_python_execution import APP, TOKEN, fixture as execution_fixture


def attributes(rows, values: dict) -> None:
    for key, value in values.items():
        item = rows.add(key=key)
        if type(value) is int:
            item.value.int_value = value
        else:
            item.value.string_value = value


def resource(value) -> None:
    attributes(value.attributes, {"service.name": "case", "service.instance.id": TOKEN, "process.pid": APP,
                                  "otelc.language": "python", "telemetry.sdk.name": "opentelemetry",
                                  "telemetry.sdk.language": "python", "telemetry.sdk.version": "1.45.1"})


def traces(*, error: bool = False):
    value = ExportTraceServiceRequest()
    group = value.resource_spans.add()
    resource(group.resource)
    scope = group.scope_spans.add()
    scope.scope.name, scope.scope.version = telemetry.SCOPE
    span = scope.spans.add(name="entry.workload", trace_id=b"t" * 16, span_id=b"s" * 8, kind=1,
                           start_time_unix_nano=1, end_time_unix_nano=2)
    attributes(span.attributes, {"code.function.name": "entry.workload", "otelc.python.code_id": 1})
    if error:
        span.status.code = 2
        event = span.events.add(name="exception", time_unix_nano=2)
        attributes(event.attributes, {"exception.type": "builtins.ValueError"})
    return value


def metrics(*, error: bool = False):
    value = ExportMetricsServiceRequest()
    group = value.resource_metrics.add()
    resource(group.resource)
    scope = group.scope_metrics.add()
    scope.scope.name, scope.scope.version = telemetry.SCOPE
    names = [telemetry.CALLS, telemetry.DURATION, *([telemetry.EXCEPTIONS] if error else [])]
    for name in names:
        metric = scope.metrics.add(name=name, unit="s" if name == telemetry.DURATION else "")
        if name == telemetry.DURATION:
            metric.histogram.aggregation_temporality = 2
            point = metric.histogram.data_points.add(count=1, sum=.0001, min=.0001, max=.0001)
            point.explicit_bounds.extend(telemetry.BOUNDS)
            point.bucket_counts.extend([0, 0, 1, 0, 0, 0, 0, 0])
        else:
            metric.sum.aggregation_temporality = 2
            metric.sum.is_monotonic = True
            point = metric.sum.data_points.add(as_int=1)
        point.start_time_unix_nano, point.time_unix_nano = 1, 3
        attributes(point.attributes, {"function": "entry.workload", "otelc.python.code_id": 1})
        exemplar = point.exemplars.add(trace_id=b"t" * 16, span_id=b"s" * 8, time_unix_nano=2)
        if name == telemetry.DURATION:
            exemplar.as_double = .0001
        else:
            exemplar.as_int = 1
    return value


class PythonTelemetryTests(unittest.TestCase):
    def setUp(self) -> None:
        temporary = tempfile.TemporaryDirectory()
        self.addCleanup(temporary.cleanup)
        intent, launch, owner, catalogue = execution_fixture(Path(temporary.name))
        self.execution = python_execution.read(intent, launch, owner, catalogue)

    def decode(self, trace=None, metric=None, *, bodies=None, functions=None, execution=None):
        if bodies is None:
            bodies = [("/v1/traces", (trace if trace is not None else traces()).SerializeToString()),
                      ("/v1/metrics", (metric if metric is not None else metrics()).SerializeToString())]
        return telemetry.decode(bodies, self.execution if execution is None else execution, "case",
                                {1: "entry.workload"} if functions is None else functions,
                                ExportTraceServiceRequest, ExportMetricsServiceRequest)

    def test_complete_code_id_receipt_and_exception_totals_remain_aggregate_observations(self) -> None:
        for error in (False, True):
            value = self.decode(traces(error=error), metrics(error=error))
            self.assertEqual(value["received"], {"trace_batches": 1, "spans": 1, "metric_batches": 1,
                                                  "metric_points": 3 if error else 2})
            self.assertEqual(value["code_calls"], {1: 1})
            self.assertEqual(value["code_errors"], {1: int(error)})
            self.assertEqual(value["functions"], {"entry.workload": 1})
            self.assertEqual((value["roots"], value["source_origin"]), (1, "unavailable"))

    def test_execution_code_catalogue_and_fixed_selected_names_are_required(self) -> None:
        for functions in ({}, [], {True: "entry.workload"}, {2: "entry.workload"}, {1: ""}, {1: "foreign"}):
            with self.subTest(functions=functions), self.assertRaises(ValueError):
                self.decode(functions=functions)
        with self.assertRaises(ValueError):
            self.decode(execution=replace(self.execution, sdk_pid=None))
        with self.assertRaises(ValueError):
            telemetry.decode([], None, "case", {1: "entry.workload"}, ExportTraceServiceRequest, ExportMetricsServiceRequest)

    def test_empty_malformed_unknown_routes_and_missing_signal_receipts_refuse(self) -> None:
        invalid = [[], [("/v1/logs", b"value")], [("/v1/traces", b"")], [("/v1/traces", b"\xff")],
                   [("/v1/metrics", b"\xff")], [("/v1/traces", b"\x0a\x00")],
                   [("/v1/metrics", b"\x0a\x00")], [("/v1/traces", bytearray(b"x"))],
                   [("/v1/traces", traces().SerializeToString())], [("/v1/metrics", metrics().SerializeToString())]]
        for bodies in invalid:
            with self.subTest(bodies=bodies), self.assertRaises(ValueError):
                self.decode(bodies=bodies)

    def test_process_service_launch_scope_and_duplicate_resource_attributes_are_bound(self) -> None:
        for metric in (False, True):
            for index in range(7):
                message = metrics() if metric else traces()
                group = message.resource_metrics[0] if metric else message.resource_spans[0]
                row = group.resource.attributes[index]
                row.value.Clear()
                row.value.string_value = "foreign" if index != 6 else ""
                with self.subTest(metric=metric, index=index), self.assertRaises(ValueError):
                    self.decode(**{"metric" if metric else "trace": message})
            message = metrics() if metric else traces()
            group = message.resource_metrics[0] if metric else message.resource_spans[0]
            group.resource.attributes.add().CopyFrom(group.resource.attributes[0])
            with self.assertRaises(ValueError):
                self.decode(**{"metric" if metric else "trace": message})
            del group.resource.attributes[-1]
            group.resource.dropped_attributes_count = 1
            with self.assertRaises(ValueError):
                self.decode(**{"metric" if metric else "trace": message})

    def test_selected_span_fields_labels_and_complete_parent_tree_are_checked(self) -> None:
        for key, value in (("name", "foreign"), ("kind", 2), ("trace_id", b""), ("span_id", b""),
                           ("parent_span_id", b"s" * 8), ("parent_span_id", b"p" * 8),
                           ("start_time_unix_nano", 0), ("end_time_unix_nano", 0),
                           ("dropped_attributes_count", 1), ("dropped_events_count", 1), ("dropped_links_count", 1)):
            message = traces(); span = message.resource_spans[0].scope_spans[0].spans[0]
            setattr(span, key, value)
            with self.subTest(key=key, value=value), self.assertRaises(ValueError):
                self.decode(trace=message)
        message = traces(); scope = message.resource_spans[0].scope_spans[0]
        scope.spans.add().CopyFrom(scope.spans[0])
        with self.assertRaises(ValueError):
            self.decode(trace=message)
        for key in ("code.function.name", "otelc.python.code_id", "extra"):
            message = traces(); span = message.resource_spans[0].scope_spans[0].spans[0]
            attributes(span.attributes, {key: "wrong"})
            with self.subTest(key=key), self.assertRaises(ValueError):
                self.decode(trace=message)

    def test_exception_events_links_and_scope_dimensions_are_closed(self) -> None:
        for metric in (False, True):
            message = metrics() if metric else traces()
            group = message.resource_metrics[0] if metric else message.resource_spans[0]
            scopes = group.scope_metrics if metric else group.scope_spans
            scopes[0].scope.version = "foreign"
            with self.assertRaises(ValueError):
                self.decode(**{"metric" if metric else "trace": message})
        for key, value in (("name", "foreign"), ("time_unix_nano", 0), ("dropped_attributes_count", 1)):
            message = traces(error=True); event = message.resource_spans[0].scope_spans[0].spans[0].events[0]
            setattr(event, key, value)
            with self.subTest(key=key), self.assertRaises(ValueError):
                self.decode(message, metrics(error=True))
        message = traces(); message.resource_spans[0].scope_spans[0].spans[0].links.add(trace_id=b"t" * 16, span_id=b"s" * 8)
        with self.assertRaises(ValueError):
            self.decode(trace=message)

    def test_metric_kinds_units_temporality_points_histogram_ranges_and_totals_are_checked(self) -> None:
        for index, key, value in ((0, "name", "unknown"), (0, "unit", "1"), (1, "unit", "seconds")):
            message = metrics(); metric = message.resource_metrics[0].scope_metrics[0].metrics[index]
            setattr(metric, key, value)
            with self.subTest(key=key, value=value), self.assertRaises(ValueError):
                self.decode(metric=message)
        for index, key, value in ((0, "as_int", 0), (0, "as_double", 1.), (0, "flags", 1),
                                  (0, "start_time_unix_nano", 0), (1, "sum", float("nan")),
                                  (1, "min", -1), (1, "max", float("inf")), (1, "count", 2)):
            message = metrics(); metric = message.resource_metrics[0].scope_metrics[0].metrics[index]
            point = getattr(metric, metric.WhichOneof("data")).data_points[0]
            setattr(point, key, value)
            with self.subTest(key=key, value=value), self.assertRaises(ValueError):
                self.decode(metric=message)
        message = metrics(); message.resource_metrics[0].scope_metrics[0].metrics[0].sum.aggregation_temporality = 1
        with self.assertRaises(ValueError):
            self.decode(metric=message)

    def test_exemplars_must_reference_the_received_selected_span_with_typed_values(self) -> None:
        for index, key, value in ((0, "trace_id", b"x" * 16), (0, "span_id", b"x" * 8), (0, "as_double", 1.),
                                  (0, "time_unix_nano", 0), (1, "as_double", float("nan"))):
            message = metrics(); metric = message.resource_metrics[0].scope_metrics[0].metrics[index]
            exemplar = getattr(metric, metric.WhichOneof("data")).data_points[0].exemplars[0]
            setattr(exemplar, key, value)
            with self.subTest(key=key, value=value), self.assertRaises(ValueError):
                self.decode(metric=message)

    def test_first_measurement_can_precede_lazy_sdk_aggregation_start(self) -> None:
        message = metrics()
        for metric in message.resource_metrics[0].scope_metrics[0].metrics:
            point = getattr(metric, metric.WhichOneof("data")).data_points[0]
            point.start_time_unix_nano = 3
            point.time_unix_nano = 4
            point.exemplars[0].time_unix_nano = 2
        self.decode(metric=message)
        message.resource_metrics[0].scope_metrics[0].metrics[0].sum.data_points[0].exemplars[0].time_unix_nano = 5
        with self.assertRaises(ValueError):
            self.decode(metric=message)

    def test_cumulative_arrival_order_duplicates_resets_conflicts_and_regressions(self) -> None:
        bucket = lambda count: tuple(count if index == 5 else 0 for index in range(8))
        sample = (1, 2, 1, bucket(1), .1, (.1, .1))
        later = (1, 3, 2, bucket(2), .2, (.1, .1))
        self.assertEqual(telemetry.cumulative({"stream": [later, sample, sample]}), {"stream": 2})
        for changed in ((2, 3, 2, (0, 2), .2, (.1, .1)), (1, 2, 2, (0, 2), .2, (.1, .1)),
                         (1, 3, 0, (0, 1), .1, (.1, .1)), (1, 3, 2, (1, 0), .2, (.1, .1)),
                         (1, 3, 2, (0, 2), .01, (.1, .1)), (1, 3, 1, (0, 1), .2, (.1, .2)),
                         (1, 3, 2, (0, 2), .2, (.2, .2)), (1, 3, 2, (0, 2), .2, (.01, .09))):
            with self.subTest(changed=changed), self.assertRaises(ValueError):
                telemetry.cumulative({"stream": [sample, changed]})

    def test_impossible_sums_and_populated_buckets_cannot_pass_complete_decode(self) -> None:
        for wrong_sum in (10., 0.):
            message = metrics()
            message.resource_metrics[0].scope_metrics[0].metrics[1].histogram.data_points[0].sum = wrong_sum
            with self.subTest(sum=wrong_sum), self.assertRaisesRegex(ValueError, "histogram sum"):
                self.decode(metric=message)
        message = metrics()
        point = message.resource_metrics[0].scope_metrics[0].metrics[1].histogram.data_points[0]
        point.bucket_counts[:] = [1, 0, 0, 0, 0, 0, 0, 0]
        with self.assertRaisesRegex(ValueError, "extrema"):
            self.decode(metric=message)

    def test_histogram_boundaries_use_the_lower_open_upper_closed_interval(self) -> None:
        for index, boundary in enumerate(telemetry.BOUNDS):
            for value, expected in ((boundary, index), (math.nextafter(boundary, math.inf), index + 1)):
                message = metrics()
                point = message.resource_metrics[0].scope_metrics[0].metrics[1].histogram.data_points[0]
                point.min = point.max = point.sum = value
                point.bucket_counts[:] = [int(position == expected) for position in range(8)]
                telemetry.histogram_range(point)
                point.bucket_counts[:] = [int(position == (expected + 1) % 8) for position in range(8)]
                with self.subTest(value=value, bucket=expected), self.assertRaises(ValueError):
                    telemetry.histogram_range(point)

    def test_histogram_sum_bounds_allow_real_rounding_and_require_actual_extrema(self) -> None:
        message = metrics()
        point = message.resource_metrics[0].scope_metrics[0].metrics[1].histogram.data_points[0]
        point.count, point.min, point.max, point.sum = 3, .1, .1, .1 + .1 + .1
        point.bucket_counts[:] = [0, 0, 0, 0, 0, 3, 0, 0]
        telemetry.histogram_range(point)
        point.count = 1
        point.min, point.max, point.sum = .01, .1, .1
        point.bucket_counts[:] = [0, 0, 0, 0, 0, 1, 0, 0]
        with self.assertRaises(ValueError):
            telemetry.histogram_range(point)
        point.count, point.min, point.max = 10, 1e-7, .2
        point.bucket_counts[:] = [9, 0, 0, 0, 0, 0, 1, 0]
        point.sum = .2 + 9e-7
        telemetry.histogram_range(point)
        point.sum = 1.
        with self.assertRaisesRegex(ValueError, "sum"):
            telemetry.histogram_range(point)
        point.count = 0
        with self.assertRaisesRegex(ValueError, "count"):
            telemetry.histogram_range(point)
        point.count, point.min, point.max, point.sum = 1, .1, .1, math.nextafter(.1, math.inf)
        point.bucket_counts[:] = [0, 0, 0, 0, 0, 1, 0, 0]
        with self.assertRaisesRegex(ValueError, "sum"):
            telemetry.histogram_range(point)
        point.count, point.min, point.max, point.sum = 2, 0., 0., math.ulp(0.)
        point.bucket_counts[:] = [2, 0, 0, 0, 0, 0, 0, 0]
        with self.assertRaisesRegex(ValueError, "sum"):
            telemetry.histogram_range(point)

    def test_histogram_bounds_accept_independently_aggregated_finite_samples(self) -> None:
        rng = random.Random(841)
        values = [0., math.ulp(0.), 1e-7, 1e-6, math.nextafter(1e-6, math.inf), .1, 1., 10., 1e300]
        message = metrics()
        point = message.resource_metrics[0].scope_metrics[0].metrics[1].histogram.data_points[0]
        for size in range(1, 40):
            samples = [rng.choice(values) for _ in range(size)]
            point.count, point.min, point.max, point.sum = size, min(samples), max(samples), sum(samples)
            buckets = [0] * 8
            for value in samples:
                index = next((index for index, bound in enumerate(telemetry.BOUNDS) if value <= bound), 7)
                buckets[index] += 1
            point.bucket_counts[:] = buckets
            with self.subTest(size=size):
                telemetry.histogram_range(point)

    def test_cumulative_added_sum_cannot_replace_previously_recorded_values(self) -> None:
        bucket = lambda count: tuple(count if index == 6 else 0 for index in range(8))
        previous = (1, 2, 100, bucket(100), 20.6, (.2, .8))
        impossible = (1, 3, 101, bucket(101), 80.2, (.2, .8))
        with self.assertRaisesRegex(ValueError, "added bucket"):
            telemetry.cumulative({"duration": [previous, impossible]})
        later = (1, 3, 101, bucket(101), 21.4, (.2, .8))
        self.assertEqual(telemetry.cumulative({"duration": [previous, later]}), {"duration": 101})
        expanded = (1, 3, 101, bucket(101), 21.5, (.2, .9))
        self.assertEqual(telemetry.cumulative({"duration": [previous, expanded]}), {"duration": 101})

    def test_cumulative_histograms_accept_independent_real_prefix_aggregates(self) -> None:
        rng = random.Random(551)
        samples, observed = [], []
        for count in range(1, 50):
            samples.append(rng.choice([0., math.ulp(0.), 1e-7, 1e-6, .1, .2, .8, 1., 10., 1e300]))
            buckets = [0] * 8
            for value in samples:
                index = next((index for index, bound in enumerate(telemetry.BOUNDS) if value <= bound), 7)
                buckets[index] += 1
            observed.append((1, count + 1, count, tuple(buckets), sum(samples), (min(samples), max(samples))))
            with self.subTest(count=count):
                self.assertEqual(telemetry.cumulative({"duration": observed}), {"duration": count})
