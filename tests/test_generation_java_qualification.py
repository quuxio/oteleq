"""Independent Java qualification oracles reject altered state and route drift."""
import copy
import hashlib
import json
from pathlib import Path
import sys
import tempfile
import tomllib
from types import SimpleNamespace as NS
import unittest
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parent))
import qualify_java_receivers as qualifier
from test_generation_java_health import report as health_report
from test_generation_java_telemetry import metrics, traces


def integer(number: int) -> dict:
    return {"kind": "integer", "type": "java.int", "value": str(number), "bits": 32, "signed": True}


def reference(index: int) -> dict:
    return {"kind": "reference", "node_id": "n" + str(index)}


def state(value: int, total: int) -> dict:
    return {"roots": {"receiver": reference(0), "argument:0": integer(7), "static:Counter.total": integer(total)},
            "nodes": [{"id": "n0", "type": "java.object:Counter", "fields": {"value": integer(value), "self": reference(0), "shared": reference(1)}},
                      {"id": "n1", "type": "java.object:[Ljava.lang.Object;", "fields": {"length": integer(2), "item:0": reference(0), "item:1": reference(1)}}]}


def attempt() -> dict:
    outcome = state(17, 7)
    outcome["roots"]["result"] = reference(0)
    return {"observation": {"before": state(10, 0), "after": state(17, 7), "gaps": [],
                            "outcome": {"kind": "return", "graph": outcome}},
            "execution": {"witness": {"functions": {"Counter.identity(int)": 1}}}}


