"""Qualify ordered Python calls against complete independent graphs and raw telemetry."""
import argparse
import copy
import hashlib
import json
import os
from pathlib import Path
import subprocess
import sys

ROOT = Path(__file__).resolve().parents[1]
sys.path[:0] = [str(ROOT / "adapters/generation"), str(ROOT / "examples")]
from python_sequence_fixture import (BUDGET_SOURCE, COMPACT_SOURCE, FUNCTIONS, METHODS,
                                     SOURCE, check_observation, function, node, raw_observation)
from qualify_project_tests import command

CONTROL_VERDICTS = {
    "missing-call": (3, "inconclusive"),
    "reordered-calls": (3, "inconclusive"),
    "missing-field": (1, "different_observed"),
    "missing-method-witness": (3, "inconclusive"),
    "undeclared-intermediate-error": (2, "blocked"),
}


def prepare(cli: Path, provider: Path, folder: Path, *, steps: int = 2,
            methods: tuple[str, ...] = METHODS, compact: bool = False,
            padding: bool = False) -> Path:
    """Freeze real package imports, independent construction and concrete calls."""
    assert steps in (1, 2, 32) and not (compact and padding)
    folder.mkdir()
    source = folder / "application"
    package = source / "src/pkg"
    package.mkdir(parents=True)
    (package / "__init__.py").write_text("")
    assert not compact or methods == ("identity",)
    (package / "state.py").write_text(COMPACT_SOURCE if compact else BUDGET_SOURCE if padding else SOURCE)
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
    workspace = Path(command([cli, "plan", "--source", source, "--otelc-root", provider,
        "--workspace-parent", folder, "--config", config], folder, "plan"))
    plan = json.loads((workspace / "plan.json").read_text())
    assert {row["otelc_function"] for row in plan["inventory"] if row["status"] == "ready"} == {function(method) for method in methods}
    assert not any(row["status"] == "blocked" for row in plan["inventory"])
    command([cli, "generate", "--workspace", workspace], folder, "generate")
    return workspace






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
        assert set(bundle["contract"]["required_roots"]) == roots
        assert len(bundle["contract"]["steps"]) == steps
        for index, step in enumerate(bundle["contract"]["steps"]):
            assert (step["id"], step["action"], set(step["required_roots"])) == ("step-" + str(index), "call", roots)
        for lane in ("baseline", "instrumented_on"):
            assert len(bundle[lane]) == 2
            for index, attempt in enumerate(bundle[lane]):
                observations += 1
                active = lane == "instrumented_on"
                raw = path.parent / case["case"] / (lane + "-" + str(index)) / "observation"
                assert json.loads(raw.read_text()) == raw_observation(method, case["arguments"][0], active, steps=steps, compact=compact), str(raw)
                check_observation(attempt["observation"], method, case["arguments"][0], active, steps=steps, compact=compact)
                assert all(attempt["execution"]["channels"][name] == [] for name in ("stdout", "stderr"))
                if active:
                    expected = steps + (int(case["arguments"][0] > 0) + int(steps == 2) if method == "recursive" else 0)
                    witness = attempt["execution"]["witness"]
                    assert witness["functions"] == {case["function"]: expected} and witness["spans"] == expected
                    assert not any(witness["losses"].values()) and witness["pending"] == 0
    return observations


def framework(workspace: Path, folder: Path, name: str, count: int = len(METHODS)) -> int:
    """The deliberate intermediate difference must fail the retained unittest."""
    output = command([sys.executable, workspace / "tests/test_equivalence.py"], folder, name, 1)
    reports = [json.loads(line) for line in output.splitlines()]
    assert len(reports) == count
    assert "Ran " + str(count) + " test" in (folder / (name + ".stderr")).read_text()
    return sum(check_report(Path(row["report"]), 1) for row in reports)


def controls(cli: Path, report: Path, folder: Path) -> None:
    """Actual retained evidence is altered without counting copies as executions."""
    cases = {FUNCTIONS[row["function"]]: row for row in json.loads(report.read_text())["cases"]}
    def bundle(method: str) -> dict:
        return json.loads((report.parent / cases[method]["case"] / "typed-bundle.json").read_text())
    original = bundle("identity")
    variants = {}
    for name in ("missing-call", "reordered-calls", "missing-field", "missing-method-witness"):
        changed = copy.deepcopy(original)
        for lane in (("baseline", "instrumented_on") if name in ("missing-call", "reordered-calls") else ("instrumented_on",)):
            for attempt in changed["cases"][0][lane]:
                observed = attempt["observation"]
                if name == "missing-call":
                    observed["steps"].pop()
                elif name == "reordered-calls":
                    observed["steps"].reverse()
                elif name == "missing-field":
                    graph = observed["steps"][0]["after"]
                    node(graph, graph["roots"]["receiver"])["fields"].pop("property:value")
                else:
                    attempt["execution"]["witness"]["functions"] = {}
        variants[name] = changed
    changed = bundle("fail")
    changed["cases"][0]["contract"]["steps"][0]["expected_baseline"] = {"kind": "return"}
    variants["undeclared-intermediate-error"] = changed
    for name, value in variants.items():
        path = folder / (name + ".json")
        path.write_text(json.dumps(value))
        command([cli, "compare-observations", path], folder, name, CONTROL_VERDICTS[name][0])


