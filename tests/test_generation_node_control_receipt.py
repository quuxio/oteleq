"""Live controls must agree with actual serial trace and cumulative metric receipt."""

import copy
import json
from pathlib import Path
import sys
import tempfile
import unittest

ROOT = Path(__file__).resolve().parents[1]
sys.path[:0] = [str(ROOT / "adapters/generation"), str(ROOT / "examples")]
import node_control_receipt as receipt
import node_live
import node_telemetry
from node_control_fixture import status
from test_generation_node_telemetry import metrics, traces, report

STATES = [{"collection": True, "emission": True}, {"collection": False, "emission": True},
          {"collection": True, "emission": False}, {"collection": False, "emission": False}]


def history(completed, previous, requested):
    intermediate = {**previous, "collection": requested["collection"]}
    return [{"command": "status", "status": status(completed, **previous)},
            {"command": "collection " + ("on" if requested["collection"] else "off"), "status": status(completed, **intermediate)},
            {"command": "emission " + ("on" if requested["emission"] else "off"), "status": status(completed, **requested)}]


def fixture():
    bodies, spans, steps = [], [], []
    previous = STATES[0]
    for index, requested in enumerate(STATES):
        before = len(bodies)
        trace = traces(error=index == 2)
        span = trace.resource_spans[0].scope_spans[0].spans[0]
        span.trace_id, span.span_id = bytes([index + 1]) * 16, bytes([index + 1]) * 8
        span.start_time_unix_nano, span.end_time_unix_nano = (index + 1) * 10, (index + 1) * 10 + 1
        spans.append(span)
        bodies.append(("/v1/traces", trace.SerializeToString()))
        if index == 0:
            bodies.append(("/v1/metrics", metrics().SerializeToString()))
        steps.append({"id": "step-" + str(index), "requested": requested.copy(),
                      "before": {"history": history(index, previous, requested), "cursor": before},
                      "after": {"status": status(index + 1, **requested), "flush": status(index + 1, **requested),
                                "settled": status(index + 1, **requested), "cursor": len(bodies),
                                "metric_bodies": [1] if index == 0 else [], "held_ns": 1000000000}})
        previous = requested
    metric = metrics(error=True)
    for item in metric.resource_metrics[0].scope_metrics[0].metrics:
        if item.name.endswith("duration"):
            point = item.histogram.data_points[0]
            point.count, point.sum, point.bucket_counts[2] = 2, .0002, 2
        else:
            point = item.sum.data_points[0]
            point.as_int = 1 if item.name.endswith("unwinds") else 2
        point.time_unix_nano = 50
    bodies.append(("/v1/metrics", metric.SerializeToString()))
    record = {"control_schema_version": 1, "plain": False, "language": "javascript", "supervisor_pid": 100, "pid": 101, "sdk_pid": 102,
              "launch_id": "a" * 32, "interval_ms": 1000, "steps": steps,
              "restored": {"history": history(4, STATES[-1], STATES[0]), "flush": status(4), "cursor": len(bodies)}}
    entry = {"language": "javascript", "otelc_function": "app.add",
             "sequence_configuration": [{"action": "call", "metrics": state.copy()} for state in STATES]}
    return entry, record, bodies, spans


