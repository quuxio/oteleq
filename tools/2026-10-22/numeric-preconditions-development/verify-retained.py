"""Recheck completed numeric-precondition routes without application launches."""
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
SOURCE = ROOT / "reviewed-source-2fae3ae"
CLI = ROOT / "quux-oteleq-0177499"


def read(path: Path):
    return json.loads(path.read_text())


def digest(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def reviewed_source() -> None:
    inputs = read(ROOT / "qualification-inputs.json")
    archive = ROOT / "source-checker-2fae3ae.tar"
    assert digest(archive) == inputs["checker_source_archive_sha256"]
    assert digest(CLI) == inputs["cli_sha256"]
    with tarfile.open(archive) as contents:
        members = contents.getmembers()
        assert all(member.isfile() or member.isdir() for member in members)
        if not SOURCE.exists():
            contents.extractall(SOURCE, filter="data")
        for member in members:
            if member.isfile():
                path = SOURCE / member.name
                assert not path.is_symlink() and path.read_bytes() == contents.extractfile(member).read()


def main() -> None:
    if sys.flags.optimize:
        raise ValueError("retained verification requires Python assertions")
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--routes", type=int, choices=(1, 2, 3, 4), default=1)
    parser.add_argument("--complete", action="store_true")
    args = parser.parse_args()
    assert not args.complete or args.routes == 4
    reviewed_source()
    sys.path[:0] = [str(SOURCE / name) for name in ("tests", "adapters/generation", "examples")]
    import precondition_fixture_oracle as oracle

    workspace = Path((ACTUAL / "plan.stdout").read_text().strip())
    plan = read(workspace / "plan.json")
    ready = [entry for entry in plan["inventory"] if entry["status"] == "ready"]
    assert len(ready) == 20 and not any(entry["status"] == "blocked" for entry in plan["inventory"])
    assert plan["source_manifest"] == {language + "/" + oracle.source(language)[0]:
        hashlib.sha256(oracle.source(language)[1].encode()).hexdigest() for language in oracle.LANGUAGES}
    for entry in ready:
        assert entry["input_preconditions"] == [oracle.LESS]
        assert entry["input_cases"] == oracle.pairs(entry["language"], oracle.kind_of(entry))

    seen, reports, comparisons = set(), {}, 0

    def check(path: Path, count: int, override=None) -> set[str]:
        nonlocal comparisons
        checked = oracle.check_report(path, count, override)
        assert seen.isdisjoint(checked), str(path)
        seen.update(checked)
        data = read(path)
        identities = set()
        for case in data["cases"]:
            assert case["case"] not in identities
            identities.add(case["case"])
            assert case["arguments_requested"] == case["arguments"]
            if "receiver_fixture" in case:
                assert case["receiver_fixture"]["factory"] == "Meter"
                assert case["receiver_fixture"]["arguments"] == [10]
            bundle = path.parent / case["case"] / "typed-bundle.json"
            result = subprocess.run([str(CLI), "compare-observations", str(bundle)], capture_output=True, check=False, timeout=30)
            assert result.returncode == case["exit_code"] and not result.stderr
            assert json.loads(result.stdout) == case["comparison"]
            comparisons += 1
        reports[str(path.resolve())] = {"cases": count, "sha256": digest(path)}
        return identities

    for language in sorted(oracle.SEQUENCES):
        name = "sequence-preflight-" + language
        assert (ACTUAL / (name + ".exit")).read_text().strip() == "0"
        check(Path(read(ACTUAL / (name + ".stdout"))["report"]), 1)
    ids = check(ACTUAL / "comparison/report.json", oracle.CASES)

    def suite(name: str, expected: set[str], override=None) -> None:
        assert (ACTUAL / (name + ".exit")).read_text().strip() == "1"
        summaries = [json.loads(line) for line in (ACTUAL / (name + ".stdout")).read_text().splitlines()]
        assert len(summaries) == len(expected)
        actual = set()
        for summary in summaries:
            observed = check(Path(summary["report"]), 1, override)
            assert actual.isdisjoint(observed)
            actual |= observed
        assert actual == expected

    if args.routes >= 2:
        suite("framework", ids)
    if args.routes >= 3:
        assert check(ACTUAL / "detached-comparison/report.json", oracle.CASES) == ids
    if args.routes >= 4:
        suite("detached-framework", ids)
    assert len(seen) == 12 + args.routes * oracle.CASES * 4

    if args.complete:
        assert (ROOT / "qualification.exit").read_text().strip() == "0"
        result = read(ACTUAL / "qualification.json")
        controls = [("unsatisfied-" + language, "no generated inputs") for language in oracle.LANGUAGES]
        controls += [("rounded-" + language, "numeric preconditions") for language in oracle.LANGUAGES]
        controls += [(prefix + language, "numeric preconditions") for language in sorted(oracle.SEQUENCES)
                     for prefix in ("fixed-invalid-", "fixed-rounded-")]
        controls.append(("search-budget", "candidate budget"))
        for name, reason in controls:
            blocked = Path((ACTUAL / (name + "-plan.stdout")).read_text().strip())
            selected = [entry for entry in read(blocked / "plan.json")["inventory"] if entry["status"] != "excluded"]
            assert len(selected) == 1 and selected[0]["status"] == "blocked" and reason in selected[0]["reason"]
            assert read(blocked / "tests/corpus.json") == []
            report = read(ACTUAL / (name + "-report/report.json"))
            assert report["cases"] == [] and report["source_preserved"] and len(report["blocked"]) == 1
            assert not list((ACTUAL / (name + "-report")).rglob("typed-observation.json"))
            assert (ACTUAL / (name + "-run.exit")).read_text().strip() == "3"
            assert (ACTUAL / (name + "-suite.exit")).read_text().strip() == "1"
            assert selected[0]["reason"] in (ACTUAL / (name + "-suite.stderr")).read_text()
        assert (ACTUAL / "malformed-plan.exit").read_text().strip() == "4"
        assert "unsupported numeric precondition operator" in (ACTUAL / "malformed-plan.stderr").read_text()
        assert len(controls) == 23 and result["prelaunch_refusal_controls"] == 24
        check(Path(read(ACTUAL / "frozen-replay.stdout")["report"]), 1)
        remaining = {path.resolve() for path in (workspace / "runs").glob("*/report.json")} - set(map(Path, reports))
        assert len(remaining) == 1
        original = next(iter(remaining))
        check(original, 1)
        copied = ACTUAL / "shrink/original/report.json"
        assert copied.read_bytes() == original.read_bytes()
        copied_attempts = oracle.check_report(copied, 1)
        def files(folder):
            return {path.relative_to(folder): digest(path) for path in folder.rglob("*") if path.is_file()}
        assert files(copied.parent) == files(original.parent)
        shrink = read(ACTUAL / "shrink/shrink.json")
        assert shrink["original_arguments"] == [0, 32] and shrink["reduced_arguments"] == [0, 7]
        assert shrink["source_preserved"] and not shrink["incomplete_trials"] and shrink["status"] == "candidate_rule_minimal"
        for trial in shrink["trials"]:
            values = trial["arguments"]
            assert len(values) == 2 and values[0] < values[1]
            assert all(type(value) is int and 0 <= value <= 32 for value in values)
            check(Path(trial["report"]), 1, values)
        check(Path(shrink["confirmation"]), 1, [0, 7])
        target = next(entry for entry in read(ACTUAL / "reduced-export/plan.json")["inventory"] if entry["status"] == "ready")
        suite("reduced-suite", {target["id"] + "-0"}, [0, 7])
        assert set(result["actual_attempt_directories"]) == seen
        physical = set()
        for parent, directories, filenames in os.walk(ACTUAL):
            directories[:] = [name for name in directories if name != "go-cache"]
            if "typed-observation.json" in filenames:
                physical.add(str(Path(parent).resolve()))
        assert physical == seen | copied_attempts and seen.isdisjoint(copied_attempts)
        for name, expected in plan["source_manifest"].items():
            assert digest(ACTUAL / "application" / name) == expected

    result = {"scope": "complete actual qualification" if args.complete else "completed initial routes only",
              "routes_verified": args.routes, "sequence_preflight_launches_verified": 12,
              "reports_verified": len(reports), "distinct_actual_attempts_verified": len(seen),
              "typed_comparisons_recomputed": comparisons,
              "complete_literal_graphs_and_raw_channels_checked": True,
              "reports": reports, "actual_attempt_directories": sorted(seen)}
    filename = "retained-independent-review.json" if args.complete else "retained-routes-" + str(args.routes) + "-review.json"
    (ROOT / filename).write_text(json.dumps(result, indent=2) + "\n")
    print(json.dumps({key: value for key, value in result.items() if key not in ("reports", "actual_attempt_directories")}, indent=2))


if __name__ == "__main__":
    main()
