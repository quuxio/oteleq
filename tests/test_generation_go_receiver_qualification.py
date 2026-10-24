"""A matching but wrong Go result or state cannot pass the independent oracle."""
import copy
import hashlib
import json
from pathlib import Path
import shutil
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

    def test_tagged_fixture_keeps_literal_oracles_and_an_observably_wrong_alternative(self):
        tags = ("feature", "tools", "\u03c0")
        policy = tomllib.loads(qualifier.policy_text(backend="source-v1", build_tags=tags))
        self.assertEqual(policy["adapters"]["go"]["build_tags"], list(tags))
        self.assertEqual(policy["fixtures"], tomllib.loads(qualifier.policy_text())["fixtures"])
        with self.assertRaises(AssertionError):
            qualifier.policy_text(build_tags=tags)
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            workspace = root / "workspace"
            workspace.mkdir()
            (workspace / "plan.json").write_text(json.dumps({"inventory": [
                {"name": "Counter." + name, "status": "ready"} for name in qualifier.METHODS]}))
            with patch.object(qualifier, "command", return_value=str(workspace)):
                qualifier.prepare(Path("cli"), Path("sdk"), root / "evidence", backend="source-v1", build_tags=tags)
            for package in ("counter", "cmd"):
                folder = root / "evidence/application" / package
                self.assertTrue((folder / "api.go").read_text().startswith("//go:build feature && tools && \u03c0\n"))
                alternative = (folder / "default.go").read_text()
                self.assertTrue(alternative.startswith("//go:build !(feature && tools && \u03c0)\n"))
                self.assertIn("value:seed+100,", alternative)

    def test_tagged_oracle_refuses_other_tags_active_files_flags_helpers_and_logs(self):
        tags = ("feature", "tools", "\u03c0")
        with tempfile.TemporaryDirectory() as temporary:
            folder = Path(temporary)
            build = folder / "go-build"
            (build / "inspection").mkdir(parents=True)
            (build / "private").mkdir()
            pin = build / "private/otel.instrumentation.go"
            pin.write_text("//go:build !feature\n")
            commands = [{"argv": [name, "build", "-tags=feature,tools,\u03c0"]} for name in ("go", "weaver")]
            evidence = {}
            for name in ("commands.json", "command-0.stdout", "command-0.stderr", "command-1.stdout", "command-1.stderr"):
                raw = b"literal compiler evidence"
                (build / name).write_bytes(raw)
                evidence[name] = {"path": str(build / name), "resolved_path": str(build / name),
                                  "size": len(raw), "sha256": hashlib.sha256(raw).hexdigest()}
            receipt = {"schema_version": 5, "build_tags": list(tags), "commands": commands,
                       "command_evidence": evidence, "plain": {"path": str(build / "plain")}}
            inventory = {"schema_version": 2, "build_tags": list(tags), "compiler_inputs": {"counter/api.go": "source"}}
            def publish():
                (build / "build.json").write_text(json.dumps(receipt))
                (build / "inspection/inventory.json").write_text(json.dumps(inventory))
            publish()
            qualifier.tagged_attempt(folder, "Read", tags)
            copied = folder / "copied"
            shutil.copytree(build, copied / "go-build")
            qualifier.tagged_attempt(copied, "Read", tags)
            original = copy.deepcopy(receipt), copy.deepcopy(inventory)
            for change in ("build", "tags", "inspection", "active", "flag", "log", "pin", "path", "resolved"):
                receipt, inventory = copy.deepcopy(original)
                if change == "build": receipt["schema_version"] = 4
                elif change == "tags": receipt["build_tags"] = ["tools"]
                elif change == "inspection": inventory["schema_version"] = 1
                elif change == "active": inventory["compiler_inputs"]["counter/default.go"] = "source"
                elif change == "flag": receipt["commands"][-1]["argv"].pop()
                elif change == "log": (build / "command-0.stderr").write_bytes(b"changed")
                elif change == "pin": pin.write_text("//go:build tools\n")
                else: receipt["command_evidence"]["commands.json"]["path" if change == "path" else "resolved_path"] = "/other/commands.json"
                publish()
                with self.subTest(change=change), self.assertRaises(AssertionError):
                    qualifier.tagged_attempt(folder, "Read", tags)
                (build / "command-0.stderr").write_bytes(b"literal compiler evidence")
                pin.write_text("//go:build !feature\n")

    def test_complete_source_framework_has_a_separate_aggregate_budget(self):
        output = "\n".join(json.dumps({"report": str(index)}) for index in range(9))
        for backend, timeout in (("legacy", 900), ("source-v1", 3600)):
            with patch.object(qualifier, "command", return_value=output) as execute, \
                    patch.object(qualifier, "check_report", return_value=4) as check:
                self.assertEqual(qualifier.framework(Path("workspace"), Path("folder"), "suite", backend=backend), 36)
            self.assertEqual(execute.call_args.kwargs, {"expected": 1, "timeout": timeout})
            self.assertEqual(check.call_count, 9)

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
