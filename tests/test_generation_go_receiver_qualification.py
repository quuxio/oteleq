"""A matching but wrong Go result or state cannot pass the independent oracle."""
import copy
import hashlib
import json
from pathlib import Path
import sys
import tempfile
import tomllib
import unittest
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parent))
import qualify_go_receivers as qualifier


class GoReceiverQualificationTests(unittest.TestCase):
    def test_source_policy_is_explicit_and_legacy_policy_keeps_its_defaults(self):
        legacy = tomllib.loads(qualifier.policy_text())
        self.assertEqual(legacy["adapters"]["go"], {"module_roots": ["."]})
        source = tomllib.loads(qualifier.policy_text(backend="source-v1"))
        self.assertEqual(source["adapters"]["go"], {"module_roots": ["."], "backend": "source-v1", "build_timeout_ms": 900000})
        self.assertEqual(source["fixtures"], legacy["fixtures"])
        with self.assertRaises(AssertionError):
            qualifier.policy_text(backend="unknown")

    def test_source_receipt_requires_owned_native_pid_exact_functions_and_closed_witness(self):
        function = "example.test/receiver/counter.Counter.Read"
        case = {"function": "counter.api.Counter.Read"}
        witness = {"decoder": "literal", "raw_otlp_sha256": "a" * 64,
                   "functions": {function: 1, "example.test/receiver/counter.Nil": 1},
                   "spans": 2, "losses": {"function_lost": 0}, "pending": 0}
        receipt = {**copy.deepcopy(witness), "sdk_pid": 12, "received": {"spans": 2},
                   "health": {"metric_exported_points": None}}
        kernel = {"supervisor": {"pid": 11, "process_group": 11},
                  "application": {"pid": 12, "parent_pid": 11, "process_group": 11}}
        with tempfile.TemporaryDirectory() as temporary:
            folder = Path(temporary)
            (folder / "go-runtime").mkdir()
            start = folder / "go-runtime/oteleq-go-start.json"
            start.write_text(json.dumps({"kernel": kernel}))
            (folder / "build-identities.json").write_text(json.dumps({"profile": "go-source-v1"}))
            attempt = {"observation": {"function_id": function}, "execution": {"witness": None}}
            qualifier.source_attempt(folder, case, attempt, "baseline")
            target = folder / "go-verified-telemetry.json"
            target.write_text(json.dumps(receipt))
            with self.assertRaises(AssertionError):
                qualifier.source_attempt(folder, case, attempt, "baseline")
            attempt["execution"]["witness"] = witness
            qualifier.source_attempt(folder, case, attempt, "instrumented_on")
            for kind in ("pid", "functions", "loss", "points", "extra-witness", "function-id", "kernel"):
                changed, altered = copy.deepcopy(receipt), copy.deepcopy(attempt)
                if kind == "pid":
                    changed["sdk_pid"] = 13
                elif kind == "functions":
                    changed["functions"] = {function: 1}
                elif kind == "loss":
                    changed["losses"]["function_lost"] = 1
                elif kind == "points":
                    changed["health"]["metric_exported_points"] = 0
                elif kind == "extra-witness":
                    altered["execution"]["witness"]["health"] = {}
                elif kind == "function-id":
                    altered["observation"]["function_id"] = "another.Function"
                else:
                    changed_kernel = copy.deepcopy(kernel)
                    changed_kernel["application"]["parent_pid"] = 99
                    start.write_text(json.dumps({"kernel": changed_kernel}))
                target.write_text(json.dumps(changed))
                with self.subTest(kind=kind), self.assertRaises(AssertionError):
                    qualifier.source_attempt(folder, case, altered, "instrumented_on")
                start.write_text(json.dumps({"kernel": kernel}))

    def test_copied_source_probe_controls_require_prelaunch_refusal(self):
        with tempfile.TemporaryDirectory() as temporary:
            folder = Path(temporary)
            def command(arguments, destination, label, expected=0):
                if "export-tests" in arguments:
                    target = Path(arguments[arguments.index("--destination") + 1]) / "go-source-provider/protocol"
                    target.mkdir(parents=True)
                    (target / "response.json").write_text("{}")
                else:
                    self.assertEqual(expected, 4)
                    (destination / (label + ".stderr")).write_text("frozen Go provider probes changed")
                return ""
            with patch.object(qualifier, "command", side_effect=command) as execute:
                result = qualifier.source_probe_guards(Path("cli"), Path("workspace"), folder, {"id": "case"})
            self.assertEqual(execute.call_count, 4)
            self.assertEqual(result, {"refusal_controls": 2, "actual_application_launches": 0, "prelaunch_refusals": 2})

    def test_shrink_selection_ignores_excluded_same_named_methods(self):
        plan = {"inventory": [{"id": "main", "name": "Counter.InstanceDifference", "status": "excluded"},
                              {"id": "library", "name": "Counter.InstanceDifference", "status": "ready"}]}
        case = {"id": "case", "function_id": "library"}
        self.assertEqual(qualifier.selected_case(plan, [case], "Counter.InstanceDifference"), case)
        plan["inventory"][0]["status"] = "ready"
        with self.assertRaises(AssertionError):
            qualifier.selected_case(plan, [case], "Counter.InstanceDifference")

    def test_exact_oracle_rejects_matching_wrong_results_arguments_and_state(self):
        graph = {"roots": {"receiver": {"kind": "null"}, "argument:0": {"kind": "integer", "value": "3"},
                           "global:shared": {"kind": "reference", "node_id": "n0"},
                           "global:total": {"kind": "reference", "node_id": "n1"}},
                 "nodes": [{"id": "n0", "fields": {"value": {"kind": "null"}}},
                           {"id": "n1", "fields": {"value": {"kind": "integer", "value": "0"}}}]}
        result = copy.deepcopy(graph)
        result["roots"]["result"] = {"kind": "integer", "value": "3"}
        observed = {"before": graph, "after": graph, "gaps": [], "outcome": {"kind": "return", "graph": result}}
        attempt = {"observation": observed, "execution": {"witness": {"functions": {"counter.api.Counter.Read": 1}}}}
        bundle = {"cases": [{"baseline": [attempt, attempt], "instrumented_on": [attempt, attempt]}]}
        report = {"source_preserved": True, "blocked": [], "cases": [{"case": "case", "function": "counter.api.Counter.Read",
                  "arguments": [3], "exit_code": 0}]}
        with tempfile.TemporaryDirectory() as temporary:
            folder = Path(temporary)
            (folder / "case").mkdir()
            path = folder / "report.json"
            path.write_text(json.dumps(report))
            for lane in ("baseline", "instrumented_on"):
                for index in range(2):
                    target = folder / "case" / (lane + "-" + str(index))
                    target.mkdir()
                    (target / "stdout").write_bytes(b"")
                    (target / "stderr").write_bytes(b"")
                    helper = target / "project/oteleq_generated_observer/observer.go"
                    helper.parent.mkdir(parents=True)
                    helper.write_bytes(b"observer source")
                    (target / "build-identities.json").write_text(json.dumps({"loaded_input_count": 1}))
                    (target / "go-bundle").mkdir()
                    (target / "go-bundle/recipe.json").write_text(json.dumps({"inputs": {str(helper): {"sha256": hashlib.sha256(helper.read_bytes()).hexdigest()}}}))
            typed = folder / "case/typed-bundle.json"
            typed.write_text(json.dumps(bundle))
            self.assertEqual(qualifier.check_report(path, 1), 4)
            for change in ("result", "argument", "total", "shared"):
                altered = copy.deepcopy(bundle)
                for lane in ("baseline", "instrumented_on"):
                    for attempt in altered["cases"][0][lane]:
                        observation = attempt["observation"]
                        if change == "result":
                            observation["outcome"]["graph"]["roots"]["result"]["value"] = "30"
                        elif change == "argument":
                            observation["before"]["roots"]["argument:0"]["value"] = "30"
                        elif change == "total":
                            observation["after"]["nodes"][1]["fields"]["value"]["value"] = "1"
                        else:
                            observation["after"]["nodes"][0]["fields"]["value"] = {"kind": "reference", "node_id": "n1"}
                typed.write_text(json.dumps(altered))
                with self.subTest(change=change), self.assertRaises(AssertionError):
                    qualifier.check_report(path, 1)
