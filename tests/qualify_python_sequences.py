"""Qualify ordered Python calls against complete independent graphs and raw telemetry."""
import argparse
import hashlib
import json
import os
from pathlib import Path
import sys

ROOT = Path(__file__).resolve().parents[1]
sys.path[:0] = [str(ROOT / "adapters/generation"), str(ROOT / "examples")]
from python_sequence_fixture import (BUDGET_SOURCE, COMPACT_SOURCE, FUNCTIONS, METHODS, REBOUND_SOURCE,
                                     SOURCE, check_observation, function, node, raw_observation)
from qualify_project_tests import command
import sequence_qualification as shared
from sequence_qualification import CONTROL_VERDICTS


def prepare(cli: Path, provider: Path, folder: Path, *, steps: int = 2,
            methods: tuple[str, ...] = METHODS, compact: bool = False,
            padding: bool = False, rebound: bool = False) -> Path:
    """Freeze real package imports, independent construction and concrete calls."""
    assert steps in (1, 2, 32) and sum((compact, padding, rebound)) <= 1
    folder.mkdir()
    source = folder / "application"
    package = source / "src/pkg"
    package.mkdir(parents=True)
    (package / "__init__.py").write_text("")
    assert not compact or methods == ("identity",)
    text = COMPACT_SOURCE if compact else BUDGET_SOURCE if padding else REBOUND_SOURCE if rebound else SOURCE
    (package / "state.py").write_text(text)
    text = 'schema_version=1\nlanguages=["python"]\n[adapters.python]\nimport_roots=["src"]\n[functions]\ninclude='
    text += json.dumps([function(method) for method in methods]) + "\n"
    for method in methods:
        text += '\n[[fixtures]]\nfunction=' + json.dumps(function(method)) + '\ncases=[[7]]\n'
        factory = "make_counter" if method == "secret" else "Counter"
        text += 'receiver={factory=' + json.dumps(factory) + ',arguments=[10]}\n'
        error = ',expected_baseline={kind="error",category="exception",type="python.builtins.ValueError"}' if method == "fail" else ""
        calls = ['{action="call",arguments="case"' + error + '}']
        calls += ['{action="call",arguments=[' + str(2 if steps == 2 else 0) + ']}'] * (steps - 1)
        text += 'sequence=[' + ','.join(calls) + ']\n'
        if method == "transient":
            text += 'domains=[{kind="integer",minimum=0,maximum=7}]\n'
    config = folder / "equivalence.toml"
    config.write_text(text)
    return shared.plan_generate(cli, provider, folder, source, config, {function(method) for method in methods})


def check_report(path: Path, count: int, *, steps: int = 2, compact: bool = False) -> int:
    """Check complete independently expected raw and typed graphs in every lane."""
    report = json.loads(path.read_text())
    assert report["source_preserved"] and not report["blocked"] and len(report["cases"]) == count
    assert len({case["function"] for case in report["cases"]}) == count
    if count == len(METHODS):
        assert {case["function"] for case in report["cases"]} == set(FUNCTIONS)
    observations = 0
    roots = {"receiver", "arguments", "static:Counter.total"}
    if not compact:
        roots |= {"global:created", "static:Counter.instances", "static:Counter.shared"}
    for case in report["cases"]:
        method = FUNCTIONS[case["function"]]
        assert case["exit_code"] == int(method == "transient")
        assert case["receiver_fixture"]["arguments"] == [10]
        bundle = json.loads((path.parent / case["case"] / "typed-bundle.json").read_text())["cases"][0]
        shared.check_contract(bundle, roots, steps)
        for lane in ("baseline", "instrumented_on"):
            assert len(bundle[lane]) == 2
            for index, attempt in enumerate(bundle[lane]):
                observations += 1
                active = lane == "instrumented_on"
                raw = path.parent / case["case"] / (lane + "-" + str(index)) / "observation"
                assert json.loads(raw.read_text()) == raw_observation(method, case["arguments"][0], active, steps=steps, compact=compact), str(raw)
                check_observation(attempt["observation"], method, case["arguments"][0], active, steps=steps, compact=compact)
                expected = steps + (int(case["arguments"][0] > 0) + int(steps == 2) if method == "recursive" else 0)
                shared.check_execution(attempt, case["function"], expected, active=lane == "instrumented_on")
    return observations


