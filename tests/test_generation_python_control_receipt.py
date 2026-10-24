"""Complete synthetic SDK/OTLP schedules detect independent evidence changes."""

import copy
from pathlib import Path
import sys
import tempfile
import unittest

REPO = Path(__file__).resolve().parents[1]
sys.path[:0] = [str(REPO / "adapters/generation"), str(REPO / "examples")]
from opentelemetry.proto.collector.metrics.v1.metrics_service_pb2 import ExportMetricsServiceRequest
from opentelemetry.proto.collector.trace.v1.trace_service_pb2 import ExportTraceServiceRequest
import python_control_receipt as receipt
import python_execution
import python_telemetry as telemetry
from python_control_fixture import report, status
from test_generation_python_execution import fixture
from test_generation_python_telemetry import traces, metrics
from test_generation_python_live import STATES


def schedule(execution, *, first=0):
    """Use independent literal SDK facts and official protobuf message objects."""
    states = STATES[first:] + STATES[:first] + [STATES[0]]
    record = {"pid": execution.application_pid, "sdk_pid": execution.sdk_pid,
              "launch_id": execution.launch_id, "policy_sha256": "b" * 64, "steps": []}
    bodies, completed, collected, errors, exports, flushes = [], 0, 0, 0, 0, 0

    def reply(flags, *, barrier=True):
        value = status(**flags, completed=completed, barrier=barrier)
        value.update(pid=record["pid"], sdk_pid=record["sdk_pid"])
        return value

    def health(flags):
        value = report(**flags, completed=completed, exports=exports)
        value.update(pid=record["pid"], sdk_pid=record["sdk_pid"], launch_id=record["launch_id"])
        value["application"].update(pid=record["pid"], sdk_pid=record["sdk_pid"])
        sdk = value["sdk"]
        sdk.update(pid=record["pid"], sdk_pid=record["sdk_pid"], launch_id=record["launch_id"], flush_started=flushes)
        sdk["metric_collection"].update(started=flushes, succeeded=flushes)
        sdk["traces"].update(started=completed, succeeded=completed)
        value["metric_flush"]["attempts"] = str(flushes)
        value["trace_exports"].update(batches_started=str(completed), batches_succeeded=str(completed))
        return value

    def history(previous, flags):
        intermediate = {"collection": flags["collection"], "emission": previous["emission"]}
        return [{"command": "status", "response": reply(previous)},
                {"command": "collection " + ("on" if flags["collection"] else "off"), "response": reply(intermediate)},
                {"command": "emission " + ("on" if flags["emission"] else "off"), "response": reply(flags)}]

    def metric_packet():
        message = metrics(error=errors > 0)
        for metric in message.resource_metrics[0].scope_metrics[0].metrics:
            histogram = metric.name == telemetry.DURATION
            points = metric.histogram.data_points if histogram else metric.sum.data_points
            for point in points:
                point.ClearField("exemplars")
                point.time_unix_nano = 10 * completed + 9
                if histogram:
                    point.count, point.sum = collected, collected * .0001
                    del point.bucket_counts[:]
                    point.bucket_counts.extend([0, 0, collected, 0, 0, 0, 0, 0])
                else:
                    point.as_int = errors if metric.name == telemetry.EXCEPTIONS else collected
        return "/v1/metrics", message.SerializeToString()

    previous = states[0]
    for index, flags in enumerate(states):
        rows = history(previous, flags)
        flushes += 1
        before = {"history": rows, "flush": reply(flags, barrier=False), "health": health(flags), "cursor": len(bodies)}
        if flags["collection"]:
            collected += 1
            errors += int(index == 0)
        completed += 1
        indices = []
        if all(flags.values()):
            exports += 1
            indices = [len(bodies)]
            bodies.append(metric_packet())
        trace = traces(error=index == 0)
        span = trace.resource_spans[0].scope_spans[0].spans[0]
        span.trace_id, span.span_id = bytes([index + 1]) * 16, bytes([index + 1]) * 8
        span.start_time_unix_nano, span.end_time_unix_nano = 10 * index + 1, 10 * index + 3
        for event in span.events:
            event.time_unix_nano = 10 * index + 2
        bodies.append(("/v1/traces", trace.SerializeToString()))
        flushes += 1
        after = {"status": reply(flags), "flush": reply(flags, barrier=False), "health": health(flags),
                 "cursor": len(bodies), "metric_bodies": indices, "held_ns": 1_000_000_000}
        flushes += 1
        after.update(settled_flush=reply(flags, barrier=False), settled=health(flags))
        record["steps"].append({"id": "step-" + str(index), "requested": flags.copy(), "before": before, "after": after})
        previous = flags
    restored = {"collection": True, "emission": True}
    rows = history(previous, restored)
    exports += 1; flushes += 1
    bodies.append(metric_packet())
    record["restored"] = {"history": rows, "flush": reply(restored, barrier=False), "health": health(restored), "cursor": len(bodies)}
    entry = {"language": "python", "python_backend": "prepared", "python_profile": "python-native-origins-v2",
             "otelc_function": "entry.workload"}
    return record, entry, bodies, record["restored"]["health"]["sdk"], collected, errors


