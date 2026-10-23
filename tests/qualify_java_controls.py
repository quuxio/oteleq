"""Actual same-PID Java metric controls, complete state oracles and replay routes."""
import argparse
import copy
import hashlib
import json
import os
from pathlib import Path
import re
import sys

from qualify_generation import command
from qualify_java_receivers import check_state, verify_builds, verify_launches, verify_prepared
from qualify_java_receivers import graph_nodes, reference_id, string_node
import qualify_java_receivers
from qualify_sequences import source_control

STATES = [(True, True), (False, True), (True, False), (False, False)]
METHODS = ("identity", "secret", "transient_value", "withheld", "fail", "recursive")
DIFFERENCES = {"transient_value", "withheld"}
FUNCTIONS = {"Counter." + method + "(int)": method for method in METHODS}
SOURCE = r'''class Counter {
 private int value;
 private static int total;
 Counter self=this;
 Object[] shared=new Object[]{this,null};
 private Counter(int start){value=start;shared[1]=shared;}
 private static Counter make(int start){return new Counter(start);}
 private static boolean active(){return java.lang.management.ManagementFactory.getRuntimeMXBean().getInputArguments().stream().anyMatch(v -> v.contains("opentelemetry-javaagent-2.32.0.jar"));}
 Counter identity(int amount){value+=amount;total+=amount;return this;}
 private int secret(int amount){System.out.println("out"+amount);System.err.println("err"+amount);value+=amount;total+=amount;return value;}
 int transient_value(int amount){if(amount==4){value=26;total=16;}else{value+=amount+(amount==2&&active()?1:0);total+=amount;}return 7;}
 int withheld(int amount){value+=amount+(amount==3&&active()?1:0);total+=amount;return 7;}
 int fail(int amount){value+=amount;total+=amount;if(amount==2)throw new IllegalArgumentException("expected");return 7;}
 int recursive(int amount){if(amount>0)recursive(0);value+=amount;total+=amount;return 7;}
}
'''


def prepare(cli: Path, provider: Path, folder: Path, profile: str, *, source_text: str = SOURCE,
            classpath: list[str] | None = None, states=STATES, case_timeout_ms: int = 20000) -> Path:
    """All states execute in one JVM per lane, using only existing source methods."""
    assert len(states) == 4 and set(states) == set(STATES)
    folder.mkdir();source = folder / "application";source.mkdir()
    (source / "Counter.java").write_text(source_text)
    text = 'schema_version=1\nlanguages=["java"]\n[adapters.java]\nbackend="prepared"\n'
    text += 'profile=' + json.dumps(profile) + '\n'
    if classpath is not None:
        text += 'source_roots=["."]\nclasspath=' + json.dumps(classpath) + '\n'
    text += '[functions]\ninclude=' + json.dumps(list(FUNCTIONS)) + '\n[limits]\ncase_timeout_ms=' + str(case_timeout_ms) + '\n'
    for function, method in FUNCTIONS.items():
        text += '\n[[fixtures]]\nfunction=' + json.dumps(function) + '\ncases=[[7]]\n'
        text += 'receiver={factory=' + json.dumps("make" if method == "secret" else "Counter") + ',arguments=[10]}\n'
        text += 'sequence=[\n'
        for index, (collection, emission) in enumerate(states):
            arguments = '"case"' if index == 0 else '[' + str(index + 1) + ']'
            expected = ',expected_baseline={kind="error",category="exception",type="java.lang.IllegalArgumentException"}' if method == "fail" and index == 1 else ''
            text += ' {action="call",arguments=' + arguments + expected + ',metrics={collection=' + str(collection).lower() + ',emission=' + str(emission).lower() + '}},\n'
        text += ']\n'
        if method == "transient_value":
            text += 'domains=[{kind="integer",minimum=0,maximum=7}]\n'
    config = folder / "equivalence.toml";config.write_text(text)
    workspace = Path(command([cli, "plan", "--source", source, "--otelc-root", provider,
                              "--workspace-parent", folder, "--config", config], folder, "plan"))
    plan = json.loads((workspace / "plan.json").read_text())
    assert {row["otelc_function"] for row in plan["inventory"] if row["status"] == "ready"} == set(FUNCTIONS)
    assert not any(row["status"] == "blocked" for row in plan["inventory"])
    command([cli, "generate", "--workspace", workspace], folder, "generate")
    return workspace


