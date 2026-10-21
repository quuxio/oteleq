"""Independent Java project oracles reject equal-but-wrong values and rehashed evidence."""
import argparse
from contextlib import redirect_stdout
import copy
import hashlib
import io
import json
import os
from pathlib import Path
import shutil
import sys
import tempfile
import unittest
from unittest.mock import patch
from types import SimpleNamespace

REPO = Path(__file__).resolve().parents[1]
sys.path[:0] = [str(REPO / "tests"), str(REPO / "adapters/generation"), str(REPO / "examples")]
import generation
import java_project_oracle as oracle
import qualify_java_project as qualifier
import typed_capture
from test_generation_java_health import report as health_report
from test_generation_java_telemetry import attribute, metrics, traces


def observed(function: str, amount: int = 7, instrumented: bool = False) -> dict:
    receiver = {"kind": "reference", "node_id": "fixture-receiver"} if function == "app.Counter.step(int)" else None
    extra = int(instrumented and function == "app.App.different(int)")
    before = oracle.expected_state(10, 2, amount, receiver)
    after = oracle.expected_state(10 + amount, 2 + amount + extra, amount, receiver)
    result = {"app.App.match(int)": amount + 36, "app.App.different(int)": 7,
              "app.App.resources(int)": amount + 32, "app.Counter.step(int)": 46 + 2 * amount}[function]
    return {"function_id": function, "fixture": {"status": "ready"}, "gaps": [], "before": before, "after": after,
            "outcome": {"kind": "return", "graph": {"nodes": after["nodes"],
                "roots": {**after["roots"], "result": oracle.scalar(result, receiver is not None)}}}}


def changed_observation(value: dict, fault: str) -> dict:
    changed = copy.deepcopy(value)
    if fault == "result": changed["outcome"]["graph"]["roots"]["result"]["value"] = "wrong"
    elif fault == "before": changed["before"]["roots"].clear()
    elif fault == "after": changed["after"]["nodes"].append({"id": "unknown"})
    elif fault == "type": changed["outcome"]["graph"]["roots"]["result"]["type"] = "unbound"
    elif fault == "extra-state": changed["before"]["roots"]["unexpected"] = oracle.scalar(9)
    else:
        assert fault == "gaps"
        changed["gaps"] = ["missing"]
    return changed


def changed_receipt(trace, metric, health: dict, fault: str) -> tuple:
    changed_trace, changed_metric, changed_health = copy.deepcopy(trace), copy.deepcopy(metric), copy.deepcopy(health)
    span = changed_trace.resource_spans[0].scope_spans[0].spans[0]
    if fault == "name": span.name = "Wrong.match"
    elif fault == "namespace": span.attributes[0].value.string_value = "wrong.App"
    elif fault == "scope": changed_trace.resource_spans[0].scope_spans[0].scope.version = "wrong"
    elif fault == "service": changed_trace.resource_spans[0].resource.attributes[0].value.string_value = "wrong-service"
    elif fault == "metric-label": changed_metric.resource_metrics[0].scope_metrics[0].metrics[0].sum.data_points[0].attributes = [attribute("function", "wrong")]
    elif fault == "metric-count": changed_metric.resource_metrics[0].scope_metrics[0].metrics[0].sum.data_points[0].as_int = 0
    else:
        assert fault == "health"
        changed_health["metric_exports"]["batches_failed"] = "1"
    return changed_trace, changed_metric, changed_health


