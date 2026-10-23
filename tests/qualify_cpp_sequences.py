"""Qualify ordered C++ calls against fixed state, alias and telemetry oracles."""
import argparse
import hashlib
import json
import os
from pathlib import Path
import sys

ROOT = Path(__file__).resolve().parents[1]
sys.path[:0] = [str(ROOT / "adapters/generation"), str(ROOT / "examples")]
import cpp_graph
import typed_capture

from qualify_cpp_receivers import SOURCE as RECEIVER_SOURCE, check_state, function, node, scalar
from qualify_project_tests import command
import sequence_qualification as shared
from sequence_qualification import CONTROL_VERDICTS

METHODS = ("identity", "secret", "transient", "fail", "recursive", "touch")
SOURCE = RECEIVER_SOURCE.replace(
    "int secret(Count amount){value_+=amount;return value_;}",
    "int secret(Count amount){value_+=amount;total_+=amount;return value_;}",
).replace(
    "void touch(Count amount){value_+=amount;}",
    "void touch(Count amount){value_+=amount;total_+=amount;}",
).replace(
    'int fail(Count amount){value_+=amount;throw std::runtime_error("expected");}',
    'int fail(Count amount){value_+=amount;total_+=amount;if(amount!=2)throw std::runtime_error("expected");return 7;}',
).replace(
    " int instance(Count amount)",
    " int transient(Count amount){if(amount==2){value_=19;total_=9;}else{value_+=amount+active();total_+=amount;}return 7;}\n"
    " int recursive(Count amount){if(amount>0)recursive(0);value_+=amount;total_+=amount;return 7;}\n"
    " int instance(Count amount)",
)
FUNCTIONS = {function(method): method for method in METHODS}
BOUND_SOURCE = '''#include <cstdint>
namespace sample {
using Count=std::int16_t;
class Counter {
 Count value_;Counter* self_;inline static Count total_=0;
public:
 explicit Counter(Count seed):value_(seed),self_(this){}
 Counter& identity(Count amount){value_+=amount;total_+=amount;return *this;}
};
}
'''


def prepare(cli: Path, provider: Path, folder: Path, *, steps: int = 2,
            methods: tuple[str, ...] = METHODS, compact: bool = False) -> Path:
    """Freeze independent construction and one, two or thirty-two fixed calls."""
    assert steps in (1, 2, 32)
    folder.mkdir()
    source = folder / "application"
    source.mkdir()
    assert not compact or methods == ("identity",)
    (source / "app.cpp").write_text(BOUND_SOURCE if compact else SOURCE)
    text = 'schema_version=1\nlanguages=["cpp"]\n[functions]\ninclude='
    text += json.dumps([function(method) for method in methods]) + "\n"
    for method in methods:
        text += '\n[[fixtures]]\nfunction=' + json.dumps(function(method)) + '\ncases=[[7]]\n'
        factory = "sample::Counter::create" if method == "secret" else "sample::Counter"
        text += 'receiver={factory=' + json.dumps(factory) + ',arguments=[10]}\n'
        error = ',expected_baseline={kind="error",category="exception",type="cpp.exception.std::runtime_error"}' if method == "fail" else ""
        calls = ['{action="call",arguments="case"' + error + '}']
        calls += ['{action="call",arguments=[' + str(2 if steps == 2 else 0) + ']}'] * (steps - 1)
        text += 'sequence=[' + ','.join(calls) + ']\n'
        if method == "transient":
            text += 'domains=[{kind="integer",minimum=0,maximum=7}]\n'
    config = folder / "equivalence.toml"
    config.write_text(text)
    return shared.plan_generate(cli, provider, folder, source, config, {function(method) for method in methods})


def check_graph(graph: dict, value: int, total: int, argument: int, compact: bool) -> None:
    """The bounded positive profile has its own complete, smaller source graph."""
    if not compact:
        check_state(graph, value, total, argument)
        return
    roots = graph["roots"]
    assert {"receiver", "argument:0", "global:sample::Counter::total_"} <= set(roots)
    receiver = node(graph, roots["receiver"])
    fields = receiver["fields"]
    assert set(fields) == {"location", "field:value_", "field:self_"}
    scalar(graph, fields["field:value_"], value, short=True)
    scalar(graph, roots["argument:0"], argument, short=True)
    scalar(graph, roots["global:sample::Counter::total_"], total, short=True)
    assert node(graph, fields["field:self_"])["fields"]["value"] == roots["receiver"]
    assert fields["location"] == node(graph, fields["field:value_"])["fields"]["location"]


