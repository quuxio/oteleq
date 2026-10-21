"""Qualify actual Java receivers, private storage, aliases and mutation controls."""
import argparse
import hashlib
import json
import os
from pathlib import Path
import sys

from qualify_generation import command


SOURCE = r'''class Counter {
 private int value;
 private static int total;
 Counter self=this;
 Object[] shared=new Object[]{this,null};
 private Counter(int start){value=start;shared[1]=shared;}
 private static Counter make(int start){return new Counter(start);}
 private static boolean active(){return java.lang.management.ManagementFactory.getRuntimeMXBean().getInputArguments().stream().anyMatch(v -> v.contains("java-agent-0.1.0-agent.jar"));}
 Counter identity(int amount){value+=amount;total+=amount;return this;}
 Object[] array(int amount){value+=amount;return shared;}
 String text(int amount){value+=amount;return new String(new char[]{'z',0,'\ud800'});}
 void touch(int amount){value+=amount;}
 private int secret(int amount){value+=amount;return value;}
 int instance(int amount){value+=amount+(active()?1:0);return 7;}
 int static_only(int amount){total+=amount+(active()?1:0);return 7;}
 String fail(int amount){value+=amount;throw new IllegalArgumentException("expected");}
}
'''
METHODS = ("identity", "array", "text", "touch", "secret", "instance", "static_only", "fail")
DIFFERENCES = {"instance", "static_only"}


def prepare(cli: Path, provider: Path, folder: Path, source_text: str = SOURCE,
            methods: tuple[str, ...] = METHODS, factory: str | None = None, *, backend: str = "legacy", profile: str | None = None) -> Path:
    """Freeze eight explicit methods and independent constructor/factory inputs."""
    folder.mkdir()
    source = folder / "application"
    source.mkdir()
    if backend == "prepared":
        source_text = source_text.replace("java-agent-0.1.0-agent.jar", "opentelemetry-javaagent-2.32.0.jar")
    (source / "Counter.java").write_text(source_text)
    policy = folder / "equivalence.toml"
    text = 'schema_version=1\nlanguages=["java"]\n[adapters.java]\nbackend=' + json.dumps(backend)
    if profile is not None:
        text += '\nprofile=' + json.dumps(profile)
    text += '\n[functions]\ninclude=' + json.dumps(["Counter." + name + "(int)" for name in methods]) + '\n'
    for name in methods:
        text += '\n[[fixtures]]\nfunction=' + json.dumps("Counter." + name + "(int)") + '\ncases=[[7]]\n'
        text += 'receiver={factory=' + json.dumps(factory or ("make" if name == "secret" else "Counter")) + ',arguments=[10]}\n'
        text += 'domains=[{kind="integer",minimum=0,maximum=7}]\n'
        if name == "fail":
            text += 'expected_baseline={kind="error",category="exception",type="java.lang.IllegalArgumentException"}\n'
    policy.write_text(text)
    workspace = Path(command([cli, "plan", "--source", source, "--otelc-root", provider,
                              "--workspace-parent", folder, "--config", policy], folder, "plan"))
    command([cli, "generate", "--workspace", workspace], folder, "generate")
    return workspace


def integer(value: int) -> dict:
    """The fixture declares primitive Java int fields, parameters and results."""
    return {"kind": "integer", "type": "java.int", "value": str(value), "bits": 32, "signed": True}


def reference_id(value: dict) -> str:
    """Local node labels may vary; reference shape and relationships may not."""
    assert type(value) is dict and set(value) == {"kind", "node_id"} and value["kind"] == "reference"
    assert type(value["node_id"]) is str and value["node_id"]
    return value["node_id"]


def graph_nodes(graph: dict) -> dict:
    """Do not hide duplicate nodes, malformed fields or extra graph dimensions."""
    assert type(graph) is dict and set(graph) == {"roots", "nodes"}
    assert type(graph["roots"]) is dict and type(graph["nodes"]) is list
    for item in graph["nodes"]:
        assert type(item) is dict and set(item) == {"id", "type", "fields"}
        assert type(item["id"]) is str and item["id"] and type(item["fields"]) is dict
    result = {item["id"]: item for item in graph["nodes"]}
    assert len(result) == len(graph["nodes"])
    return result


