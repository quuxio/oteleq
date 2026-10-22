"""Qualify generated domains through actual eight-language retained workflows."""
import argparse
import hashlib
import json
import os
from pathlib import Path
import sys

from domain_fixture_oracle import DOMAINS, arguments, check_report, kind_of, kinds, source
from qualify_generation import command
from qualify_returns import LANGUAGES, toml_value

CASES = 82


def write_policy(path: Path, fixtures: list[tuple], *, budget=3, seed=123) -> None:
    """The fixture file contains domains and deliberately no literal cases."""
    text = ("schema_version=1\nlanguages=" + json.dumps(list(dict.fromkeys(row[0] for row in fixtures)))
            + "\n[generation]\nseed=" + str(seed) + "\ncases_per_function=" + str(budget)
            + "\n[functions]\ninclude=" + json.dumps(list(dict.fromkeys("*domain_" + row[1] + "*" for row in fixtures))) + "\n")
    for language, kind, domains in fixtures:
        text += ("\n[[fixtures]]\nlanguage=" + json.dumps(language)
                 + "\nfunction=" + json.dumps("*domain_" + kind + "*")
                 + "\ndomains=[" + ",".join(toml_value(value) for value in domains) + "]\n")
    path.write_text(text)


def prepare(cli: Path, provider: Path, folder: Path) -> Path:
    """Create one mixed tree and assert every generated request independently."""
    application = folder / "application"
    application.mkdir()
    fixtures = []
    for language in LANGUAGES:
        name, text = source(language)
        target = application / language / name
        target.parent.mkdir()
        target.write_text(text)
        fixtures.extend((language, kind, [DOMAINS[kind]]) for kind in kinds(language))
    write_policy(folder / "policy.toml", fixtures)
    workspace = Path(command([cli, "plan", "--source", application, "--otelc-root", provider,
        "--workspace-parent", folder, "--config", folder / "policy.toml"], folder, "plan"))
    data = json.loads((workspace / "plan.json").read_text())
    ready = [entry for entry in data["inventory"] if entry["status"] == "ready"]
    assert len(ready) == 30 and not any(entry["status"] == "blocked" for entry in data["inventory"])
    assert all("cases" not in item for item in data["configuration"]["fixtures"])
    for entry in ready:
        kind = kind_of(entry)
        assert entry["input_cases"] == [[value] for value in arguments(entry["language"], kind)]
    command([cli, "generate", "--workspace", workspace], folder, "generate")
    corpus = json.loads((workspace / "tests/corpus.json").read_text())
    assert len(corpus) == CASES and all("arguments_requested" in case for case in corpus)
    return workspace


def direct(cli: Path, workspace: Path, folder: Path, name: str, *, resume: bool) -> set[str]:
    """Completed retained routes are rechecked rather than launched twice."""
    destination = folder / name
    if not resume or not (destination / "report.json").is_file():
        if destination.exists():
            raise ValueError("incomplete route must be retained separately: " + str(destination))
        command([cli, "run", "--workspace", workspace, "--report-dir", destination], folder, name, expected=1, timeout=3600)
    return check_report(destination / "report.json", count=CASES)


def framework(workspace: Path, folder: Path, name: str, *, resume: bool, count=CASES,
              expected_arguments=None) -> set[str]:
    """Every generated test is executed, including the two deliberate differences."""
    stdout = folder / (name + ".stdout")
    output = stdout.read_text() if resume and stdout.is_file() else command(
        [sys.executable, workspace / "tests/test_equivalence.py"], folder, name, expected=1, timeout=3600)
    summaries = [json.loads(line) for line in output.splitlines()]
    assert len(summaries) == count
    attempts = set()
    for summary in summaries:
        observed = check_report(Path(summary["report"]), count=1, expected_arguments=expected_arguments)
        assert attempts.isdisjoint(observed)
        attempts.update(observed)
    return attempts


def routes(cli: Path, provider: Path, folder: Path, *, resume: bool) -> tuple[Path, set[str]]:
    """Preserve direct, generated, detached-direct and detached-generated evidence."""
    workspace = Path((folder / "plan.stdout").read_text().strip()) if resume else prepare(cli, provider, folder)
    data = json.loads((workspace / "plan.json").read_text())
    if Path(data["otelc_root"]).resolve() != provider or Path(data["source"]).resolve() != folder / "application":
        raise ValueError("qualification source or provider differs from the retained plan")
    expected = {}
    for language in LANGUAGES:
        name, text = source(language)
        expected[language + "/" + name] = hashlib.sha256(text.encode()).hexdigest()
    if data["source_manifest"] != expected:
        raise ValueError("retained source is not this qualifier's fixed fixture")
    command([cli, "export-tests", "--workspace", workspace, "--destination", folder / "identity-check"], folder, "identity-check")
    attempts = direct(cli, workspace, folder, "comparison", resume=resume)
    attempts |= framework(workspace, folder, "framework", resume=resume)
    exported = folder / "exported"
    if not exported.exists():
        command([cli, "export-tests", "--workspace", workspace, "--destination", exported, "--apply"], folder, "export")
    offline, application = folder / "application-offline", folder / "application"
    application.rename(offline)
    try:
        detached = direct(cli, exported, folder, "detached-comparison", resume=resume)
        generated = framework(exported, folder, "detached-framework", resume=resume)
        assert attempts.isdisjoint(detached | generated) and detached.isdisjoint(generated)
        attempts |= detached | generated
    finally:
        offline.rename(application)
    assert len(attempts) == CASES * 16
    return workspace, attempts


