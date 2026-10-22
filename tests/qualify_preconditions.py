"""Qualify frozen numeric relations across actual eight-language workflows."""
import argparse
import copy
import hashlib
import json
import os
from pathlib import Path
import sys

from precondition_fixture_oracle import CASES, FLOAT, INTEGER, LANGUAGES, LESS, NAMES, PROBE, SEQUENCES
from precondition_fixture_oracle import check_report, float_pool, kind_of, kinds, pairs, source
from qualify_generation import command as execute


def command(arguments: list, folder: Path, name: str, expected=0, timeout=900) -> str:
    """Keep a successful expected-exit receipt before any completed-route reuse."""
    text = execute(arguments, folder, name, expected=expected, timeout=timeout)
    (folder / (name + ".exit")).write_text(str(expected) + "\n")
    return text


def toml(value) -> str:
    if isinstance(value, dict):
        return "{" + ",".join(key + "=" + toml(item) for key, item in value.items()) + "}"
    if isinstance(value, list):
        return "[" + ",".join(map(toml, value)) + "]"
    return json.dumps(value, allow_nan=False)


def fixture(language: str, kind: str) -> dict:
    domain = {"integer": INTEGER, "float": FLOAT, "probe": PROBE, "sequence": FLOAT}[kind]
    result = {"language": language, "source": language + "/" + source(language)[0],
              "function": "*" + NAMES[kind] + "*", "domains": [copy.deepcopy(domain), copy.deepcopy(domain)],
              "preconditions": [LESS.copy()]}
    if kind == "sequence":
        low, _, middle = float_pool(language)
        result.update(cases=pairs(language, kind), receiver={"factory": "Meter", "arguments": [10]},
                      sequence=[{"action": "call", "arguments": [low, middle]}, {"action": "call", "arguments": "case"}])
    return result


def write_policy(path: Path, fixtures: list[dict], budget=3) -> None:
    header = {"schema_version": 1, "languages": list(dict.fromkeys(item["language"] for item in fixtures))}
    text = "\n".join(key + "=" + toml(value) for key, value in header.items())
    text += "\n[generation]\nseed=123\ncases_per_function=" + str(budget)
    text += "\n[functions]\ninclude=" + toml(list(dict.fromkeys(item["function"] for item in fixtures))) + "\n"
    for item in fixtures:
        text += "\n[[fixtures]]\n" + "\n".join(key + "=" + toml(value) for key, value in item.items()) + "\n"
    path.write_text(text)


def prepare(cli: Path, provider: Path, folder: Path) -> Path:
    """Planning freezes every pair independently before application execution."""
    application = folder / "application"
    application.mkdir()
    fixtures = []
    for language in LANGUAGES:
        filename, text = source(language)
        target = application / language / filename
        target.parent.mkdir()
        target.write_text(text)
        fixtures.extend(fixture(language, kind) for kind in kinds(language))
    config = folder / "policy.toml"
    write_policy(config, fixtures)
    workspace = Path(command([cli, "plan", "--source", application, "--otelc-root", provider,
        "--workspace-parent", folder, "--config", config], folder, "plan"))
    data = json.loads((workspace / "plan.json").read_text())
    ready = [entry for entry in data["inventory"] if entry["status"] == "ready"]
    assert len(ready) == 20 and not any(entry["status"] == "blocked" for entry in data["inventory"])
    for entry in ready:
        assert entry["input_preconditions"] == [LESS]
        assert entry["input_cases"] == pairs(entry["language"], kind_of(entry))
    command([cli, "generate", "--workspace", workspace], folder, "generate")
    assert len(json.loads((workspace / "tests/corpus.json").read_text())) == CASES
    return workspace


def sequence_preflight(cli: Path, workspace: Path, folder: Path, resume: bool) -> set[str]:
    """Check complete actual receiver graphs before the longer full routes."""
    data = json.loads((workspace / "plan.json").read_text())
    corpus = json.loads((workspace / "tests/corpus.json").read_text())
    attempts = set()
    for entry in data["inventory"]:
        if entry["status"] != "ready" or kind_of(entry) != "sequence":
            continue
        name = "sequence-preflight-" + entry["language"]
        stdout, receipt = folder / (name + ".stdout"), folder / (name + ".exit")
        if resume and stdout.exists():
            assert receipt.read_text().strip() == "0", "incomplete preflight must not be repeated"
            text = stdout.read_text()
        else:
            marker = folder / (name + ".started")
            assert not marker.exists(), "incomplete preflight must be inspected, not repeated"
            marker.write_text("One actual replay; confirm terminal before any recovery.\n")
            case = next(item for item in corpus if item["function_id"] == entry["id"])
            text = command([cli, "replay", "--workspace", workspace, "--case", case["id"]], folder, name)
        observed = check_report(Path(json.loads(text)["report"]), 1)
        assert attempts.isdisjoint(observed)
        attempts |= observed
    assert len(attempts) == 12
    return attempts