class NodeControlReceiptTests(unittest.TestCase):
    def verify(self, record, bodies, spans):
        entry = fixture()[0]
        node_telemetry.function_metrics(bodies, entry, "case", report(), spans, {"app.add"}, controls=record)

    def test_only_collection_enabled_calls_are_recorded_and_emission_off_values_return(self):
        _, record, bodies, spans = fixture()
        self.verify(record, bodies, spans)
        self.assertEqual([len(tree) for tree in receipt.trees(spans)], [1, 1, 1, 1])
        child = copy.deepcopy(spans[0])
        child.span_id, child.parent_span_id = b"c" * 8, spans[0].span_id
        self.assertEqual([len(tree) for tree in receipt.trees([*spans, child])], [2, 1, 1, 1])

    def test_altered_state_pid_schedule_counter_and_raw_metric_window_refuse(self):
        _, original, bodies, spans = fixture()
        changes = [("pid", 999), ("sdk_pid", 999), ("launch_id", "b" * 32)]
        for key, changed in changes:
            record = copy.deepcopy(original)
            record[key] = changed
            with self.subTest(key=key), self.assertRaises(ValueError):
                self.verify(record, bodies, spans)
        for change in ("setter", "counter", "metric-window", "missing-trace", "restoration", "positive-metric"):
            record, altered, calls = copy.deepcopy(original), list(bodies), list(spans)
            if change == "setter":
                record["steps"][1]["before"]["history"][1]["status"]["emission"] = False
            elif change == "counter":
                record["steps"][2]["after"]["settled"]["function_completions"] = 2
            elif change == "metric-window":
                record["steps"][1]["after"]["metric_bodies"] = [1]
            elif change == "missing-trace":
                calls.pop()
            elif change == "restoration":
                record["restored"]["cursor"] -= 1
            else:
                altered[1] = ("/v1/metrics", b"")
            with self.subTest(change=change), self.assertRaises(ValueError):
                self.verify(record, altered, calls)
        for count in (1, 3, 4):
            changed = copy.deepcopy(bodies)
            metric = metrics()
            for item in metric.resource_metrics[0].scope_metrics[0].metrics:
                if item.name.endswith("duration"):
                    item.histogram.data_points[0].count = count
                    item.histogram.data_points[0].bucket_counts[2] = count
                else:
                    item.sum.data_points[0].as_int = count
            changed[-1] = ("/v1/metrics", metric.SerializeToString())
            with self.subTest(count=count), self.assertRaises(ValueError):
                self.verify(original, changed, spans)

    def test_ambiguous_overlapping_missing_parent_or_repeated_trace_trees_refuse(self):
        spans = fixture()[3]
        for change in ("overlap", "missing-parent", "repeat", "cycle", "escaping-child"):
            calls = copy.deepcopy(spans)
            if change == "overlap":
                calls[1].start_time_unix_nano = 10
            elif change == "missing-parent":
                calls[1].parent_span_id = b"p" * 8
            elif change == "repeat":
                calls.append(calls[0])
            elif change == "cycle":
                calls[1].parent_span_id = calls[1].span_id
            else:
                calls[1].trace_id, calls[1].parent_span_id = calls[0].trace_id, calls[0].span_id
            with self.subTest(change=change), self.assertRaises(ValueError):
                receipt.trees(calls)

    def save(self, folder, value, plain):
        (folder / node_live.RECORD).write_text(json.dumps(value))
        (folder / node_live.RECORD).chmod(0o600)
        for name, content in (("process.json", {"pid": 100}), ("node-source-application.json", {"pid": 101}),
                              ("node-source-completion.json", {"application_pid": 101, "sdk_pid": None if plain else 102})):
            (folder / name).write_text(json.dumps(content))

    def test_retained_record_binds_actual_processes_and_plain_lane_has_no_sdk_replies(self):
        entry, original, bodies, _ = fixture()
        with tempfile.TemporaryDirectory() as temporary:
            folder = Path(temporary)
            (folder / "node-runtime").mkdir()
            (folder / "node-runtime/node-status.json").write_text(json.dumps(report()))
            self.save(folder, original, False)
            self.assertIn("record_sha256", receipt.read(folder, entry, bodies, plain=False))
            plain = copy.deepcopy(original)
            plain.update(plain=True, sdk_pid=None, launch_id=None)
            for step in plain["steps"]:
                step["before"] = {"history": [], "cursor": 0}
                step["after"].update(status=None, flush=None, settled=None, cursor=0, metric_bodies=[])
            plain["restored"] = {"history": [], "flush": None, "cursor": 0}
            self.save(folder, plain, True)
            receipt.read(folder, entry, [], plain=True)
            for change in ("pid", "steps", "flags", "window", "held", "restored", "fabricated"):
                changed = copy.deepcopy(plain)
                if change == "pid":
                    changed["pid"] = 100
                elif change == "steps":
                    changed["steps"].pop()
                elif change == "flags":
                    changed["steps"][0]["requested"]["emission"] = 1
                elif change == "window":
                    changed["steps"][0]["after"]["cursor"] = True
                elif change == "held":
                    changed["steps"][1]["after"]["held_ns"] = 0
                elif change == "restored":
                    changed["restored"] = None
                else:
                    changed["steps"][0]["after"]["status"] = status()
                self.save(folder, changed, True)
                with self.subTest(change=change), self.assertRaises(ValueError):
                    receipt.read(folder, entry, [], plain=True)