def refusal(cli: Path, provider: Path, folder: Path, name: str, fixtures: list[tuple],
            expected_reason: str, *, budget=3) -> None:
    """A blocked domain contract fails both the public run and generated suite."""
    policy = folder / (name + ".toml")
    write_policy(policy, fixtures, budget=budget)
    workspace = Path(command([cli, "plan", "--source", folder / "application", "--otelc-root", provider,
        "--workspace-parent", folder, "--config", policy], folder, name + "-plan"))
    data = json.loads((workspace / "plan.json").read_text())
    selected = [entry for entry in data["inventory"] if entry["status"] != "excluded"]
    assert len(selected) == 1 and selected[0]["status"] == "blocked" and selected[0]["reason"]
    assert expected_reason in selected[0]["reason"], selected[0]["reason"]
    command([cli, "generate", "--workspace", workspace], folder, name + "-generate")
    assert json.loads((workspace / "tests/corpus.json").read_text()) == []
    command([cli, "run", "--workspace", workspace, "--report-dir", folder / (name + "-report")],
            folder, name + "-run", expected=3)
    report = json.loads((folder / (name + "-report/report.json")).read_text())
    assert report["cases"] == [] and report["source_preserved"] and len(report["blocked"]) == 1
    assert not list((folder / (name + "-report")).rglob("typed-observation.json"))
    output = command([sys.executable, workspace / "tests/test_equivalence.py"], folder, name + "-suite", expected=1)
    assert output == ""
    failure = (folder / (name + "-suite.stderr")).read_text()
    assert selected[0]["reason"] in failure and "Ran 1 test" in failure


def refusal_controls(cli: Path, provider: Path, folder: Path) -> int:
    """Exercise argument arity, empty float32 intervals and byte-budget refusals."""
    for language in LANGUAGES:
        refusal(cli, provider, folder, "arity-" + language,
                [(language, "integer", [DOMAINS["integer"]] * 2)], "argument count")
    for language in ("c", "cpp", "rust", "java", "go"):
        refusal(cli, provider, folder, "unrepresentable-" + language,
                [(language, "float", [{"kind": "float", "minimum": 1.3, "maximum": 1.3}])], "representable")
    refusal(cli, provider, folder, "input-budget",
            [("python", "string", [{**DOMAINS["string"], "minimum_length": 4096, "maximum_length": 4096}])],
            "byte budget", budget=1024)
    return 14


def frozen_replay(cli: Path, workspace: Path, folder: Path) -> set[str]:
    """Changing the original external policy cannot resample a frozen corpus."""
    data = json.loads((workspace / "plan.json").read_text())
    target = next(entry for entry in data["inventory"] if entry["language"] == "rust" and "domain_float" in entry["name"])
    case = next(item for item in json.loads((workspace / "tests/corpus.json").read_text())
                if item["function_id"] == target["id"])
    policy = folder / "policy.toml"
    original = policy.read_bytes()
    policy.write_text("this is not a new valid policy\n")
    try:
        text = command([cli, "replay", "--workspace", workspace, "--case", case["id"]], folder, "frozen-replay")
        return check_report(Path(json.loads(text)["report"]), count=1)
    finally:
        policy.write_bytes(original)


def reduce_case(cli: Path, workspace: Path, folder: Path) -> set[str]:
    """Retain a real telemetry-sensitive difference and reduce it to seven."""
    data = json.loads((workspace / "plan.json").read_text())
    target = next(entry for entry in data["inventory"] if entry["language"] == "python" and "domain_probe" in entry["name"])
    case = next(item for item in json.loads((workspace / "tests/corpus.json").read_text())
                if item["function_id"] == target["id"] and item["arguments"] == [32])
    before = set(workspace.rglob("typed-observation.json"))
    command([cli, "shrink", "--workspace", workspace, "--case", case["id"],
             "--report-dir", folder / "shrink", "--trials", "32"], folder, "shrink", expected=1, timeout=1800)
    summary = json.loads((folder / "shrink/shrink.json").read_text())
    assert summary["reduced_arguments"] == [7] and summary["status"] == "candidate_rule_minimal"
    assert summary["source_preserved"] and summary["incomplete_trials"] == 0
    added = set(workspace.rglob("typed-observation.json")) - before
    original_reports = {path.parent.parent.parent / "report.json" for path in added}
    assert len(added) == 4 and len(original_reports) == 1
    original = next(iter(original_reports))
    attempts = check_report(original, count=1)
    assert (folder / "shrink/original/report.json").read_bytes() == original.read_bytes()
    for trial in summary["trials"]:
        arguments_ = trial["arguments"]
        assert len(arguments_) == 1 and type(arguments_[0]) is int and 0 <= arguments_[0] <= 32
        attempts |= check_report(Path(trial["report"]), count=1, expected_arguments=arguments_)
    attempts |= check_report(folder / "shrink/confirmation/report.json", count=1, expected_arguments=[7])
    reduced = folder / "reduced-export"
    command([cli, "export-tests", "--workspace", summary["workspace"], "--destination", reduced, "--apply"], folder, "reduced-export")
    attempts |= framework(reduced, folder, "reduced-suite", resume=False, count=1, expected_arguments=[7])
    return attempts