def observation(value: dict, method: str, amount: int, active: bool) -> None:
    """Every scalar type, root, field, node and alias has an independent expectation."""
    assert value["gaps"] == [] and len(value["steps"]) == 4
    number, total = 10, 0
    for index, (step, argument) in enumerate(zip(value["steps"], (amount, 2, 3, 4))):
        assert step["id"] == "step-" + str(index) and step["action"] == "call" and step["gaps"] == []
        check_state(step["before"], number, total, argument)
        if method == "transient_value" and index == 3:
            number, total = 26, 16
        else:
            difference = active and (method == "transient_value" and index == 1 or method == "withheld" and index == 2)
            number += argument + int(difference);total += argument
        check_state(step["after"], number, total, argument)
        error = method == "fail" and index == 1
        result = "fail" if error else "identity" if method == "identity" else "secret" if method == "secret" else "instance"
        check_state(step["outcome"]["graph"], number, total, argument, method=result)
        assert step["outcome"]["kind"] == ("error" if error else "return")
        if error:
            assert step["outcome"]["category"] == "exception"
    assert value["before"] == value["steps"][0]["before"]
    assert value["outcome"] == value["steps"][-1]["outcome"] and value["after"] == value["steps"][-1]["after"]


def control_status(value: dict, pid: int, state: tuple, completed: int) -> None:
    """Never turn an absent counter into zero or accept a different process."""
    assert type(value) is dict and set(value) == {"schema_version", "pid", "collection", "emission", "in_flight_exports", "effective_emission_off", "completed", "lifetime_lost"}
    expected = {"schema_version": 1, "pid": pid, "collection": state[0], "emission": state[1],
                "completed": completed, "lifetime_lost": 0}
    assert json.dumps({key: value[key] for key in expected}, sort_keys=True) == json.dumps(expected, sort_keys=True)
    assert type(value["in_flight_exports"]) is int and 0 <= value["in_flight_exports"] < 2**63
    assert type(value["effective_emission_off"]) is bool
    assert value["effective_emission_off"] == (not state[1] and value["in_flight_exports"] == 0)


def transition(rows: list, pid: int, previous: tuple, selected: tuple, completed: int) -> None:
    assert type(rows) is list and 3 <= len(rows) <= 256
    commands = ["status", "collection " + ("on" if selected[0] else "off"), "emission " + ("on" if selected[1] else "off")]
    for index, row in enumerate(rows):
        assert set(row) == {"command", "status"} and row["command"] == (commands[index] if index < 3 else "status")
        state = previous if index == 0 else (selected[0], previous[1]) if index == 1 else selected
        control_status(row["status"], pid, state, completed)
    assert selected[1] or rows[-1]["status"]["effective_emission_off"]


