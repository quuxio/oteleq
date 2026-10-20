"""Synthetic route tests; actual SDK evidence is qualified separately."""
from contextlib import redirect_stderr, redirect_stdout
import copy
import hashlib
import io
import json
import os
from pathlib import Path
import tempfile
import unittest
from unittest.mock import MagicMock, patch

from effect_qualification import EffectQualification


def write(path: Path, value: object) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(value))


class EffectRouteTests(unittest.TestCase):
    def setUp(self):
        self.temporary = tempfile.TemporaryDirectory()
        self.addCleanup(self.temporary.cleanup)
        self.base = Path(self.temporary.name).resolve()
        self.provider = self.base / "provider"; self.provider.mkdir()
        self.cli = self.base / "cli"; self.cli.write_text("fixture CLI")
        self.runner = EffectQualification(MagicMock(), MagicMock(return_value=4),
            "http:service", "match", "difference", ("controls.json", "effect.json"), "fixture scope")

    def test_literal_return_witness_and_difference_oracles_refuse_alterations(self):
        attempt = {"execution": {"channels": {"stdout": [], "stderr": []}},
                   "observation": {"outcome": {"kind": "return", "graph": {"roots": {"result": {"kind": "integer", "value": "7"}}}}}}
        self.runner.return_seven(attempt)
        attempt["observation"]["outcome"]["graph"]["roots"]["result"] = {"kind": "float", "bits": "401c000000000000"}
        self.runner.return_seven(attempt)
        altered = copy.deepcopy(attempt); altered["execution"]["channels"]["stdout"] = [1]
        with self.assertRaises(AssertionError):
            self.runner.return_seven(altered)
        execution = {"witness": {"functions": {"actual": 1}, "losses": {"lost": 0}}}
        entry, case = {"otelc_runtime_function": "actual"}, {"function": "source"}
        self.runner.witness(execution, entry, case, "baseline")
        self.runner.witness(execution, entry, case, "instrumented_on")
        execution["witness"]["losses"]["lost"] = 1
        with self.assertRaises(AssertionError):
            self.runner.witness(execution, entry, case, "instrumented_on")
        case = {"exit_code": 1, "comparison": {"cases": [{"execution": {"differences": [{"path": "channels.http:service"}]}, "pairs": [{"comparison": {"differences": []}}]}]}}
        self.runner.differences(case)
        case["exit_code"] = 0; self.runner.differences(case)
        case["exit_code"] = 1; case["comparison"]["cases"][0]["pairs"][0]["comparison"]["differences"] = ["different outcome"]
        with self.assertRaises(AssertionError):
            self.runner.differences(case)

    def test_all_initial_routes_and_resume_preserve_evidence_controls(self):
        folder = self.base / "evidence"
        workspace = folder / "cases/retained"
        def prepare(*_):
            write(workspace / "plan.json", {"otelc_root": str(self.provider)})
            return workspace
        def execute(args, destination, name, **options):
            text = ""
            if name == "run":
                cases = [{"case": str(i), "function": "effect_match"} for i in range(8)] + [{"case": "other", "function": "effect_difference"}]
                write(folder / "comparison/report.json", {"cases": cases})
                for case in cases[:8]:
                    write(folder / "comparison" / case["case"] / "typed-bundle.json",
                          {"cases": [{"instrumented_on": [{"execution": {"channels": {"http:service": [1]}, "capture_complete": True}}]}]})
            elif name.startswith("control-"):
                altered = json.loads(Path(args[2]).read_text())["cases"][0]["instrumented_on"][0]["execution"]
                self.assertTrue("http:service" not in altered["channels"] or not altered["capture_complete"])
                self.assertEqual(options["expected"], 3)
            elif name in ("framework", "export-framework"):
                text = '\n'.join(json.dumps({"report": str(folder / f"{name}-{i}/report.json")}) for i in range(18))
            elif name == "export":
                write(folder / "exported/plan.json", {})
            elif name == "export-run":
                write(folder / "export-comparison/report.json", {})
            (destination / (name + ".stdout")).write_text(text)
            return text
        self.runner.prepare = prepare
        self.runner.command = MagicMock(side_effect=execute)
        with redirect_stdout(io.StringIO()):
            result = self.runner.retained_workflows(self.cli, self.provider, folder, False)
        self.assertEqual(result, (workspace, folder / "exported", 152, 16))
        original = (folder / "comparison/0/typed-bundle.json").read_bytes()
        self.runner.command.reset_mock()
        self.assertEqual(self.runner.retained_workflows(self.cli, self.provider, folder, True), result)
        self.assertEqual((folder / "comparison/0/typed-bundle.json").read_bytes(), original)
        names = [call.args[2] for call in self.runner.command.call_args_list]
        self.assertEqual(len(names), 17)
        self.assertEqual(names[0], "resume-identity-check")
        self.assertTrue(all(name.startswith("control-") for name in names[1:]))

    def test_reduction_and_resume_keep_original_trial_framework_and_replay_reports(self):
        case = {"case": "case", "function": "effect_difference"}
        target = self.base / "shrink-case"
        def execute(args, folder, name, **_):
            if name.startswith("shrink-"):
                write(target / "shrink.json", {"status": "candidate_rule_minimal", "reduced_arguments": [1],
                    "workspace": str(self.base / "reduced"), "trials": [{"report": str(target / "trial/report.json")}]})
                text = ""
            else:
                text = json.dumps({"report": str(self.base / name / "report.json")})
            (folder / (name + ".stdout")).write_text(text)
            return text
        self.runner.command = MagicMock(side_effect=execute)
        with redirect_stdout(io.StringIO()):
            first = self.runner.reduce_case(self.cli, self.base / "workspace", self.base, case, False)
            self.runner.command.reset_mock()
            repeated = self.runner.reduce_case(self.cli, self.base / "workspace", self.base, case, True)
        self.assertEqual(first, repeated)
        self.assertEqual(first, (20, {"function": "effect_difference", "arguments": [1]}))
        self.runner.command.assert_not_called()

    def test_summary_counts_unique_launches_and_refuses_changed_sources(self):
        source = self.base / "application"; source.mkdir()
        (source / "input").write_bytes(b"original")
        plan = {"source": str(source), "source_manifest": {"input": hashlib.sha256(b"original").hexdigest()}}
        workspace, exported = self.base / "workspace", self.base / "exported"
        for path in (workspace, exported):write(path / "plan.json", plan)
        write(self.base / "comparison/report.json", {"cases": [{"case": str(i), "function": "effect_difference"} for i in range(8)] + [{"function": "effect_match"}]})
        for i in range(8):
            write(self.base / str(i) / "command.json", ["application", str(i)])
            write(self.base / str(i) / "http-capture.json", {})
        self.runner.retained_workflows = MagicMock(return_value=(workspace, exported, 0, 16))
        self.runner.reduce_case = MagicMock(return_value=(1, {"arguments": [1]}))
        result = self.runner.run(self.cli, self.provider, self.base, True)
        self.assertEqual(result["actual_application_launches"], 8)
        self.assertEqual(result["same_return_http_difference_cases"], 8)
        self.assertTrue(result["source_preserved"])
        (source / "input").write_bytes(b"changed")
        with self.assertRaises(AssertionError):
            self.runner.run(self.cli, self.provider, self.base, True)

    def test_cli_writes_summary_and_refuses_a_provider_output_directory(self):
        folder = self.base / "report"
        def run(*_):
            folder.mkdir()
            return {"claim": "fixture"}
        self.runner.run = MagicMock(side_effect=run)
        args = ["--cli", str(self.cli), "--otelc-root", str(self.provider), "--report-dir", str(folder)]
        with patch.dict(os.environ), redirect_stdout(io.StringIO()):
            self.runner.main(args)
        self.assertEqual(json.loads((folder / "QUALIFICATION.json").read_text()), {"claim": "fixture"})
        forbidden = args[:-1] + [str(self.provider / "report")]
        self.runner.run.reset_mock()
        with redirect_stderr(io.StringIO()), self.assertRaises(SystemExit):
            self.runner.main(forbidden)
        self.runner.run.assert_not_called()