def seeded(cli: Path, provider: Path, folder: Path) -> set[str]:
    """Independently fixed seed-seven values exercise actual non-edge samples."""
    policy = folder / "seeded.toml"
    write_policy(policy, [("python", "integer", [{"kind": "integer", "minimum": -100, "maximum": 100}])], budget=8, seed=7)
    workspace = Path(command([cli, "plan", "--source", folder / "application", "--otelc-root", provider,
        "--workspace-parent", folder, "--config", policy], folder, "seeded-plan"))
    data = json.loads((workspace / "plan.json").read_text())
    entry = next(item for item in data["inventory"] if item["status"] == "ready")
    expected = [0, -100, 100, -18, -62, 1, 66, -88]
    assert entry["input_cases"] == [[value] for value in expected]
    command([cli, "generate", "--workspace", workspace], folder, "seeded-generate")
    command([cli, "run", "--workspace", workspace, "--report-dir", folder / "seeded-report"], folder, "seeded-run")
    return check_report(folder / "seeded-report/report.json", count=8, expected_arguments=expected)


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--cli", type=Path, required=True)
    parser.add_argument("--otelc-root", type=Path, required=True)
    parser.add_argument("--report-dir", type=Path, required=True)
    parser.add_argument("--resume", action="store_true")
    args = parser.parse_args()
    cli, provider, folder = args.cli.resolve(strict=True), args.otelc_root.resolve(strict=True), args.report_dir.resolve()
    if any(folder.is_relative_to(root) for root in (provider, Path(__file__).resolve().parents[1])):
        raise ValueError("qualification output must be outside provider and implementation sources")
    if not args.resume:
        folder.mkdir(mode=0o700, exist_ok=False)
    os.environ.update(OTELEQ_PYTHON=sys.executable, OTELEQ_CLI=str(cli), PYTHONDONTWRITEBYTECODE="1", PYTHONOPTIMIZE="0")
    workspace, attempts = routes(cli, provider, folder, resume=args.resume)
    assert not (folder / "post-routes-started").exists(), "resume supports completed initial routes only"
    (folder / "post-routes-started").write_text("Later controls and reduction must not be silently repeated.\n")
    count = refusal_controls(cli, provider, folder)
    for more in (frozen_replay(cli, workspace, folder), reduce_case(cli, workspace, folder), seeded(cli, provider, folder)):
        assert attempts.isdisjoint(more)
        attempts |= more
    original = json.loads((workspace / "plan.json").read_text())
    for name, expected in original["source_manifest"].items():
        assert hashlib.sha256((folder / "application" / name).read_bytes()).hexdigest() == expected
    command([cli, "export-tests", "--workspace", workspace, "--destination", folder / "final-identity-check"],
            folder, "final-identity-check")
    command([cli, "render-report", folder / "comparison/report.json", "--output-dir", folder / "presentation"], folder, "render")
    result = {"claim": "equivalence over these tests and observations", "artefact_class": "diagnostic",
              "cli_sha256": hashlib.sha256(cli.read_bytes()).hexdigest(),
              "driver_sha256": hashlib.sha256(Path(__file__).read_bytes()).hexdigest(),
              "oracle_sha256": hashlib.sha256(Path(__file__).with_name("domain_fixture_oracle.py").read_bytes()).hexdigest(),
              "languages": list(LANGUAGES), "selected_functions": 30, "initial_cases": CASES,
              "qualified_application_launches": len(attempts), "prelaunch_refusal_controls": count,
              "complete_literal_graph_oracles": True, "source_preserved": True,
              "actual_attempt_directories": sorted(attempts),
              "limits": "Recorded legacy diagnostic profiles; strings supported in five languages. Probe intentionally observes telemetry. No shipping equivalence."}
    (folder / "qualification.json").write_text(json.dumps(result, indent=2) + "\n")
    print(json.dumps({key: value for key, value in result.items() if key != "actual_attempt_directories"}), flush=True)


if __name__ == "__main__":
    main()