def controls(folder: Path, method: str, *, plain: bool, states=STATES) -> dict:
    """Recheck actual SDK acknowledgements and every private checkpoint pair."""
    assert len(states) == 4 and set(states) == set(STATES)
    record = json.loads((folder / "java-controls.json").read_text())
    process = json.loads((folder / "process.json").read_text())
    assert type(process) is dict and set(process) == {"pid", "argv"}
    assert process["argv"] == json.loads((folder / "command.json").read_text())
    pid = process["pid"];assert type(pid) is int and pid > 0
    assert type(record) is dict and set(record) == {"control_schema_version", "plain", "pid", "interval_ms", "steps", "restored"}
    identity = {"control_schema_version": 1, "plain": plain, "pid": pid, "interval_ms": 1000}
    assert json.dumps({key: record[key] for key in identity}, sort_keys=True) == json.dumps(identity, sort_keys=True)
    assert type(record["steps"]) is list and len(record["steps"]) == 4
    http = json.loads((folder / "http-capture.json").read_text());assert not http["errors"]
    cursor, maximum = 0, len(http["bodies"])
    size, before, previous = (2 if method == "recursive" else 1), 0, states[0]
    for index, (step, state) in enumerate(zip(record["steps"], states)):
        assert type(step) is dict and set(step) == {"id", "requested", "before", "after"} and step["id"] == "step-" + str(index)
        assert json.dumps(step["requested"], sort_keys=True) == json.dumps(dict(collection=state[0], emission=state[1]), sort_keys=True)
        assert set(step["before"]) == {"history", "cursor"}
        assert set(step["after"]) == {"status", "flush", "settled", "cursor", "metric_bodies", "held_ns"}
        start, end = step["before"]["cursor"], step["after"]["cursor"]
        assert type(start) is int and type(end) is int and cursor <= start <= end <= maximum
        received = [position for position in range(start, end) if http["bodies"][position]["path"] == "/v1/metrics"]
        assert type(step["after"]["metric_bodies"]) is list and all(type(position) is int for position in step["after"]["metric_bodies"])
        assert step["after"]["metric_bodies"] == received and (state[1] or not received)
        cursor = end
        after = before + (size if state[0] else 0)
        if plain:
            assert step["before"]["history"] == []
            assert all(step["after"][name] is None for name in ("status", "flush", "settled"))
        else:
            transition(step["before"]["history"], pid, previous, state, before)
            for name in ("status", "flush", "settled"):
                control_status(step["after"][name], pid, state, after)
                assert state[1] or step["after"][name]["effective_emission_off"]
        assert type(step["after"]["held_ns"]) is int and (0 if state[1] else 1000000000) <= step["after"]["held_ns"] <= 20000000000
        before, previous = after, state
    restored = record["restored"]
    assert type(restored) is dict and set(restored) == {"history", "flush", "cursor"}
    assert type(restored["cursor"]) is int and cursor <= restored["cursor"] <= maximum
    if plain:
        assert restored["history"] == [] and restored["flush"] is None
    else:
        transition(restored["history"], pid, previous, (True, True), before)
        control_status(restored["flush"], pid, (True, True), before)
    root = folder / "java-rendezvous"
    phases = [prefix + "-" + str(index) for index in range(4) for prefix in ("before", "after")] + ["finish"]
    assert {path.name for path in root.iterdir()} == {phase + suffix for phase in phases for suffix in (".ready", ".resume")}
    token = None
    for phase in phases:
        ready, resumed = (root / (phase + suffix) for suffix in (".ready", ".resume"))
        raw = ready.read_bytes();assert raw == resumed.read_bytes()
        match = re.fullmatch(rb"([0-9a-f]{32}) " + phase.encode() + rb"\n", raw)
        assert match and (token is None or token == match[1]);token = match[1]
    return record


def check_report(path: Path, count: int, *, states=STATES, console_prefix: str = "") -> int:
    report = json.loads(path.read_text())
    assert count in (1, 6) and report["source_preserved"] and not report["blocked"] and len(report["cases"]) == count
    assert len({row["function"] for row in report["cases"]}) == count
    if count == 6:
        assert {row["function"] for row in report["cases"]} == set(FUNCTIONS)
    for case in report["cases"]:
        method = FUNCTIONS[case["function"]];amount, = case["arguments"]
        assert type(amount) is int and 0 <= amount <= 7 and case["receiver_fixture"]["arguments"] == [10]
        assert case["exit_code"] == int(method in DIFFERENCES)
        assert len(case["sequence"]) == 4
        bundle = json.loads((path.parent / case["case"] / "typed-bundle.json").read_text())["cases"][0]
        assert bundle["contract"]["function_id"] == case["function"] and len(bundle["contract"]["steps"]) == 4
        assert set(bundle["contract"]["required_roots"]) == {"receiver", "argument:0", "static:Counter.total"}
        for lane in ("baseline", "instrumented_on"):
            assert len(bundle[lane]) == 2
            for index, attempt in enumerate(bundle[lane]):
                observation(attempt["observation"], method, amount, lane == "instrumented_on")
                folder = path.parent / case["case"] / (lane + "-" + str(index))
                controls(folder, method, plain=lane == "baseline", states=states)
                expected_out = ''.join(console_prefix + "out" + str(value) + "\n" for value in (amount, 2, 3, 4)).encode() if method == "secret" else b""
                expected_err = expected_out.replace(b"out", b"err")
                assert (folder / "stdout").read_bytes() == expected_out and (folder / "stderr").read_bytes() == expected_err
                if lane == "instrumented_on":
                    witness = attempt["execution"]["witness"]
                    spans = 8 if method == "recursive" else 4
                    assert witness["functions"] == {case["function"]: spans} and witness["spans"] == spans
                    assert not any(witness["losses"].values()) and witness["pending"] == 0
    return count * 4


