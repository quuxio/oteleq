"""Qualify Java intermediate graphs, recursive calls and strict repeated replay."""
import argparse
import copy
import hashlib
import json
import os
from pathlib import Path
import sys

from qualify_generation import command
from qualify_java_receivers import check_state, verify_builds, verify_launches, verify_prepared
from qualify_sequences import source_control

METHODS = ("identity", "secret", "transient", "fail", "recursive")
SOURCE = '''class Counter {
 private int value;
 private static int total;
 Counter self=this;
 Object[] shared=new Object[]{this,null};
 private Counter(int start){value=start;shared[1]=shared;}
 private static Counter make(int start){return new Counter(start);}
 private static boolean active(){return java.lang.management.ManagementFactory.getRuntimeMXBean().getInputArguments().stream().anyMatch(v -> v.contains("opentelemetry-javaagent-2.32.0.jar"));}
 Counter identity(int amount){value+=amount;total+=amount;return this;}
 private int secret(int amount){value+=amount;total+=amount;return value;}
 int transient_value(int amount){if(amount==2){value=19;total=9;}else{value+=amount+(active()?1:0);total+=amount;}return 7;}
 int fail(int amount){value+=amount;total+=amount;if(amount!=2)throw new IllegalArgumentException("expected");return 7;}
 int recursive(int amount){if(amount>0)recursive(0);value+=amount;total+=amount;return 7;}
}
'''
SOURCE_METHOD = {method: "transient_value" if method == "transient" else method for method in METHODS}
FUNCTIONS = {"Counter." + SOURCE_METHOD[method] + "(int)": method for method in METHODS}
CONTROL_VERDICTS = {"missing-call": "inconclusive", "reordered-calls": "inconclusive",
                    "missing-field": "different_observed", "missing-method-witness": "inconclusive",
                    "undeclared-intermediate-error": "blocked"}


def prepare(cli: Path, provider: Path, folder: Path, backend: str) -> Path:
    """Every fixture declares two calls on one independently constructed receiver."""
    folder.mkdir()
    source = folder / "application";source.mkdir()
    text = SOURCE if backend == "prepared" else SOURCE.replace("opentelemetry-javaagent-2.32.0.jar", "java-agent-0.1.0-agent.jar")
    (source / "Counter.java").write_text(text)
    policy = 'schema_version=1\nlanguages=["java"]\n[adapters.java]\nbackend=' + json.dumps(backend)
    policy += '\n[functions]\ninclude=' + json.dumps(list(FUNCTIONS)) + '\n'
    for function, method in FUNCTIONS.items():
        policy += '\n[[fixtures]]\nfunction=' + json.dumps(function) + '\ncases=[[7]]\n'
        policy += 'receiver={factory=' + json.dumps("make" if method == "secret" else "Counter") + ',arguments=[10]}\n'
        error = ',expected_baseline={kind="error",category="exception",type="java.lang.IllegalArgumentException"}' if method == "fail" else ''
        policy += 'sequence=[{action="call",arguments="case"' + error + '},{action="call",arguments=[2]}]\n'
        if method == "transient":
            policy += 'domains=[{kind="integer",minimum=0,maximum=7}]\n'
    config = folder / "equivalence.toml";config.write_text(policy)
    workspace = Path(command([cli, "plan", "--source", source, "--otelc-root", provider,
                              "--workspace-parent", folder, "--config", config], folder, "plan"))
    plan = json.loads((workspace / "plan.json").read_text())
    assert {row["otelc_function"] for row in plan["inventory"] if row["status"] == "ready"} == set(FUNCTIONS)
    assert not any(row["status"] == "blocked" for row in plan["inventory"])
    command([cli, "generate", "--workspace", workspace], folder, "generate")
    return workspace


def check_observation(observed: dict, method: str, amount: int, active: bool) -> None:
    """Require complete literal graphs, outcomes and aliases at every boundary."""
    assert not observed["gaps"] and len(observed["steps"]) == 2
    first = 10 + amount + int(method == "transient" and active)
    value, total = 10, 0
    for index, (step, argument) in enumerate(zip(observed["steps"], (amount, 2))):
        assert step["id"] == "step-" + str(index) and step["action"] == "call" and step["gaps"] == []
        check_state(step["before"], value, total, argument)
        value = first if index == 0 else 19 if method == "transient" else value + argument
        total = 9 if index == 1 and method == "transient" else total + argument
        check_state(step["after"], value, total, argument)
        error = method == "fail" and index == 0
        expected = "fail" if error else "identity" if method == "identity" else "secret" if method == "secret" else "instance"
        check_state(step["outcome"]["graph"], value, total, argument, method=expected)
        assert step["outcome"]["kind"] == ("error" if error else "return")
        if error:
            assert step["outcome"]["category"] == "exception"
    assert observed["before"] == observed["steps"][0]["before"]
    assert observed["outcome"] == observed["steps"][-1]["outcome"]
    assert observed["after"] == observed["steps"][-1]["after"]


