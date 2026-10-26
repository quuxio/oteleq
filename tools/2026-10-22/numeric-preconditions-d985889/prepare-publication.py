"""Build the public numeric-precondition record from completed retained receipts."""
import hashlib
import json
import platform
from pathlib import Path
import subprocess

ROOT = Path(__file__).resolve().parent
WORKTREE = Path("/Users/sclarke/github/oteleq-qualification/work/oteleq-preconditions")
BUILT = Path("/Users/sclarke/github/oteleq-qualification/work/native-workflow-target/debug/quux-oteleq")


def read(name: str) -> dict:
    return json.loads((ROOT / name).read_text())


def digest(path: Path) -> str:
    with path.open("rb") as stream:
        return hashlib.file_digest(stream, "sha256").hexdigest()


def main() -> None:
    actual = read("actual/qualification.json")
    review = read("retained-independent-review.json")
    inputs = read("qualification-inputs.json")
    frozen = read("frozen-build.json")
    manifest = read("raw-evidence-manifest.json")
    visual = read("presentation-review.json")
    validation = read("local-validation-d985889.json")
    shrink = read("actual/shrink/shrink.json")
    if (ROOT / "qualification.exit").read_text().strip() != "0":
        raise ValueError("actual qualifier did not finish successfully")
    if actual["qualified_application_launches"] != 912 or review["distinct_actual_attempts_verified"] != 912:
        raise ValueError("actual and reviewed launch counts differ")
    if review["reports_verified"] != 122 or review["typed_comparisons_recomputed"] != 228:
        raise ValueError("retained review is incomplete")
    if actual["prelaunch_refusal_controls"] != 24 or not actual["source_preserved"]:
        raise ValueError("control or source-preservation evidence is incomplete")
    if digest(BUILT) != frozen["cli_sha256"]:
        raise ValueError("current build is not byte-identical to the qualified frozen CLI")
    subprocess.run(["git", "diff", "--quiet", inputs["runtime_revision"], "--",
                    "src", "adapters", "examples", "Cargo.toml", "Cargo.lock"], cwd=WORKTREE, check=True)
    for name, expected in visual["files"].items():
        if digest(ROOT / "actual/presentation" / name) != expected:
            raise ValueError("final presentation differs from browser-reviewed output")
    record = {
        "schema_version": 1, "claim": actual["claim"], "artefact_class": "diagnostic", "date": "2026-10-22",
        "runtime_revision": inputs["runtime_revision"], "runtime_cli_sha256": actual["cli_sha256"],
        "runtime_source_archive_sha256": frozen["source_archive_sha256"],
        "qualification_checker_revision": inputs["checker_revision"],
        "checker_source_archive_sha256": inputs["checker_source_archive_sha256"],
        "qualification_driver_sha256": actual["driver_sha256"], "qualification_oracle_sha256": actual["oracle_sha256"],
        "application_implementation_unchanged_since_qualified_runtime": True,
        "main_integration_revision": "757fc1de4665fa6faa136c6891612a1df088029f",
        "integrated_cli_byte_identical_to_qualified_runtime": True,
        "provider_revision": read("provider-input-recheck.json")["provider_commit"],
        "host": platform.platform(), "languages": actual["languages"], "selected_functions": 20,
        "initial_generated_cases": 54, "main_route_matching_cases": 51, "main_route_deliberate_difference_cases": 3,
        "actual_application_launches": 912, "instrumented_application_launches": 456,
        "routes": {"sequence_preflights": 12, "direct": 216, "generated_suite": 216,
                   "detached_direct": 216, "detached_generated_suite": 216, "frozen_policy_replay": 4,
                   "shrink_original": 4, "shrink_trials": 20, "shrink_confirmation": 4, "reduced_exported_suite": 4},
        "prelaunch_refusal_controls": {"total": 24, "unsatisfied_self_order": 8, "explicit_target_rounding": 8,
            "fixed_sequence_order": 3, "fixed_sequence_rounding": 3, "candidate_search_budget": 1,
            "malformed_operator_policy": 1, "actual_application_launches": 0,
            "selected_blockers_fail_public_run_and_generated_suite": 23},
        "frozen_external_policy_edit_does_not_resample": True,
        "shrink": {key: shrink[key] for key in ("original_arguments", "reduced_arguments", "incomplete_trials", "status")},
        "complete_literal_graph_oracles": True, "raw_stdout_stderr_checked": True,
        "selected_function_witnesses_checked": True, "source_preserved": True,
        "provider_input_recheck": read("provider-input-recheck.json"),
        "retained_review": {key: review[key] for key in (
            "reports_verified", "distinct_actual_attempts_verified", "typed_comparisons_recomputed")},
        "retained_evidence_records": manifest["retained_evidence_records"],
        "retained_evidence_manifest_sha256": digest(ROOT / "raw-evidence-manifest.json"),
        "rebuildable_evidence_exclusions": manifest["excluded_rebuildable_directories"], "validation": validation,
        "limits": [
            "The actual corpus exercises strict ordering; all six closed operators have separate component regressions.",
            "Bounded declared numeric relations over finite primitive values; no inferred predicates, arithmetic expressions, objects or dependent factories.",
            "Recorded legacy scalar and plain receiver profiles on macOS ARM64; other providers, platforms, shipping artefacts and general action-scoped witnesses remain separately unqualified.",
            "The Python probe deliberately observes instrumentation presence; its differences qualify failure reporting rather than an instrumentation defect.",
            "Recomputed typed graphs and decoded witnesses do not independently authenticate raw telemetry provenance."],
        "overall_project_complete": False}
    record["shrink"].update(trials=len(shrink["trials"]), copied_original_attempts_verified_but_not_counted=4,
                            all_trial_relations_preserved=True)
    record["retained_review"].update(first_route_junit=visual["junit"], junit_excluded_constructor_entries=3,
        browser_review=visual["browser_review"], final_presentation_byte_identical_to_browser_review=True)
    record["validation"]["final_delivery_checks"] = (
        "Required on final PR63 head and merged main; recorded by GitHub checks and the separate delivery receipt.")
    text = json.dumps(record, indent=2) + "\n"
    (ROOT / "publication-record.json").write_text(text)
    (WORKTREE / "docs/qualification/numeric-preconditions-2026-10-22.json").write_text(text)
    print(json.dumps({"launches": 912, "reports": 122, "comparisons": 228,
        "records": manifest["retained_evidence_records"], "integrated_cli_byte_identical": True,
        "final_presentation_byte_identical": True}, indent=2))


if __name__ == "__main__":
    main()