def framework(workspace: Path, folder: Path, name: str, count: int = len(METHODS)) -> int:
    """Check the retained unittest against this language's independent graph oracle."""
    return shared.framework(workspace, folder, name, count, check_report)


def controls(cli: Path, report: Path, folder: Path) -> None:
    """Alter retained evidence using the declared Python receiver field."""
    shared.controls(cli, report, folder, FUNCTIONS, node, 'property:value')


def verify_operations(folder: Path, cli: Path) -> int:
    """Verify exact terminal receipts for the declared Python routes."""
    return shared.verify_operations(folder, cli, METHODS, FUNCTIONS, ("edge-rich-thirty-two", "rebound-class"))


def verify_budget_refusal(folder: Path) -> int:
    """A declared rich graph exceeding the shared budget must remain refused."""
    report = json.loads((folder / "comparison/report.json").read_text())
    assert report["source_preserved"] and not report["blocked"] and len(report["cases"]) == 1
    case = report["cases"][0]
    assert case["function"] == function("identity") and case["exit_code"] == 4
    assert case["error"] == "case observation exceeds comparator channel budget"
    assert len(case["sequence"]) == 32 and case["arguments"] == [7]
    commands = list((folder / "comparison").rglob("command.json"))
    assert len(commands) == 1 and commands[0].parent.name == "baseline-0"
    raw = (commands[0].parent / "observation").read_bytes()
    assert 262144 < len(raw) <= 1048576
    assert json.loads(raw) == raw_observation("identity", 7, False, steps=32, padding=True)
    return 1


def verify_class_refusal(folder: Path) -> int:
    """Coordinated module/instance rebinding cannot retain a passing old class view."""
    report = json.loads((folder / "comparison/report.json").read_text())
    assert report["source_preserved"] and not report["blocked"] and len(report["cases"]) == 1
    case = report["cases"][0]
    assert case["function"] == function("identity") and case["arguments"] == [7]
    assert case["exit_code"] == 4 and len(case["sequence"]) == 2
    assert case["error"] == "application exit or OTLP capture failed; inspect retained stdout/stderr"
    commands = list((folder / "comparison").rglob("command.json"))
    assert len(commands) == 1 and commands[0].parent.name == "baseline-0"
    attempt = commands[0].parent
    assert not (attempt / "observation").exists() and not (attempt / "typed-observation.json").exists()
    assert (attempt / "stdout").read_bytes() == b""
    assert (attempt / "stderr").read_bytes().endswith(
        b"ValueError: receiver class binding differs from its frozen source identity\n")
    return 1


def verify_routes(folder: Path) -> None:
    """Require every language-specific function and fixed input on every retained route."""
    shared.verify_routes(folder, METHODS, FUNCTIONS, function)


def verify_receipts(folder: Path) -> int:
    """Decode raw OTLP against independently expected call/recursive/error counts."""

    checked = 0
    for path in folder.rglob("instrumented_on-*/command.json"):
        attempt = path.parent
        observed = json.loads((attempt / "typed-observation.json").read_text())
        method = FUNCTIONS[observed["function_id"]]
        amounts = [int(node(step["before"], step["before"]["roots"]["arguments"])["fields"]["item:0"]["value"])
                   for step in observed["steps"]]
        expected = [1 + int(method == "recursive" and value > 0) for value in amounts]
        errors = sum(method == "fail" and value != 2 for value in amounts)
        spans, counters = shared.decode_receipt(attempt)
        shared.check_serial_trees(spans, expected, observed["function_id"])
        assert sum(span.status.code == 2 for span in spans) == errors
        assert set(counters) == {"otelc.function.calls", "otelc.function.duration"}
        assert all(values and max(values) == len(spans) for values in counters.values())
        runtime = json.loads((attempt / "runtime.json").read_text())
        assert runtime["language"] == "python" and runtime["function_calls"] == len(spans) and runtime["export_finished"]
        assert runtime["export_loss"] == 0 and not any(runtime["losses"].values())
        assert runtime["functions"] == {observed["function_id"]: {"count": len(spans), "unwinds": errors}}
        assert runtime["traces"] == {"active_trees": 0, "completed_trees": len(expected),
            "losses": {}, "queued_trees": 0, "sampled_out_roots": 0, "pending_contexts": 0}
        checked += 1
    assert checked
    return checked