def string_node(identity: str, units: str) -> dict:
    """Expected UTF-16 units come from the fixed source, never its observations."""
    return {"id": identity, "type": "java.object:java.lang.String", "fields": {
        "value": {"kind": "string", "type": "java.lang.String", "encoding": "utf16_be", "value": units}}}


def result_nodes(graph: dict, nodes: dict, method: str, value: int, receiver: dict, shared: dict) -> tuple:
    """Construct the complete declared result/error graph with opaque local IDs."""
    key = "error" if method == "fail" else "result"
    assert key in graph["roots"]
    result = graph["roots"][key]
    if method == "fail":
        error = reference_id(result)
        assert error in nodes and "message" in nodes[error]["fields"]
        message = nodes[error]["fields"]["message"]
        text = reference_id(message)
        return key, result, [{"id": error, "type": "java.lang.IllegalArgumentException", "fields": {"message": message}},
                             string_node(text, "00650078007000650063007400650064")]
    if method == "text":
        return key, result, [string_node(reference_id(result), "007a0000d800")]
    values = {"identity": receiver, "array": shared, "touch": {"kind": "undefined"},
              "secret": integer(value), "instance": integer(7), "static_only": integer(7)}
    assert method in values
    return key, values[method], []


def check_state(graph: dict, value: int, total: int, amount: int, *, method: str | None = None) -> None:
    """Require every literal type, value, root, field and alias in this fixture."""
    nodes = graph_nodes(graph)
    assert "receiver" in graph["roots"]
    receiver = graph["roots"]["receiver"]
    receiver_id = reference_id(receiver)
    assert receiver_id in nodes and "shared" in nodes[receiver_id]["fields"]
    shared = nodes[receiver_id]["fields"]["shared"]
    array_id = reference_id(shared)
    roots = {"receiver": receiver, "argument:0": integer(amount), "static:Counter.total": integer(total)}
    expected = {receiver_id: {"id": receiver_id, "type": "java.object:Counter", "fields": {
        "value": integer(value), "self": receiver, "shared": shared}},
        array_id: {"id": array_id, "type": "java.object:[Ljava.lang.Object;", "fields": {
            "length": integer(2), "item:0": receiver, "item:1": shared}}}
    assert receiver_id != array_id
    if method is not None:
        key, result, additional = result_nodes(graph, nodes, method, value, receiver, shared)
        roots[key] = result
        for item in additional:
            assert item["id"] not in expected
            expected[item["id"]] = item
    assert json.dumps(graph["roots"], sort_keys=True) == json.dumps(roots, sort_keys=True)
    assert json.dumps(nodes, sort_keys=True) == json.dumps(expected, sort_keys=True)


def check_report(path: Path, expected_cases: int) -> tuple[int, dict]:
    """Check each actual lane observation and its decoded instrumentation witness."""
    report = json.loads(path.read_text())
    assert report["source_preserved"] and not report["blocked"] and len(report["cases"]) == expected_cases
    launches = 0
    for case in report["cases"]:
        method = case["function"].split(".")[-1].split("(")[0]
        assert method in METHODS
        assert case["function"] == "Counter." + method + "(int)"
        assert case["exit_code"] == int(method in DIFFERENCES)
        assert case["receiver_fixture"]["arguments"] == [10]
        assert len(case["arguments"]) == 1 and type(case["arguments"][0]) is int and 0 <= case["arguments"][0] <= 7
        bundle = json.loads((path.parent / case["case"] / "typed-bundle.json").read_text())["cases"][0]
        assert set(bundle["contract"]["required_roots"]) == {"receiver", "argument:0", "static:Counter.total"}
        for lane in ("baseline", "instrumented_on"):
            assert len(bundle[lane]) == 2
            for attempt in bundle[lane]:
                launches += 1
                observed = attempt["observation"]
                assert not observed["gaps"]
                amount, active = case["arguments"][0], int(lane == "instrumented_on")
                check_state(observed["before"], 10, 0, amount)
                value = 10 if method == "static_only" else 10 + amount + (active if method == "instance" else 0)
                total = amount + active if method == "static_only" else amount if method == "identity" else 0
                check_state(observed["after"], value, total, amount)
                outcome = observed["outcome"]
                check_state(outcome["graph"], value, total, amount, method=method)
                if method == "fail":
                    assert outcome["kind"] == "error" and outcome["category"] == "exception"
                else:
                    assert outcome["kind"] == "return"
                if lane == "instrumented_on":
                    assert attempt["execution"]["witness"]["functions"] == {case["function"]: 1}
    return launches, report