def verify_receipt(folder: Path, launch: dict, pid: int, trace_decoder, metric_decoder,
                   *, getter: bool = False, states=STATES) -> None:
    """Known fixture counts corroborate final health and actual retained metrics."""
    function = json.loads((folder / "typed-observation.json").read_text())["function_id"]
    if getter:
        assert function == "Counter.run(int)"
    method = "run" if getter else FUNCTIONS[function];size = 2 if method == "recursive" else 1
    record = controls(folder, method, plain=False, states=states)
    health = json.loads((folder / "sdk-runtime/health.json").read_text())
    assert record["pid"] == health["pid"] == pid and health["phase"] == "final" and health["sdk_attached"] is True
    assert health["policy_sha256"] == launch["policy_sha256"] and health["selection_sha256"] == launch["selection_sha256"]
    assert health["lifecycle"] == {"flush": "succeeded", "shutdown": "succeeded"}
    http = json.loads((folder / "http-capture.json").read_text());assert not http["errors"]
    spans, points, batches, series = [], 0, {"/v1/traces": 0, "/v1/metrics": 0}, {}
    all_values = {"otelc.function.calls": [], "otelc.function.duration": []}
    for index, body in enumerate(http["bodies"]):
        route, filename = body["path"], body["file"]
        assert re.fullmatch(r"otlp-\d+\.protobuf", filename, re.ASCII)
        batches[route] += 1;raw = (folder / filename).read_bytes()
        if route == "/v1/traces":
            message = trace_decoder.FromString(raw)
            spans += [span for group in message.resource_spans for scope in group.scope_spans for span in scope.spans]
        else:
            message = metric_decoder.FromString(raw);current = {name: [] for name in all_values}
            for group in message.resource_metrics:
                for scope in group.scope_metrics:
                    for metric in scope.metrics:
                        data = getattr(metric, metric.WhichOneof("data"));points += len(data.data_points)
                        if metric.name in current:
                            values = [(point.time_unix_nano, point.as_int if metric.name.endswith("calls") else point.count) for point in data.data_points]
                            current[metric.name].extend(values);all_values[metric.name].extend(values)
            series[index] = current
    assert len(spans) == 4 * size and sum(not span.parent_span_id for span in spans) == 4
    assert all(span.name == "Counter." + method for span in spans)
    assert sum(span.status.code == 2 for span in spans) == (4 if getter else int(method == "fail"))
    assert len({(span.trace_id, span.span_id) for span in spans}) == 4 * size
    for values in all_values.values():
        ordered = [value for _, value in sorted(values)]
        assert ordered and ordered[-1] == 2 * size and ordered == sorted(ordered) and all(0 <= value <= 2 * size for value in ordered)
    for index, step in enumerate(record["steps"]):
        start, end = step["before"]["cursor"], step["after"]["cursor"]
        assert type(start) is int and type(end) is int and 0 <= start <= end <= len(http["bodies"])
        received = [position for position in range(start, end) if http["bodies"][position]["path"] == "/v1/metrics"]
        assert step["after"]["metric_bodies"] == received
        if not states[index][1]:
            assert received == []
        if states[index] == (True, True):
            completed = size * sum(state[0] for state in states[:index + 1])
            for name in all_values:
                values = [value for position in received for value in series[position][name]]
                assert values and sorted(values)[-1][1] == completed
    start, end = record["steps"][-1]["after"]["cursor"], record["restored"]["cursor"]
    assert type(start) is int and type(end) is int and 0 <= start <= end <= len(http["bodies"])
    for name in all_values:
        values = [value for position in range(start, end) if position in series for value in series[position][name]]
        assert values and sorted(values)[-1][1] == 2 * size
    assert health["span_accounting"] == {"processors_observed": 1, "batch_processors_observed": 1,
           "sampled_started": str(4 * size), "sampled_ended": str(4 * size), "sampled_active": "0",
           "queue_pending": "0", "queue_dropped": "0", "queue_evidence": "derived_after_shutdown"}
    for group, route, units in (("trace_exports", "/v1/traces", 4 * size), ("metric_exports", "/v1/metrics", points)):
        exported = health[group]
        assert exported["batches_started"] == exported["batches_succeeded"] == str(batches[route])
        assert exported["units_started"] == exported["units_succeeded"] == str(units)
        assert all(exported[name] == "0" for name in ("batches_failed", "units_failed", "batches_pending"))


def framework(workspace: Path, folder: Path, name: str, count: int = 6) -> None:
    output = command([sys.executable, workspace / "tests/test_equivalence.py"], folder, name, expected=1)
    reports = [json.loads(line) for line in output.splitlines()];assert len(reports) == count
    for row in reports:
        check_report(Path(row["report"]), 1)


