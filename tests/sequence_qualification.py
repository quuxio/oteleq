"""Shared retained-route mechanics; language fixtures and graph oracles stay separate."""
import copy
import hashlib
import json
from pathlib import Path
import subprocess
import sys
from collections.abc import Callable

from qualify_project_tests import command

CONTROL_VERDICTS = {
    "missing-call": (3, "inconclusive"),
    "reordered-calls": (3, "inconclusive"),
    "missing-field": (1, "different_observed"),
    "missing-method-witness": (3, "inconclusive"),
    "undeclared-intermediate-error": (2, "blocked"),
}


def plan_generate(cli: Path, provider: Path, folder: Path, source: Path,
                  config: Path, expected_functions: set[str]) -> Path:
    """Require the complete selected inventory before generating a retained suite."""
    workspace = Path(command([cli, "plan", "--source", source, "--otelc-root", provider,
        "--workspace-parent", folder, "--config", config], folder, "plan"))
    plan = json.loads((workspace / "plan.json").read_text())
    assert {row["otelc_function"] for row in plan["inventory"] if row["status"] == "ready"} == expected_functions
    assert not any(row["status"] == "blocked" for row in plan["inventory"])
    command([cli, "generate", "--workspace", workspace], folder, "generate")
    return workspace


def check_contract(bundle: dict, roots: set[str], steps: int) -> None:
    """Every intermediate boundary needs the same declared roots and call order."""
    assert set(bundle["contract"]["required_roots"]) == roots
    assert len(bundle["contract"]["steps"]) == steps
    for index, step in enumerate(bundle["contract"]["steps"]):
        assert (step["id"], step["action"], set(step["required_roots"])) == ("step-" + str(index), "call", roots)


def check_execution(attempt: dict, function_id: str, expected: int, *, active: bool) -> None:
    """Empty application channels and complete selected-function witness are required."""
    assert all(attempt["execution"]["channels"][name] == [] for name in ("stdout", "stderr"))
    if active:
        witness = attempt["execution"]["witness"]
        assert witness["functions"] == {function_id: expected} and witness["spans"] == expected
        assert not any(witness["losses"].values()) and witness["pending"] == 0


def framework(workspace: Path, folder: Path, name: str, count: int, check_report: Callable[..., int]) -> int:
    """The deliberate intermediate difference must fail the retained unittest."""
    output = command([sys.executable, workspace / "tests/test_equivalence.py"], folder, name, 1)
    reports = [json.loads(line) for line in output.splitlines()]
    assert len(reports) == count
    assert "Ran " + str(count) + " test" in (folder / (name + ".stderr")).read_text()
    return sum(check_report(Path(row["report"]), 1) for row in reports)


def controls(cli: Path, report: Path, folder: Path, functions: dict[str, str],
             node: Callable, value_field: str) -> None:
    """Actual retained evidence is altered without counting copies as executions."""
    cases = {functions[row["function"]]: row for row in json.loads(report.read_text())["cases"]}
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
                    node(graph, graph["roots"]["receiver"])["fields"].pop(value_field)
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