def verify_operations(folder: Path, cli: Path) -> int:
    """Require every route's terminal receipt; omissions cannot be a partial pass."""
    required = {"run": 1, "framework": 1, "export": 0, "export-run": 1,
        "export-framework": 1, "shrink": 1, "reduced-framework": 1, "reduced-replay": 1,
        "changed-source": 4, **{"replay-" + method: int(method == "transient") for method in METHODS},
        **{name: expected for name, (expected, _) in CONTROL_VERDICTS.items()}}
    workspace = Path((folder / "cases/plan.stdout").read_text().strip())
    assert workspace.is_relative_to(folder / "cases")
    provider = Path(json.loads((workspace / "plan.json").read_text())["otelc_root"])
    cases = {FUNCTIONS[case["function"]]: case["case"]
             for case in json.loads((folder / "comparison/report.json").read_text())["cases"]}
    reduced = Path(json.loads((folder / "shrink/shrink.json").read_text())["workspace"])
    expected_argv = {
        "run": [cli, "run", "--workspace", workspace, "--report-dir", folder / "comparison"],
        "framework": [sys.executable, workspace / "tests/test_equivalence.py"],
        "export": [cli, "export-tests", "--workspace", workspace, "--destination", folder / "exported", "--apply"],
        "export-run": [cli, "run", "--workspace", folder / "exported", "--report-dir", folder / "export-comparison"],
        "export-framework": [sys.executable, folder / "exported/tests/test_equivalence.py"],
        "shrink": [cli, "shrink", "--workspace", workspace, "--case", cases["transient"], "--report-dir", folder / "shrink", "--trials", "1"],
        "reduced-framework": [sys.executable, reduced / "tests/test_equivalence.py"],
        "reduced-replay": [cli, "replay", "--workspace", reduced, "--case", cases["transient"]],
        "changed-source": [cli, "replay", "--workspace", workspace, "--case", cases["transient"]],
        **{"replay-" + method: [cli, "replay", "--workspace", workspace, "--case", case] for method, case in cases.items()},
        **{name: [cli, "compare-observations", folder / (name + ".json")] for name in CONTROL_VERDICTS},
    }
    assert {path.name.removesuffix(".started.json") for path in folder.glob("*.started.json")} == set(required)
    for name, expected in required.items():
        marker = json.loads((folder / (name + ".started.json")).read_text())
        assert marker == {"argv": list(map(str, expected_argv[name])), "expected_exit": expected}
        assert (folder / (name + ".exit")).read_text() == str(expected) + "\n"
        for suffix in ("stdout", "stderr"):
            assert (folder / (name + "." + suffix)).is_file()
        if name in CONTROL_VERDICTS:
            assert json.loads((folder / (name + ".stdout")).read_text())["verdict"] == CONTROL_VERDICTS[name][1]
    assert (folder / "changed-source.stderr").read_bytes() == b"oteleq: application source or immutable snapshot changed\n"
    assert (folder / "changed-source.stdout").read_bytes() == b""
    for name in ("cases", "edge-one", "edge-thirty-two", "edge-rich-thirty-two"):
        route = folder / name
        selected = Path((route / "plan.stdout").read_text().strip())
        assert selected.is_relative_to(route)
        expected = {
            "plan": [cli, "plan", "--source", route / "application", "--otelc-root", provider,
                "--workspace-parent", route, "--config", route / "equivalence.toml"],
            "generate": [cli, "generate", "--workspace", selected],
        }
        if name != "cases":
            expected["run"] = [cli, "run", "--workspace", selected, "--report-dir", route / "comparison"]
        assert {path.name.removesuffix(".started.json") for path in route.glob("*.started.json")} == set(expected)
        for operation, argv in expected.items():
            marker = json.loads((route / (operation + ".started.json")).read_text())
            expected_exit = 4 if name == "edge-rich-thirty-two" and operation == "run" else 0
            assert marker == {"argv": list(map(str, argv)), "expected_exit": expected_exit}
        for operation in ("plan", "generate"):
            assert (folder / name / (operation + ".exit")).read_text() == "0\n"
        if name != "cases":
            assert (folder / name / "run.exit").read_text() == ("4\n" if name == "edge-rich-thirty-two" else "0\n")
    return len(required) + 11


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


