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
            methods: tuple[str, ...] = METHODS, factory: str | None = None) -> Path:
    """Freeze eight explicit methods and independent constructor/factory inputs."""
    folder.mkdir()
    source = folder / "application"
    source.mkdir()
    (source / "Counter.java").write_text(source_text)
    policy = folder / "equivalence.toml"
    text = 'schema_version=1\nlanguages=["java"]\n[functions]\ninclude=' + json.dumps(["Counter." + name + "(int)" for name in methods]) + '\n'
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


def node(graph: dict, value: dict) -> dict:
    """Resolve local graph identity, never application equality or formatting."""
    return next(item for item in graph["nodes"] if item["id"] == value["node_id"])


def check_state(graph: dict, value: int, total: int) -> None:
    """Independent literal oracles cover private fields, aliases and array cycles."""
    roots = graph["roots"]
    fields = node(graph, roots["receiver"])["fields"]
    assert fields["value"]["value"] == str(value)
    assert roots["static:Counter.total"]["value"] == str(total)
    assert fields["self"] == roots["receiver"]
    array = node(graph, fields["shared"])
    assert array["type"] == "java.object:[Ljava.lang.Object;"
    assert array["fields"]["length"]["value"] == "2"
    assert array["fields"]["item:0"] == roots["receiver"]
    assert array["fields"]["item:1"] == fields["shared"]


def check_report(path: Path, expected_cases: int) -> tuple[int, dict]:
    """Check each actual lane observation and its decoded instrumentation witness."""
    report = json.loads(path.read_text())
    assert report["source_preserved"] and not report["blocked"] and len(report["cases"]) == expected_cases
    launches = 0
    for case in report["cases"]:
        method = case["function"].split(".")[-1].split("(")[0]
        assert method in METHODS
        assert case["exit_code"] == int(method in DIFFERENCES)
        assert case["receiver_fixture"]["arguments"] == [10]
        bundle = json.loads((path.parent / case["case"] / "typed-bundle.json").read_text())["cases"][0]
        assert set(bundle["contract"]["required_roots"]) == {"receiver", "argument:0", "static:Counter.total"}
        for lane in ("baseline", "instrumented_on"):
            assert len(bundle[lane]) == 2
            for attempt in bundle[lane]:
                launches += 1
                observed = attempt["observation"]
                assert not observed["gaps"]
                check_state(observed["before"], 10, 0)
                amount, active = case["arguments"][0], int(lane == "instrumented_on")
                value = 10 if method == "static_only" else 10 + amount + (active if method == "instance" else 0)
                total = amount + active if method == "static_only" else amount if method == "identity" else 0
                check_state(observed["after"], value, total)
                outcome = observed["outcome"]
                check_state(outcome["graph"], value, total)
                if method == "fail":
                    assert outcome["kind"] == "error" and outcome["category"] == "exception"
                    error = node(outcome["graph"], outcome["graph"]["roots"]["error"])
                    assert error["type"] == "java.lang.IllegalArgumentException"
                    message = node(outcome["graph"], error["fields"]["message"])["fields"]["value"]
                    assert message["value"] == "00650078007000650063007400650064"
                else:
                    result = outcome["graph"]["roots"]["result"]
                    assert outcome["kind"] == "return"
                    if method == "identity":
                        assert result == outcome["graph"]["roots"]["receiver"]
                    elif method == "array":
                        assert result == node(outcome["graph"], outcome["graph"]["roots"]["receiver"])["fields"]["shared"]
                    elif method == "text":
                        assert node(outcome["graph"], result)["fields"]["value"]["value"] == "007a0000d800"
                    elif method == "touch":
                        assert result == {"kind": "undefined"}
                    else:
                        assert result["value"] == str(value if method == "secret" else 7)
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


def refusals(cli: Path, provider: Path, folder: Path) -> tuple[int, int]:
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
        workspace = prepare(cli, provider, destination, source, (method,), factory)
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
    args = parser.parse_args()
    cli, provider = args.cli.resolve(strict=True), args.otelc_root.resolve(strict=True)
    destination = args.report_dir.resolve()
    if destination.is_relative_to(provider) or destination.is_relative_to(Path(__file__).resolve().parents[1]):
        parser.error("report directory must be new and outside both repositories")
    destination.mkdir(mode=0o700, exist_ok=False)
    os.environ["OTELEQ_PYTHON"], os.environ["OTELEQ_CLI"] = sys.executable, str(cli)
    workspace = prepare(cli, provider, destination / "complete")
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
    launches += framework(exported, destination, "exported-framework")
    launches += reduction(cli, workspace, destination, report)
    refused_launches, refusal_controls = refusals(cli, provider, destination)
    launches += refused_launches
    refusal_controls += source_guards(cli, workspace, destination, report)
    counts = verify_launches(destination, launches)
    builds = verify_builds(destination)
    result = {"claim": "equivalence over these tests and observations", "artefact_class": "diagnostic",
              "cases": len(METHODS), "matching_cases": 6, "same_return_state_differences": 2,
              "actual_launches": launches, **counts,
              "compiler_builds": builds,
              "refusal_controls": refusal_controls, "scalar_shrink": {"original": [7], "reduced": [0]},
              "routes": ["run", "replay", "generated", "exported"],
              "cli_sha256": hashlib.sha256(cli.read_bytes()).hexdigest(), "source_preserved": True}
    (destination / "qualification.json").write_text(json.dumps(result, indent=2) + "\n")
    print(json.dumps(result))


if __name__ == "__main__":
    main()