def retained(folder: Path, cli: Path) -> dict:
    """Recheck every recorded state and source seal without new application runs."""
    reports = sorted(folder.rglob("report.json"))
    assert reports
    verify_routes(folder)
    refused = verify_budget_refusal(folder / "edge-rich-thirty-two")
    class_refused = verify_class_refusal(folder / "rebound-class")
    observations, comparisons = shared.compare_reports(folder, reports, cli, check_report, ("edge-rich-thirty-two", "rebound-class"))
    raw = [path for path in folder.rglob("command.json") if path.parent.name.startswith(("baseline-", "instrumented_on-"))]
    identities = {hashlib.sha256(path.read_bytes()).hexdigest() for path in raw}
    assert observations == 152 and len(raw) == observations + refused + class_refused == 154
    assert len(identities) == 150 and comparisons == 38
    shared.verify_sources(folder)
    return {"claim": "equivalence over these tests and observations", "artefact_class": "diagnostic",
        "cli_sha256": hashlib.sha256(cli.read_bytes()).hexdigest(), "cases": len(METHODS),
        "matching_cases": len(METHODS) - 1, "intermediate_difference_controls": 1,
        "qualified_reports": len(reports), "retained_observations": observations,
        "recomputed_comparisons": comparisons, "raw_instrumented_receipts": verify_receipts(folder),
        "actual_application_launches": len(identities), "required_operations": verify_operations(folder, cli),
        "source_control_actual_exit": 4,
        "evidence_refusals": len(CONTROL_VERDICTS), "source_preserved": True,
        "actual_budget_refusal_launches": refused,
        "actual_class_refusal_launches": class_refused,
        "scope": "Declared plain Python package receivers, call-only schedules, source factories, intermediate exceptions, recursion and complete raw/typed graph oracles. No invocation attribution, shipping artefact or other provider/platform admission."}


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--otelc-root", type=Path, required=True)
    parser.add_argument("--report-dir", type=Path, required=True)
    parser.add_argument("--cli", type=Path, required=True)
    parser.add_argument("--recheck", action="store_true")
    args = parser.parse_args()
    if sys.flags.optimize:
        parser.error("qualification requires Python assertion checks")
    cli, provider, folder = args.cli.resolve(strict=True), args.otelc_root.resolve(strict=True), args.report_dir.resolve()
    if folder.is_relative_to(provider) or folder.is_relative_to(Path(__file__).resolve().parents[1]):
        parser.error("qualification directory must be new and external")
    if not args.recheck:
        folder.mkdir(mode=0o700)
        os.environ.update(OTELEQ_PYTHON=sys.executable, OTELEQ_CLI=str(cli))
        workspace = prepare(cli, provider, folder / "cases")
        source, target = shared.exercise_routes(cli, folder, workspace, METHODS, FUNCTIONS,
            check_report, controls, framework)
        for name, steps, compact, expected in (("edge-one", 1, False, 0),
                ("edge-rich-thirty-two", 32, False, 4), ("edge-thirty-two", 32, True, 0)):
            edge = folder / name
            edge_workspace = prepare(cli, provider, edge, steps=steps, methods=("identity",), compact=compact, padding=name == "edge-rich-thirty-two")
            command([cli, "run", "--workspace", edge_workspace, "--report-dir", edge / "comparison"], edge, "run", expected)
            if expected:
                verify_budget_refusal(edge)
            else:
                check_report(edge / "comparison/report.json", 1, steps=steps, compact=compact)
        rebound = folder / "rebound-class"
        rebound_workspace = prepare(cli, provider, rebound, methods=("identity",), rebound=True)
        command([cli, "run", "--workspace", rebound_workspace, "--report-dir", rebound / "comparison"], rebound, "run", 4)
        verify_class_refusal(rebound)
        path = source / "src/pkg/state.py"
        original = path.read_bytes()
        try:
            path.write_bytes(original + b"\n# changed-source refusal\n")
            command([cli, "replay", "--workspace", workspace, "--case", target["case"]], folder, "changed-source", 4)
        finally:
            path.write_bytes(original)
    result = retained(folder, cli)
    (folder / "qualification.json").write_text(json.dumps(result, indent=2) + "\n")
    print(json.dumps(result), flush=True)


if __name__ == "__main__":
    main()