def direct(cli: Path, workspace: Path, folder: Path, name: str, resume: bool) -> set[str]:
    destination = folder / name
    if not resume or not (destination / "report.json").is_file():
        assert not destination.exists(), "retain incomplete route; do not relaunch it"
        command([cli, "run", "--workspace", workspace, "--report-dir", destination], folder, name, 1, 3600)
    else:
        assert (folder / (name + ".exit")).read_text().strip() == "1"
    return check_report(destination / "report.json", CASES)


def framework(workspace: Path, folder: Path, name: str, resume: bool, *, count=CASES, override=None) -> set[str]:
    stdout = folder / (name + ".stdout")
    if resume and stdout.exists():
        assert (folder / (name + ".exit")).read_text().strip() == "1"
        text = stdout.read_text()
    else:
        marker = folder / (name + ".started")
        assert not marker.exists(), "incomplete framework route must be inspected, not repeated"
        marker.write_text("One generated suite; confirm terminal before any recovery.\n")
        text = command([sys.executable, workspace / "tests/test_equivalence.py"], folder, name, 1, 3600)
    summaries = [json.loads(line) for line in text.splitlines()]
    assert len(summaries) == count
    attempts, cases = set(), set()
    for summary in summaries:
        report = Path(summary["report"])
        observed = check_report(report, 1, override)
        case = json.loads(report.read_text())["cases"][0]["case"]
        assert attempts.isdisjoint(observed) and case not in cases
        cases.add(case)
        attempts |= observed
    expected = {item["id"] for item in json.loads((workspace / "tests/corpus.json").read_text())}
    assert cases == expected
    return attempts


def routes(cli: Path, provider: Path, folder: Path, resume: bool) -> tuple[Path, set[str]]:
    workspace = Path((folder / "plan.stdout").read_text().strip()) if resume else prepare(cli, provider, folder)
    data = json.loads((workspace / "plan.json").read_text())
    assert Path(data["otelc_root"]).resolve() == provider and Path(data["source"]).resolve() == folder / "application"
    assert data["source_manifest"] == {language + "/" + source(language)[0]:
        hashlib.sha256(source(language)[1].encode()).hexdigest() for language in LANGUAGES}
    command([cli, "export-tests", "--workspace", workspace, "--destination", folder / "seal-check"], folder, "seal-check")
    attempts = sequence_preflight(cli, workspace, folder, resume)
    for observed in (direct(cli, workspace, folder, "comparison", resume), framework(workspace, folder, "framework", resume)):
        assert attempts.isdisjoint(observed)
        attempts |= observed
    exported = folder / "exported"
    if not exported.exists():
        command([cli, "export-tests", "--workspace", workspace, "--destination", exported, "--apply"], folder, "export")
    application = folder / "application"
    application.rename(folder / "application-offline")
    try:
        for observed in (direct(cli, exported, folder, "detached-comparison", resume), framework(exported, folder, "detached-framework", resume)):
            assert attempts.isdisjoint(observed)
            attempts |= observed
    finally:
        (folder / "application-offline").rename(application)
    assert len(attempts) == CASES * 16 + 12
    return workspace, attempts


