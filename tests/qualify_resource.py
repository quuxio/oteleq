"""Qualify the fixed resource diagnostic and reject altered retained channels."""
import argparse
import hashlib
import json
import os
from pathlib import Path
import sys

from qualify_generation import command


def main() -> None:
    """Run both actual lanes before checking an explicit evidence-only control."""
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--otelc-root", type=Path, required=True)
    parser.add_argument("--report-dir", type=Path, required=True)
    parser.add_argument("--cli", type=Path, required=True)
    args = parser.parse_args()
    root, cli = args.otelc_root.resolve(strict=True), args.cli.resolve(strict=True)
    destination = args.report_dir.resolve()
    repository = Path(__file__).resolve().parents[1]
    if any(destination.is_relative_to(parent) for parent in (root, repository)):
        parser.error("qualification directory must be new and outside both repositories")
    destination.mkdir(mode=0o700, exist_ok=False)
    os.environ["PYTHONDONTWRITEBYTECODE"] = "1"
    command([sys.executable, repository / "examples/capture_otelc_languages.py", "--otelc-root", root,
             "--report-dir", destination / "capture", "--comparator", cli, "--workload", "python-resource"],
            destination, "capture")
    evidence = destination / "capture/python"
    bundle = json.loads((evidence / "bundle.json").read_text())
    assert json.loads((evidence / "comparison.json").read_text())["verdict"] == "equivalent_observed"
    case = bundle["cases"][0]
    assert len(case["baseline"]) == len(case["instrumented_on"]) == 2
    for attempt in case["instrumented_on"]:
        assert attempt["witness"]["spans"] == 3 and not any(attempt["witness"]["losses"].values())
        attempt["channels"]["stdout"] += list(b"altered retained channel\n")
    (destination / "altered-bundle.json").write_text(json.dumps(bundle))
    command([cli, "compare-workload", destination / "altered-bundle.json"], destination, "altered-comparison", expected=1)
    summary = {"claim": "equivalence over these tests and observations", "artefact_class": "diagnostic",
               "scope": "fixed Python resource workload only; no generated object sequences or all-language claim",
               "oteleq_cli_sha256": hashlib.sha256(cli.read_bytes()).hexdigest(),
               "otelc_cli_sha256": hashlib.sha256((root / "target/debug/quux-otelc").read_bytes()).hexdigest(),
               "source_sha256": bundle["scope"]["source_sha256"], "attempts": 4, "spans_per_instrumented_attempt": 3,
               "resource_instances": 2, "expected_failed_releases": 1, "metric_and_creation_link_checks": True,
               "altered_retained_stdout_rejected": True, "source_preserved": True}
    (destination / "qualification.json").write_text(json.dumps(summary, indent=2) + "\n")
    print(json.dumps(summary), flush=True)


if __name__ == "__main__":
    main()