def framework(workspace: Path, folder: Path, name: str, expected_cases: int = len(METHODS)) -> int:
    """Generated unittest failures must correspond to the two deliberate controls."""
    output = command([sys.executable, workspace / "tests/test_equivalence.py"], folder, name, expected=1)
    summaries = [json.loads(line) for line in output.splitlines()]
    assert len(summaries) == expected_cases
    return sum(check_report(Path(item["report"]), 1)[0] for item in summaries)


def commands(folder: Path) -> list[Path]:
    """Count application launches separately from javac builds and copied evidence."""
    return [path for path in folder.rglob("command.json") if path.parent.name.startswith(("baseline-", "instrumented_on-"))]


def check_build(folder: Path) -> int:
    """Independently recheck compiler reads, class origins and retained products."""
    def sha(path: Path) -> str:
        return hashlib.sha256(path.read_bytes()).hexdigest()
    def inventory(root: Path) -> dict:
        paths = list(root.rglob("*"))
        assert all(not path.is_symlink() for path in paths)
        return {path.relative_to(root).as_posix(): sha(path) for path in paths if path.is_file()}
    record = json.loads((folder / "build-identities.json").read_text())
    project, classes = folder / "project", folder / "scratch/classes"
    assert inventory(project) == record["source_sha256"]
    assert inventory(classes) == record["classes_sha256"]
    for name, key in (("java-compiler.json", "compiler_metadata_sha256"),
                      ("java-compiler-identity.json", "compiler_identity_sha256"),
                      ("prepared-application.json", "prepared_application_sha256")):
        assert sha(folder / name) == record[key]
    metadata = json.loads((folder / "java-compiler.json").read_text())
    identity = json.loads((folder / "java-compiler-identity.json").read_text())
    application = json.loads((folder / "prepared-application.json").read_text())
    original_project, original_classes = map(Path, identity["argv"][4:6])
    assert metadata == json.loads((folder / "build/stdout").read_text())
    assert identity["compiler_metadata_sha256"] == record["compiler_metadata_sha256"]
    assert len(identity["inputs_sha256"]) == 3
    assert all(sha(Path(name)) == value for name, value in identity["inputs_sha256"].items())
    assert application["schema_version"] == 1 and application["classpath"] == [str(original_classes)]
    assert application["main_class"] == record["main_class"] and application["main_class"] in application["bindings"]
    assert metadata["success"] is True and len(metadata["outputs"]) == len(application["bindings"]) == len(record["classes_sha256"])
    assert {output["class"] for output in metadata["outputs"]} == set(application["bindings"])
    assert {name.replace(".", "/") + ".class" for name in application["bindings"]} == set(record["classes_sha256"])
    for source, expected in metadata["source_reads_sha256"].items():
        assert sha(project / Path(source).relative_to(original_project)) == expected
    for output in metadata["outputs"]:
        source, = output["origins"]
        binding = application["bindings"][output["class"]]
        copied_source = project / Path(source).relative_to(original_project)
        assert binding["source"] == source and binding["source_sha256"] == metadata["source_reads_sha256"][source] == sha(copied_source)
        relative = output["class"].replace(".", "/") + ".class"
        assert output["output"] == str(original_classes / relative) and binding["class_sha256"] == sha(classes / relative)
        assert binding["provenance"] == "oteleq.jdk-file-manager-v1:" + record["compiler_identity_sha256"]
    return len(application["bindings"])


