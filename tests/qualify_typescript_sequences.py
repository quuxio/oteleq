"""Qualify original TypeScript collection identities through both explicit emitters."""
import argparse
import hashlib
import json
import os
from pathlib import Path
import sys
import tomllib

import qualify_sequences as shared

CASES = {
    "identity.ts": ("identity", "Counter", "typescript", 0),
    "async_factory.mts": ("later", "make", "typescript", 0),
    "identity_cts.cts": ("identity", "Counter", "typescript", 0),
    "expected_error.cts": ("fail", "Counter", "typescript", 0),
    "finalized.ts": ("identity", "Counter", "typescript", 0),
    "transient.mts": ("transient", "Counter", "typescript", 1),
    "retained.cts": ("identity", "Counter", "typescript", 3),
}
OPTIONS = {"cases": CASES, "collection_languages": ("typescript",)}


def check_report(path: Path, backend: str, count: int = 7) -> int:
    """Check literal application oracles plus actual frozen emitter/probe controls."""
    launches = shared.check_report(path, count, **OPTIONS)
    report = json.loads(path.read_text())
    inventory = {item["otelc_function"]: item for item in report["inventory"]}
    for case in report["cases"]:
        entry = inventory[case["function"]]
        assert entry["typescript_backend"] == backend
        probe = entry["typescript_provider"]
        assert probe["status"] == 0 and probe["resolved"]["backend"] == backend
        assert probe["resolved"]["language"] == "typescript" and probe["resolved"]["execution_available"] is True
        assert probe["resolved"]["lifetimes"]["include"] == [entry["node_class_label"]]
        for lane in ("baseline", "instrumented_on"):
            for index in range(2):
                folder = path.parent / case["case"] / (lane + "-" + str(index))
                controls = json.loads((folder / "typescript-controls.json").read_text())
                assert controls["OTELC_TYPESCRIPT_BACKEND"] == backend and controls["provider"] == probe
                policy = tomllib.loads((folder / "policy.toml").read_text())
                assert policy["adapters"]["typescript"]["backend"] == backend
                assert policy["lifetimes"]["include"] == [entry["node_class_label"]]
    return launches


def framework(workspace: Path, folder: Path, name: str, backend: str, count: int = 7) -> int:
    summaries = shared.command([sys.executable, workspace / "tests/test_equivalence.py"], folder, name, expected=1)
    reports = [json.loads(line) for line in summaries.splitlines()]
    assert len(reports) == count
    return sum(check_report(Path(row["report"]), backend, 1) for row in reports)


def unsupported_provider(cli: Path, provider: Path, workspace: Path, folder: Path, backend: str) -> dict:
    """An older actual provider must refuse the requested policy before application launch."""
    plan = json.loads((workspace / "plan.json").read_text())
    config = folder / "cases/equivalence.toml"
    refused = Path(shared.command([cli, "plan", "--source", plan["source"], "--otelc-root", provider,
                                  "--workspace-parent", folder, "--config", config], folder, "unsupported-plan"))
    data = json.loads((refused / "plan.json").read_text())
    selected = [item for item in data["inventory"] if item["status"] != "excluded"]
    assert len(selected) == 7 and all(item["status"] == "blocked" for item in selected)
    for entry in selected:
        probe = entry["typescript_provider"]
        assert probe["status"] == 1 and json.loads(probe["stdout"])["execution_available"] is False
        assert entry["typescript_backend"] == backend and "cannot execute" in entry["reason"]
    shared.command([cli, "generate", "--workspace", refused], folder, "unsupported-generate")
    shared.command([cli, "run", "--workspace", refused, "--report-dir", folder / "unsupported-comparison"], folder, "unsupported-run", expected=3)
    report = json.loads((folder / "unsupported-comparison/report.json").read_text())
    assert not report["cases"] and len(report["blocked"]) == 7 and report["source_preserved"]
    assert not list((folder / "unsupported-comparison").rglob("observation"))
    return {"backend": backend, "selected_blocked": 7, "application_launches": 0}