def routes(cli: Path, provider: Path, folder: Path, profile: str) -> None:
    workspace = prepare(cli, provider, folder / "cases", profile)
    command([cli, "run", "--workspace", workspace, "--report-dir", folder / "comparison"], folder, "run", expected=1)
    check_report(folder / "comparison/report.json", 6)
    report = json.loads((folder / "comparison/report.json").read_text())
    source_control(cli, workspace, folder, report["cases"][0], source_name="Counter.java")
    for case in report["cases"]:
        replay = json.loads(command([cli, "replay", "--workspace", workspace, "--case", case["case"]], folder,
                                    "replay-" + FUNCTIONS[case["function"]], expected=case["exit_code"]))
        check_report(Path(replay["report"]), 1)
    framework(workspace, folder, "framework")
    exported = folder / "exported"
    command([cli, "export-tests", "--workspace", workspace, "--destination", exported, "--apply"], folder, "export")
    source = Path(json.loads((workspace / "plan.json").read_text())["source"]);detached = source.with_name("application-detached")
    source.rename(detached)
    try:
        command([cli, "run", "--workspace", exported, "--report-dir", folder / "export-comparison"], folder, "export-run", expected=1)
        check_report(folder / "export-comparison/report.json", 6)
        framework(exported, folder, "export-framework")
    finally:
        detached.rename(source)
    target = next(row for row in report["cases"] if FUNCTIONS[row["function"]] == "transient_value")
    reduced = folder / "shrink"
    command([cli, "shrink", "--workspace", workspace, "--case", target["case"], "--report-dir", reduced, "--trials", "1"], folder, "shrink", expected=1)
    shrink = json.loads((reduced / "shrink.json").read_text())
    assert shrink["original_arguments"] == [7] and shrink["reduced_arguments"] == [0] and shrink["status"] == "candidate_rule_minimal"
    replay = Path(shrink["workspace"])
    framework(replay, folder, "reduced-framework", 1)
    result = json.loads(command([cli, "replay", "--workspace", replay, "--case", target["case"]], folder, "reduced-replay", expected=1))
    check_report(Path(result["report"]), 1)


def retained(folder: Path, cli: Path) -> dict:
    """Recheck every actual route and copied original without executing JVMs again."""
    reports = sorted(folder.rglob("report.json"));assert len(reports) == 26
    observations = sum(check_report(path, len(json.loads(path.read_text())["cases"])) for path in reports)
    assert observations == 144
    launches = verify_launches(folder, 140);assert launches["raw_attempt_folders"] == 144
    builds = verify_builds(folder);prepared = verify_prepared(folder, verify_receipt)
    assert prepared["unique_processes"] == 140 and prepared["retained_instrumented_receipts"] == 72
    for path in folder.rglob("plan.json"):
        plan = json.loads(path.read_text())
        for name, digest in plan["source_manifest"].items():
            assert hashlib.sha256((Path(plan["source"]) / name).read_bytes()).hexdigest() == digest
    return {"claim": "equivalence over these tests and observations", "artefact_class": "diagnostic",
            "cli_sha256": hashlib.sha256(cli.read_bytes()).hexdigest(), "cases": 6, "matching_cases": 4,
            "state_difference_controls": 2, "actual_jvm_launches": 140, "retained_observations": 144,
            "qualified_reports": len(reports), "launches": launches, "builds": builds, "prepared": prepared,
            "source_preserved": True, "detached_export": True, "original_short_runtimes_removed": True,
            "scope": "Selected synchronous Java receiver call trees; four live metric states in one unchanged JVM/build, independent tracing, private checkpoints and bounded export windows. No general SDK-instrument or invocation-cookie/shipping claim."}


def getter_outcome(graph: dict, number: int, total: int, amount: int) -> None:
    """The supported outer error is exact RuntimeException/message, not its cause."""
    nodes = graph_nodes(graph)
    error = reference_id(graph["roots"]["error"])
    message = reference_id(nodes[error]["fields"]["message"])
    assert error != message
    assert nodes[error] == {"id": error, "type": "java.lang.RuntimeException", "fields": {"message": {"kind": "reference", "node_id": message}}}
    assert nodes[message] == string_node(message, "006f0075007400650072")
    context = copy.deepcopy(graph)
    del context["roots"]["error"]
    context["nodes"] = [node for node in context["nodes"] if node["id"] not in (error, message)]
    check_state(context, number, total, amount)


