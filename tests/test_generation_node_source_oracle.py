"""The independent SDK oracle must reject equal but incorrect retained evidence."""

import copy
import json
from pathlib import Path
import sys
import tempfile
import unittest

sys.path.insert(0, str(Path(__file__).resolve().parent))
import node_source_oracle as oracle
from test_generation_node_telemetry import metrics, report, traces


class NodeSourceOracleTests(unittest.TestCase):
    spec = {"language": "javascript", "function": "app.add"}

    def test_fixed_single_call_final_health_and_negative_controls(self):
        oracle.check_health(report(), self.spec, 101)
        changes = (("pid", True), ("pid", 102), ("language", "typescript"), ("schema_version", True),
                   ("function_completions", 2), ("phase", "failed"), ("sdk_phase", "failed"),
                   ("collection", False), ("emission", False), ("effective_emission_off", True),
                   ("export_succeeded", False), ("export_started", 0), ("active_functions", 1),
                   ("runtime_losses.invalid", 1), ("runtime_losses.incomplete", False),
                   ("span_observation.handed_off", True), ("span_accounting.queue_pending", 1),
                   ("traces.failed", False), ("traces.succeeded", 0), ("traces.exported_items", 2),
                   ("metric_collection.pending", 1), ("handoff.accepted", 1), ("handoff.sdk_process_failed", True))
        for field, replacement in changes:
            value = report()
            parts = field.split(".")
            target = value if len(parts) == 1 else value[parts[0]]
            target[parts[-1]] = replacement
            with self.subTest(field=field), self.assertRaises(ValueError):
                oracle.check_health(value, self.spec, 101)

    def fixture(self, folder):
        bodies = []
        for index, (route, message) in enumerate((("/v1/traces", traces()), ("/v1/metrics", metrics()))):
            filename = str(index) + ".pb"
            (folder / filename).write_bytes(message.SerializeToString())
            bodies.append({"path": route, "file": filename})
        return {"bodies": bodies, "errors": []}

    def test_actual_protobuf_decode_and_raw_signal_substitutions_refuse(self):
        with tempfile.TemporaryDirectory() as temporary:
            folder = Path(temporary)
            capture = self.fixture(folder)
            value = oracle.decode(folder, capture, self.spec, "a" * 32, "case")
            # Real SDK duration points have extrema; keep them explicit in this unit fixture.
            histogram = value["metrics"][1]["points"][0]
            histogram.update(minimum=.0001, maximum=.0001, has_min=True, has_max=True)
            oracle.check_telemetry(value, self.spec, "a" * 32, "case")
            for field, replacement in (("scope", ["wrong", ""]), ("name", "wrong"),
                                       ("attributes", {}), ("trace_id", "0" * 32), ("parent", "1" * 16)):
                edited = copy.deepcopy(value)
                edited["spans"][0][field] = replacement
                with self.subTest(field=field), self.assertRaises(ValueError):
                    oracle.check_telemetry(edited, self.spec, "a" * 32, "case")
            for changes in ({"value": 0}, {"value_type": "as_double"}, {"attributes": {}}, {"flags": 1}):
                edited = copy.deepcopy(value)
                edited["metrics"][0]["points"][0].update(changes)
                with self.subTest(changes=changes), self.assertRaises(ValueError):
                    oracle.check_telemetry(edited, self.spec, "a" * 32, "case")
            for edited in ({**value, "spans": []}, {**value, "metrics": []}):
                with self.assertRaises(ValueError):
                    oracle.check_telemetry(edited, self.spec, "a" * 32, "case")

    def test_sdk_queue_scope_is_separate_and_unknown_routes_or_names_refuse(self):
        with tempfile.TemporaryDirectory() as temporary:
            folder = Path(temporary)
            capture = self.fixture(folder)
            message = metrics()
            queue = message.resource_metrics[0].scope_metrics.add()
            queue.scope.name = "@opentelemetry/sdk-trace"
            queue.metrics.add(name="otel.sdk.processor.span.queue.size").gauge.data_points.add(as_int=1)
            (folder / "1.pb").write_bytes(message.SerializeToString())
            self.assertEqual(len(oracle.decode(folder, capture, self.spec, "a" * 32, "case")["metrics"]), 2)
            queue.metrics[0].name = "unknown"
            (folder / "1.pb").write_bytes(message.SerializeToString())
            with self.assertRaises(ValueError):
                oracle.decode(folder, capture, self.spec, "a" * 32, "case")
            for route, filename in (("/unknown", "1.pb"), ("/v1/metrics", "../1.pb")):
                with self.assertRaises(ValueError):
                    oracle.decode(folder, {"bodies": [{"path": route, "file": filename}]}, self.spec, "a" * 32, "case")

    def test_attempt_binds_original_policy_actual_app_sdk_and_launch(self):
        with tempfile.TemporaryDirectory() as temporary:
            folder = Path(temporary)
            capture = self.fixture(folder)
            message = metrics()
            point = message.resource_metrics[0].scope_metrics[0].metrics[1].histogram.data_points[0]
            point.min = point.max = .0001
            (folder / "1.pb").write_bytes(message.SerializeToString())
            runtime = folder / "node-runtime"
            runtime.mkdir()
            (folder / "policy.toml").write_text('[resource]\nservice_name="case"\n')
            (folder / "node-source-application.json").write_text('{"pid":101}')
            (folder / "node-source-completion.json").write_text('{"sdk_pid":102}')
            (runtime / "node-launch.json").write_text(json.dumps({"launch_id": "a" * 32}))
            path = runtime / "node-status.json"
            value = report()
            path.write_text(json.dumps(value))
            oracle.check_attempt(folder, self.spec, capture)
            value["sdk_pid"] = 103
            path.write_text(json.dumps(value))
            with self.assertRaisesRegex(ValueError, "process/launch"):
                oracle.check_attempt(folder, self.spec, capture)


if __name__ == "__main__":
    unittest.main()
