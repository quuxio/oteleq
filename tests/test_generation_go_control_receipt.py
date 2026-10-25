"""Independent Go retained-record refusals and collection-enabled tree arithmetic."""

from collections import Counter
import copy
import json
from pathlib import Path
import sys
from types import SimpleNamespace
import unittest

REPO = Path(__file__).resolve().parents[1]
sys.path[:0] = [str(REPO / "adapters/generation"), str(REPO / "examples")]
import go_build
import go_control_receipt as receipt
import go_live
import go_telemetry as telemetry
import test_generation_go_live as live_fixture
from test_generation_go_prepared import private
from test_generation_go_telemetry import FACTORY, FUNCTION, VERSION, fixture, labels


class GoControlReceiptTests(unittest.TestCase):
    def context(self, plain=False):
        helper = live_fixture.GoLiveTests()
        self.addCleanup(helper.doCleanups)
        session, _ = helper.run_session(plain=plain)
        run = SimpleNamespace(prepared=session.launch, session=session, sdk_version=VERSION,
                              caller=SimpleNamespace(targets=(go_build.Target(FUNCTION, "app.go", 1, 1),
                                                              go_build.Target(FACTORY, "factory.go", 1, 1))))
        return session, run

    def model(self):
        session, run = self.context()
        record = receipt.read(session.folder, run, session.sequence, [])
        _, traces, first = fixture(factory=True)
        spans = traces.resource_spans[0].scope_spans[0].spans
        for index in range(1, 4):
            span = spans.add()
            span.CopyFrom(spans[0])
            span.trace_id, span.span_id = bytes([index]) * 16, bytes([index]) * 8
            span.start_time_unix_nano, span.end_time_unix_nano = 100 + 200 * index, 200 + 200 * index
            if index == 2:
                span.status.code = 2
                labels(span.attributes, {"error.type": "panic"})
        service = run.prepared.intent.policy["resource"]["service_name"]
        for item in first.resource_metrics[0].resource.attributes:
            if item.key == "service.name": item.value.string_value = service
        scope = first.resource_metrics[0].scope_metrics[0]
        for metric in scope.metrics:
            if metric.name == telemetry.DURATION:
                for point in metric.histogram.data_points:
                    del point.explicit_bounds[:]
                    point.explicit_bounds.extend(run.prepared.intent.policy["metrics"]["histogram_boundaries_seconds"])
                    del point.bucket_counts[:]
                    point.bucket_counts.extend([1, 0, 0])
        second = copy.deepcopy(first)
        for metric in second.resource_metrics[0].scope_metrics[0].metrics:
            points = (metric.histogram.data_points if metric.name == telemetry.DURATION else
                      metric.gauge.data_points if metric.name == telemetry.LIVE else metric.sum.data_points)
            for point in points:
                point.time_unix_nano = 2000
                if telemetry.attributes(point.attributes).get("function") == FUNCTION:
                    if metric.name == telemetry.CALLS: point.as_int = 2
                    elif metric.name == telemetry.DURATION:
                        point.count, point.sum = 2, .01
                        point.bucket_counts[0] = 2
        errors = second.resource_metrics[0].scope_metrics[0].metrics.add(name=telemetry.ERRORS, unit="{error}")
        errors.sum.is_monotonic, errors.sum.aggregation_temporality = True, 2
        point = errors.sum.data_points.add(start_time_unix_nano=1, time_unix_nano=2000, as_int=1)
        labels(point.attributes, {"function": FUNCTION, "error.type": "panic"})
        bodies = [("/v1/metrics", first.SerializeToString()), ("/v1/metrics", second.SerializeToString())]
        for index, step in enumerate(record["steps"]):
            step["before"]["cursor"] = int(index > 0)
            step["after"].update(cursor=1, metric_bodies=[0] if index == 0 else [])
        record["restored"]["cursor"] = 2
        series, windows, points = telemetry.metric_series(bodies, run, service, {FUNCTION, FACTORY})
        self.assertEqual(points, 13)
        return session, run, record, bodies, list(spans), series, windows

    def test_retained_reader_binds_both_lanes_and_actual_private_checkpoint_files(self):
        for plain in (False, True):
            session, run = self.context(plain)
            value = receipt.read(session.folder, run, session.sequence, [])
            self.assertEqual(value["pid"], session.started.owner.application_pid)
            self.assertEqual(value["sdk_pid"], None if plain else value["pid"])
            self.assertEqual(len(value["record_sha256"]), 64)

    def test_record_shape_flags_cursors_intervals_and_missing_checkpoint_refuse(self):
        session, run = self.context()
        original = copy.deepcopy(session.record)
        path = session.folder / go_live.RECORD
        for mutate in (lambda value: value.update(pid=value["pid"] + 1),
                       lambda value: value.update(plain=0),
                       lambda value: value.update(extra=True),
                       lambda value: value["steps"][0].update(id="step-1"),
                       lambda value: value["steps"][0]["requested"].update(collection=False),
                       lambda value: value["steps"][0]["before"].update(cursor=True),
                       lambda value: value["steps"][0]["after"].update(cursor=1),
                       lambda value: value["steps"][1]["after"].update(held_ns=0),
                       lambda value: value["steps"][1]["after"].update(metric_bodies=[0]),
                       lambda value: value["restored"].update(cursor=1)):
            changed = copy.deepcopy(original); mutate(changed); private(path, changed)
            with self.assertRaises(ValueError):
                receipt.read(session.folder, run, session.sequence, [])
        private(path, original)
        marker = session.binding.root / "after-0.tmp"
        value = json.loads(marker.read_text()); value["pid"] += 1; private(marker, value)
        with self.assertRaises(ValueError):
            receipt.read(session.folder, run, session.sequence, [])

    def test_plain_lane_cannot_fabricate_controls_or_metric_receipt(self):
        session, run = self.context(True)
        value = copy.deepcopy(session.record)
        value["steps"][0]["before"]["history"] = [{}]
        private(session.folder / go_live.RECORD, value)
        with self.assertRaises(ValueError):
            receipt.read(session.folder, run, session.sequence, [])

    def test_only_collected_trees_count_and_emission_off_measurements_survive_restoration(self):
        _, run, record, bodies, spans, series, windows = self.model()
        calls, errors = receipt.qualify(record, run, bodies, spans, windows)
        self.assertEqual(calls, Counter({FUNCTION: 2, FACTORY: 1}))
        self.assertEqual(errors, Counter({(FUNCTION, "panic"): 1}))
        telemetry.metric_totals(telemetry.cumulative_totals(series), calls, errors)
        telemetry.metric_totals({(telemetry.CALLS, FUNCTION, ""): 1,
                                 (telemetry.DURATION, FUNCTION, ""): 1}, {FUNCTION: 1, FACTORY: 0}, {})
        bad = copy.deepcopy(windows)
        bad[1][telemetry.CALLS, FUNCTION, ""] = 3
        with self.assertRaisesRegex(ValueError, "uncollected"):
            receipt.qualify(record, run, bodies, spans, bad)
        with self.assertRaisesRegex(ValueError, "missing"):
            receipt.qualify(record, run, bodies, spans, {0: windows[0], 1: {}})

    def test_wrong_setter_counts_health_tree_order_and_counter_regression_refuse(self):
        _, run, record, bodies, spans, _, windows = self.model()
        changes = (lambda value: value["steps"][0]["before"]["history"][1].update(command="off"),
                   lambda value: value["steps"][0]["before"]["history"][0]["response"].update(collection=False),
                   lambda value: value["steps"][0]["after"]["settled"]["probe_accounting"].update(function_ended="9"),
                   lambda value: value["steps"][0]["after"]["settled"]["metric_exports"].update(attempts="9", succeeded="9"))
        for mutate in changes:
            changed = copy.deepcopy(record); mutate(changed)
            with self.assertRaises(ValueError):
                receipt.qualify(changed, run, bodies, spans, windows)
        changed = copy.deepcopy(record)
        changed["steps"][0]["after"]["health"]["metric_flush"]["attempts"] = "1"
        with self.assertRaisesRegex(ValueError, "advancing SDK counters"):
            receipt.qualify(changed, run, bodies, spans, windows)
        with self.assertRaises(ValueError):
            receipt.qualify(record, run, bodies, spans[:-1], windows)
        changed = copy.deepcopy(spans)
        changed[0].name = "unselected"
        with self.assertRaises(ValueError):
            receipt.qualify(record, run, bodies, changed, windows)
        with self.assertRaises(ValueError):
            receipt.transition([], record, STATES_ON)
        run.session.execution.health["probe_accounting"]["function_ended"] = "6"
        with self.assertRaisesRegex(ValueError, "final health"):
            receipt.qualify(record, run, bodies, spans, windows)


STATES_ON = {"collection": True, "emission": True}