def refusal(cli: Path, provider: Path, folder: Path, name: str, selected: dict, reason: str, budget=3) -> None:
    policy = folder / (name + ".toml")
    write_policy(policy, [selected], budget)
    workspace = Path(command([cli, "plan", "--source", folder / "application", "--otelc-root", provider,
        "--workspace-parent", folder, "--config", policy], folder, name + "-plan"))
    data = json.loads((workspace / "plan.json").read_text())
    entries = [entry for entry in data["inventory"] if entry["status"] != "excluded"]
    assert len(entries) == 1 and entries[0]["status"] == "blocked" and reason in entries[0]["reason"]
    command([cli, "generate", "--workspace", workspace], folder, name + "-generate")
    assert json.loads((workspace / "tests/corpus.json").read_text()) == []
    output = folder / (name + "-report")
    command([cli, "run", "--workspace", workspace, "--report-dir", output], folder, name + "-run", 3)
    report = json.loads((output / "report.json").read_text())
    assert report["cases"] == [] and report["source_preserved"] and len(report["blocked"]) == 1
    assert not list(output.rglob("typed-observation.json"))
    assert command([sys.executable, workspace / "tests/test_equivalence.py"], folder, name + "-suite", 1) == ""
    failure = (folder / (name + "-suite.stderr")).read_text()
    assert entries[0]["reason"] in failure and "Ran 1 test" in failure


def refusal_controls(cli: Path, provider: Path, folder: Path) -> int:
    for language in LANGUAGES:
        item = fixture(language, "integer")
        item["preconditions"] = [{**LESS, "right": 0}]
        refusal(cli, provider, folder, "unsatisfied-" + language, item, "no generated inputs")
        item = fixture(language, "float")
        item.pop("domains")
        base = 2**24 if language in ("c", "cpp", "rust", "java", "go") else 2**53
        item["cases"] = [[base, base + 1]]
        refusal(cli, provider, folder, "rounded-" + language, item, "numeric preconditions")
    for language in sorted(SEQUENCES):
        item = fixture(language, "sequence")
        low, high, _ = float_pool(language)
        item["sequence"][0]["arguments"] = [high, low]
        refusal(cli, provider, folder, "fixed-invalid-" + language, item, "numeric preconditions")
        base = 2**24 if language == "java" else 2**53
        item["sequence"][0]["arguments"] = [base, base + 1]
        refusal(cli, provider, folder, "fixed-rounded-" + language, item, "numeric preconditions")
    item = fixture("python", "integer")
    item["domains"] = [{**INTEGER, "minimum": 0, "maximum": 1000}] * 2
    item["preconditions"] = [{**LESS, "operator": "=="}]
    refusal(cli, provider, folder, "search-budget", item, "candidate budget", 512)
    malformed = fixture("python", "integer")
    malformed["preconditions"] = [{**LESS, "operator": "eval"}]
    policy = folder / "malformed.toml"
    write_policy(policy, [malformed])
    command([cli, "plan", "--source", folder / "application", "--otelc-root", provider,
             "--workspace-parent", folder, "--config", policy], folder, "malformed-plan", 4)
    assert "unsupported numeric precondition operator" in (folder / "malformed-plan.stderr").read_text()
    return 24


def frozen_replay(cli: Path, workspace: Path, folder: Path) -> set[str]:
    data = json.loads((workspace / "plan.json").read_text())
    entry = next(item for item in data["inventory"] if item["status"] == "ready" and item["language"] == "rust" and kind_of(item) == "float")
    case = next(item for item in json.loads((workspace / "tests/corpus.json").read_text()) if item["function_id"] == entry["id"])
    policy = folder / "policy.toml"
    original = policy.read_bytes()
    policy.write_text("external policy deliberately invalid\n")
    try:
        text = command([cli, "replay", "--workspace", workspace, "--case", case["id"]], folder, "frozen-replay")
        return check_report(Path(json.loads(text)["report"]), 1)
    finally:
        policy.write_bytes(original)


