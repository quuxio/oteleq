"""Qualify in-source retained suites through real eight-language execution."""
import argparse
import hashlib
import json
import os
from pathlib import Path
import sys

from node_project_oracle import number, object_node
from qualify_generation import command
from qualify_returns import LANGUAGES, check_attempt, scalar, source, toml_value


def expected_graph(language: str, *, returned: bool = False) -> dict:
    """Declare all roots and nodes from these simple sources, independently."""
    graph = {"roots": {}, "nodes": []}
    if language == "python":
        graph = {"roots": {"arguments": {"kind": "reference", "node_id": "n0"}},
                 "nodes": [{"id": "n0", "type": "python.builtins.list",
                            "fields": {"item:0": scalar(language, 3)}}]}
    if language in ("javascript", "typescript"):
        graph = {"roots": {"arguments": {"kind": "reference", "node_id": "n0"}},
                 "nodes": [object_node(language, "n0", "ecmascript.array.prototype:Array",
                                       {"0": number(language, 3), "length": number(language, 1)}, array=True)]}
    if returned:
        graph["roots"]["result"] = scalar(language, 7)
    return graph


def check_report(path: Path, exclusions: set[str], count: int = 8) -> set[str]:
    """Check literal full graphs, raw bytes and witnesses in every actual lane."""
    report = json.loads(path.read_text())
    assert report["source_preserved"] and not report["blocked"] and report["exit_code"] == 0
    assert len(report["cases"]) == count
    assert {entry["path"] for entry in report["owned_source_exclusions"]} == exclusions
    entries = {entry["otelc_function"]: entry for entry in report["inventory"]}
    attempts = set()
    for case in report["cases"]:
        entry = entries[case["function"]]
        language = entry["language"]
        assert case["arguments"] == [3] and case["exit_code"] == 0
        parent = path.parent / case["case"]
        paired = json.loads((parent / "typed-bundle.json").read_text())["cases"][0]
        assert paired["contract"]["expected_baseline"] == {"kind": "return_value", "value": scalar(language, 7)}
        for lane in ("baseline", "instrumented_on"):
            assert len(paired[lane]) == 2
            for index, attempt in enumerate(paired[lane]):
                check_attempt(attempt, entry, lane)
                observed = attempt["observation"]
                assert observed["before"] == observed["after"] == expected_graph(language)
                assert observed["outcome"] == {"kind": "return", "graph": expected_graph(language, returned=True)}
                folder = parent / f"{lane}-{index}"
                assert json.loads((folder / "typed-observation.json").read_text()) == observed
                assert (folder / "stdout").read_bytes() == (folder / "stderr").read_bytes() == b""
                assert (folder / "command.json").is_file()
                attempts.add(str(folder.resolve()))
    assert len(attempts) == count * 4
    return attempts


def framework(workspace: Path, folder: Path, name: str, exclusions: set[str]) -> set[str]:
    """Check all eight retained framework replays without counting copies."""
    text = command([sys.executable, workspace / "tests/test_equivalence.py"], folder, name)
    reports = [json.loads(line) for line in text.splitlines()]
    assert len(reports) == 8
    attempts = set()
    for result in reports:
        checked = check_report(Path(result["report"]), exclusions, 1)
        assert not attempts.intersection(checked)
        attempts.update(checked)
    return attempts


def prepare(cli: Path, provider: Path, folder: Path) -> tuple[Path, Path, Path]:
    """One selected x+4 function per language, plus explicit Java source roots."""
    application = folder / "application"
    application.mkdir()
    policy = 'schema_version=1\n[functions]\ninclude=["*selected_match*"]\n'
    for language in LANGUAGES:
        name, text = source(language)
        path = application / language / name
        path.parent.mkdir()
        path.write_text(text)
        policy += (f'\n[[fixtures]]\nlanguage="{language}"\nfunction="*selected_match*"\ncases=[[3]]\n'
                   + 'expected_baseline={kind="return_value",value=' + toml_value(scalar(language, 7)) + '}\n')
    policy += '\n[adapters.java]\nsource_roots=["."]\nclasspath=[]\n'
    config = folder / "policy.toml"
    config.write_text(policy)
    workspace = plan(cli, provider, application, folder, config, "initial")
    command([cli, "generate", "--workspace", workspace], folder, "initial-generate")
    return application, workspace, config


def plan(cli: Path, provider: Path, application: Path, folder: Path, config: Path, name: str) -> Path:
    """Retain each public plan's output, including prelaunch refusal controls."""
    return Path(command([cli, "plan", "--source", application, "--otelc-root", provider,
                         "--workspace-parent", folder, "--config", config], folder, name + "-plan"))