def verify_routes(folder: Path) -> None:
    """Require each named route's complete methods and independently fixed inputs."""
    def report(path: Path, count: int, method: str | None = None, amount: int = 7) -> None:
        assert path.is_relative_to(folder)
        cases = json.loads(path.read_text())["cases"]
        assert len(cases) == count and all(case["arguments"] == [amount] for case in cases)
        if method:
            assert cases[0]["function"] == function(method)
        else:
            assert {case["function"] for case in cases} == set(FUNCTIONS)

    for name in ("comparison", "export-comparison"):
        report(folder / name / "report.json", len(METHODS))
    for method in METHODS:
        summary = json.loads((folder / ("replay-" + method + ".stdout")).read_text())
        report(Path(summary["report"]), 1, method)
    for name in ("framework", "export-framework", "reduced-framework"):
        rows = [json.loads(line) for line in (folder / (name + ".stdout")).read_text().splitlines()]
        reduced = name == "reduced-framework"
        assert len(rows) == (1 if reduced else len(METHODS))
        functions = []
        for row in rows:
            path = Path(row["report"])
            case = json.loads(path.read_text())["cases"][0]
            method = FUNCTIONS[case["function"]]
            report(path, 1, "transient" if reduced else method, 0 if reduced else 7)
            functions.append(method)
        assert set(functions) == ({"transient"} if reduced else set(METHODS))
    summary = json.loads((folder / "reduced-replay.stdout").read_text())
    report(Path(summary["report"]), 1, "transient", 0)
    for name in ("edge-one", "edge-thirty-two"):
        report(folder / name / "comparison/report.json", 1, "identity")