def getter_report(path: Path, delta: int) -> int:
    """A genuine producer difference remains a failed equivalence comparison."""
    report = json.loads(path.read_text())
    assert report["source_preserved"] and not report["blocked"] and len(report["cases"]) == 1
    case = report["cases"][0]
    assert case["function"] == "Counter.run(int)" and case["arguments"] == [7] and case["exit_code"] == int(delta != 0)
    bundle = json.loads((path.parent / case["case"] / "typed-bundle.json").read_text())["cases"][0]
    for lane in ("baseline", "instrumented_on"):
        assert len(bundle[lane]) == 2
        for index, attempt in enumerate(bundle[lane]):
            observed = attempt["observation"];assert observed["gaps"] == [] and len(observed["steps"]) == 4
            number, total = 10, 0
            for step, amount in zip(observed["steps"], (7, 2, 3, 4)):
                check_state(step["before"], number, total, amount)
                number += amount + (delta if lane == "instrumented_on" else 0);total += amount
                check_state(step["after"], number, total, amount)
                getter_outcome(step["outcome"]["graph"], number, total, amount)
                assert step["outcome"]["kind"] == "error" and step["outcome"]["category"] == "exception"
            assert observed["before"] == observed["steps"][0]["before"]
            assert observed["after"] == observed["steps"][-1]["after"] and observed["outcome"] == observed["steps"][-1]["outcome"]
            folder = path.parent / case["case"] / (lane + "-" + str(index))
            controls(folder, "run", plain=lane == "baseline")
            assert (folder / "stdout").read_bytes() == (folder / "stderr").read_bytes() == b""
            if lane == "instrumented_on":
                witness = attempt["execution"]["witness"]
                assert witness["functions"] == {"Counter.run(int)": 4} and not any(witness["losses"].values()) and witness["pending"] == 0
    return 4


def getter_case(cli: Path, provider: Path, folder: Path, delta: int, profile: str) -> dict:
    """Retain the requested producer regression without broadening the error codec."""
    folder.mkdir();source = folder / "application";source.mkdir()
    fixture = Path(__file__).parent / "fixtures/java_getter_cause/Counter.java"
    (source / "Counter.java").write_bytes(fixture.read_bytes())
    text = 'schema_version=1\nlanguages=["java"]\n[adapters.java]\nbackend="prepared"\n[functions]\ninclude=["Counter.run(int)"]\n[limits]\ncase_timeout_ms=20000\n[[fixtures]]\nfunction="Counter.run(int)"\ncases=[[7]]\nreceiver={factory="Counter",arguments=[10]}\nsequence=[\n'
    for index, (collection, emission) in enumerate(STATES):
        argument = '"case"' if index == 0 else '[' + str(index + 1) + ']'
        text += ' {action="call",arguments=' + argument + ',expected_baseline={kind="error",category="exception",type="java.lang.RuntimeException"},metrics={collection=' + str(collection).lower() + ',emission=' + str(emission).lower() + '}},\n'
    text = text.replace('backend="prepared"\n', 'backend="prepared"\nprofile=' + json.dumps(profile) + '\n', 1)
    config = folder / "equivalence.toml";config.write_text(text + ']\n')
    workspace = Path(command([cli, "plan", "--source", source, "--otelc-root", provider, "--config", config,
                              "--workspace-parent", folder], folder, "plan"))
    command([cli, "generate", "--workspace", workspace], folder, "generate")
    command([cli, "run", "--workspace", workspace, "--report-dir", folder / "comparison"], folder, "run", expected=int(delta != 0))
    getter_report(folder / "comparison/report.json", delta)
    output = command([sys.executable, workspace / "tests/test_equivalence.py"], folder, "framework", expected=int(delta != 0))
    reports = [json.loads(line) for line in output.splitlines()];assert len(reports) == 1
    getter_report(Path(reports[0]["report"]), delta)
    verify_launches(folder, 8);builds = verify_builds(folder)
    prepared = verify_prepared(folder, lambda *args: verify_receipt(*args, getter=True))
    return {"actual_jvm_launches": 8, "expected_getter_delta_per_call": delta, "equivalent": delta == 0,
            "comparison_exit": int(delta != 0), "source_sha256": hashlib.sha256(fixture.read_bytes()).hexdigest(),
            "builds": builds, "prepared": prepared,
            "scope": "Exact outer RuntimeException class/message; custom cause remains unobserved, while application getter side effects mutate a fully observed private receiver field."}