def refusal_controls(cli: Path, provider: Path, application: Path, folder: Path, config: Path) -> int:
    """An invalid marker or changed bundle cannot hide new application code."""
    retained = application / "retained"
    controls = (
        (retained / "snapshot/python/app.py", "def hidden():return 9\n"),
        (retained / "tests/user.py", "def hidden():return 9\n"),
        (retained / ".oteleq-owned.json", "{}"),
        (retained / "unrelated.py", "def hidden():return 9\n"),
    )
    for index, (path, replacement) in enumerate(controls):
        original = path.read_bytes() if path.exists() else None
        path.write_text(replacement)
        try:
            name = "refusal-" + str(index)
            command([cli, "plan", "--source", application, "--otelc-root", provider,
                     "--workspace-parent", folder, "--config", config], folder, name, expected=4)
            assert "invalid retained oteleq workspace" in (folder / (name + ".stderr")).read_text()
        finally:
            if original is None:
                path.unlink()
            else:
                path.write_bytes(original)
    return len(controls)


def main() -> None:
    """Retain four full execution routes, source guards and detached evidence."""
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--cli", type=Path, required=True)
    parser.add_argument("--otelc-root", type=Path, required=True)
    parser.add_argument("--report-dir", type=Path, required=True)
    args = parser.parse_args()
    cli, provider = args.cli.resolve(strict=True), args.otelc_root.resolve(strict=True)
    folder = args.report_dir.resolve()
    folder.mkdir(mode=0o700, exist_ok=False)
    os.environ.update(OTELEQ_CLI=str(cli), OTELEQ_PYTHON=sys.executable, PYTHONDONTWRITEBYTECODE="1")
    application, initial, config = prepare(cli, provider, folder)
    first = json.loads((initial / "plan.json").read_text())
    retained = application / "retained"
    command([cli, "export-tests", "--workspace", initial, "--destination", retained, "--apply"], folder, "retain")
    controls = refusal_controls(cli, provider, application, folder, config)
    workspace = plan(cli, provider, application, folder, config, "replan")
    data = json.loads((workspace / "plan.json").read_text())
    assert data["source_manifest"] == first["source_manifest"] and len(data["source_manifest"]) == 8
    fields = ("id", "path", "language", "name", "status", "reason", "source_sha256")
    assert [[entry[field] for field in fields] for entry in data["inventory"]] == [
        [entry[field] for field in fields] for entry in first["inventory"]]
    assert data["java_context"]["source_units"] == ["java/App.java"]
    assert [item["path"] for item in data["owned_source_exclusions"]] == ["retained"]
    command([cli, "generate", "--workspace", workspace], folder, "generate")
    command([cli, "run", "--workspace", workspace, "--report-dir", folder / "comparison"], folder, "run")
    attempts = check_report(folder / "comparison/report.json", {"retained"})
    attempts |= framework(workspace, folder, "framework", {"retained"})
    python_id = next(case["id"] for case in json.loads((initial / "tests/corpus.json").read_text()) if case["language"] == "python")
    replay = json.loads(command([cli, "replay", "--workspace", initial, "--case", python_id], folder, "initial-replay"))
    attempts |= check_report(Path(replay["report"]), {"retained"}, 1)
    command([cli, "export-tests", "--workspace", workspace, "--destination", application / "retained-second", "--apply"], folder, "retain-second")
    replay = json.loads(command([cli, "replay", "--workspace", workspace, "--case", python_id], folder, "added-bundle-replay"))
    attempts |= check_report(Path(replay["report"]), {"retained", "retained-second"}, 1)
    exported = folder / "detached"
    command([cli, "export-tests", "--workspace", workspace, "--destination", exported, "--apply"], folder, "export")
    application.rename(folder / "application-offline")
    try:
        command([cli, "run", "--workspace", exported, "--report-dir", folder / "detached-comparison"], folder, "detached-run")
        attempts |= check_report(folder / "detached-comparison/report.json", set())
        attempts |= framework(exported, folder, "detached-framework", set())
    finally:
        (folder / "application-offline").rename(application)
    assert len(attempts) == 136
    command([cli, "render-report", folder / "comparison/report.json", "--output-dir", folder / "presentation"], folder, "render")
    assert "retained; workspace" in (folder / "presentation/index.html").read_text()
    command([cli, "export-tests", "--workspace", workspace, "--destination", folder / "identity-check"], folder, "identity-check")
    summary = {"claim": "equivalence over these tests and observations", "artefact_class": "diagnostic",
               "cli_sha256": hashlib.sha256(cli.read_bytes()).hexdigest(), "languages": list(LANGUAGES),
               "actual_application_launches": len(attempts), "refusal_controls": controls,
               "source_files_before_and_after_retention": 8, "selected_ready_functions": 8,
               "java_source_units": ["java/App.java"], "actual_attempt_directories": sorted(attempts),
               "complete_literal_graph_oracles": True, "source_preserved": True,
               "detached_source_offline": True, "shipping_qualification": False}
    (folder / "qualification.json").write_text(json.dumps(summary, indent=2) + "\n")
    print(json.dumps({key: value for key, value in summary.items() if key != "actual_attempt_directories"}), flush=True)


if __name__ == "__main__":
    main()