def qualify(cli: Path, provider: Path, unsupported: Path, folder: Path, backend: str) -> dict:
    folder.mkdir()
    workspace = shared.prepare(cli, provider, folder / "cases", typescript_backend=backend, **OPTIONS)
    refusal = unsupported_provider(cli, unsupported, workspace, folder, backend)
    shared.command([cli, "run", "--workspace", workspace, "--report-dir", folder / "comparison"], folder, "run", expected=3)
    launches = check_report(folder / "comparison/report.json", backend)
    controls = shared.evidence_controls(cli, folder / "comparison/report.json", folder)
    report = json.loads((folder / "comparison/report.json").read_text())
    original = next(item for item in report["cases"] if item["function"] == "identity.Counter.identity")
    shared.source_control(cli, workspace, folder, original, source_name="identity.ts")
    launches += framework(workspace, folder, "framework", backend)
    exported = folder / "exported"
    shared.command([cli, "export-tests", "--workspace", workspace, "--destination", exported, "--apply"], folder, "export")
    shared.command([cli, "run", "--workspace", exported, "--report-dir", folder / "export-comparison"], folder, "export-run", expected=3)
    launches += check_report(folder / "export-comparison/report.json", backend)
    launches += framework(exported, folder, "export-framework", backend)
    target = next(item for item in report["cases"] if item["function"] == "transient.Counter.transient")
    shared.command([cli, "shrink", "--workspace", workspace, "--case", target["case"], "--report-dir", folder / "shrink", "--trials", "1"], folder, "shrink", expected=1)
    shrink = json.loads((folder / "shrink/shrink.json").read_text())
    assert shrink["reduced_arguments"] == [0] and shrink["status"] == "candidate_rule_minimal"
    for path in [folder / "shrink/original/report.json", folder / "shrink/confirmation/report.json", *[Path(row["report"]) for row in shrink["trials"]]]:
        launches += check_report(path, backend, 1)
    reduced = Path(shrink["workspace"])
    launches += framework(reduced, folder, "reduced-framework", backend, 1)
    replay = json.loads(shared.command([cli, "replay", "--workspace", reduced, "--case", target["case"]], folder, "replay", expected=1))
    launches += check_report(Path(replay["report"]), backend, 1)
    assert launches == 132
    for path in (workspace, exported, reduced):
        plan = json.loads((path / "plan.json").read_text())
        assert all(hashlib.sha256((Path(plan["source"]) / name).read_bytes()).hexdigest() == sha for name, sha in plan["source_manifest"].items())
    return {"backend": backend, "cases": 7, "matching_cases": 5, "transient_difference_controls": 1,
            "retained_collection_inconclusive_controls": 1, "actual_application_launches": launches,
            "evidence_refusal_controls": controls, "prelaunch_source_refusals": 1, "old_provider_refusal": refusal,
            "source_preserved": True}


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--otelc-root", type=Path, required=True)
    parser.add_argument("--unsupported-otelc-root", type=Path, required=True)
    parser.add_argument("--report-dir", type=Path, required=True)
    parser.add_argument("--cli", type=Path, required=True)
    args = parser.parse_args()
    cli, provider, unsupported = args.cli.resolve(strict=True), args.otelc_root.resolve(strict=True), args.unsupported_otelc_root.resolve(strict=True)
    folder = args.report_dir.resolve()
    if any(folder.is_relative_to(path) for path in (provider, unsupported, Path(__file__).resolve().parents[1])):
        parser.error("qualification directory must be new and outside all repositories")
    folder.mkdir(mode=0o700)
    os.environ.update(OTELEQ_PYTHON=sys.executable, OTELEQ_CLI=str(cli))
    results = [qualify(cli, provider, unsupported, folder / backend, backend) for backend in ("source", "native")]
    result = {"claim": "equivalence over these tests and observations", "artefact_class": "diagnostic",
              "cli_sha256": hashlib.sha256(cli.read_bytes()).hexdigest(), "results": results,
              "actual_application_launches": sum(item["actual_application_launches"] for item in results),
              "source_preserved": True,
              "scope": "Ordinary source-bound TypeScript receivers and original collection roots through explicit source/native emitters; ts/mts/cts, factories, awaited methods, transient mutation, errors, finalizers, retained objects, generated/exported suites and scalar replay; no timing/leak/shipping proof."}
    (folder / "QUALIFICATION.json").write_text(json.dumps(result, indent=2) + "\n")
    print(json.dumps(result), flush=True)


if __name__ == "__main__":
    main()