def check_observation(observed: dict, method: str, amount: int, active: bool,
                      *, steps: int = 2, compact: bool = False) -> None:
    """Check all fields, scalar bits, aliases, outcomes and intermediate states."""
    assert method in METHODS and type(amount) is int and 0 <= amount <= 7
    assert steps in (1, 2, 32) and not observed["gaps"] and len(observed["steps"]) == steps
    value, total = 10, 0
    arguments = [amount] + [2 if steps == 2 else 0] * (steps - 1)
    for index, (step, argument) in enumerate(zip(observed["steps"], arguments)):
        assert (step["id"], step["action"], step["gaps"]) == ("step-" + str(index), "call", [])
        check_graph(step["before"], value, total, argument, compact)
        if method == "transient" and argument == 2:
            value, total = 19, 9
        else:
            value += argument + int(method == "transient" and active)
            total += argument
        check_graph(step["after"], value, total, argument, compact)
        outcome = step["outcome"]
        graph = outcome["graph"]
        check_graph(graph, value, total, argument, compact)
        error = method == "fail" and argument != 2
        assert outcome["kind"] == ("error" if error else "return")
        if error:
            assert outcome["category"] == "exception"
            assert graph["roots"]["error"] == {"kind": "bytes", "type": "cpp.exception.std::runtime_error", "hex": b"expected".hex()}
        elif method == "identity":
            returned = node(graph, graph["roots"]["result"])
            assert returned["fields"]["value"] == graph["roots"]["receiver"]
            assert returned["fields"]["location"] == node(graph, graph["roots"]["receiver"])["fields"]["location"]
        elif method == "touch":
            assert graph["roots"]["result"] == {"kind": "unit", "type": "cpp.unit"}
        else:
            scalar(graph, graph["roots"]["result"], value if method == "secret" else 7)
    assert observed["before"] == observed["steps"][0]["before"]
    assert observed["after"] == observed["steps"][-1]["after"]
    assert observed["outcome"] == observed["steps"][-1]["outcome"]


def check_report(path: Path, count: int, *, steps: int = 2, compact: bool = False) -> int:
    """Equal but wrong fixtures cannot qualify in either lane or any repeat."""
    report = json.loads(path.read_text())
    assert report["source_preserved"] and not report["blocked"] and len(report["cases"]) == count
    assert len({case["function"] for case in report["cases"]}) == count
    if count == len(METHODS):
        assert {case["function"] for case in report["cases"]} == set(FUNCTIONS)
    observations = 0
    for case in report["cases"]:
        method = FUNCTIONS[case["function"]]
        assert case["exit_code"] == int(method == "transient")
        assert case["receiver_fixture"]["arguments"] == [10]
        bundle = json.loads((path.parent / case["case"] / "typed-bundle.json").read_text())["cases"][0]
        roots = {"receiver", "argument:0", "global:sample::Counter::total_"}
        shared.check_contract(bundle, roots, steps)
        for lane in ("baseline", "instrumented_on"):
            assert len(bundle[lane]) == 2
            for attempt in bundle[lane]:
                observations += 1
                check_observation(attempt["observation"], method, case["arguments"][0], lane == "instrumented_on", steps=steps, compact=compact)
                expected = steps + (int(case["arguments"][0] > 0) + int(steps == 2) if method == "recursive" else 0)
                shared.check_execution(attempt, case["function"], expected, active=lane == "instrumented_on")
    return observations


def framework(workspace: Path, folder: Path, name: str, count: int = len(METHODS)) -> int:
    """Check the retained unittest against this language's independent graph oracle."""
    return shared.framework(workspace, folder, name, count, check_report)


def controls(cli: Path, report: Path, folder: Path) -> None:
    """Alter retained evidence using the declared C++ receiver field."""
    shared.controls(cli, report, folder, FUNCTIONS, node, 'field:value_')


def verify_operations(folder: Path, cli: Path, *, historical_source_expectation: bool = False) -> int:
    """Verify exact terminal receipts for the declared C++ routes."""
    return shared.verify_operations(folder, cli, METHODS, FUNCTIONS, ("edge-rich-thirty-two",),
        historical_source_expectation=historical_source_expectation)


def verify_budget_refusal(folder: Path) -> int:
    """A valid rich sequence exceeding the shared case budget stays incomplete."""
    report = json.loads((folder / "comparison/report.json").read_text())
    assert report["source_preserved"] and not report["blocked"] and len(report["cases"]) == 1
    case = report["cases"][0]
    assert case["function"] == function("identity") and case["exit_code"] == 4
    assert case["error"] == "case observation exceeds comparator channel budget"
    assert len(case["sequence"]) == 32 and case["arguments"] == [7]
    commands = list((folder / "comparison").rglob("command.json"))
    assert len(commands) == 1 and commands[0].parent.name == "baseline-0"
    raw = (commands[0].parent / "observation").read_bytes()
    assert 262144 < len(raw) <= 790528
    entry = next(row for row in report["inventory"] if row.get("otelc_function") == case["function"])
    observed = cpp_graph.boundaries(raw, entry, typed_capture.native_scalar)
    observed["gaps"] = []
    check_observation(observed, "identity", 7, False, steps=32)
    return 1


def verify_routes(folder: Path) -> None:
    """Require every language-specific function and fixed input on every retained route."""
    shared.verify_routes(folder, METHODS, FUNCTIONS, function)