def compatibility(cli: Path, provider: Path, folder: Path, backend: str, profile: str) -> dict:
    """Live controls remain opt-in; ordinary matching/mutation routes still work."""
    workspace = qualify_java_receivers.prepare(cli, provider, folder, methods=("identity", "instance"), backend=backend,
                                              profile=profile if backend == "prepared" else None)
    command([cli, "run", "--workspace", workspace, "--report-dir", folder / "comparison"], folder, "run", expected=1)
    launches, _ = qualify_java_receivers.check_report(folder / "comparison/report.json", 2)
    assert launches == 8 and not list((folder / "comparison").rglob("java-controls.json"))
    return {"backend": backend, "actual_jvm_launches": launches, "opt_in_preserved": True,
            "builds": verify_builds(folder)}


def recheck_supplementary(folder: Path, delta: int) -> dict:
    """Supplementary summaries cannot replace their retained observations/receipts."""
    recorded = json.loads((folder / "supplementary.json").read_text())
    root = folder / "getter-cause"
    reports = sorted(root.rglob("report.json"));assert len(reports) == 2
    assert sum(getter_report(path, delta) for path in reports) == 8
    verify_launches(root, 8);verify_builds(root)
    verify_prepared(root, lambda *args: verify_receipt(*args, getter=True))
    assert recorded["getter_cause"]["expected_getter_delta_per_call"] == delta
    assert recorded["getter_cause"]["equivalent"] is (delta == 0)
    for key in ("ordinary_prepared", "ordinary_legacy"):
        if key not in recorded:
            continue
        root = folder / key.replace("_", "-")
        assert qualify_java_receivers.check_report(root / "comparison/report.json", 2)[0] == 8
        verify_launches(root, 8);verify_builds(root)
        if key == "ordinary_prepared":
            verify_prepared(root)
    for path in folder.rglob("plan.json"):
        plan = json.loads(path.read_text())
        for name, digest in plan["source_manifest"].items():
            assert hashlib.sha256((Path(plan["source"]) / name).read_bytes()).hexdigest() == digest
    return recorded


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--otelc-root", type=Path, required=True)
    parser.add_argument("--report-dir", type=Path, required=True)
    parser.add_argument("--cli", type=Path, required=True)
    parser.add_argument("--legacy-root", type=Path)
    parser.add_argument("--java-profile", choices=("stock-methods-v1", "safe-methods-v1"), default="stock-methods-v1")
    parser.add_argument("--getter-expectation", choices=("different", "equivalent"), default="different")
    parser.add_argument("--recheck", action="store_true")
    args = parser.parse_args()
    cli, provider, folder = args.cli.resolve(strict=True), args.otelc_root.resolve(strict=True), args.report_dir.resolve()
    if folder.is_relative_to(provider) or folder.is_relative_to(Path(__file__).resolve().parents[1]):
        parser.error("qualification directory must be new and outside both repositories")
    if not args.recheck:
        folder.mkdir(mode=0o700)
        os.environ.update(OTELEQ_PYTHON=sys.executable, OTELEQ_CLI=str(cli))
        corpus = folder / "corpus";corpus.mkdir()
        routes(cli, provider, corpus, args.java_profile)
        supplementary = {"getter_cause": getter_case(cli, provider, folder / "getter-cause", int(args.getter_expectation == "different"), args.java_profile),
                         "ordinary_prepared": compatibility(cli, provider, folder / "ordinary-prepared", "prepared", args.java_profile)}
        if args.legacy_root:
            supplementary["ordinary_legacy"] = compatibility(cli, args.legacy_root.resolve(strict=True), folder / "ordinary-legacy", "legacy", args.java_profile)
        (folder / "supplementary.json").write_text(json.dumps(supplementary, indent=2) + "\n")
    result = retained(folder / "corpus", cli)
    result["supplementary"] = recheck_supplementary(folder, int(args.getter_expectation == "different"))
    for path in folder.rglob("plan.json"):
        plan = json.loads(path.read_text())
        for entry in plan["inventory"]:
            if entry["status"] == "ready" and entry.get("java_backend") == "prepared":
                assert entry.get("java_profile", "stock-methods-v1") == args.java_profile
    result["java_profile"] = args.java_profile
    (folder / "qualification.json").write_text(json.dumps(result, indent=2) + "\n")
    print(json.dumps(result), flush=True)


if __name__ == "__main__":
    main()
