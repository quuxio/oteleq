"""Qualification must reject equal observations of stale or incorrect source."""
import copy
import json
from pathlib import Path
import tempfile
import unittest

import project_fixture_oracle as oracle
import qualify_project_tests as driver


class ProjectQualificationOracleTests(unittest.TestCase):
    def setUp(self):
        temporary = tempfile.TemporaryDirectory()
        self.addCleanup(temporary.cleanup)
        self.folder = Path(temporary.name)

    def attempt(self, language: str, kind: str, stage: str, lane: str = "baseline") -> tuple:
        arguments = oracle.arguments_for(language, kind)[0]
        result = oracle.expected_result(language, kind, arguments, lane, stage)
        observation = {"fixture": {"status": "ready"}, "gaps": [],
            "before": oracle.graph(language, kind, arguments), "after": oracle.graph(language, kind, arguments),
            "outcome": {"kind": "return", "graph": oracle.graph(language, kind, arguments, result)}}
        witness = {"functions": {"selected": 1}, "spans": 1, "pending": 0, "losses": {"incomplete": 0}}
        execution = {"capture_complete": True, "termination": {"kind": "exit", "code": 0},
            "channels": {"stdout": [], "stderr": []}, "witness": witness if lane == "instrumented_on" else None}
        entry = {"language": language, "otelc_function": "selected"}
        attempt = {"observation": observation, "execution": execution}
        self.save(attempt)
        return attempt, entry, arguments

    def save(self, attempt: dict) -> None:
        (self.folder / "typed-observation.json").write_text(json.dumps(attempt["observation"]))
        (self.folder / "stdout").write_bytes(b"")
        (self.folder / "stderr").write_bytes(b"")

    def test_all_eight_changed_body_results_are_independent_of_lane_agreement(self):
        for language in oracle.LANGUAGES:
            with self.subTest(language=language):
                attempt, entry, arguments = self.attempt(language, "integer", "changed")
                oracle.check_attempt(self.folder, attempt, entry, "integer", arguments, "baseline", "changed")
                self.assertEqual(oracle.expected_result(language, "integer", arguments, "baseline", "initial"), 709)
                self.assertEqual(oracle.expected_result(language, "integer", arguments, "baseline", "changed"), 1709)
                attempt["observation"]["outcome"]["graph"] = oracle.graph(language, "integer", arguments, 709)
                self.save(attempt)
                with self.assertRaises(AssertionError):
                    oracle.check_attempt(self.folder, attempt, entry, "integer", arguments, "baseline", "changed")

    def test_new_zero_argument_callers_and_node_empty_array_descriptors(self):
        for language in oracle.LANGUAGES:
            with self.subTest(language=language):
                attempt, entry, arguments = self.attempt(language, "added", "added")
                self.assertEqual(arguments, [])
                oracle.check_attempt(self.folder, attempt, entry, "added", arguments, "baseline", "added")
                self.assertIn("current_added", driver.added_source(language))
        value = oracle.graph("javascript", "added", [])
        self.assertEqual(value["nodes"][0]["fields"]["property:length"]["bits"], "0000000000000000")
        self.assertNotIn("property:0", value["nodes"][0]["fields"])

    def test_non_bmp_argument_and_unbounded_return_remain_exact(self):
        attempt, entry, arguments = self.attempt("python", "text", "initial")
        oracle.check_attempt(self.folder, attempt, entry, "text", arguments, "baseline", "initial")
        argument = attempt["observation"]["before"]["nodes"][0]["fields"]["item:0"]
        self.assertEqual(argument, {"kind": "string", "type": "python.string", "encoding": "codepoints32_be", "value": "0001f642"})
        returned = attempt["observation"]["outcome"]["graph"]["roots"]["result"]
        self.assertIsNone(returned["bits"])
        for graph in ("before", "after"):
            attempt["observation"][graph]["nodes"][0]["fields"]["item:0"]["value"] = "00000078"
        self.save(attempt)
        with self.assertRaises(AssertionError):
            oracle.check_attempt(self.folder, attempt, entry, "text", arguments, "baseline", "initial")

    def test_matching_values_cannot_hide_capture_or_witness_failure(self):
        original, entry, arguments = self.attempt("python", "probe", "different", "instrumented_on")
        oracle.check_attempt(self.folder, original, entry, "probe", arguments, "instrumented_on", "different")
        edits = [("capture_complete", False), ("termination", {"kind": "exit", "code": 1}),
                 ("channels", {"stdout": ["00"], "stderr": []}),
                 ("witness", {"functions": {"selected": 1}, "spans": 1, "pending": 1, "losses": {}}),
                 ("witness", {"functions": {"selected": 1}, "spans": 1, "pending": 0, "losses": {"incomplete": 1}})]
        for key, value in edits:
            with self.subTest(key=key):
                attempt = copy.deepcopy(original)
                attempt["execution"][key] = value
                with self.assertRaises(AssertionError):
                    oracle.check_attempt(self.folder, attempt, entry, "probe", arguments, "instrumented_on", "different")

    def test_unclassified_functions_cannot_enter_the_accepted_corpus(self):
        with self.assertRaises(AssertionError):
            oracle.kind_of({"name": "unknown"})


if __name__ == "__main__":
    unittest.main()