def verify_builds(folder: Path) -> dict:
    """Keep copied shrink evidence separate from unique compiler identities."""
    manifests = list(folder.rglob("prepared-application.json"))
    assert manifests
    counts = [check_build(path.parent) for path in manifests]
    unique = {hashlib.sha256(path.read_bytes()).hexdigest() for path in manifests}
    return {"retained_manifests": len(manifests), "unique_manifest_identities": len(unique),
            "retained_class_bindings": sum(counts)}


def verify_launches(folder: Path, expected: int) -> dict:
    """Copied original shrink evidence must not inflate the actual launch count."""
    raw = commands(folder)
    unique = {hashlib.sha256(path.read_bytes()).hexdigest() for path in raw}
    assert len(unique) == expected
    return {"raw_attempt_folders": len(raw), "unique_command_identities": len(unique)}


def verify_prepared(folder: Path, receipt_verifier=None) -> dict:
    """Independently inspect retained PID, archive and actual protobuf accounting."""
    from opentelemetry.proto.collector.metrics.v1.metrics_service_pb2 import ExportMetricsServiceRequest
    from opentelemetry.proto.collector.trace.v1.trace_service_pb2 import ExportTraceServiceRequest
    records, identities, instrumented = [], set(), 0
    for path in folder.rglob("prepared-launch.json"):
        attempt = path.parent
        launch = json.loads(path.read_text())
        process = json.loads((attempt / "process.json").read_text())
        assert process["argv"] == launch["argv"] == json.loads((attempt / "command.json").read_text())
        assert type(process["pid"]) is int and process["pid"] > 0
        identities.add((process["pid"], tuple(process["argv"])))
        archive = json.loads((attempt / "runtime-archive.json").read_text())
        original = Path(archive["original"])
        assert original.name == "r" and original.parent.name.startswith("oej-") and not original.exists()
        retained = attempt / "sdk-runtime"
        files = {item.relative_to(retained).as_posix() for item in retained.rglob("*") if item.is_file()}
        assert files == set(archive["files"])
        for name, identity in archive["files"].items():
            assert hashlib.sha256((retained / name).read_bytes()).hexdigest() == identity["sha256"]
            assert identity["path"] == str(original / name)
        records.append(launch)
        if not launch["plain"]:
            (receipt_verifier or verify_receipt)(attempt, launch, process["pid"], ExportTraceServiceRequest, ExportMetricsServiceRequest)
            instrumented += 1
    assert records and instrumented
    return {"retained_attempts": len(records), "unique_processes": len(identities),
            "retained_instrumented_receipts": instrumented, "short_runtimes_removed": True}


def verify_receipt(attempt: Path, launch: dict, pid: int, trace_decoder, metric_decoder) -> None:
    """Literal one-call receiver oracles bind real health to all received units."""
    health = json.loads((attempt / "sdk-runtime/health.json").read_text())
    http = json.loads((attempt / "http-capture.json").read_text())
    assert not http["errors"] and health["pid"] == pid
    assert health["policy_sha256"] == launch["policy_sha256"] and health["selection_sha256"] == launch["selection_sha256"]
    assert health["phase"] == "final" and health["sdk_attached"] is True
    assert health["lifecycle"] == {"flush": "succeeded", "shutdown": "succeeded"}
    spans, points, batches = [], 0, {"/v1/traces": 0, "/v1/metrics": 0}
    for body in http["bodies"]:
        route = body["path"];batches[route] += 1
        raw = (attempt / body["file"]).read_bytes()
        if route == "/v1/traces":
            message = trace_decoder.FromString(raw)
            spans += [span for group in message.resource_spans for scope in group.scope_spans for span in scope.spans]
        else:
            message = metric_decoder.FromString(raw)
            points += sum(len(getattr(metric, metric.WhichOneof("data")).data_points)
                          for group in message.resource_metrics for scope in group.scope_metrics for metric in scope.metrics)
    assert len(spans) == 1 and points > 0 and not spans[0].parent_span_id
    observed = json.loads((attempt / "typed-observation.json").read_text())
    assert observed["function_id"] in {"Counter." + method + "(int)" for method in METHODS}
    assert spans[0].name == observed["function_id"].split("(", 1)[0]
    accounting = health["span_accounting"]
    assert accounting == {"processors_observed": 1, "batch_processors_observed": 1,
                          "sampled_started": "1", "sampled_ended": "1", "sampled_active": "0",
                          "queue_pending": "0", "queue_dropped": "0", "queue_evidence": "derived_after_shutdown"}
    for group, route, units in (("trace_exports", "/v1/traces", 1), ("metric_exports", "/v1/metrics", points)):
        exported = health[group]
        assert exported["batches_started"] == exported["batches_succeeded"] == str(batches[route])
        assert exported["units_started"] == exported["units_succeeded"] == str(units)
        assert all(exported[name] == "0" for name in ("batches_failed", "units_failed", "batches_pending"))


