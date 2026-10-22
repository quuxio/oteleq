"""Qualify declared Java roots, private dependencies, literal state and retained builds."""
import argparse
import copy
import hashlib
import json
import math
import os
from pathlib import Path
import shutil
import subprocess
import sys
import tempfile
import tomllib
import zipfile

import java_project_oracle as oracle
from qualify_generation import command
from qualify_java_receivers import commands, verify_launches, verify_prepared

METHOD_SCOPE = ("io.opentelemetry.methods", "2.32.0-alpha")
BOUNDS = [1e-6, 1e-5, 1e-4, .001, .01, .1, 1.]
CALLS = "otelc.function.calls"
DURATION = "otelc.function.duration"

SOURCES = {
    "src/main/java/app/App.java": '''package app;
public class App {
 static int total=2;
 static boolean active(){return java.lang.management.ManagementFactory.getRuntimeMXBean().getInputArguments().stream().anyMatch(v -> v.contains("AGENT_NAME"));}
 static int sum(int n){return dep.Library.value(n)+other.More.value()+Generated.value()+Helper.value();}
 public static int match(int n){total+=n;return sum(n);}
 public static int different(int n){total+=n+(active()?1:0);return sum(n)-n-29;}
 public static int resources(int n)throws java.lang.Exception{total+=n;return n+dep.Library.resource()+other.More.resource();}
}
''',
    "src/main/java/app/Counter.java": '''package app;
public class Counter {
 private int value;
 private static int total=2;
 private Counter(int start){value=start;}
 public int step(int n){value+=n;total+=n;return value+App.sum(n);}
}
''',
    "src/main/java/app/Helper.java": "package app;class Helper {static int value(){return 3;}}\n",
    "target/generated-sources/app/Generated.java": "package app;class Generated {static int value(){return 17;}}\n",
    "pom.xml": "<project><!-- Existing build descriptor: never executed or rewritten. --></project>\n",
    "gradle.lockfile": "existing-lock=1\n",
}


def fixture(folder: Path, backend: str) -> Path:
    """Materialise source/dependency fixtures without invoking a build manager."""
    source = folder / "application"
    source.mkdir()
    agent = "opentelemetry-javaagent-2.32.0.jar" if backend == "prepared" else "java-agent-0.1.0-agent.jar"
    for name, text in SOURCES.items():
        path = source / name
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(text.replace("AGENT_NAME", agent))
    java = Path(os.environ.get("OTELC_JAVA") or shutil.which("java")).resolve()
    dependencies = folder / "dependency classes"
    for package, name, value, resource, output in (("dep", "Library", "n+5", 13, folder / "jar-classes"),
                                                   ("other", "More", "11", 19, dependencies)):
        path = folder / (name + ".java")
        parameters = "int n" if name == "Library" else ""
        path.write_text('package ' + package + ';public class ' + name + ' {public static int value('
            + parameters + '){return ' + value + ';}public static int resource()throws java.lang.Exception {'
            'return java.lang.Integer.parseInt(new java.lang.String(' + name
            + '.class.getResourceAsStream("/' + package + '-factor.txt").readAllBytes(),java.nio.charset.StandardCharsets.UTF_8));}}')
        result = subprocess.run([java.with_name("javac"), "-encoding", "UTF-8", "-proc:none", "-d", output, path],
                                check=False, capture_output=True, timeout=30)
        (folder / (name + "-build.stdout")).write_bytes(result.stdout)
        (folder / (name + "-build.stderr")).write_bytes(result.stderr)
        assert result.returncode == 0
        (output / (package + "-factor.txt")).write_text(str(resource))
    (dependencies / "empty-resource").mkdir()
    jar = source / "lib/library.jar"
    jar.parent.mkdir()
    with zipfile.ZipFile(jar, "w") as archive:
        for path in sorted((folder / "jar-classes").rglob("*")):
            if path.is_file():
                archive.write(path, path.relative_to(folder / "jar-classes").as_posix())
    return source


