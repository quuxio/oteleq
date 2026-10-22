"""Independent domain-fixture oracles reject equal but incorrect observations."""
import copy
import hashlib
import json
from pathlib import Path
import sys
import tempfile
import unittest
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[1]
sys.path[:0] = [str(ROOT / "tests"), str(ROOT / "adapters/generation"), str(ROOT / "examples")]
import domain_fixture_oracle as oracle
import policy
import qualify_domains


class DomainQualificationTests(unittest.TestCase):
    def setUp(self):
        temporary = tempfile.TemporaryDirectory()
        self.addCleanup(temporary.cleanup)
        self.root = Path(temporary.name)

    def report(self, language="python", kind="integer"):
        value = oracle.arguments(language, kind)[0]
        function = "app.domain_" + kind
        entry = {"id": "case", "language": language, "name": "domain_" + kind, "otelc_function": function}
        parent = self.root / "case-0"
        parent.mkdir()
        bundle = {"contract": {"expected_baseline": {"kind": "return"}}}
        for lane in ("baseline", "instrumented_on"):
            attempts = []
            for index in range(2):
                folder = parent / (lane + "-" + str(index))
                folder.mkdir()
                observed = {"fixture": {"status": "ready"}, "gaps": [],
                    "before": oracle.graph(language, kind, value),
                    "after": oracle.graph(language, kind, value),
                    "outcome": {"kind": "return", "graph": oracle.graph(language, kind, value, returned=True)}}
                witness = ({"functions": {function: 1}, "spans": 1, "pending": 0,
                            "losses": {"export": 0}} if lane == "instrumented_on" else None)
                attempts.append({"observation": observed, "execution": {"capture_complete": True,
                    "termination": {"kind": "exit", "code": 0}, "channels": {"stdout": [], "stderr": []},
                    "witness": witness}})
                (folder / "typed-observation.json").write_text(json.dumps(observed))
                (folder / "stdout").write_bytes(b"")
                (folder / "stderr").write_bytes(b"")
            bundle[lane] = attempts
        (parent / "typed-bundle.json").write_text(json.dumps({"cases": [bundle]}))
        report = {"source_preserved": True, "blocked": [], "inventory": [entry], "exit_code": 0,
                  "cases": [{"case": "case-0", "function": function, "arguments": [value], "exit_code": 0}]}
        path = self.root / "report.json"
        path.write_text(json.dumps(report))
        return path, parent, bundle

    def test_sources_and_policy_cover_every_declared_profile_without_literal_cases(self):
        fixtures = []
        for language in oracle.LANGUAGES:
            name, text = oracle.source(language)
            self.assertTrue(name and text)
            self.assertTrue(all("domain_" + kind in text for kind in oracle.kinds(language)))
            fixtures.extend((language, kind, [oracle.DOMAINS[kind]]) for kind in oracle.kinds(language))
        path = self.root / "policy.toml"
        qualify_domains.write_policy(path, fixtures)
        frozen = policy.load(path)
        self.assertEqual(len(frozen["fixtures"]), 30)
        self.assertTrue(all("cases" not in row for row in frozen["fixtures"]))
        self.assertEqual(sum(len(oracle.arguments(language, kind))
            for language in oracle.LANGUAGES for kind in oracle.kinds(language)), 82)

    def test_known_scalar_labels_bits_and_string_units_are_literal(self):
        self.assertEqual(oracle.typed("c", "boolean", True),
                         {"kind": "boolean", "type": "c._Bool", "value": True})
        self.assertEqual(oracle.typed("java", "float", 0.1),
                         {"kind": "float", "type": "java.float", "bits": "3dcccccd"})
        self.assertEqual(oracle.typed("go", "string", "\u03bb"),
                         {"kind": "string", "type": "go.string", "encoding": "raw_bytes", "value": "cebb"})
        self.assertEqual(oracle.typed("python", "string", "\u03bb")["value"], "000003bb")
        self.assertEqual(oracle.typed("javascript", "string", "\u03bb")["value"], "03bb")

    def test_complete_oracle_accepts_every_repeat_and_no_more(self):
        path, _, _ = self.report()
        self.assertEqual(len(oracle.check_report(path, count=1)), 4)
        with self.assertRaises(AssertionError):
            oracle.check_report(path, count=2)

    def test_java_primitive_float_label_is_preserved_and_boxed_substitution_is_rejected(self):
        path, parent, bundle = self.report("java", "float")
        for lane in ("baseline", "instrumented_on"):
            for index, attempt in enumerate(bundle[lane]):
                observed = attempt["observation"]
                observed["outcome"]["graph"]["roots"]["result"]["type"] = "java.float"
                (parent / (lane + "-" + str(index)) / "typed-observation.json").write_text(json.dumps(observed))
        (parent / "typed-bundle.json").write_text(json.dumps({"cases": [bundle]}))
        self.assertEqual(len(oracle.check_report(path, count=1)), 4)
        for lane in ("baseline", "instrumented_on"):
            for index, attempt in enumerate(bundle[lane]):
                observed = attempt["observation"]
                observed["outcome"]["graph"]["roots"]["result"]["type"] = "java.lang.Float"
                (parent / (lane + "-" + str(index)) / "typed-observation.json").write_text(json.dumps(observed))
        (parent / "typed-bundle.json").write_text(json.dumps({"cases": [bundle]}))
        with self.assertRaises(AssertionError):
            oracle.check_report(path, count=1)

    def test_equal_but_wrong_results_are_rejected_in_both_lanes(self):
        path, parent, bundle = self.report()
        for lane in ("baseline", "instrumented_on"):
            for index, attempt in enumerate(bundle[lane]):
                observed = attempt["observation"]
                observed["outcome"]["graph"]["roots"]["result"]["value"] = "999"
                (parent / (lane + "-" + str(index)) / "typed-observation.json").write_text(json.dumps(observed))
        (parent / "typed-bundle.json").write_text(json.dumps({"cases": [bundle]}))
        with self.assertRaises(AssertionError):
            oracle.check_report(path, count=1)

    def test_missing_witness_and_raw_output_changes_cannot_pass(self):
        path, parent, bundle = self.report()
        altered = copy.deepcopy(bundle)
        altered["instrumented_on"][0]["execution"]["witness"]["spans"] = 0
        (parent / "typed-bundle.json").write_text(json.dumps({"cases": [altered]}))
        with self.assertRaises(AssertionError):
            oracle.check_report(path, count=1)
        (parent / "typed-bundle.json").write_text(json.dumps({"cases": [bundle]}))
        (parent / "baseline-0/stdout").write_bytes(b"unexpected application output")
        with self.assertRaises(AssertionError):
            oracle.check_report(path, count=1)

    def test_probe_is_an_explicit_stable_difference_not_an_invalid_baseline(self):
        baseline = oracle.graph("python", "probe", 32, returned=True, lane="baseline")
        instrumented = oracle.graph("python", "probe", 32, returned=True, lane="instrumented_on")
        self.assertEqual(baseline["roots"]["result"]["value"], "0")
        self.assertEqual(instrumented["roots"]["result"]["value"], "1")
        self.assertEqual(oracle.graph("python", "probe", 0, returned=True, lane="instrumented_on")
                         ["roots"]["result"]["value"], "0")

    def finish_inputs(self) -> tuple[Path, Path, Path]:
        cli = self.root / "cli"
        cli.write_bytes(b"frozen CLI identity")
        workspace = self.root / "workspace"
        workspace.mkdir()
        folder = self.root / "results"
        source = folder / "application/app.py"
        source.parent.mkdir(parents=True)
        source.write_bytes(b"def selected():return 7\n")
        (workspace / "plan.json").write_text(json.dumps({
            "source_manifest": {"app.py": hashlib.sha256(source.read_bytes()).hexdigest()}}))
        return cli, workspace, folder

    def test_final_presentation_accepts_deliberate_differences_without_relaunching_cases(self):
        cli, workspace, folder = self.finish_inputs()
        attempts = {"retained-attempt-0", "retained-attempt-1"}
        with patch.object(qualify_domains, "command") as command:
            result = qualify_domains.finish(cli, workspace, folder, attempts, 14)
        self.assertEqual([call.args[0][1] for call in command.call_args_list], ["export-tests", "render-report"])
        self.assertNotIn("--apply", command.call_args_list[0].args[0])
        self.assertEqual(command.call_args_list[1].kwargs.get("expected", 0), 1)
        self.assertEqual(result["actual_attempt_directories"], sorted(attempts))
        self.assertEqual(result["qualified_application_launches"], 2)
        self.assertEqual(json.loads((folder / "qualification.json").read_text()), result)

    def test_finalisation_refuses_changed_application_sources_before_presentation(self):
        cli, workspace, folder = self.finish_inputs()
        (folder / "application/app.py").write_text("def selected():return 99\n")
        with patch.object(qualify_domains, "command") as command:
            with self.assertRaises(AssertionError):
                qualify_domains.finish(cli, workspace, folder, {"retained-attempt"}, 14)
        command.assert_not_called()
        self.assertFalse((folder / "qualification.json").exists())


if __name__ == "__main__":
    unittest.main()