class PythonControlReceiptTests(unittest.TestCase):
    def setUp(self):
        temporary = tempfile.TemporaryDirectory()
        self.addCleanup(temporary.cleanup)
        intent, launch, owner, catalogue = fixture(Path(temporary.name))
        self.execution = python_execution.read(intent, launch, owner, catalogue)

    def qualify(self, record, entry, bodies, final):
        return receipt.qualify(record, entry, bodies, self.execution, "case", {1: "entry.workload"},
                               ExportTraceServiceRequest, ExportMetricsServiceRequest, final)

    def test_every_initial_state_has_complete_traces_and_only_collected_metrics_and_errors(self):
        for first in range(4):
            with self.subTest(first=first):
                record, entry, bodies, final, count, errors = schedule(self.execution, first=first)
                calls, failures, chosen = self.qualify(record, entry, bodies, final)
                self.assertEqual(calls, {1: count})
                self.assertEqual(failures, {1: errors})
                self.assertEqual(len(chosen), count)

    def test_changed_sdk_pid_flags_call_counts_or_final_counters_refuse(self):
        for section, key, changed in (("status", "sdk_pid", 99), ("status", "function_completions", 99),
                                      ("status", "collection", False), ("health", "launch_id", "c" * 32)):
            record, entry, bodies, final, _, _ = schedule(self.execution)
            record["steps"][0]["after"][section][key] = changed
            with self.subTest(section=section, key=key), self.assertRaises(ValueError):
                self.qualify(record, entry, bodies, final)
        record, entry, bodies, final, _, _ = schedule(self.execution)
        final = {**final, "export_started": 0}
        with self.assertRaises(ValueError):
            self.qualify(record, entry, bodies, final)

    def test_a_drained_off_window_rejects_new_admission_without_any_metric_packet(self):
        record, entry, bodies, final, _, _ = schedule(self.execution)
        health = record["steps"][2]["after"]["health"]
        for key in ("export_started", "export_succeeded"):
            health["sdk"][key] += 1
        for key in ("batches_started", "batches_succeeded"):
            health["metric_exports"][key] = str(int(health["metric_exports"][key]) + 1)
        with self.assertRaisesRegex(ValueError, "admitted exports after emission-off"):
            self.qualify(record, entry, bodies, final)

    def test_missing_or_wrongly_named_call_trees_refuse(self):
        record, entry, bodies, final, _, _ = schedule(self.execution)
        without = [body for body in bodies if body[0] != "/v1/traces"]
        with self.assertRaises(ValueError):
            self.qualify(record, entry, without, final)
        changed = copy.deepcopy(bodies)
        index = next(i for i, row in enumerate(changed) if row[0] == "/v1/traces")
        value = ExportTraceServiceRequest.FromString(changed[index][1])
        value.resource_spans[0].scope_spans[0].spans[0].name = "other"
        changed[index] = ("/v1/traces", value.SerializeToString())
        with self.assertRaises(ValueError):
            self.qualify(record, entry, changed, final)


if __name__ == "__main__":
    unittest.main()
