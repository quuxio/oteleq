"""Shared execution and evidence checks for the eight-language effect corpora."""
import argparse
from collections import defaultdict
from collections.abc import Callable
import copy
from dataclasses import dataclass
import hashlib
import json
import os
from pathlib import Path
import struct
import sys

from qualify_generation import command


@dataclass
class EffectQualification:
    """Keep protocol oracles separate from identical execution/replay routes."""

    prepare: Callable[[Path, Path, Path], Path]
    check_report: Callable[..., int]
    channel: str
    match_name: str
    difference_name: str
    sidecars: tuple[str, ...]
    scope: str
    command: Callable[..., str] = command

    def actual_attempt(self, folder: Path, case_id: str) -> tuple[Path, Path]:
        """A copied original keeps its actual command, directory and bindings."""
        cwd = Path(json.loads((folder / "working-directory.json").read_text()))
        assert cwd.name == "project"
        actual = cwd.parent
        assert actual.name == folder.name and actual.parent.name == case_id
        if actual.resolve() != folder.resolve():
            assert folder.parent.parent.name == "original"
            assert actual.resolve().is_relative_to(folder.parents[3].resolve())
            for name in ("command.json", "working-directory.json", "typed-observation.json", "http-capture.json", *self.sidecars):
                assert (actual / name).read_bytes() == (folder / name).read_bytes(), name
        return cwd, actual

    @staticmethod
    def return_seven(attempt: dict) -> None:
        """Verify the literal return oracle, independently of lane agreement."""
        execution, observation = attempt["execution"], attempt["observation"]
        value = observation["outcome"]["graph"]["roots"]["result"]
        actual = struct.unpack('>d', bytes.fromhex(value["bits"]))[0] if value["kind"] == "float" else int(value["value"])
        assert actual == 7 and observation["outcome"]["kind"] == "return"
        assert execution["channels"]["stdout"] == execution["channels"]["stderr"] == []

    @staticmethod
    def witness(execution: dict, entry: dict, case: dict, lane: str) -> None:
        if lane == "instrumented_on":
            assert execution["witness"]["functions"] == {entry.get("otelc_runtime_function", case["function"]): 1}
            assert not any(execution["witness"]["losses"].values())

    def differences(self, case: dict) -> None:
        if case["exit_code"] == 1:
            compared = case["comparison"]["cases"][0]
            assert {item["path"] for item in compared["execution"]["differences"]} == {"channels." + self.channel}
            assert all(not pair["comparison"]["differences"] for pair in compared["pairs"])

    def framework(self, workspace: Path, folder: Path, name: str, count: int = 18, *, resume: bool = False) -> int:
        retained = folder / (name + ".stdout")
        text = retained.read_text() if resume and retained.is_file() else self.command([sys.executable, workspace / "tests/test_equivalence.py"], folder, name, expected=1)
        reports = [json.loads(line) for line in text.splitlines()]
        assert len(reports) == count
        return sum(self.check_report(Path(row["report"]), 1) for row in reports)

    def evidence_controls(self, cli: Path, folder: Path) -> int:
        report = json.loads((folder / "comparison/report.json").read_text())
        controls = 0
        for case in report["cases"]:
            if self.match_name not in case["function"]:
                continue
            original = json.loads((folder / "comparison" / case["case"] / "typed-bundle.json").read_text())
            for kind in ("missing", "incomplete"):
                altered = copy.deepcopy(original)
                execution = altered["cases"][0]["instrumented_on"][0]["execution"]
                if kind == "missing":
                    del execution["channels"][self.channel]
                else:
                    execution["capture_complete"] = False
                name = "control-" + case["case"] + "-" + kind
                path = folder / (name + ".json")
                path.write_text(json.dumps(altered))
                self.command([cli, "compare-observations", path], folder, name, expected=3)
                controls += 1
        assert controls == 16
        return controls

    def retained_workflows(self, cli: Path, provider: Path, folder: Path, resume: bool) -> tuple[Path, Path, int, int]:
        """Resume completed routes without repeating application launches."""
        if resume:
            required = ("comparison/report.json", "framework.stdout", "exported/plan.json", "export-comparison/report.json", "export-framework.stdout")
            if not all((folder / name).is_file() for name in required):
                raise ValueError("resume requires all four completed initial execution routes")
            plans = list((folder / "cases").glob("*/plan.json"))
            assert len(plans) == 1
            assert Path(json.loads(plans[0].read_text())["otelc_root"]).resolve() == provider
            workspace = plans[0].parent
            self.command([cli, "export-tests", "--workspace", workspace, "--destination", folder / "resume-identity-check"], folder, "resume-identity-check")
        else:
            folder.mkdir(mode=0o700)
            workspace = self.prepare(cli, provider, folder / "cases")
            self.command([cli, "run", "--workspace", workspace, "--report-dir", folder / "comparison"], folder, "run", expected=3)
        launches = self.check_report(folder / "comparison/report.json")
        controls = self.evidence_controls(cli, folder)
        launches += self.framework(workspace, folder, "framework", resume=resume)
        exported = folder / "exported"
        if not resume:
            self.command([cli, "export-tests", "--workspace", workspace, "--destination", exported, "--apply"], folder, "export")
            self.command([cli, "run", "--workspace", exported, "--report-dir", folder / "export-comparison"], folder, "export-run", expected=3)
        launches += self.check_report(folder / "export-comparison/report.json")
        launches += self.framework(exported, folder, "export-framework", resume=resume)
        return workspace, exported, launches, controls

    def reduce_case(self, cli: Path, workspace: Path, folder: Path, case: dict, resume: bool) -> tuple[int, dict]:
        target = folder / ("shrink-" + case["case"])
        if not (resume and (target / "shrink.json").is_file()):
            self.command([cli, "shrink", "--workspace", workspace, "--case", case["case"], "--report-dir", target, "--trials", "8"], folder, target.name, expected=1)
        shrink = json.loads((target / "shrink.json").read_text())
        assert shrink["reduced_arguments"] == [1] and shrink["status"] == "candidate_rule_minimal"
        launches = sum(self.check_report(path, 1) for path in [target / "original/report.json", target / "confirmation/report.json", *[Path(row["report"]) for row in shrink["trials"]]])
        reduced = Path(shrink["workspace"])
        launches += self.framework(reduced, folder, "reduced-" + case["case"], 1, resume=resume)
        name = "replay-" + case["case"]
        retained = folder / (name + ".stdout")
        text = retained.read_text() if resume and retained.is_file() else self.command([cli, "replay", "--workspace", reduced, "--case", case["case"]], folder, name, expected=1)
        launches += self.check_report(Path(json.loads(text)["report"]), 1)
        print(json.dumps({"completed_reduction": case["function"], "arguments": shrink["reduced_arguments"], "actual_launches": launches}), flush=True)
        return launches, {"function": case["function"], "arguments": shrink["reduced_arguments"]}

    def run(self, cli: Path, provider: Path, folder: Path, resume: bool) -> dict:
        workspace, exported, launches, controls = self.retained_workflows(cli, provider, folder, resume)
        report = json.loads((folder / "comparison/report.json").read_text())
        reductions = []
        for case in report["cases"]:
            if self.difference_name in case["function"]:
                actual, reduction = self.reduce_case(cli, workspace, folder, case, resume)
                launches += actual
                reductions.append(reduction)
        assert len(reductions) == 8
        identities = defaultdict(list)
        for path in folder.rglob("command.json"):
            if (path.parent / "http-capture.json").is_file():
                identities[hashlib.sha256(path.read_bytes()).hexdigest()].append(str(path.parent))
        assert len(identities) == launches
        for path in (workspace, exported):
            plan = json.loads((path / "plan.json").read_text())
            assert all(hashlib.sha256((Path(plan["source"]) / name).read_bytes()).hexdigest() == sha for name, sha in plan["source_manifest"].items())
        return {"claim": "equivalence over these tests and observations", "artefact_class": "diagnostic",
                "cli_sha256": hashlib.sha256(cli.read_bytes()).hexdigest(), "cases": 18, "matching_cases": 8,
                "same_return_" + self.channel.split(":")[0] + "_difference_cases": 8, "incomplete_effect_cases": 2,
                "actual_application_launches": launches, "source_preserved": True,
                "altered_evidence_controls": controls, "reductions": reductions,
                "raw_attempt_folders": sum(map(len, identities.values())), "unique_command_identities": len(identities),
                "scope": self.scope}

    def main(self, argv: list[str] | None = None) -> None:
        parser = argparse.ArgumentParser(description=self.scope)
        parser.add_argument("--otelc-root", type=Path, required=True)
        parser.add_argument("--report-dir", type=Path, required=True)
        parser.add_argument("--cli", type=Path, required=True)
        parser.add_argument("--resume", action="store_true", help="revalidate retained completed routes/shrinks and continue; never restart an unfinished shrink")
        args = parser.parse_args(argv)
        cli, provider, folder = args.cli.resolve(strict=True), args.otelc_root.resolve(strict=True), args.report_dir.resolve()
        if any(folder.is_relative_to(path) for path in (provider, Path(__file__).resolve().parents[1])):
            parser.error("qualification directory must be new and outside both repositories")
        os.environ.update(OTELEQ_PYTHON=sys.executable, OTELEQ_CLI=str(cli))
        result = self.run(cli, provider, folder, args.resume)
        (folder / "QUALIFICATION.json").write_text(json.dumps(result, indent=2) + "\n")
        print(json.dumps(result), flush=True)
