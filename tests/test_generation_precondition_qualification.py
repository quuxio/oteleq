"""Qualification oracles must reject equal but wrong input/result observations."""
import copy
import json
from pathlib import Path
import sys
import tempfile
import unittest
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[1]
sys.path[:0] = [str(ROOT / name) for name in ("tests", "adapters/generation", "examples")]
import policy
import precondition_fixture_oracle as oracle
import qualify_preconditions


class PreconditionQualificationTests(unittest.TestCase):
    def setUp(self):
        temporary = tempfile.TemporaryDirectory()
        self.addCleanup(temporary.cleanup)
        self.root = Path(temporary.name)

    def report(self, language="python", kind="integer"):
        values = oracle.pairs(language, kind)[0]
        function = "app." + oracle.NAMES[kind]
        entry = {"id": "case", "language": language, "name": oracle.NAMES[kind],
                 "otelc_function": function, "input_preconditions": [oracle.LESS]}
        parent = self.root / "case-0"
        parent.mkdir()
        bundle = {"contract": {"expected_baseline": {"kind": "return"}}}
        for lane in ("baseline", "instrumented_on"):
            attempts = []
            for index in range(2):
                folder = parent / (lane + "-" + str(index))
                folder.mkdir()
                result = oracle.expected_result(language, kind, values, lane)
                observed = {"fixture": {"status": "ready"}, "gaps": [],
                            "before": oracle.plain_graph(language, kind, values),
                            "after": oracle.plain_graph(language, kind, values),
                            "outcome": {"kind": "return", "graph": oracle.plain_graph(language, kind, values, result)}}
                witness = {"functions": {function: 1}, "spans": 1, "pending": 0, "losses": {"export": 0}}
                attempts.append({"observation": observed, "execution": {"capture_complete": True,
                    "termination": {"kind": "exit", "code": 0}, "channels": {"stdout": [], "stderr": []},
                    "witness": witness if lane == "instrumented_on" else None}})
                (folder / "typed-observation.json").write_text(json.dumps(observed))
                (folder / "stdout").write_bytes(b"")
                (folder / "stderr").write_bytes(b"")
            bundle[lane] = attempts
        (parent / "typed-bundle.json").write_text(json.dumps({"cases": [bundle]}))
        report = {"source_preserved": True, "blocked": [], "inventory": [entry], "exit_code": 0,
                  "cases": [{"case": "case-0", "function": function, "arguments": values, "exit_code": 0}]}
        path = self.root / "report.json"
        path.write_text(json.dumps(report))
        return path, parent, bundle

    def test_sources_and_policy_cover_twenty_functions_and_fifty_four_cases(self):
        fixtures = [qualify_preconditions.fixture(language, kind)
                    for language in oracle.LANGUAGES for kind in oracle.kinds(language)]
        path = self.root / "policy.toml"
        qualify_preconditions.write_policy(path, fixtures)
        frozen = policy.load(path)
        self.assertEqual(len(frozen["fixtures"]), 20)
        self.assertEqual(sum(len(oracle.pairs(language, kind))
            for language in oracle.LANGUAGES for kind in oracle.kinds(language)), oracle.CASES)
        self.assertTrue(all(row["preconditions"] == [oracle.LESS] for row in frozen["fixtures"]))
        self.assertEqual(sum("cases" in row for row in frozen["fixtures"]), 3)
        for language in oracle.LANGUAGES:
            name, text = oracle.source(language)
            self.assertTrue(name and all(oracle.NAMES[kind].split(".")[-1] in text for kind in oracle.kinds(language)))

    def test_fixed_pairs_and_results_bind_both_arguments(self):
        self.assertEqual(oracle.pairs("python", "integer"), [[7, 9], [7, 8], [8, 9]])
        self.assertEqual([oracle.expected_result("c", "integer", values, "baseline")
                          for values in oracle.pairs("c", "integer")], [709, 708, 809])
        for language in oracle.LANGUAGES:
            for kind in oracle.kinds(language):
                self.assertTrue(all(left < right for left, right in oracle.pairs(language, kind)))
        self.assertEqual(oracle.expected_result("python", "probe", [0, 7], "baseline"), 0)
        self.assertEqual(oracle.expected_result("python", "probe", [0, 7], "instrumented_on"), 1)

    def test_complete_literal_oracle_accepts_each_actual_repeat(self):
        path, _, _ = self.report()
        self.assertEqual(len(oracle.check_report(path, 1)), 4)
        with self.assertRaises(AssertionError):
            oracle.check_report(path, 2)

    def test_equal_but_wrong_result_in_both_lanes_is_rejected(self):
        path, parent, bundle = self.report()
        for lane in ("baseline", "instrumented_on"):
            for index, attempt in enumerate(bundle[lane]):
                attempt["observation"]["outcome"]["graph"]["roots"]["result"]["value"] = "999"
                (parent / (lane + "-" + str(index)) / "typed-observation.json").write_text(json.dumps(attempt["observation"]))
        (parent / "typed-bundle.json").write_text(json.dumps({"cases": [bundle]}))
        with self.assertRaises(AssertionError):
            oracle.check_report(path, 1)

    def test_wrong_argument_graph_and_missing_witness_are_rejected(self):
        path, parent, bundle = self.report()
        altered = copy.deepcopy(bundle)
        altered["instrumented_on"][0]["execution"]["witness"]["spans"] = 0
        (parent / "typed-bundle.json").write_text(json.dumps({"cases": [altered]}))
        with self.assertRaises(AssertionError):
            oracle.check_report(path, 1)
        altered = copy.deepcopy(bundle)
        observed = altered["baseline"][0]["observation"]
        observed["before"]["nodes"][0]["fields"]["item:1"]["value"] = "10"
        (parent / "baseline-0/typed-observation.json").write_text(json.dumps(observed))
        (parent / "typed-bundle.json").write_text(json.dumps({"cases": [altered]}))
        with self.assertRaises(AssertionError):
            oracle.check_report(path, 1)

    def test_java_receiver_float_arguments_retain_primitive_types_and_complete_fields(self):
        low, _, middle = oracle.float_pool("java")
        graph = {"roots": {"receiver": {"kind": "reference", "node_id": "opaque"},
                            "argument:0": {"kind": "float", "type": "java.float", "bits": "3dcccccd"},
                            "argument:1": {"kind": "float", "type": "java.float", "bits": "3e4ccccc"}},
                 "nodes": [{"id": "opaque", "type": "java.object:Meter", "fields": {
                     "total": {"kind": "integer", "type": "java.int", "value": "10", "bits": 32, "signed": True}}}]}
        oracle.check_receiver_graph(graph, "java", [low, middle], 10)
        altered = copy.deepcopy(graph)
        altered["roots"]["argument:0"]["type"] = "java.lang.Float"
        with self.assertRaises(AssertionError):
            oracle.check_receiver_graph(altered, "java", [low, middle], 10)
        graph["nodes"][0]["fields"]["extra"] = {"kind": "null"}
        with self.assertRaises(AssertionError):
            oracle.check_receiver_graph(graph, "java", [low, middle], 10)

    def test_incomplete_generated_route_is_not_silently_restarted(self):
        (self.root / "framework.started").write_text("prior process must be checked\n")
        with patch.object(qualify_preconditions, "command") as command:
            with self.assertRaisesRegex(AssertionError, "incomplete framework"):
                qualify_preconditions.framework(self.root / "workspace", self.root, "framework", True)
        command.assert_not_called()

    def test_post_route_resume_refuses_before_any_execution_route(self):
        cli, provider, output = self.root / "cli", self.root / "provider", self.root / "results"
        cli.write_bytes(b"test CLI")
        provider.mkdir()
        output.mkdir()
        (output / "post-routes-started").write_text("later controls already started\n")
        arguments = ["qualify_preconditions", "--cli", str(cli), "--otelc-root", str(provider),
                     "--report-dir", str(output), "--resume"]
        with patch.object(sys, "argv", arguments), patch.object(qualify_preconditions, "routes") as routes:
            with self.assertRaisesRegex(AssertionError, "later controls must not repeat"):
                qualify_preconditions.main()
        routes.assert_not_called()


if __name__ == "__main__":
    unittest.main()
