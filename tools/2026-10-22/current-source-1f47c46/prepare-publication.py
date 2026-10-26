"""Publish the completed current-source diagnostic qualification from receipts."""
import hashlib
import json
import platform
from pathlib import Path
import subprocess

ROOT = Path(__file__).resolve().parent
WORKTREE = Path("/Users/sclarke/github/oteleq-qualification/work/oteleq-project-tests")
BUILT = Path("/Users/sclarke/github/oteleq-qualification/work/project-tests-target/debug/quux-oteleq")


def read(name):
    return json.loads((ROOT / name).read_text())


def digest(path):
    with path.open("rb") as stream:
        return hashlib.file_digest(stream, "sha256").hexdigest()


def main():
    actual, review, frozen = read("actual/qualification.json"), read("retained-independent-review.json"), read("freeze.json")
    manifest, visual, validation = read("raw-evidence-manifest.json"), read("presentation-review.json"), read("local-validation.json")
    assert (ROOT / "qualification.exit").read_text().strip() == "0"
    assert actual["status"] == "complete" and actual["actual_launches"] == 936 and actual["prelaunch_refusals"] == 10
    assert review["distinct_launches_verified"] == 956 and review["reports_verified"] == review["typed_comparisons_recomputed"] == 239
    assert digest(BUILT) == actual["cli_sha256"] == frozen["cli_sha256"]
    assert digest(ROOT / "source-1f47c46.tar") == frozen["source_archive_sha256"]
    subprocess.run(["git", "diff", "--quiet", frozen["head"], "--", "src", "adapters", "examples", "Cargo.toml", "Cargo.lock"], cwd=WORKTREE, check=True)
    for name, expected in visual["files"].items():
        assert digest(ROOT / "presentation-different" / name) == expected
    source = ROOT / "reviewed-source-1f47c46"
    go = read("go-build-budget-different-review.json")
    record = {
        "schema_version": 1, "date": "2026-10-22", "claim": actual["claim"], "artefact_class": "diagnostic",
        "runtime_revision": frozen["head"], "runtime_cli_sha256": frozen["cli_sha256"],
        "runtime_source_archive_sha256": frozen["source_archive_sha256"],
        "qualification_checker_revision": frozen["head"],
        "qualification_driver_sha256": digest(source / "tests/qualify_project_tests.py"),
        "qualification_oracle_sha256": digest(source / "tests/project_fixture_oracle.py"),
        "application_implementation_unchanged_since_qualified_runtime": True,
        "integrated_cli_byte_identical_to_qualified_runtime": True,
        "provider_revision": read("provider-verification.json")["source_commit"], "host": platform.platform(),
        "languages": ["c", "cpp", "rust", "python", "java", "javascript", "typescript", "go"],
        "main_qualification_launches": 936, "preliminary_preflight_launches": 20,
        "actual_application_launches": 956, "instrumented_application_launches": 478,
        "routes": {"preliminary_preflight": 20, "main_preflight": 20, "initial": 212,
                   "changed_bodies": 212, "relocated_checkout_added_functions": 244, "external_suite_deliberate_difference": 248},
        "route_functions_and_cases": actual["stages"],
        "final_route": {"selected_functions": 29, "cases": 62, "matches": 61, "deliberate_differences": 1,
                        "incomplete": 0, "excluded_callables": 4},
        "prelaunch_refusals": {"total": 10, "actual_application_launches": 0,
            "controls": ["missing-source", "missing-file", "extra-file", "changed-file", "linked-file", "changed-cli",
                         "changed-generator", "changed-provider", "empty-source", "resealed-foreign"]},
        "complete_literal_graph_oracles": True, "raw_stdout_stderr_checked": True,
        "selected_function_witnesses_checked": True, "source_preserved_per_run": True,
        "transport_scope": "bounded server response-header lifecycle records; client acknowledgement is not observed",
        "go_build_budgets": {key: go[key] for key in ("go_attempts", "build_commands", "per_build_timeout_ms", "unchanged_application_timeout_ms")},
        "provider_input_recheck": read("provider-verification.json"),
        "retained_review": {key: review[key] for key in ("distinct_launches_verified", "reports_verified", "typed_comparisons_recomputed")},
        "retained_evidence_records": manifest["retained_evidence_records"],
        "retained_evidence_manifest_sha256": digest(ROOT / "raw-evidence-manifest.json"),
        "rebuildable_evidence_exclusions": manifest["excluded_rebuildable_directories"],
        "validation": validation,
        "earlier_incomplete_experiments": [
            "03b9658 retained an opaque Python exporter failure; this later result does not establish its cause.",
            "f0b7f3e retained a 180-second Go SDK build timeout before application launch. The new experiment declares 600 seconds per build; the default 180 seconds and application timeout are unchanged. No silent retry or causal resolution is claimed."],
        "limits": [
            "Recorded legacy diagnostic profiles on macOS ARM64; other providers/platforms and shipping artefacts need separate qualification.",
            "Bounded declared scalar and supported Java/Node sequence fixtures, not general semantic/build/dependency or arbitrary object/async support.",
            "The deliberately added Python probe observes instrumentation presence; its stable 0/1 return difference checks failure reporting, not an instrumentation defect.",
            "Typed recomputation and decoded telemetry consistency do not authenticate raw telemetry provenance or supply action-scoped attribution.",
            "Native property frameworks, broader fixture/dependency integration and baseline-only regression promotion remain open."],
        "overall_project_complete": False,
    }
    record["retained_review"].update(junit=visual["junit"], browser_review=visual["browser_review"],
        final_presentation_byte_identical_to_browser_review=True)
    record["go_build_budgets"]["default_build_timeout_ms"] = 180000
    record["validation"]["final_delivery_checks"] = "Required on final PR64 head and merged main; recorded separately in GitHub and delivery receipts."
    text = json.dumps(record, indent=2) + "\n"
    (ROOT / "publication-record.json").write_text(text)
    (WORKTREE / "docs/qualification/current-source-tests-2026-10-22.json").write_text(text)
    print(json.dumps({"launches": 956, "comparisons": 239, "raw_records": manifest["retained_evidence_records"],
                      "integrated_cli_byte_identical": True, "presentation_byte_identical": True}))


if __name__ == "__main__":
    main()
