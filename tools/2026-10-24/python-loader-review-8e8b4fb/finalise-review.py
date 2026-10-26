"""Record the independently inspected optional source-loader component."""

import hashlib
import json
from pathlib import Path
import subprocess


ROOT = Path(__file__).resolve().parent
SOURCE = ROOT / "source-8e8b4fb"


def sha(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def main() -> None:
    manifest = json.loads((ROOT / "source-8e8b4fb.json").read_bytes())
    files = manifest["files"]
    assert len(files) == 375
    assert all(sha(SOURCE / name) == digest for name, digest in files.items())
    changed = subprocess.check_output(
        ["git", "-C", "/Users/sclarke/github/otelc", "diff", "--name-only",
         manifest["base"], manifest["head"]], text=True,
    ).splitlines()
    assert len(changed) == 21
    controls = {}
    proof_names = ["source-8e8b4fb.json", "check-unexecuted-roots.py"]
    for runtime in ("312", "314"):
        log = (ROOT / f"focused-{runtime}.log").read_text()
        assert "Ran 28 tests" in log and "OK (skipped=1)" in log
        assert "test_unavailable_profile_cannot_claim_capture_success" in log
        result_name = f"unexecuted-roots-{runtime}/result.json"
        result = json.loads((ROOT / result_name).read_bytes())
        assert result["head"] == manifest["head"]
        assert result["source_files_preserved"] == 375
        assert [row["case"] for row in result["controls"]] == ["compiled-only", "module-only"]
        assert [row["actual_code_executions"] for row in result["controls"]] == [0, 1]
        assert all(row["loader_roots"] == 1 and row["capture_complete"] for row in result["controls"])
        controls[runtime] = result
        proof_names.extend([f"focused-{runtime}.log", f"unexecuted-roots-{runtime}.log", result_name])
    review = {
        "review_schema_version": 1,
        "repository": "quuxio/otelc",
        "head": manifest["head"],
        "base": manifest["base"],
        "source_archive_sha256": manifest["archive_sha256"],
        "verdict": "clear_for_declared_optional_source_loader_component",
        "findings": [],
        "changed_files_reviewed": changed,
        "source_files_preserved": len(files),
        "focused_tests": {
            "runtimes": ["3.12.15", "3.14.8"],
            "tests_each": 28,
            "active_source_loader_tests_each": 11,
            "expected_skips_each": 1,
            "skip_reason": "The unavailable-image control is conditional; the independently built native image is available",
        },
        "independent_additional_controls": controls,
        "inspected_contract": [
            "Exact pinned frozen helper/code identities and original builtin compiler object; returned immutable read-object identity joins actual compiler and loader returns",
            "Distinct read sequences, loader identities and weak code membership; exact local VM return/start events rather than equal bytes or filename identity",
            "Original output/status/exception preservation, bounded pending/read/catalogue state, abandoned-frame cleanup, ordinary worker transactions and owned teardown",
            "Cached/custom/substituted paths retain capture loss rather than claiming a source root; ordinary public journal-1 launch remains unchanged",
        ],
        "limits": [
            "Optional macOS ARM64 GIL CPython 3.12/3.14 native image component only",
            "Whole-loader capture can refuse cached libraries outside the application; selected-root policy is a separate follow-up, not silently accepted here",
            "SDK code joins, public journal-2 negotiation, both-lane integration, complete dependency/source closure and generated-provider admission remain separate requirements",
            "Owner full repository, protected hosted and final-main delivery checks remain required",
        ],
        "proof_sha256": {name: sha(ROOT / name) for name in proof_names},
    }
    output = ROOT / "review.json"
    output.write_text(json.dumps(review, indent=2) + "\n")
    print(json.dumps({"review": str(output), "sha256": sha(output), "verdict": review["verdict"],
                      "sources_preserved": len(files), "tests_each": 28, "extra_controls_each": 2}))


if __name__ == "__main__":
    main()