class JavaQualificationTests(unittest.TestCase):
    def test_prepared_policy_and_actual_agent_control_are_explicit(self):
        with tempfile.TemporaryDirectory() as temporary:
            folder = Path(temporary) / "case"
            with patch.object(qualifier, "command", return_value=str(folder / "workspace")):
                qualifier.prepare(Path("/cli"), Path("/provider"), folder, backend="prepared")
            policy = tomllib.loads((folder / "equivalence.toml").read_text())
            self.assertEqual(policy["adapters"]["java"]["backend"], "prepared")
            source = (folder / "application/Counter.java").read_text()
            self.assertIn("opentelemetry-javaagent-2.32.0.jar", source)
            self.assertNotIn("java-agent-0.1.0-agent.jar", source)

    def test_retained_prepared_oracle_rechecks_raw_receipt_pid_hashes_and_copies(self):
        trace, metric = traces(), metrics()
        trace.resource_spans[0].scope_spans[0].spans[0].name = "Counter.identity"
        modules = {"opentelemetry.proto.collector.trace.v1.trace_service_pb2": NS(ExportTraceServiceRequest=NS(FromString=lambda _: trace)),
                   "opentelemetry.proto.collector.metrics.v1.metrics_service_pb2": NS(ExportMetricsServiceRequest=NS(FromString=lambda _: metric))}
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary);folder = root / "case";folder.mkdir()
            runtime = folder / "sdk-runtime";runtime.mkdir()
            health = health_report()
            health["metric_exports"].update(batches_started="1", batches_succeeded="1", units_started="2", units_succeeded="2")
            (runtime / "health.json").write_text(json.dumps(health))
            launch = {"argv": ["java", "Class"], "plain": False, "policy_sha256": "a" * 64, "selection_sha256": "b" * 64}
            for name, data in (("prepared-launch.json", launch), ("process.json", {"argv": launch["argv"], "pid": 123}),
                               ("command.json", launch["argv"]), ("typed-observation.json", {"function_id": "Counter.identity(int)"}),
                               ("http-capture.json", {"errors": [], "bodies": [{"path": "/v1/traces", "file": "trace"}, {"path": "/v1/metrics", "file": "metric"}]})):
                (folder / name).write_text(json.dumps(data))
            (folder / "trace").write_bytes(b"trace");(folder / "metric").write_bytes(b"metric")
            original = root / "oej-removed/r"
            archive = {"original": str(original), "files": {"health.json": {"path": str(original / "health.json"),
                       "sha256": hashlib.sha256((runtime / "health.json").read_bytes()).hexdigest()}}}
            (folder / "runtime-archive.json").write_text(json.dumps(archive))
            with patch.dict(sys.modules, modules):
                self.assertEqual(qualifier.verify_prepared(root), {"retained_attempts": 1, "unique_processes": 1,
                                  "retained_instrumented_receipts": 1, "short_runtimes_removed": True})
                for group, key in (("trace_exports", "units_succeeded"), ("metric_exports", "batches_succeeded"),
                                   ("span_accounting", "sampled_ended")):
                    changed = copy.deepcopy(health);changed[group][key] = "2"
                    (runtime / "health.json").write_text(json.dumps(changed))
                    with self.subTest(group=group), self.assertRaises(AssertionError):
                        qualifier.verify_receipt(folder, launch, 123, modules[next(iter(modules))].ExportTraceServiceRequest,
                                                 modules[list(modules)[1]].ExportMetricsServiceRequest)
                (runtime / "health.json").write_text(json.dumps(health))
                (folder / "process.json").write_text(json.dumps({"argv": ["other"], "pid": 123}))
                with self.assertRaises(AssertionError):qualifier.verify_prepared(root)
                (folder / "process.json").write_text(json.dumps({"argv": launch["argv"], "pid": 123}))
                (runtime / "health.json").write_text("{}")
                with self.assertRaises(AssertionError):qualifier.verify_prepared(root)

    def test_literal_value_alias_and_witness_oracles_reject_altered_records(self):
        with tempfile.TemporaryDirectory() as temporary:
            folder = Path(temporary)
            (folder / "case").mkdir()
            report = {"source_preserved": True, "blocked": [], "cases": [{"case": "case", "function": "Counter.identity(int)",
                       "exit_code": 0, "arguments": [7], "receiver_fixture": {"arguments": [10]}}]}
            (folder / "report.json").write_text(json.dumps(report))
            bundle = {"contract": {"required_roots": ["receiver", "argument:0", "static:Counter.total"]},
                      "baseline": [attempt(), attempt()], "instrumented_on": [attempt(), attempt()]}
            path = folder / "case/typed-bundle.json"
            path.write_text(json.dumps({"cases": [bundle]}))
            self.assertEqual(qualifier.check_report(folder / "report.json", 1)[0], 4)
            for kind in ("private", "static", "initial", "alias", "cycle", "return", "witness", "gap"):
                changed = copy.deepcopy(bundle)
                target = changed["instrumented_on"][0]
                observed = target["observation"]
                if kind == "private":
                    observed["after"]["nodes"][0]["fields"]["value"] = integer(18)
                elif kind == "static":
                    observed["after"]["roots"]["static:Counter.total"] = integer(8)
                elif kind == "initial":
                    observed["before"]["nodes"][0]["fields"]["value"] = integer(11)
                elif kind == "alias":
                    observed["after"]["nodes"][0]["fields"]["self"] = reference(1)
                elif kind == "cycle":
                    observed["after"]["nodes"][1]["fields"]["item:1"] = reference(0)
                elif kind == "return":
                    observed["outcome"]["graph"]["roots"]["result"] = reference(1)
                elif kind == "witness":
                    target["execution"]["witness"]["functions"]["Counter.identity(int)"] = 2
                else:
                    observed["gaps"] = ["missing observation"]
                path.write_text(json.dumps({"cases": [changed]}))
                with self.subTest(kind=kind), self.assertRaises(AssertionError):
                    qualifier.check_report(folder / "report.json", 1)

    def test_main_uses_per_case_replay_and_explicit_export_application(self):
        with tempfile.TemporaryDirectory() as temporary:
            folder = Path(temporary)
            cli, provider = folder / "cli", folder / "provider"
            cli.write_bytes(b"cli")
            provider.mkdir()
            cases = [{"case": str(i), "exit_code": int(i >= 6)} for i in range(8)]

            def command(arguments, *args, **kwargs):
                return json.dumps({"report": str(folder / "replay.json")}) if arguments[1] == "replay" else ""

            def check_report(path, expected):
                return (32, {"cases": cases}) if expected == 8 else (4, {})

            with patch.object(sys, "argv", ["qualifier", "--otelc-root", str(provider), "--cli", str(cli), "--report-dir", str(folder / "result")]), patch.object(qualifier, "prepare", return_value=folder / "workspace"), patch.object(qualifier, "command", side_effect=command) as commands, patch.object(qualifier, "check_report", side_effect=check_report), patch.object(qualifier, "framework", return_value=32), patch.object(qualifier, "reduction", return_value=0), patch.object(qualifier, "refusals", return_value=(0, 5)), patch.object(qualifier, "source_guards", return_value=2), patch.object(qualifier, "verify_builds", return_value={"retained_manifests": 128}), patch.object(qualifier, "verify_launches", return_value={"raw_attempt_folders": 128, "unique_command_identities": 128}), patch.dict(qualifier.os.environ), patch("builtins.print"):
                qualifier.main()
            replays = [call.args[0] for call in commands.call_args_list if call.args[0][1] == "replay"]
            self.assertEqual(len(replays), 8)
            for arguments, case in zip(replays, cases):
                self.assertEqual(arguments[-2:], ["--case", case["case"]])
                self.assertNotIn("--report-dir", arguments)
            exports = [call.args[0] for call in commands.call_args_list if call.args[0][1] == "export-tests"]
            self.assertEqual(len(exports), 2)
            self.assertNotIn("--apply", exports[0])
            self.assertEqual(exports[1][-1], "--apply")
            result = json.loads((folder / "result/qualification.json").read_text())
            self.assertEqual(result["actual_launches"], 128)

    def test_launch_count_excludes_compiler_commands_and_deduplicates_copied_evidence(self):
        with tempfile.TemporaryDirectory() as temporary:
            folder = Path(temporary)
            for name, content in (("one/baseline-0", b'["java","one"]'), ("copy/baseline-0", b'["java","one"]'),
                                  ("two/instrumented_on-0", b'["java","two"]'), ("one/baseline-0/build", b'["javac"]')):
                target = folder / name
                target.mkdir(parents=True)
                (target / "command.json").write_bytes(content)
            self.assertEqual(qualifier.verify_launches(folder, 2), {"raw_attempt_folders": 3, "unique_command_identities": 2})
            with self.assertRaises(AssertionError):
                qualifier.verify_launches(folder, 3)


if __name__ == "__main__":
    unittest.main()
