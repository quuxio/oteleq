"""The declared-return qualification checks complete independently known results."""
import copy
import fnmatch
import json
from pathlib import Path
import tempfile
import tomllib
import unittest
from unittest.mock import patch

import qualify_returns as qualify


def attempt(language: str, lane: str) -> dict:
    witness = {"functions": {"selected_match": 1}, "spans": 1, "pending": 0, "losses": {"export": 0}}
    return {"execution": {"capture_complete": True, "termination": {"kind": "exit", "code": 0},
                          "channels": {"stdout": [], "stderr": []},
                          "witness": witness if lane == "instrumented_on" else None},
            "observation": {"fixture": {"status": "ready"}, "gaps": [],
                            "outcome": {"kind": "return", "graph": {"roots": {"result": qualify.scalar(language, 7)}}}}}


class ReturnQualificationTests(unittest.TestCase):
    def test_fixture_patterns_match_source_and_signature_qualified_identities(self):
        with tempfile.TemporaryDirectory() as temporary:
            folder = Path(temporary)
            workspace = folder / "workspace"
            workspace.mkdir()
            with patch.object(qualify, "command", return_value=str(workspace)):
                qualify.prepare(Path("cli"), Path("provider"), folder)
            policy = tomllib.loads((folder / "policy.toml").read_text())
            self.assertEqual(len(policy["fixtures"]), 16)
            for fixture in policy["fixtures"]:
                suffix = "wrong_fixture" if "wrong_fixture" in fixture["function"] else "match"
                identity = "Owner.selected_" + suffix
                if fixture["language"] in ("cpp", "java"):
                    identity += "(int)"
                with self.subTest(language=fixture["language"], suffix=suffix):
                    self.assertTrue(fnmatch.fnmatchcase(identity, fixture["function"]))
                    self.assertEqual(fixture["cases"], [[3]])

    def test_all_language_sources_and_toml_expectations_are_concrete(self):
        for language in qualify.LANGUAGES:
            name, text = qualify.source(language)
            with self.subTest(language=language):
                self.assertIn("selected_match", text)
                self.assertIn("selected_wrong_fixture", text)
                self.assertTrue(name)
                self.assertIn('value="7"' if language not in ("javascript", "typescript") else 'bits="401c000000000000"',
                              qualify.toml_value(qualify.scalar(language, 7)))

    def test_wrong_equal_values_output_termination_capture_and_witness_refuse(self):
        for language in qualify.LANGUAGES:
            entry = {"language": language, "otelc_function": "selected_match"}
            for lane in ("baseline", "instrumented_on"):
                original = attempt(language, lane)
                qualify.check_attempt(original, entry, lane)
                for fault in ("return", "type", "stdout", "exit", "capture", "witness"):
                    changed = copy.deepcopy(original)
                    if fault == "return":
                        changed["observation"]["outcome"]["graph"]["roots"]["result"] = qualify.scalar(language, 8)
                    elif fault == "type":
                        changed["observation"]["outcome"]["graph"]["roots"]["result"]["type"] = "wrong.type"
                    elif fault == "stdout":
                        changed["execution"]["channels"]["stdout"] = [1]
                    elif fault == "exit":
                        changed["execution"]["termination"]["code"] = 1
                    elif fault == "capture":
                        changed["execution"]["capture_complete"] = False
                    else:
                        changed["execution"]["witness"] = {"functions": {}, "spans": 0, "pending": 1, "losses": {"export": 1}}
                    with self.subTest(language=language, lane=lane, fault=fault), self.assertRaises(AssertionError):
                        qualify.check_attempt(changed, entry, lane)

    def test_single_case_reports_preserve_the_declared_contract_and_lane_counts(self):
        with tempfile.TemporaryDirectory() as temporary:
            folder = Path(temporary)
            case = folder / "case"
            case.mkdir()
            report = {"source_preserved": True, "blocked": [],
                      "inventory": [{"otelc_function": "selected_match", "language": "python"}],
                      "cases": [{"case": "case", "function": "selected_match", "arguments": [3], "exit_code": 0,
                                 "comparison": {"verdict": "equivalent_observed"}}]}
            paired = {"contract": {"expected_baseline": {"kind": "return_value", "value": qualify.scalar("python", 7)}},
                      "baseline": [attempt("python", "baseline") for _ in range(2)],
                      "instrumented_on": [attempt("python", "instrumented_on") for _ in range(2)]}
            path = folder / "report.json"
            path.write_text(json.dumps(report))
            bundle = case / "typed-bundle.json"
            bundle.write_text(json.dumps({"cases": [paired]}))
            self.assertEqual(qualify.check_report(path, 1), 4)
            paired["contract"]["expected_baseline"]["value"] = qualify.scalar("python", 8)
            bundle.write_text(json.dumps({"cases": [paired]}))
            with self.assertRaises(AssertionError):
                qualify.check_report(path, 1)


if __name__ == "__main__":
    unittest.main()