def verify_receipts(folder: Path) -> int:
    """Decode actual OTLP independently and require each fixture's exact trees."""

    checked = 0
    for path in folder.rglob("instrumented_on-*/command.json"):
        attempt = path.parent
        observed = json.loads((attempt / "typed-observation.json").read_text())
        method = FUNCTIONS[observed["function_id"]]
        amounts = [int(node(step["before"], step["before"]["roots"]["argument:0"])["fields"]["value"]["value"])
                   for step in observed["steps"]]
        expected = [1 + int(method == "recursive" and value > 0) for value in amounts]
        spans, counters = shared.decode_receipt(attempt)
        shared.check_serial_trees(spans, expected, observed["function_id"])
        assert set(counters) == {"otelc.function.calls", "otelc.function.duration"}
        assert all(values and max(values) == len(spans) for values in counters.values())
        runtime = json.loads((attempt / "runtime.json").read_text())
        assert runtime["function_calls"] == len(spans) and runtime["drained"] and runtime["export_finished"]
        assert runtime["export_dropped_batches"] == 0 and not any(runtime["losses"].values())
        assert runtime["traces"] == {"active_trees": 0, "completed_trees": len(expected),
            "losses": {}, "queued_trees": 0, "sampled_out_roots": 0}
        identities = json.loads((attempt / "build-identities.json").read_text())
        assert identities["application"] == hashlib.sha256((attempt / "scratch/application").read_bytes()).hexdigest()
        checked += 1
    assert checked
    return checked


def retained(folder: Path, cli: Path, *, historical_source_expectation: bool = False) -> dict:
    """Recheck every recorded state and source seal without new application runs."""
    reports = sorted(folder.rglob("report.json"))
    assert reports
    verify_routes(folder)
    refused = verify_budget_refusal(folder / "edge-rich-thirty-two")
    observations, comparisons = shared.compare_reports(folder, reports, cli, check_report, ("edge-rich-thirty-two",))
    raw = [path for path in folder.rglob("command.json") if path.parent.name.startswith(("baseline-", "instrumented_on-"))]
    identities = {hashlib.sha256(path.read_bytes()).hexdigest() for path in raw}
    assert observations == 152 and len(raw) == observations + refused == 153
    assert len(identities) == 149 and comparisons == 38
    shared.verify_sources(folder)
    return {"claim": "equivalence over these tests and observations", "artefact_class": "diagnostic",
        "cli_sha256": hashlib.sha256(cli.read_bytes()).hexdigest(), "cases": len(METHODS),
        "matching_cases": len(METHODS) - 1, "intermediate_difference_controls": 1,
        "qualified_reports": len(reports), "retained_observations": observations,
        "recomputed_comparisons": comparisons, "raw_instrumented_receipts": verify_receipts(folder),
        "actual_application_launches": len(identities), "required_operations": verify_operations(folder, cli,
            historical_source_expectation=historical_source_expectation),
        "source_control_recorded_expectation": 2 if historical_source_expectation else 4,
        "source_control_actual_exit": 4,
        "historical_source_expectation_corrected": historical_source_expectation,
        "evidence_refusals": len(CONTROL_VERDICTS), "source_preserved": True,
        "actual_budget_refusal_launches": refused,
        "scope": "Declared C++ source receivers, call-only schedules, private factories, intermediate standard errors, recursion and aliases. No invocation attribution, shipping artefact or other provider/platform admission."}


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--otelc-root", type=Path, required=True)
    parser.add_argument("--report-dir", type=Path, required=True)
    parser.add_argument("--cli", type=Path, required=True)
    parser.add_argument("--recheck", action="store_true")
    parser.add_argument("--historical-source-expectation", action="store_true",
        help="retained-only recovery of the original source control's recorded expectation 2; actual exit must be 4")
    args = parser.parse_args()
    if args.historical_source_expectation and not args.recheck:
        parser.error("historical source expectation is only valid with --recheck")
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
            edge_workspace = prepare(cli, provider, edge, steps=steps, methods=("identity",), compact=compact)
            command([cli, "run", "--workspace", edge_workspace, "--report-dir", edge / "comparison"], edge, "run", expected)
            if expected:
                verify_budget_refusal(edge)
            else:
                check_report(edge / "comparison/report.json", 1, steps=steps, compact=compact)
        path = source / "app.cpp"
        original = path.read_bytes()
        try:
            path.write_bytes(original + b"\n// changed-source refusal\n")
            command([cli, "replay", "--workspace", workspace, "--case", target["case"]], folder, "changed-source", 4)
        finally:
            path.write_bytes(original)
    result = retained(folder, cli, historical_source_expectation=args.historical_source_expectation)
    (folder / "qualification.json").write_text(json.dumps(result, indent=2) + "\n")
    print(json.dumps(result), flush=True)


if __name__ == "__main__":
    main()