def reduce_case(cli: Path, workspace: Path, folder: Path) -> set[str]:
    data = json.loads((workspace / "plan.json").read_text())
    entry = next(item for item in data["inventory"] if item["status"] == "ready" and kind_of(item) == "probe")
    case = next(item for item in json.loads((workspace / "tests/corpus.json").read_text()) if item["function_id"] == entry["id"])
    before = set(workspace.rglob("typed-observation.json"))
    command([cli, "shrink", "--workspace", workspace, "--case", case["id"],
             "--report-dir", folder / "shrink", "--trials", "32"], folder, "shrink", 1, 1800)
    shrink = json.loads((folder / "shrink/shrink.json").read_text())
    assert shrink["original_arguments"] == [0, 32] and shrink["reduced_arguments"] == [0, 7]
    assert shrink["status"] == "candidate_rule_minimal" and shrink["source_preserved"] and not shrink["incomplete_trials"]
    added = set(workspace.rglob("typed-observation.json")) - before
    reports = {path.parent.parent.parent / "report.json" for path in added}
    assert len(added) == 4 and len(reports) == 1
    original = next(iter(reports))
    attempts = check_report(original, 1)
    assert (folder / "shrink/original/report.json").read_bytes() == original.read_bytes()
    for trial in shrink["trials"]:
        values = trial["arguments"]
        assert values[0] < values[1] and all(type(value) is int and 0 <= value <= 32 for value in values)
        observed = check_report(Path(trial["report"]), 1, values)
        assert attempts.isdisjoint(observed)
        attempts |= observed
    observed = check_report(Path(shrink["confirmation"]), 1, [0, 7])
    assert attempts.isdisjoint(observed)
    attempts |= observed
    derived = Path(shrink["workspace"])
    assert json.loads((derived / "plan.json").read_text())["configuration"]["fixtures"][0]["preconditions"] == [LESS]
    exported = folder / "reduced-export"
    command([cli, "export-tests", "--workspace", derived, "--destination", exported, "--apply"], folder, "reduced-export")
    observed = framework(exported, folder, "reduced-suite", False, count=1, override=[0, 7])
    assert attempts.isdisjoint(observed)
    attempts |= observed
    return attempts


def main() -> None:
    if sys.flags.optimize:
        raise ValueError("qualification requires Python assertions")
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--cli", type=Path, required=True)
    parser.add_argument("--otelc-root", type=Path, required=True)
    parser.add_argument("--report-dir", type=Path, required=True)
    parser.add_argument("--resume", action="store_true")
    args = parser.parse_args()
    cli, provider, folder = args.cli.resolve(strict=True), args.otelc_root.resolve(strict=True), args.report_dir.resolve()
    assert not any(folder.is_relative_to(path) for path in (provider, Path(__file__).resolve().parents[1]))
    assert not (folder / "post-routes-started").exists(), "resume supports only initial routes; later controls must not repeat"
    if not args.resume:
        folder.mkdir(mode=0o700, exist_ok=False)
    os.environ.update(OTELEQ_PYTHON=sys.executable, OTELEQ_CLI=str(cli), PYTHONDONTWRITEBYTECODE="1", PYTHONOPTIMIZE="0")
    workspace, attempts = routes(cli, provider, folder, args.resume)
    marker = folder / "post-routes-started"
    assert not marker.exists(), "resume supports only initial routes; later controls must not repeat"
    marker.write_text("Inspect later partial controls; do not silently repeat them.\n")
    controls = refusal_controls(cli, provider, folder)
    for observed in (frozen_replay(cli, workspace, folder), reduce_case(cli, workspace, folder)):
        assert attempts.isdisjoint(observed)
        attempts |= observed
    data = json.loads((workspace / "plan.json").read_text())
    for name, expected in data["source_manifest"].items():
        assert hashlib.sha256((folder / "application" / name).read_bytes()).hexdigest() == expected
    command([cli, "export-tests", "--workspace", workspace, "--destination", folder / "final-seal-check"], folder, "final-seal-check")
    command([cli, "render-report", folder / "comparison/report.json", "--output-dir", folder / "presentation"], folder, "render", 1)
    result = {"claim": "equivalence over these tests and observations", "artefact_class": "diagnostic",
              "cli_sha256": hashlib.sha256(cli.read_bytes()).hexdigest(),
              "driver_sha256": hashlib.sha256(Path(__file__).read_bytes()).hexdigest(),
              "oracle_sha256": hashlib.sha256(Path(__file__).with_name("precondition_fixture_oracle.py").read_bytes()).hexdigest(),
              "selected_functions": 20, "initial_cases": CASES, "languages": list(LANGUAGES),
              "qualified_application_launches": len(attempts), "actual_attempt_directories": sorted(attempts),
              "prelaunch_refusal_controls": controls, "complete_literal_graph_oracles": True,
              "source_preserved": True, "limits": "Recorded legacy diagnostic scalar and plain receiver profiles. No general predicates, shipping or other-platform qualification."}
    (folder / "qualification.json").write_text(json.dumps(result, indent=2) + "\n")
    print(json.dumps({key: value for key, value in result.items() if key != "actual_attempt_directories"}), flush=True)


if __name__ == "__main__":
    main()