def check_report(path: Path, count: int = 5) -> int:
    """Cross-lane agreement cannot replace the independently fixed fixture oracle."""
    report = json.loads(path.read_text())
    assert count in (1, 5) and report["source_preserved"] and not report["blocked"] and len(report["cases"]) == count
    functions = {case["function"] for case in report["cases"]}
    assert len(functions) == count and (count == 1 or functions == set(FUNCTIONS))
    observations = 0
    for case in report["cases"]:
        method = FUNCTIONS[case["function"]]
        assert case["exit_code"] == int(method == "transient") and case["receiver_fixture"]["arguments"] == [10]
        amount, = case["arguments"]
        assert type(amount) is int and 0 <= amount <= 7
        bundle = json.loads((path.parent / case["case"] / "typed-bundle.json").read_text())["cases"][0]
        assert set(bundle["contract"]["required_roots"]) == {"receiver", "argument:0", "static:Counter.total"}
        assert [(step["id"], step["action"]) for step in bundle["contract"]["steps"]] == [("step-0", "call"), ("step-1", "call")]
        for lane in ("baseline", "instrumented_on"):
            assert len(bundle[lane]) == 2
            for index, attempt in enumerate(bundle[lane]):
                observations += 1
                check_observation(attempt["observation"], method, amount, lane == "instrumented_on")
                folder = path.parent / case["case"] / (lane + "-" + str(index))
                assert (folder / "stdout").read_bytes() == (folder / "stderr").read_bytes() == b""
                if lane == "instrumented_on":
                    calls = 4 if method == "recursive" else 2
                    witness = attempt["execution"]["witness"]
                    assert witness["functions"] == {case["function"]: calls} and witness["spans"] == calls
                    assert not any(witness["losses"].values()) and witness["pending"] == 0
    return observations


def verify_receipt(attempt: Path, launch: dict, pid: int, trace_decoder, metric_decoder) -> None:
    """Independently bind known call/root counts and actual exports to final health."""
    observation = json.loads((attempt / "typed-observation.json").read_text())
    method = FUNCTIONS[observation["function_id"]]
    expected = 4 if method == "recursive" else 2
    health = json.loads((attempt / "sdk-runtime/health.json").read_text())
    assert health["pid"] == pid and health["policy_sha256"] == launch["policy_sha256"]
    assert health["selection_sha256"] == launch["selection_sha256"] and health["sdk_attached"] is True
    assert health["phase"] == "final" and health["lifecycle"] == {"flush": "succeeded", "shutdown": "succeeded"}
    http = json.loads((attempt / "http-capture.json").read_text());assert not http["errors"]
    spans, points, batches, counters = [], 0, {"/v1/traces": 0, "/v1/metrics": 0}, {}
    for body in http["bodies"]:
        route = body["path"];batches[route] += 1
        raw = (attempt / body["file"]).read_bytes()
        if route == "/v1/traces":
            message = trace_decoder.FromString(raw)
            spans += [span for group in message.resource_spans for scope in group.scope_spans for span in scope.spans]
        else:
            message = metric_decoder.FromString(raw)
            for group in message.resource_metrics:
                for scope in group.scope_metrics:
                    for metric in scope.metrics:
                        data = getattr(metric, metric.WhichOneof("data"));points += len(data.data_points)
                        if metric.name in ("otelc.function.calls", "otelc.function.duration"):
                            counters.setdefault(metric.name, []).extend((point.time_unix_nano, point.as_int if metric.name.endswith("calls") else point.count) for point in data.data_points)
    assert len(spans) == expected and sum(not span.parent_span_id for span in spans) == 2
    assert all(span.name == "Counter." + SOURCE_METHOD[method] for span in spans)
    assert len({(span.trace_id, span.span_id) for span in spans}) == expected
    assert set(counters) == {"otelc.function.calls", "otelc.function.duration"}
    assert all(sorted(values)[-1][1] == expected for values in counters.values())
    assert health["span_accounting"] == {"processors_observed": 1, "batch_processors_observed": 1,
           "sampled_started": str(expected), "sampled_ended": str(expected), "sampled_active": "0",
           "queue_pending": "0", "queue_dropped": "0", "queue_evidence": "derived_after_shutdown"}
    for group, route, units in (("trace_exports", "/v1/traces", expected), ("metric_exports", "/v1/metrics", points)):
        exported = health[group]
        assert exported["batches_started"] == exported["batches_succeeded"] == str(batches[route])
        assert exported["units_started"] == exported["units_succeeded"] == str(units)
        assert all(exported[name] == "0" for name in ("batches_failed", "units_failed", "batches_pending"))