def reduction(cli: Path, workspace: Path, folder: Path, report: dict) -> int:
    """Keep construction inputs fixed while a same-return static difference shrinks."""
    target = next(case for case in report["cases"] if case["function"] == "Counter.static_only(int)")
    reduced = folder / "shrinking"
    command([cli, "shrink", "--workspace", workspace, "--case", target["case"], "--report-dir", reduced, "--trials", "16"], folder, "shrink", expected=1)
    result = json.loads((reduced / "shrink.json").read_text())
    assert result["original_arguments"] == [7] and result["reduced_arguments"] == [0]
    assert result["status"] == "candidate_rule_minimal" and result["source_preserved"]
    reports = [reduced / "original/report.json", reduced / "confirmation/report.json",
               *(Path(trial["report"]) for trial in result["trials"])]
    launches = sum(check_report(path, 1)[0] for path in reports)
    replay_workspace = Path(result["workspace"])
    launches += framework(replay_workspace, folder, "shrunk-framework", expected_cases=1)
    replay = json.loads(command([cli, "replay", "--workspace", replay_workspace, "--case", target["case"]], folder, "shrunk-replay", expected=1))
    return launches + check_report(Path(replay["report"]), 1)[0]


def refusals(cli: Path, provider: Path, folder: Path, *, backend: str = "legacy") -> tuple[int, int]:
    """Unavailable fixtures cannot become matching outcomes or trigger formatters."""
    unknown = 'class UnknownException extends RuntimeException {public String toString(){return "APP_CALLBACK";}public String getMessage(){throw new AssertionError("APP_CALLBACK");}}'
    controls = [
        ("missing-factory", SOURCE, "instance", "missing", 3),
        ("interface-storage", SOURCE.replace("class Counter {", "class Counter implements java.io.Serializable {"), "instance", None, 3),
        ("wrong-class", SOURCE.replace("private static Counter make(int start){return new Counter(start);}", "private static Object make(int start){return new Object();}"), "secret", "make", 4),
        ("custom-error", SOURCE.replace('throw new IllegalArgumentException("expected");', 'throw new UnknownException();') + unknown, "fail", None, 4),
        ("initialisation-error", SOURCE.replace("private int value;", "private int value;static {if(true)throw new UnknownException();}") + unknown, "instance", None, 4),
    ]
    launches = 0
    for name, source, method, factory, expected in controls:
        destination = folder / name
        workspace = prepare(cli, provider, destination, source, (method,), factory, backend=backend)
        comparison = destination / "comparison"
        command([cli, "run", "--workspace", workspace, "--report-dir", comparison], folder, name, expected=expected)
        report = json.loads((comparison / "report.json").read_text())
        assert report["source_preserved"]
        if expected == 3:
            assert len(report["blocked"]) == 1 and not report["cases"] and not commands(comparison)
        else:
            assert not report["blocked"] and len(report["cases"]) == 1 and report["cases"][0]["exit_code"] == 4
            assert len(commands(comparison)) == 1 and not list(comparison.rglob("observation"))
            launches += 1
        assert all(b"APP_CALLBACK" not in path.read_bytes() for path in comparison.rglob("stderr"))
    return launches, len(controls)