def configuration(folder: Path, backend: str, profile: str) -> Path:
    """Write the same finite input/return contracts for every execution route."""
    text = 'languages=["java"]\n[functions]\ninclude=' + json.dumps(list(oracle.FUNCTIONS)) + '\n[adapters.java]\nbackend=' + json.dumps(backend)
    if backend == "prepared":
        text += '\nprofile=' + json.dumps(profile)
    text += '\nsource_roots=["src/main/java","target/generated-sources"]\nclasspath=' + json.dumps(["lib/library.jar", str(folder / "dependency classes")]) + '\n'
    for function, method in oracle.FUNCTIONS.items():
        text += '\n[[fixtures]]\nfunction=' + json.dumps(function) + '\ncases=[[7]]\n'
        if method == "receiver":
            text += 'receiver={factory="Counter",arguments=[10]}\n'
        if method == "different":
            text += 'domains=[{kind="integer",minimum=0,maximum=7}]\n'
        result = {"match": 43, "different": 7, "resources": 39, "receiver": 60}[method]
        text += 'expected_baseline=' + json.dumps({"kind": "return_value", "value": oracle.scalar(result, method == "receiver")}).replace(': ', '=') + '\n'
    config = folder / "equivalence.toml"
    config.write_text(text)
    return config


def prepare(cli: Path, provider: Path, folder: Path, *, backend: str = "prepared", profile: str = "safe-methods-v1") -> Path:
    folder.mkdir()
    source = fixture(folder, backend)
    config = configuration(folder, backend, profile)
    workspace = Path(command([cli, "plan", "--source", source, "--otelc-root", provider,
        "--workspace-parent", folder, "--config", config], folder, "plan"))
    plan = oracle.document(workspace / "plan.json")
    assert {row["otelc_function"] for row in plan["inventory"] if row["status"] == "ready"} == set(oracle.FUNCTIONS)
    assert not any(row["status"] == "blocked" for row in plan["inventory"])
    command([cli, "generate", "--workspace", workspace], folder, "generate")
    return workspace


def framework(workspace: Path, folder: Path, label: str, expected_cases: int = 4) -> int:
    output = command([sys.executable, workspace / "tests/test_equivalence.py"], folder, label, expected=1)
    reports = [json.loads(line) for line in output.splitlines()]
    assert len(reports) == expected_cases
    return sum(oracle.check_report(Path(row["report"]), 1)[0] for row in reports)


def verify_receipt(attempt: Path, launch: dict, pid: int, trace_decoder, metric_decoder, *, functions=oracle.FUNCTIONS) -> None:
    """Bind actual direct health to every decoded batch, span and metric point."""
    health = oracle.document(attempt / "sdk-runtime/health.json")
    captured = oracle.document(attempt / "http-capture.json")
    assert not captured["errors"] and health["pid"] == pid
    assert health["policy_sha256"] == launch["policy_sha256"] and health["selection_sha256"] == launch["selection_sha256"]
    assert health["phase"] == "final" and health["sdk_attached"] is True
    assert health["lifecycle"] == {"flush": "succeeded", "shutdown": "succeeded"}
    policy = tomllib.loads((attempt / "policy.toml").read_text())
    assert launch["policy_sha256"] == hashlib.sha256(json.dumps(policy, sort_keys=True).encode()).hexdigest()
    service = policy["resource"]["service_name"]
    observed = oracle.document(attempt / "typed-observation.json")
    assert observed["function_id"] in functions
    owner, method = observed["function_id"].split("(", 1)[0].rsplit(".", 1)
    spans, points, batches = [], 0, {"/v1/traces": 0, "/v1/metrics": 0}
    recorded = {CALLS: [], DURATION: []}
    for record in captured["bodies"]:
        route = record["path"]
        batches[route] += 1
        raw = (attempt / record["file"]).read_bytes()
        if route == "/v1/traces":
            message = trace_decoder.FromString(raw)
            spans += receipt_spans(message, service)
        else:
            message = metric_decoder.FromString(raw)
            points += receipt_metrics(message, method, recorded, service)
    assert len(spans) == 1 and not spans[0].parent_span_id and points > 0
    assert spans[0].name == owner.rsplit(".", 1)[-1] + "." + method
    attributes = {row.key: row.value.string_value for row in spans[0].attributes}
    assert attributes["code.namespace"] == owner and attributes["code.function"] == method
    for values in recorded.values():
        ordered = [value for _, value in sorted(values)]
        assert ordered and ordered[-1] == 1 and ordered == sorted(ordered) and all(0 <= value <= 1 for value in ordered)
    assert health["span_accounting"] == {"processors_observed": 1, "batch_processors_observed": 1,
        "sampled_started": "1", "sampled_ended": "1", "sampled_active": "0", "queue_pending": "0",
        "queue_dropped": "0", "queue_evidence": "derived_after_shutdown"}
    for name, route, units in (("trace_exports", "/v1/traces", 1), ("metric_exports", "/v1/metrics", points)):
        group = health[name]
        assert group["batches_started"] == group["batches_succeeded"] == str(batches[route])
        assert group["units_started"] == group["units_succeeded"] == str(units)
        assert all(group[key] == "0" for key in ("batches_failed", "units_failed", "batches_pending"))