def framework(workspace: Path, folder: Path, name: str, count: int = 5) -> int:
    """Exactly the deliberate intermediate difference fails the generated suite."""
    output = command([sys.executable, workspace / "tests/test_equivalence.py"], folder, name, expected=1)
    reports = [json.loads(line) for line in output.splitlines()]
    assert len(reports) == count
    return sum(check_report(Path(row["report"]), 1) for row in reports)


def controls(cli: Path, report: Path, folder: Path) -> int:
    """Missing state/actions/telemetry and undeclared errors cannot pass."""
    rows = json.loads(report.read_text())["cases"]
    cases = {FUNCTIONS[row["function"]]: row for row in rows}
    def bundle(method):
        return json.loads((report.parent / cases[method]["case"] / "typed-bundle.json").read_text())
    original = bundle("identity");variants = []
    for name, edit in (("missing-call", lambda item: item["steps"].pop()),
                       ("reordered-calls", lambda item: item["steps"].reverse()),
                       ("missing-field", lambda item: item["steps"][0]["after"]["nodes"][0]["fields"].pop("value"))):
        changed = copy.deepcopy(original)
        for lane in (("instrumented_on",) if name == "missing-field" else ("baseline", "instrumented_on")):
            for attempt in changed["cases"][0][lane]:
                edit(attempt["observation"])
        variants.append((name, changed, 3 if name != "missing-field" else 1))
    changed = copy.deepcopy(original)
    changed["cases"][0]["instrumented_on"][0]["execution"]["witness"]["functions"] = {}
    variants.append(("missing-method-witness", changed, 3))
    changed = bundle("fail");changed["cases"][0]["contract"]["steps"][0]["expected_baseline"] = {"kind": "return"}
    variants.append(("undeclared-intermediate-error", changed, 2))
    for name, data, expected in variants:
        path = folder / (name + ".json");path.write_text(json.dumps(data))
        command([cli, "compare-observations", path], folder, name, expected=expected)
    return len(variants)


def audit_counts(observations: int, launches: dict) -> int:
    """The selected route sum counts shrink's fresh original confirmation once."""
    assert observations == launches["unique_command_identities"] == 120
    assert launches["raw_attempt_folders"] == observations + 4
    return observations


def verify_controls(folder: Path) -> int:
    """Retained refusal evidence must report its separately required verdict."""
    for name, expected in CONTROL_VERDICTS.items():
        assert json.loads((folder / (name + ".stdout")).read_text())["verdict"] == expected
    assert "application source or immutable snapshot changed" in (folder / "changed-source.stderr").read_text()
    return len(CONTROL_VERDICTS)


