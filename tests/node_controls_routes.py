"""Qualify reduced and fresh-source live-control suites on actual applications."""

import hashlib
import json
from pathlib import Path
import sys

import node_controls_oracle as oracle
from qualify_generation import command
from qualify_project_tests import command as project_command
import qualify_node_controls as controls


def current_suite(bundle: Path, application: Path, folder: Path, name: str, *, result: float) -> set[tuple[str, int]]:
    """Check the fresh snapshot and complete observations after a real body change."""
    output = project_command([sys.executable, "-I", "-B", bundle / "test_equivalence.py"],
        folder, name, 1, {"OTELEQ_SOURCE": str(application), "OTELEQ_WORKSPACE_PARENT": str(folder)})
    rows = [json.loads(line) for line in output.splitlines()]
    if len(rows) != len(oracle.METHODS) + 1 or rows[0].get("project_source") != str(application):
        raise ValueError("promoted live-control suite lost its current source or cases")
    workspace = Path(rows[0]["workspace"])
    plan = json.loads((workspace / "plan.json").read_bytes())
    for name, digest in plan["source_manifest"].items():
        if hashlib.sha256((application / name).read_bytes()).hexdigest() != digest:
            raise ValueError("promoted live-control snapshot differs from current source")
    identities, methods = set(), set()
    for row in rows[1:]:
        path = Path(row["report"])
        case = json.loads(path.read_bytes())["cases"][0]
        method = case["function"].rsplit('.', 1)[-1]
        if method in methods:
            raise ValueError("promoted live-control suite repeated a method")
        methods.add(method)
        identities |= controls.check_report(path, {method}, result=result)
    if methods != set(oracle.METHODS) or len(identities) != 16:
        raise ValueError("promoted live-control suite did not execute every method independently")
    return identities


def retained_routes(cli: Path, profile: Path, workspace: Path, filename: Path) -> dict:
    """Preserve all four states through reduction, replay and current-source promotion."""
    folder = profile / "retained-routes"
    folder.mkdir(mode=0o700)
    report = json.loads((profile / "comparison/report.json").read_bytes())
    target = next(case for case in report["cases"] if case["function"].endswith('.difference'))
    reduced = folder / "shrink"
    command([cli, "shrink", "--workspace", workspace, "--case", target["case"],
             "--report-dir", reduced, "--trials", "1"], folder, "shrink", expected=1)
    shrink = json.loads((reduced / "shrink.json").read_bytes())
    if (shrink["original_arguments"] != [7] or shrink["reduced_arguments"] != [1]
            or shrink["status"] != "candidate_rule_minimal" or len(shrink["trials"]) != 1):
        raise ValueError("live-control reduction lost its independent domain or stable difference")
    identities = set()
    for path in [reduced / "original/report.json", reduced / "confirmation/report.json",
                 *[Path(trial["report"]) for trial in shrink["trials"]]]:
        identities |= controls.check_report(path, {"difference"})
    replay = Path(shrink["workspace"])
    identities |= controls.framework(replay, folder, "reduced-framework", {"difference"})
    output = json.loads(command([cli, "replay", "--workspace", replay, "--case", target["case"]],
                                folder, "reduced-replay", expected=1))
    identities |= controls.check_report(Path(output["report"]), {"difference"})
    if len(identities) != 20:
        raise ValueError("live-control reduction/replay launch count differs")
    bundle = folder / "project-tests"
    application = filename.parent
    arguments = [cli, "promote", "--workspace", workspace, "--source", application, "--destination", bundle]
    dry = json.loads(command(arguments, folder, "promote-plan"))
    if dry["mode"] != "dry-run" or len(dry["files"]) != 6 or bundle.exists():
        raise ValueError("live-control promotion dry-run changed files")
    command([*arguments, "--apply"], folder, "promote-apply")
    identities |= current_suite(bundle, application, folder, "promoted-original", result=42)
    original = filename.read_text()
    if original.count('return 42;') != 4:
        raise ValueError("live-control body-change fixture differs")
    try:
        filename.write_text(original.replace('return 42;', 'return 43;'))
        identities |= current_suite(bundle, application, folder, "promoted-changed", result=43)
    finally:
        filename.write_text(original)
    if len(identities) != 52:
        raise ValueError("live-control retained routes reused an application")
    record = {"actual_applications": len(identities), "application_identities": sorted(identities),
              "reduced_arguments": shrink["reduced_arguments"], "changed_return": 43,
              "source_preserved": filename.read_text() == original}
    (folder / "QUALIFICATION.json").write_text(json.dumps(record, indent=2) + '\n')
    return record