def receipt_resource(resource, service: str) -> None:
    attributes = {row.key: row.value.string_value for row in resource.attributes}
    assert len(attributes) == len(resource.attributes)
    assert attributes.get("service.name") == service and attributes.get("otelc.language") == "java"


def receipt_spans(message, service: str) -> list:
    spans = []
    for group in message.resource_spans:
        receipt_resource(group.resource, service)
        for scope in group.scope_spans:
            assert (scope.scope.name, scope.scope.version) == METHOD_SCOPE
            spans.extend(scope.spans)
    return spans


def receipt_metrics(message, method: str, recorded: dict, service: str) -> int:
    points = 0
    for group in message.resource_metrics:
        receipt_resource(group.resource, service)
        for scope in group.scope_metrics:
            for metric in scope.metrics:
                data = getattr(metric, metric.WhichOneof("data"))
                points += len(data.data_points)
                if metric.name in recorded:
                    function_metric(metric, scope.scope, method, recorded)
    return points


def function_metric(metric, scope, method: str, recorded: dict) -> None:
    calls = metric.name == CALLS
    assert (scope.name, scope.version) == METHOD_SCOPE
    assert metric.unit == ("{call}" if calls else "s")
    assert metric.WhichOneof("data") == ("sum" if calls else "histogram")
    data = getattr(metric, metric.WhichOneof("data"))
    assert data.aggregation_temporality == 2
    for point in data.data_points:
        assert {row.key: row.value.string_value for row in point.attributes} == {"function": method}
        assert point.flags == 0 and 0 < point.start_time_unix_nano <= point.time_unix_nano
        recorded[metric.name].append((point.time_unix_nano, metric_value(metric, data, point)))


def metric_value(metric, data, point) -> int:
    if metric.name == CALLS:
        assert data.is_monotonic and point.WhichOneof("value") == "as_int"
        return point.as_int
    assert list(point.explicit_bounds) == BOUNDS and len(point.bucket_counts) == len(BOUNDS) + 1
    assert sum(point.bucket_counts) == point.count
    assert point.HasField("sum") and math.isfinite(point.sum) and point.sum >= 0
    return point.count


def reductions(cli: Path, workspace: Path, folder: Path, report: dict) -> int:
    case, = [row for row in report["cases"] if row["function"] == "app.App.different(int)"]
    reduced = folder / "shrinking"
    command([cli, "shrink", "--workspace", workspace, "--case", case["case"], "--report-dir", reduced,
             "--trials", "8"], folder, "shrink", expected=1)
    result = oracle.document(reduced / "shrink.json")
    assert result["source_preserved"] and result["original_arguments"] == [7] and result["reduced_arguments"] == [0]
    assert result["status"] == "candidate_rule_minimal"
    reports = [reduced / "original/report.json", reduced / "confirmation/report.json",
               *(Path(trial["report"]) for trial in result["trials"])]
    launches = sum(oracle.check_report(path, 1)[0] for path in reports)
    replay_workspace = Path(result["workspace"])
    launches += framework(replay_workspace, folder, "reduced-framework", 1)
    replay = json.loads(command([cli, "replay", "--workspace", replay_workspace, "--case", case["case"]],
                                folder, "reduced-replay", expected=1))
    return launches + oracle.check_report(Path(replay["report"]), 1)[0]


def refusal_controls(cli: Path, workspace: Path, folder: Path, case: str) -> int:
    """Changed source, original/frozen dependencies and probes must launch no application."""
    plan = oracle.document(workspace / "plan.json")
    source = Path(plan["source"])
    paths = [source / "target/generated-sources/app/Generated.java", source / "lib/library.jar",
             Path(plan["java_context"]["entries"][1]["source"]) / "other-factor.txt",
             workspace / "java-context/classpath/0000.jar"]
    if "java_provider_manifest" in plan:
        paths.append(next((workspace / "java-provider").rglob("stdout")))
    before = len(commands(folder))
    for index, path in enumerate(paths):
        raw = path.read_bytes()
        try:
            path.write_bytes(raw + b"changed")
            command([cli, "replay", "--workspace", workspace, "--case", case], folder, "refuse-" + str(index), expected=4)
            assert len(commands(folder)) == before
        finally:
            path.write_bytes(raw)
    return len(paths)