def source_guards(cli: Path, workspace: Path, folder: Path, report: dict) -> int:
    """Changed source and snapshot inputs must refuse before any JVM launch."""
    plan = json.loads((workspace / "plan.json").read_text())
    before = len(commands(folder))
    for name, source in (("source", Path(plan["source"]) / "Counter.java"), ("snapshot", workspace / "snapshot/Counter.java")):
        original = source.read_bytes()
        try:
            source.write_bytes(original + b"\n// changed input\n")
            command([cli, "replay", "--workspace", workspace, "--case", report["cases"][0]["case"]], folder, "changed-" + name, expected=4)
            assert b"source" in (folder / ("changed-" + name + ".stderr")).read_bytes()
            assert len(commands(folder)) == before
        finally:
            source.write_bytes(original)
    return 2


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--otelc-root", type=Path, required=True)
    parser.add_argument("--cli", type=Path, required=True)
    parser.add_argument("--report-dir", type=Path, required=True)
    parser.add_argument("--java-backend", choices=("legacy", "prepared"), default="legacy")
    args = parser.parse_args()
    cli, provider = args.cli.resolve(strict=True), args.otelc_root.resolve(strict=True)
    destination = args.report_dir.resolve()
    if destination.is_relative_to(provider) or destination.is_relative_to(Path(__file__).resolve().parents[1]):
        parser.error("report directory must be new and outside both repositories")
    destination.mkdir(mode=0o700, exist_ok=False)
    os.environ["OTELEQ_PYTHON"], os.environ["OTELEQ_CLI"] = sys.executable, str(cli)
    workspace = prepare(cli, provider, destination / "complete", backend=args.java_backend)
    launches = 0
    command([cli, "run", "--workspace", workspace, "--report-dir", destination / "run"], destination, "run", expected=1)
    launches, report = check_report(destination / "run/report.json", len(METHODS))
    for case in report["cases"]:
        expected = case["exit_code"]
        output = command([cli, "replay", "--workspace", workspace, "--case", case["case"]],
                         destination, "replay-" + case["case"], expected=expected)
        replay = json.loads(output)
        launches += check_report(Path(replay["report"]), 1)[0]
    launches += framework(workspace, destination, "generated-framework")
    exported = destination / "exported"
    command([cli, "export-tests", "--workspace", workspace, "--destination", exported], destination, "export-dry-run")
    assert not exported.exists()
    command([cli, "export-tests", "--workspace", workspace, "--destination", exported, "--apply"], destination, "export-apply")
    source = destination / "complete/application"
    offline = source.with_name("application-offline")
    if args.java_backend == "prepared":
        source.rename(offline)
    try:
        launches += framework(exported, destination, "exported-framework")
    finally:
        if args.java_backend == "prepared":
            offline.rename(source)
    launches += reduction(cli, workspace, destination, report)
    refused_launches, refusal_controls = refusals(cli, provider, destination, backend=args.java_backend)
    launches += refused_launches
    refusal_controls += source_guards(cli, workspace, destination, report)
    counts = verify_launches(destination, launches)
    builds = verify_builds(destination)
    prepared = verify_prepared(destination) if args.java_backend == "prepared" else None
    result = {"claim": "equivalence over these tests and observations", "artefact_class": "diagnostic",
              "java_backend": args.java_backend,
              "cases": len(METHODS), "matching_cases": 6, "same_return_state_differences": 2,
              "actual_launches": launches, **counts,
              "compiler_builds": builds,
              "prepared_provider": prepared,
              "exported_without_original_source": args.java_backend == "prepared",
              "refusal_controls": refusal_controls, "scalar_shrink": {"original": [7], "reduced": [0]},
              "routes": ["run", "replay", "generated", "exported"],
              "cli_sha256": hashlib.sha256(cli.read_bytes()).hexdigest(), "source_preserved": True}
    (destination / "qualification.json").write_text(json.dumps(result, indent=2) + "\n")
    print(json.dumps(result))


if __name__ == "__main__":
    main()