def verify_receipts(folder: Path) -> int:
    """Decode raw OTLP against independently expected call/recursive/error counts."""
    from opentelemetry.proto.collector.metrics.v1.metrics_service_pb2 import ExportMetricsServiceRequest
    from opentelemetry.proto.collector.trace.v1.trace_service_pb2 import ExportTraceServiceRequest

    checked = 0
    for path in folder.rglob("instrumented_on-*/command.json"):
        attempt = path.parent
        observed = json.loads((attempt / "typed-observation.json").read_text())
        method = FUNCTIONS[observed["function_id"]]
        amounts = [int(node(step["before"], step["before"]["roots"]["arguments"])["fields"]["item:0"]["value"])
                   for step in observed["steps"]]
        expected = [1 + int(method == "recursive" and value > 0) for value in amounts]
        errors = sum(method == "fail" and value != 2 for value in amounts)
        receipt = json.loads((attempt / "http-capture.json").read_text())
        assert not receipt["errors"]
        spans, counters = [], {}
        for body in receipt["bodies"]:
            raw = (attempt / body["file"]).read_bytes()
            if body["path"] == "/v1/traces":
                decoded = ExportTraceServiceRequest.FromString(raw)
                spans += [span for resource in decoded.resource_spans for scope in resource.scope_spans for span in scope.spans]
            else:
                assert body["path"] == "/v1/metrics"
                decoded = ExportMetricsServiceRequest.FromString(raw)
                for resource in decoded.resource_metrics:
                    for scope in resource.scope_metrics:
                        for metric in scope.metrics:
                            kind = metric.WhichOneof("data")
                            if metric.name in ("otelc.function.calls", "otelc.function.duration"):
                                assert kind == ("sum" if metric.name.endswith("calls") else "histogram")
                                counters.setdefault(metric.name, []).extend(
                                    point.as_int if kind == "sum" else point.count
                                    for point in getattr(metric, kind).data_points)
        roots = sorted((span for span in spans if not span.parent_span_id), key=lambda span: span.start_time_unix_nano)
        assert len(roots) == len(expected) and len(spans) == sum(expected)
        assert all(span.name == observed["function_id"] for span in spans)
        assert len({(span.trace_id, span.span_id) for span in spans}) == len(spans)
        assert sum(span.status.code == 2 for span in spans) == errors
        for index, (root, count) in enumerate(zip(roots, expected)):
            members = [span for span in spans if span.trace_id == root.trace_id]
            assert len(members) == count and len(root.trace_id) == 16 and any(root.trace_id)
            assert len(root.span_id) == 8 and any(root.span_id)
            assert 0 < root.start_time_unix_nano <= root.end_time_unix_nano
            if index:
                assert roots[index - 1].start_time_unix_nano < root.start_time_unix_nano
                assert roots[index - 1].end_time_unix_nano <= root.start_time_unix_nano
            for child in members:
                assert child is root or child.parent_span_id == root.span_id
                assert root.start_time_unix_nano <= child.start_time_unix_nano <= child.end_time_unix_nano <= root.end_time_unix_nano
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
    observations, comparisons = 0, 0
    for path in reports:
        if path.is_relative_to(folder / "edge-rich-thirty-two"):
            continue
        steps = 32 if path.is_relative_to(folder / "edge-thirty-two") else 1 if path.is_relative_to(folder / "edge-one") else 2
        observations += check_report(path, len(json.loads(path.read_text())["cases"]), steps=steps, compact=steps == 32)
        for case in json.loads(path.read_text())["cases"]:
            bundle = path.parent / case["case"] / "typed-bundle.json"
            result = subprocess.run([str(cli), "compare-observations", str(bundle)],
                capture_output=True, check=False, timeout=30)
            assert result.returncode == case["exit_code"] and json.loads(result.stdout) == case["comparison"]
            comparisons += 1
    raw = [path for path in folder.rglob("command.json") if path.parent.name.startswith(("baseline-", "instrumented_on-"))]
    identities = {hashlib.sha256(path.read_bytes()).hexdigest() for path in raw}
    assert observations == 152 and len(raw) == observations + refused == 153
    assert len(identities) == 149 and comparisons == 38
    for path in folder.rglob("plan.json"):
        plan = json.loads(path.read_text())
        for name, expected in plan["source_manifest"].items():
            assert hashlib.sha256((Path(plan["source"]) / name).read_bytes()).hexdigest() == expected
    return {"claim": "equivalence over these tests and observations", "artefact_class": "diagnostic",
        "cli_sha256": hashlib.sha256(cli.read_bytes()).hexdigest(), "cases": len(METHODS),
        "matching_cases": len(METHODS) - 1, "intermediate_difference_controls": 1,
        "qualified_reports": len(reports), "retained_observations": observations,
        "recomputed_comparisons": comparisons, "raw_instrumented_receipts": verify_receipts(folder),
        "actual_application_launches": len(identities), "required_operations": verify_operations(folder, cli),
        "source_control_actual_exit": 4,
        "evidence_refusals": len(CONTROL_VERDICTS), "source_preserved": True,
        "actual_budget_refusal_launches": refused,
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
        report_path = folder / "comparison/report.json"
        command([cli, "run", "--workspace", workspace, "--report-dir", report_path.parent], folder, "run", 1)
        check_report(report_path, len(METHODS))
        controls(cli, report_path, folder)
        report = json.loads(report_path.read_text())
        for case in report["cases"]:
            result = json.loads(command([cli, "replay", "--workspace", workspace, "--case", case["case"]],
                folder, "replay-" + FUNCTIONS[case["function"]], case["exit_code"]))
            check_report(Path(result["report"]), 1)
        framework(workspace, folder, "framework")
        exported = folder / "exported"
        command([cli, "export-tests", "--workspace", workspace, "--destination", exported, "--apply"], folder, "export")
        source = Path(json.loads((workspace / "plan.json").read_text())["source"])
        detached = source.with_name("application-detached")
        source.rename(detached)
        try:
            command([cli, "run", "--workspace", exported, "--report-dir", folder / "export-comparison"], folder, "export-run", 1)
            check_report(folder / "export-comparison/report.json", len(METHODS))
            framework(exported, folder, "export-framework")
        finally:
            detached.rename(source)
        target = next(row for row in report["cases"] if FUNCTIONS[row["function"]] == "transient")
        reduced = folder / "shrink"
        command([cli, "shrink", "--workspace", workspace, "--case", target["case"], "--report-dir", reduced, "--trials", "1"], folder, "shrink", 1)
        shrink = json.loads((reduced / "shrink.json").read_text())
        assert shrink["reduced_arguments"] == [0] and shrink["status"] == "candidate_rule_minimal"
        reduced_workspace = Path(shrink["workspace"])
        framework(reduced_workspace, folder, "reduced-framework", 1)
        replay = json.loads(command([cli, "replay", "--workspace", reduced_workspace, "--case", target["case"]], folder, "reduced-replay", 1))
        check_report(Path(replay["report"]), 1)
        for name, steps, compact, expected in (("edge-one", 1, False, 0),
                ("edge-rich-thirty-two", 32, False, 4), ("edge-thirty-two", 32, True, 0)):
            edge = folder / name
            edge_workspace = prepare(cli, provider, edge, steps=steps, methods=("identity",), compact=compact, padding=name == "edge-rich-thirty-two")
            command([cli, "run", "--workspace", edge_workspace, "--report-dir", edge / "comparison"], edge, "run", expected)
            if expected:
                verify_budget_refusal(edge)
            else:
                check_report(edge / "comparison/report.json", 1, steps=steps, compact=compact)
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