def retained_evidence(folder: Path, expected_launches: int, backend: str) -> dict:
    """Count original JVMs once, while rechecking all copied reduction evidence."""
    launches = verify_launches(folder, expected_launches)
    records = list(folder.rglob("prepared-application.json"))
    counts = []
    for path in records:
        attempt = path.parent
        counts.append(oracle.check_build(attempt))
        observed = oracle.document(attempt / "typed-observation.json")
        oracle.check_origins(attempt, observed["function_id"])
    result = {"actual_application_jvm_launches": expected_launches, "launches": launches,
        "retained_builds": len(records), "unique_builds": len({oracle.sha(path) for path in records}),
        "retained_class_bindings": sum(counts)}
    if backend == "prepared":
        result["prepared"] = verify_prepared(folder, verify_receipt)
    return result


def repair_metadata(folder: Path, metadata: dict) -> None:
    """Retain a deliberately rehashed control, not a trivial broken-file checksum."""
    raw = json.dumps(metadata, indent=2) + "\n"
    (folder / "java-compiler.json").write_text(raw)
    (folder / "build/stdout").write_text(raw)
    identity = oracle.document(folder / "java-compiler-identity.json")
    identity["compiler_metadata_sha256"] = oracle.sha(folder / "java-compiler.json")
    (folder / "java-compiler-identity.json").write_text(json.dumps(identity))
    record = oracle.document(folder / "build-identities.json")
    record["compiler_metadata_sha256"] = identity["compiler_metadata_sha256"]
    record["compiler_identity_sha256"] = oracle.sha(folder / "java-compiler-identity.json")
    application = oracle.document(folder / "prepared-application.json")
    for binding in application["bindings"].values():
        binding["provenance"] = "oteleq.jdk-file-manager-v1:" + record["compiler_identity_sha256"]
    (folder / "prepared-application.json").write_text(json.dumps(application))
    record["prepared_application_sha256"] = oracle.sha(folder / "prepared-application.json")
    (folder / "build-identities.json").write_text(json.dumps(record))


def evidence_controls(folder: Path, *, report_root: Path | None = None) -> int:
    """Reject altered compiler reads/options, resource bytes and loaded origins."""
    source = next((report_root or folder / "comparison").rglob("java-compiler.json")).parent
    count = 0
    for fault in ("changed-read", "foreign-read", "compiler-options", "resource", "loaded-origin"):
        with tempfile.TemporaryDirectory(prefix="oracle-control-", dir=folder) as temporary:
            copied = Path(temporary) / "evidence"
            shutil.copytree(source, copied)
            oracle.check_build(copied)
            observed = oracle.document(copied / "typed-observation.json")
            metadata = alter_evidence(copied, fault)
            try:
                oracle.check_build(copied)
                oracle.check_origins(copied, observed["function_id"])
            except (AssertionError, KeyError):
                count += 1
            else:
                raise AssertionError("altered evidence passed: " + fault)
            (folder / ("control-" + fault + ".json")).write_text(json.dumps({"fault": fault, "refused": True,
                "original_attempt": str(source), "compiler_metadata": metadata}, indent=2) + "\n")
    return count


def alter_evidence(folder: Path, fault: str) -> dict:
    """Each control changes one semantic input and repairs only its outer receipts."""
    metadata = copy.deepcopy(oracle.document(folder / "java-compiler.json"))
    if fault == "changed-read":
        metadata["class_reads_sha256"][next(iter(metadata["class_reads_sha256"]))] = "0" * 64
    elif fault == "foreign-read":
        metadata["class_reads_sha256"]["file:/unowned/Foreign.class"] = "0" * 64
    elif fault == "compiler-options":
        metadata["options"].append("-parameters")
    elif fault == "resource":
        (folder / "java-classpath/0001/other-factor.txt").write_text("changed")
    else:
        assert fault == "loaded-origin"
        log = folder / "sdk-runtime/class-load.log" if (folder / "prepared-launch.json").exists() else folder / "class-load.log"
        log.write_text(log.read_text().replace("dep.Library source: file:", "dep.Library source: file:/unowned"))
    if fault in ("changed-read", "foreign-read", "compiler-options"):
        repair_metadata(folder, metadata)
    return metadata