def retained(folder: Path, cli: Path, backend: str) -> dict:
    """Recheck every retained report/build/receipt without launching another JVM."""
    reports = sorted(folder.rglob("report.json"))
    assert reports
    observations = sum(check_report(path, len(json.loads(path.read_text())["cases"])) for path in reports)
    builds = verify_builds(folder)
    launches = verify_launches(folder, 120)
    assert observations == launches["raw_attempt_folders"] == 124
    prepared = verify_prepared(folder, verify_receipt) if backend == "prepared" else None
    for path in folder.rglob("plan.json"):
        plan = json.loads(path.read_text())
        for name, digest in plan["source_manifest"].items():
            assert hashlib.sha256((Path(plan["source"]) / name).read_bytes()).hexdigest() == digest
    return {"claim": "equivalence over these tests and observations", "artefact_class": "diagnostic",
            "backend": backend, "cli_sha256": hashlib.sha256(cli.read_bytes()).hexdigest(),
            "cases": 5, "matching_cases": 4, "intermediate_difference_controls": 1,
            "qualified_reports": len(reports), "retained_observations": observations,
            "actual_jvm_launches": launches["unique_command_identities"], "evidence_refusals": verify_controls(folder),
            "prelaunch_source_refusals": 1, "source_preserved": True,
            "detached_export": True, "builds": builds, "launches": launches, "prepared": prepared,
            "scope": "Two ordered calls on declared Java receivers; private factories, fields/statics, aliases/cycles, expected intermediate exceptions and recursive trees. No release, collection, invocation attribution or shipping artefact claim."}


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--otelc-root", type=Path, required=True)
    parser.add_argument("--report-dir", type=Path, required=True)
    parser.add_argument("--cli", type=Path, required=True)
    parser.add_argument("--java-backend", choices=("legacy", "prepared"), default="prepared")
    parser.add_argument("--recheck", action="store_true", help="verify completed retained routes without launching JVMs")
    args = parser.parse_args()
    cli, provider, folder = args.cli.resolve(strict=True), args.otelc_root.resolve(strict=True), args.report_dir.resolve()
    if folder.is_relative_to(provider) or folder.is_relative_to(Path(__file__).resolve().parents[1]):
        parser.error("qualification directory must be new and outside both repositories")
    if args.recheck:
        result = retained(folder, cli, args.java_backend)
        (folder / "qualification.json").write_text(json.dumps(result, indent=2) + "\n")
        print(json.dumps(result), flush=True)
        return
    folder.mkdir(mode=0o700)
    os.environ.update(OTELEQ_PYTHON=sys.executable, OTELEQ_CLI=str(cli))
    workspace = prepare(cli, provider, folder / "cases", args.java_backend)
    command([cli, "run", "--workspace", workspace, "--report-dir", folder / "comparison"], folder, "run", expected=1)
    observations = check_report(folder / "comparison/report.json")
    refusals = controls(cli, folder / "comparison/report.json", folder)
    report = json.loads((folder / "comparison/report.json").read_text())
    source_control(cli, workspace, folder, report["cases"][0], source_name="Counter.java")
    for case in report["cases"]:
        result = json.loads(command([cli, "replay", "--workspace", workspace, "--case", case["case"]],
                                    folder, "replay-" + FUNCTIONS[case["function"]], expected=case["exit_code"]))
        observations += check_report(Path(result["report"]), 1)
    observations += framework(workspace, folder, "framework")
    exported = folder / "exported"
    command([cli, "export-tests", "--workspace", workspace, "--destination", exported, "--apply"], folder, "export")
    source = Path(json.loads((workspace / "plan.json").read_text())["source"])
    detached = source.with_name("application-detached")
    source.rename(detached)
    try:
        command([cli, "run", "--workspace", exported, "--report-dir", folder / "export-comparison"], folder, "export-run", expected=1)
        observations += check_report(folder / "export-comparison/report.json")
        observations += framework(exported, folder, "export-framework")
    finally:
        detached.rename(source)
    target = next(row for row in report["cases"] if FUNCTIONS[row["function"]] == "transient")
    reduced = folder / "shrink"
    command([cli, "shrink", "--workspace", workspace, "--case", target["case"], "--report-dir", reduced, "--trials", "1"], folder, "shrink", expected=1)
    shrink = json.loads((reduced / "shrink.json").read_text())
    assert shrink["reduced_arguments"] == [0] and shrink["status"] == "candidate_rule_minimal"
    for path in [reduced / "original/report.json", reduced / "confirmation/report.json", *[Path(row["report"]) for row in shrink["trials"]]]:
        observations += check_report(path, 1)
    replay = Path(shrink["workspace"])
    observations += framework(replay, folder, "reduced-framework", 1)
    result = json.loads(command([cli, "replay", "--workspace", replay, "--case", target["case"]], folder, "reduced-replay", expected=1))
    observations += check_report(Path(result["report"]), 1)
    audit_counts(observations, verify_launches(folder, 120))
    assert refusals == 5
    result = retained(folder, cli, args.java_backend)
    (folder / "qualification.json").write_text(json.dumps(result, indent=2) + "\n")
    print(json.dumps(result), flush=True)


if __name__ == "__main__":
    main()