def verify_operations(folder: Path, cli: Path, methods: tuple[str, ...], functions: dict[str, str],
                      refusals: tuple[str, ...], *, historical_source_expectation: bool = False) -> int:
    """Require every route's terminal receipt; omissions cannot be a partial pass."""
    required = {"run": 1, "framework": 1, "export": 0, "export-run": 1,
        "export-framework": 1, "shrink": 1, "reduced-framework": 1, "reduced-replay": 1,
        "changed-source": 4, **{"replay-" + method: int(method == "transient") for method in methods},
        **{name: expected for name, (expected, _) in CONTROL_VERDICTS.items()}}
    workspace = Path((folder / "cases/plan.stdout").read_text().strip())
    assert workspace.is_relative_to(folder / "cases")
    provider = Path(json.loads((workspace / "plan.json").read_text())["otelc_root"])
    cases = {functions[case["function"]]: case["case"]
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
        recorded = 2 if historical_source_expectation and name == "changed-source" else expected
        assert marker == {"argv": list(map(str, expected_argv[name])), "expected_exit": recorded}
        assert (folder / (name + ".exit")).read_text() == str(expected) + "\n"
        for suffix in ("stdout", "stderr"):
            assert (folder / (name + "." + suffix)).is_file()
        if name in CONTROL_VERDICTS:
            assert json.loads((folder / (name + ".stdout")).read_text())["verdict"] == CONTROL_VERDICTS[name][1]
    assert (folder / "changed-source.stderr").read_bytes() == b"oteleq: application source or immutable snapshot changed\n"
    assert (folder / "changed-source.stdout").read_bytes() == b""
    for name in ("cases", "edge-one", "edge-thirty-two", *refusals):
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
            expected_exit = 4 if name in refusals and operation == "run" else 0
            assert marker == {"argv": list(map(str, argv)), "expected_exit": expected_exit}
        for operation in ("plan", "generate"):
            assert (folder / name / (operation + ".exit")).read_text() == "0\n"
        if name != "cases":
            assert (folder / name / "run.exit").read_text() == ("4\n" if name in refusals else "0\n")
    return len(required) + 3 * (3 + len(refusals)) - 1


def verify_routes(folder: Path, methods: tuple[str, ...],
                  functions: dict[str, str], function: Callable[[str], str]) -> None:
    """Require each named route's complete methods and independently fixed inputs."""
    def report(path: Path, count: int, method: str | None = None, amount: int = 7) -> None:
        assert path.is_relative_to(folder)
        cases = json.loads(path.read_text())["cases"]
        assert len(cases) == count and all(case["arguments"] == [amount] for case in cases)
        if method:
            assert cases[0]["function"] == function(method)
        else:
            assert {case["function"] for case in cases} == set(functions)

    for name in ("comparison", "export-comparison"):
        report(folder / name / "report.json", len(methods))
    for method in methods:
        summary = json.loads((folder / ("replay-" + method + ".stdout")).read_text())
        report(Path(summary["report"]), 1, method)
    for name in ("framework", "export-framework", "reduced-framework"):
        rows = [json.loads(line) for line in (folder / (name + ".stdout")).read_text().splitlines()]
        reduced = name == "reduced-framework"
        assert len(rows) == (1 if reduced else len(methods))
        seen = []
        for row in rows:
            path = Path(row["report"])
            case = json.loads(path.read_text())["cases"][0]
            method = functions[case["function"]]
            report(path, 1, "transient" if reduced else method, 0 if reduced else 7)
            seen.append(method)
        assert set(seen) == ({"transient"} if reduced else set(methods))
    summary = json.loads((folder / "reduced-replay.stdout").read_text())
    report(Path(summary["report"]), 1, "transient", 0)
    for name in ("edge-one", "edge-thirty-two"):
        report(folder / name / "comparison/report.json", 1, "identity")


def decode_receipt(attempt: Path) -> tuple[list, dict]:
    """Read exact captured OTLP bodies and reject transport errors or foreign signals."""
    from opentelemetry.proto.collector.metrics.v1.metrics_service_pb2 import ExportMetricsServiceRequest
    from opentelemetry.proto.collector.trace.v1.trace_service_pb2 import ExportTraceServiceRequest
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
    return spans, counters


def check_serial_trees(spans: list, expected: list[int], function_id: str) -> None:
    """Require complete non-overlapping root trees with valid parent/child identities."""
    roots = sorted((span for span in spans if not span.parent_span_id), key=lambda span: span.start_time_unix_nano)
    assert len(roots) == len(expected) and len(spans) == sum(expected)
    assert all(span.name == function_id for span in spans)
    assert len({(span.trace_id, span.span_id) for span in spans}) == len(spans)
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


def compare_reports(folder: Path, reports: list[Path], cli: Path,
                    check_report: Callable[..., int], excluded: tuple[str, ...]) -> tuple[int, int]:
    """Recompute every retained comparison while preserving the original report bytes."""
    observations, comparisons = 0, 0
    for path in reports:
        if any(path.is_relative_to(folder / name) for name in excluded):
            continue
        steps = 32 if path.is_relative_to(folder / "edge-thirty-two") else 1 if path.is_relative_to(folder / "edge-one") else 2
        observations += check_report(path, len(json.loads(path.read_text())["cases"]), steps=steps, compact=steps == 32)
        for case in json.loads(path.read_text())["cases"]:
            bundle = path.parent / case["case"] / "typed-bundle.json"
            result = subprocess.run([str(cli), "compare-observations", str(bundle)], capture_output=True, check=False, timeout=30)
            assert result.returncode == case["exit_code"] and json.loads(result.stdout) == case["comparison"]
            comparisons += 1
    return observations, comparisons


def verify_sources(folder: Path, *, excluded: tuple[str, ...] = ()) -> None:
    """Check current sources outside explicitly separate workflow audits."""
    for path in folder.rglob("plan.json"):
        if any(path.is_relative_to(folder / name) for name in excluded):
            continue
        plan = json.loads(path.read_text())
        for name, expected in plan["source_manifest"].items():
            assert hashlib.sha256((Path(plan["source"]) / name).read_bytes()).hexdigest() == expected, str(path)


def exercise_routes(cli: Path, folder: Path, workspace: Path, methods: tuple[str, ...],
                    functions: dict[str, str], check_report: Callable[..., int],
                    controls: Callable, framework: Callable) -> tuple[Path, dict]:
    """Exercise direct, replay, framework, detached and reduced routes on the same fixed corpus."""
    report_path = folder / "comparison/report.json"
    command([cli, "run", "--workspace", workspace, "--report-dir", report_path.parent], folder, "run", 1)
    check_report(report_path, len(methods))
    controls(cli, report_path, folder)
    report = json.loads(report_path.read_text())
    for case in report["cases"]:
        result = json.loads(command([cli, "replay", "--workspace", workspace, "--case", case["case"]],
            folder, "replay-" + functions[case["function"]], case["exit_code"]))
        check_report(Path(result["report"]), 1)
    framework(workspace, folder, "framework")
    exported = folder / "exported"
    command([cli, "export-tests", "--workspace", workspace, "--destination", exported, "--apply"], folder, "export")
    source = Path(json.loads((workspace / "plan.json").read_text())["source"])
    detached = source.with_name("application-detached")
    source.rename(detached)
    try:
        command([cli, "run", "--workspace", exported, "--report-dir", folder / "export-comparison"], folder, "export-run", 1)
        check_report(folder / "export-comparison/report.json", len(methods))
        framework(exported, folder, "export-framework")
    finally:
        detached.rename(source)
    target = next(row for row in report["cases"] if functions[row["function"]] == "transient")
    reduced = folder / "shrink"
    command([cli, "shrink", "--workspace", workspace, "--case", target["case"], "--report-dir", reduced, "--trials", "1"], folder, "shrink", 1)
    shrink = json.loads((reduced / "shrink.json").read_text())
    assert shrink["reduced_arguments"] == [0] and shrink["status"] == "candidate_rule_minimal"
    reduced_workspace = Path(shrink["workspace"])
    framework(reduced_workspace, folder, "reduced-framework", 1)
    replay = json.loads(command([cli, "replay", "--workspace", reduced_workspace, "--case", target["case"]], folder, "reduced-replay", 1))
    check_report(Path(replay["report"]), 1)
    return source, target