def run(cli: Path, provider: Path, folder: Path, backend: str, profile: str) -> dict:
    workspace = prepare(cli, provider, folder / "complete", backend=backend, profile=profile)
    plan = oracle.document(workspace / "plan.json")
    source, dependency_root = Path(plan["source"]), folder / "complete/dependency classes"
    before_source, before_dependency = oracle.inventory(source), oracle.inventory(dependency_root)
    command([cli, "run", "--workspace", workspace, "--report-dir", folder / "comparison"], folder, "run", expected=1)
    launches, report = oracle.check_report(folder / "comparison/report.json", 4)
    print(json.dumps({"stage": "direct", "actual_application_jvm_launches": launches}), flush=True)
    for case in report["cases"]:
        replay = json.loads(command([cli, "replay", "--workspace", workspace, "--case", case["case"]],
            folder, "replay-" + case["case"], expected=case["exit_code"]))
        launches += oracle.check_report(Path(replay["report"]), 1)[0]
    launches += framework(workspace, folder, "generated-framework")
    print(json.dumps({"stage": "replay-and-generated", "actual_application_jvm_launches": launches}), flush=True)
    controls = refusal_controls(cli, workspace, folder, report["cases"][0]["case"])
    launches += reductions(cli, workspace, folder, report)
    print(json.dumps({"stage": "reduction", "actual_application_jvm_launches": launches}), flush=True)
    exported = folder / "exported"
    command([cli, "export-tests", "--workspace", workspace, "--destination", exported, "--apply"], folder, "export")
    source.rename(source.with_name("application-offline"))
    dependency_root.rename(dependency_root.with_name("dependency-offline"))
    try:
        launches += framework(exported, folder, "detached-framework")
    finally:
        source.with_name("application-offline").rename(source)
        dependency_root.with_name("dependency-offline").rename(dependency_root)
    assert oracle.inventory(source) == before_source and oracle.inventory(dependency_root) == before_dependency
    evidence = retained_evidence(folder, launches, backend)
    altered_controls = evidence_controls(folder)
    return {"claim": "equivalence over these tests and observations", "artefact_class": "diagnostic",
            "cli_sha256": oracle.sha(cli), "java_backend": backend, "java_profile": profile if backend == "prepared" else None,
            "cases": 4, "matching_cases": 3, "same_return_state_differences": 1, "prelaunch_refusal_controls": controls,
            "altered_evidence_controls": altered_controls,
            "source_preserved": True, "dependency_preserved": True, "detached_export": True,
            "scalar_shrink": {"original": [7], "reduced": [0]}, **evidence,
            "scope": "Declared ordinary source roots and JAR/class/resource inputs; complete independent fixed-fixture values, compiler reads/products and loaded origins. No modules, MR-JAR, general build-system or shipping-artefact qualification."}


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--otelc-root", type=Path, required=True)
    parser.add_argument("--cli", type=Path, required=True)
    parser.add_argument("--report-dir", type=Path, required=True)
    parser.add_argument("--java-backend", choices=("legacy", "prepared"), default="prepared")
    parser.add_argument("--java-profile", choices=("stock-methods-v1", "safe-methods-v1"))
    args = parser.parse_args()
    if args.java_backend == "legacy" and args.java_profile is not None:
        parser.error("--java-profile requires the prepared backend")
    cli, provider, folder = args.cli.resolve(strict=True), args.otelc_root.resolve(strict=True), args.report_dir.resolve()
    if folder.is_relative_to(provider) or folder.is_relative_to(Path(__file__).resolve().parents[1]):
        parser.error("report directory must be new and outside both repositories")
    folder.mkdir(mode=0o700, exist_ok=False)
    os.environ.update(OTELEQ_PYTHON=sys.executable, OTELEQ_CLI=str(cli))
    result = run(cli, provider, folder, args.java_backend, args.java_profile or "safe-methods-v1")
    (folder / "qualification.json").write_text(json.dumps(result, indent=2) + "\n")
    print(json.dumps(result), flush=True)


if __name__ == "__main__":
    main()
