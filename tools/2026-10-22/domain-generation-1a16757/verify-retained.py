"""Recheck immutable domain evidence and recompute comparisons, without app launches."""
import argparse
import hashlib
import json
import os
from pathlib import Path
import subprocess
import sys
import tarfile

ROOT = Path(__file__).resolve().parent
ACTUAL = ROOT / "actual"
SOURCE = ROOT / "reviewed-source-dbf9908"
CLI = ROOT / "quux-oteleq"


def read(path: Path):
    return json.loads(path.read_text())


def digest(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def reviewed_source() -> None:
    """Load the archived checker, independently of either live checkout."""
    correction = read(ROOT / "reporting-correction.json")
    archive = ROOT / "source-dbf9908.tar"
    assert digest(archive) == correction["source_archive_sha256"]
    assert digest(CLI) == read(ROOT / "frozen-build.json")["cli_sha256"]
    with tarfile.open(archive) as contents:
        members = contents.getmembers()
        assert all(item.isfile() or item.isdir() for item in members)
        if not SOURCE.exists():
            contents.extractall(SOURCE, filter="data")
        for member in members:
            if member.isfile():
                path = SOURCE / member.name
                assert not path.is_symlink()
                assert path.read_bytes() == contents.extractfile(member).read()


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--initial", action="store_true", help="Check only the completed first two routes")
    args = parser.parse_args()
    reviewed_source()
    sys.path[:0] = [str(SOURCE / name) for name in ("tests", "adapters/generation", "examples")]
    import domain_fixture_oracle as oracle

    workspace = Path((ACTUAL / "plan.stdout").read_text().strip())
    plan = read(workspace / "plan.json")
    assert len([entry for entry in plan["inventory"] if entry["status"] == "ready"]) == 30
    assert not any(entry["status"] == "blocked" for entry in plan["inventory"])
    assert all("cases" not in fixture for fixture in plan["configuration"]["fixtures"])
    for entry in plan["inventory"]:
        if entry["status"] == "ready":
            expected = oracle.arguments(entry["language"], oracle.kind_of(entry))
            assert entry["input_cases"] == [[value] for value in expected]
    assert plan["source_manifest"] == {language + "/" + oracle.source(language)[0]:
        hashlib.sha256(oracle.source(language)[1].encode()).hexdigest() for language in oracle.LANGUAGES}

    seen, reports, recomputed = set(), {}, 0

    def check(path: Path, count: int, expected=None) -> set[str]:
        """Check full literal observations and independently recompute each verdict."""
        nonlocal recomputed
        checked = oracle.check_report(path, count=count, expected_arguments=expected)
        assert seen.isdisjoint(checked), str(path)
        seen.update(checked)
        data = read(path)
        identities = set()
        for case in data["cases"]:
            assert case["case"] not in identities
            identities.add(case["case"])
            assert case["arguments_requested"] == case["arguments"]
            bundle = path.parent / case["case"] / "typed-bundle.json"
            result = subprocess.run([str(CLI), "compare-observations", str(bundle)],
                                    capture_output=True, check=False, timeout=30)
            assert result.returncode == case["exit_code"] and not result.stderr
            assert json.loads(result.stdout) == case["comparison"]
            recomputed += 1
        reports[str(path.resolve())] = {"cases": count, "sha256": digest(path)}
        return identities

    initial_ids = check(ACTUAL / "comparison/report.json", 82)

    def suite(name: str, expected_ids: set[str], expected=None) -> None:
        summaries = [json.loads(line) for line in (ACTUAL / (name + ".stdout")).read_text().splitlines()]
        assert len(summaries) == len(expected_ids)
        ids = set()
        for summary in summaries:
            actual = check(Path(summary["report"]), 1, expected)
            assert ids.isdisjoint(actual)
            ids.update(actual)
        assert ids == expected_ids

    suite("framework", initial_ids)
    if args.initial:
        assert len(seen) == 656 and recomputed == 164
        result = {"scope": "completed direct and generated-suite routes only", "reports_verified": len(reports),
                  "actual_attempts_verified": len(seen), "comparisons_recomputed": recomputed,
                  "complete_literal_graphs_and_raw_channels": True, "reports": reports}
        (ROOT / "initial-retained-review.json").write_text(json.dumps(result, indent=2) + "\n")
        print(json.dumps({key: value for key, value in result.items() if key != "reports"}, indent=2))
        return

    assert (ROOT / "qualification-a0fc8e7.exit").read_text().strip() == "1"
    assert "render returned 1, expected 0" in (ROOT / "qualification-a0fc8e7.log").read_text()
    assert check(ACTUAL / "detached-comparison/report.json", 82) == initial_ids
    suite("detached-framework", initial_ids)
    assert len(seen) == 1312

    refusal_specs = [("arity-" + language, "argument count") for language in oracle.LANGUAGES]
    refusal_specs += [("unrepresentable-" + language, "representable")
                     for language in ("c", "cpp", "rust", "java", "go")]
    refusal_specs.append(("input-budget", "byte budget"))
    for name, reason in refusal_specs:
        blocked_workspace = Path((ACTUAL / (name + "-plan.stdout")).read_text().strip())
        data = read(blocked_workspace / "plan.json")
        selected = [entry for entry in data["inventory"] if entry["status"] != "excluded"]
        assert len(selected) == 1 and selected[0]["status"] == "blocked"
        assert reason in selected[0]["reason"]
        assert read(blocked_workspace / "tests/corpus.json") == []
        refusal_report = ACTUAL / (name + "-report/report.json")
        report = read(refusal_report)
        assert report["cases"] == [] and report["source_preserved"] and report["exit_code"] == 3
        assert len(report["blocked"]) == 1
        assert not list(refusal_report.parent.rglob("typed-observation.json"))
        assert (ACTUAL / (name + "-suite.stdout")).read_bytes() == b""
        failure = (ACTUAL / (name + "-suite.stderr")).read_text()
        assert selected[0]["reason"] in failure and "Ran 1 test" in failure

    replay = Path(read(ACTUAL / "frozen-replay.stdout")["report"])
    check(replay, 1)
    summary = read(ACTUAL / "shrink/shrink.json")
    assert summary["original_arguments"] == [32] and summary["reduced_arguments"] == [7]
    assert summary["source_preserved"] and summary["incomplete_trials"] == 0
    assert summary["status"] == "candidate_rule_minimal"
    remaining = {path.resolve() for path in (workspace / "runs").glob("*/report.json")} - set(map(Path, reports))
    assert len(remaining) == 1
    original = next(iter(remaining))
    check(original, 1)
    copied = ACTUAL / "shrink/original/report.json"
    assert copied.read_bytes() == original.read_bytes()
    copied_attempts = oracle.check_report(copied, count=1)
    original_files = {path.relative_to(original.parent): digest(path)
                      for path in original.parent.rglob("*") if path.is_file()}
    assert original_files == {path.relative_to(copied.parent): digest(path)
                             for path in copied.parent.rglob("*") if path.is_file()}
    for trial in summary["trials"]:
        values = trial["arguments"]
        assert len(values) == 1 and type(values[0]) is int and 0 <= values[0] <= 32
        check(Path(trial["report"]), 1, values)
    check(Path(summary["confirmation"]), 1, [7])
    reduced_plan = read(ACTUAL / "reduced-export/plan.json")
    target = next(entry for entry in reduced_plan["inventory"] if entry["status"] == "ready")
    suite("reduced-suite", {target["id"] + "-0"}, [7])
    check(ACTUAL / "seeded-report/report.json", 8, [0, -100, 100, -18, -62, 1, 66, -88])

    physical = set()
    for parent, directories, files in os.walk(ACTUAL):
        directories[:] = [name for name in directories if name != "go-cache"]
        path = Path(parent)
        if "typed-observation.json" in files:
            physical.add(str(path.resolve()))
    assert physical == seen | copied_attempts
    assert seen.isdisjoint(copied_attempts)
    result = {"scope": "all completed fixed domain workflows; copied original evidence excluded from launches",
              "reports_verified": len(reports), "actual_attempts_verified": len(seen),
              "comparisons_recomputed": recomputed, "copied_original_attempts_verified_but_not_counted": 4,
              "prelaunch_refusal_controls_verified": len(refusal_specs),
              "complete_literal_graphs_and_raw_channels": True, "reports": reports,
              "actual_attempt_directories": sorted(seen)}
    (ROOT / "retained-independent-review.json").write_text(json.dumps(result, indent=2) + "\n")
    print(json.dumps({key: value for key, value in result.items()
                     if key not in ("reports", "actual_attempt_directories")}, indent=2))


if __name__ == "__main__":
    main()