class JavaProjectValueOracleTests(unittest.TestCase):
    def test_explicit_prepared_profile_is_not_accepted_on_the_legacy_backend(self):
        arguments = ["qualify_java_project.py", "--otelc-root", "/not-read", "--cli", "/not-read",
                     "--report-dir", "/not-created", "--java-backend", "legacy", "--java-profile", "safe-methods-v1"]
        with patch.object(sys, "argv", arguments), redirect_stdout(io.StringIO()), \
             patch.object(sys, "stderr", io.StringIO()), self.assertRaises(SystemExit) as error:
            qualifier.main()
        self.assertEqual(error.exception.code, 2)

    def test_all_literal_results_state_and_primitive_identities_are_required(self):
        for function in oracle.FUNCTIONS:
            for lane in (False, True):
                value = observed(function, instrumented=lane)
                oracle.observation(value, function, 7, lane)
                for fault in ("result", "before", "after", "type", "extra-state", "gaps"):
                    changed = changed_observation(value, fault)
                    with self.subTest(function=function, lane=lane, fault=fault), self.assertRaises(AssertionError):
                        oracle.observation(changed, function, 7, lane)
        oracle.observation(observed("app.App.different(int)", 0, True), "app.App.different(int)", 0, True)

    def test_receiver_node_labels_are_independent_at_each_boundary(self):
        value = observed("app.Counter.step(int)")
        value = json.loads(json.dumps(value))
        for index, graph in enumerate((value["before"], value["after"], value["outcome"]["graph"])):
            identity = "boundary-" + str(index)
            graph["roots"]["receiver"]["node_id"] = identity
            graph["nodes"][0]["id"] = identity
        oracle.observation(value, "app.Counter.step(int)", 7, False)

    def test_report_requires_both_repeats_and_real_instrumentation_for_each_case(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            cases = []
            for index, function in enumerate(oracle.FUNCTIONS):
                identity = str(index);folder = root / identity;folder.mkdir()
                captured = {"contract": {"function_id": function}}
                for lane in ("baseline", "instrumented_on"):
                    captured[lane] = [{"observation": observed(function, instrumented=lane != "baseline"),
                                      "execution": {"channels": {"stdout": [], "stderr": []},
                                                    "witness": {"functions": {function: 1}, "losses": {"dropped": 0}}}}
                                     for _ in range(2)]
                (folder / "typed-bundle.json").write_text(json.dumps({"cases": [captured]}))
                cases.append({"case": identity, "function": function, "arguments": [7],
                              "exit_code": int(function == "app.App.different(int)")})
            report = root / "report.json"
            report.write_text(json.dumps({"source_preserved": True, "blocked": [], "cases": cases}))
            self.assertEqual(oracle.check_report(report, 4)[0], 16)
            path = root / "0/typed-bundle.json"
            original = path.read_bytes()
            for fault in ("repeat", "witness", "loss", "stdout"):
                changed = json.loads(original)
                attempts = changed["cases"][0]["instrumented_on"]
                if fault == "repeat": attempts.pop()
                elif fault == "witness": attempts[0]["execution"]["witness"]["functions"] = {"Wrong.method": 1}
                elif fault == "loss": attempts[0]["execution"]["witness"]["losses"]["dropped"] = 1
                else: attempts[0]["execution"]["channels"]["stdout"] = [9]
                path.write_text(json.dumps(changed))
                with self.subTest(fault=fault), self.assertRaises(AssertionError):
                    oracle.check_report(report, 4)
            path.write_bytes(original)


class JavaProjectBuildOracleTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        temporary = tempfile.TemporaryDirectory(prefix="Java project oracle ")
        cls.addClassCleanup(temporary.cleanup)
        cls.root = Path(temporary.name).resolve()
        inputs = cls.root / "inputs";inputs.mkdir()
        source = qualifier.fixture(inputs, "legacy")
        config = qualifier.configuration(inputs, "legacy", "safe-methods-v1")
        provider = cls.root / "provider";provider.mkdir()
        cli = cls.root / "cli";cli.write_text("fixed CLI")
        java = Path(os.environ.get("OTELC_JAVA") or shutil.which("java"))
        with patch.dict(os.environ, {"OTELEQ_EXECUTABLE": str(cli)}), \
             patch.object(generation.capture, "selected_tools", return_value={"java": java}), \
             patch.object(generation.capture, "artefacts", return_value={"fixture": "fixed"}), \
             patch.object(generation, "provider_stable"), redirect_stdout(io.StringIO()) as output:
            generation.plan(argparse.Namespace(source=source, otelc_root=provider, workspace_parent=cls.root,
                config=config, language=None, exclude=[], cases=1))
            cls.workspace = Path(output.getvalue().strip())
            with redirect_stdout(io.StringIO()):
                generation.generate(argparse.Namespace(workspace=cls.workspace))
            data = generation.read(cls.workspace / "plan.json")
            entry = next(row for row in data["inventory"] if row["otelc_function"] == "app.App.match(int)")
            case = next(row for row in generation.read(cls.workspace / "tests/corpus.json") if row["function_id"] == entry["id"])
            cls.folder = cls.root / "comparison" / case["id"] / "baseline-0"
            execution = generation.attempt(cls.workspace, data, entry, case, "baseline", cls.folder, None)
            contract = {"observation_schema_version": 1, "case_id": case["id"], "function_id": entry["otelc_function"],
                        "fixture_sha256": "fixture", "required_roots": typed_capture.required_roots(entry)}
            value = typed_capture.observation(bytes(execution["channels"]["state-and-outcome"]), entry, contract)
            generation.write(cls.folder / "typed-observation.json", value)

    def test_real_jdk_build_and_loaded_dependencies_satisfy_independent_oracles(self):
        self.assertGreaterEqual(oracle.check_build(self.folder), 5)
        oracle.check_origins(self.folder, "app.App.match(int)")
        self.assertEqual(qualifier.evidence_controls(self.root), 5)
        value = oracle.document(self.folder / "typed-observation.json")
        oracle.observation(value, "app.App.match(int)", 7, False)

    def test_source_class_binding_cannot_be_reassigned_to_another_compiled_unit(self):
        with tempfile.TemporaryDirectory(dir=self.root) as temporary:
            copied = Path(temporary) / "copied"
            shutil.copytree(self.folder, copied)
            metadata = oracle.document(copied / "java-compiler.json")
            output = next(row for row in metadata["outputs"] if row["class"] == "app.App")
            helper = str(Path(output["origins"][0]).with_name("Helper.java"))
            output["origins"] = [helper]
            application = oracle.document(copied / "prepared-application.json")
            binding = application["bindings"]["app.App"]
            binding.update(source=helper, policy_path="src/main/java/app/Helper.java",
                           source_sha256=metadata["source_reads_sha256"][helper])
            (copied / "prepared-application.json").write_text(json.dumps(application))
            qualifier.repair_metadata(copied, metadata)
            with self.assertRaises(AssertionError):
                oracle.check_build(copied)


class JavaProjectReceiptTests(unittest.TestCase):
    def test_namespace_scope_metrics_and_direct_health_are_all_required(self):
        trace, metric = traces(), metrics()
        span = trace.resource_spans[0].scope_spans[0].spans[0]
        span.name = "App.match"
        span.attributes = [attribute("code.namespace", "app.App"), attribute("code.function", "match")]
        for item in metric.resource_metrics[0].scope_metrics[0].metrics:
            for point in getattr(item, item.WhichOneof("data")).data_points:
                point.attributes = [attribute("function", "match")]
        decoders = [SimpleNamespace(FromString=lambda _: trace), SimpleNamespace(FromString=lambda _: metric)]
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            (root / "sdk-runtime").mkdir()
            health = health_report()
            health["metric_exports"].update(batches_started="1", batches_succeeded="1", units_started="2", units_succeeded="2")
            policy = {"resource": {"service_name": "case"}}
            health["policy_sha256"] = hashlib.sha256(json.dumps(policy, sort_keys=True).encode()).hexdigest()
            (root / "policy.toml").write_text('[resource]\nservice_name="case"\n')
            generation.write(root / "sdk-runtime/health.json", health)
            generation.write(root / "http-capture.json", {"errors": [], "bodies": [
                {"path": "/v1/traces", "file": "trace.bin"}, {"path": "/v1/metrics", "file": "metric.bin"}]})
            (root / "trace.bin").write_bytes(b"trace");(root / "metric.bin").write_bytes(b"metric")
            generation.write(root / "typed-observation.json", {"function_id": "app.App.match(int)"})
            launch = {"policy_sha256": health["policy_sha256"], "selection_sha256": "b" * 64}
            qualifier.verify_receipt(root, launch, 123, *decoders)
            for fault in ("name", "namespace", "scope", "service", "metric-label", "metric-count", "health"):
                changed_trace, changed_metric, changed_health = changed_receipt(trace, metric, health, fault)
                generation.write(root / "sdk-runtime/health.json", changed_health)
                trace_decoder = SimpleNamespace(FromString=lambda _: changed_trace)
                metric_decoder = SimpleNamespace(FromString=lambda _: changed_metric)
                with self.subTest(fault=fault), self.assertRaises(AssertionError):
                    qualifier.verify_receipt(root, launch, 123, trace_decoder, metric_decoder)
                generation.write(root / "sdk-runtime/health.json", health)


if __name__ == "__main__":
    unittest.main()
