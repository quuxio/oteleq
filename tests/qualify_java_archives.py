"""Qualify actual generated Java suites against explicit runtime archive selection."""
import argparse
from functools import partial
import json
import os
from pathlib import Path
import shutil
import subprocess
import sys
import tempfile
import zipfile

import java_archive_oracle as oracle
import java_project_oracle as project
from qualify_generation import command
from qualify_java_project import verify_receipt
from qualify_java_project import repair_metadata
from qualify_java_receivers import commands, verify_launches, verify_prepared

PROFILE = "archive-methods-v1"


def libraries(folder: Path, java: Path) -> dict[int, bytes]:
    """Compile independently distinguishable constants and method bodies once."""
    result = {}
    for number in (5, 9, 17, 21, 22):
        root = folder / str(number)
        root.mkdir()
        source = root / "Library.java"
        source.write_text('package dep;public class Library {public static final int INLINE=' + str(number)
            + '; public static int value(){return ' + str(number) + ';}'
            'public static int resource()throws java.lang.Exception{return java.lang.Integer.parseInt(new java.lang.String('
            'Library.class.getResourceAsStream("/factor.txt").readAllBytes(),java.nio.charset.StandardCharsets.UTF_8));}}')
        command([java.with_name("javac"), "-encoding", "UTF-8", "-proc:none", "-d", root, source], root, "compile")
        result[number] = (root / "dep/Library.class").read_bytes()
    return result


def prepare(cli: Path, provider: Path, folder: Path, variant: str, compiled: dict[int, bytes], java: Path) -> Path:
    """Keep the real JAR intact; configure only existing source and classpath inputs."""
    folder.mkdir()
    source = folder / "application"
    (source / "src/app").mkdir(parents=True)
    helper = 'helper=io.quux.otelc.methods.MethodMetrics.value();' if variant == "collision" else ""
    returned = "7" if variant == "mutation" else "n+compiled+method+resource+directory" + ("+helper-3" if helper else "")
    extra = '+(java.lang.management.ManagementFactory.getRuntimeMXBean().getInputArguments().stream().anyMatch('
    extra += 'v -> v.contains("opentelemetry-javaagent-2.32.0.jar"))?1:0)' if variant == "mutation" else ""
    if variant != "mutation":
        extra = ""
    (source / "src/app/App.java").write_text('package app;public class App {'
        'static int total=2,compiled=0,method=0,resource=0,directory=0,helper=0;'
        'public static int selected(int n)throws java.lang.Exception {total+=n' + extra + ';'
        'compiled=dep.Library.INLINE;method=dep.Library.value();resource=dep.Library.resource();'
        'directory=other.More.value();' + helper + 'return ' + returned + ';}}')
    if helper:
        path = source / "src/io/quux/otelc/methods/MethodMetrics.java"
        path.parent.mkdir(parents=True)
        path.write_text('package io.quux.otelc.methods;public class MethodMetrics {public static int value(){return 3;}}')
    (source / "pom.xml").write_text("<project><!-- Not executed or rewritten. --></project>\n")
    (source / "gradle.lockfile").write_text("existing-lock=1\n")
    dependencies = folder / "dependency classes"
    more = folder / "More.java"
    more.write_text('package other;public class More {public static int value(){return 11;}}')
    command([java.with_name("javac"), "-encoding", "UTF-8", "-proc:none", "-d", dependencies, more], folder, "directory")
    (dependencies / "empty-resource").mkdir()
    (dependencies / "resource.bin").write_bytes(b"unchanged\x00resource")
    jar = source / "lib/library.jar"
    jar.parent.mkdir()
    flag, versions, base, _, _, _ = oracle.VARIANTS[variant]
    with zipfile.ZipFile(jar, "x") as archive:
        manifest = b"Manifest-Version: 1.0\r\n" + (b"Multi-Release: " + flag + b"\r\n" if flag else b"") + b"\r\n"
        archive.writestr("META-INF/MANIFEST.MF", manifest)
        if base:
            archive.writestr("dep/Library.class", compiled[5])
            archive.writestr("factor.txt", "13")
        for number in versions:
            prefix = "META-INF/versions/" + str(number) + "/"
            archive.writestr(prefix + "dep/Library.class", compiled[5 if variant == "identical" else number])
            archive.writestr(prefix + "factor.txt", str(number + 8))
    policy = folder / "equivalence.toml"
    text = 'languages=["java"]\n[functions]\ninclude=["' + oracle.FUNCTION + '"]\n'
    text += '[adapters.java]\nbackend="prepared"\nprofile="' + PROFILE + '"\nsource_roots=["src"]\n'
    text += 'classpath=' + json.dumps([str(dependencies), "lib/library.jar"]) + '\n'
    text += '[[fixtures]]\nfunction="' + oracle.FUNCTION + '"\ncases=[[7]]\n'
    if variant == "mutation":
        text += 'domains=[{kind="integer",minimum=0,maximum=7}]\n'
    text += 'expected_baseline=' + json.dumps({"kind": "return_value", "value": project.scalar(oracle.result(variant, 7))}).replace(': ', '=') + '\n'
    policy.write_text(text)
    workspace = Path(command([cli, "plan", "--source", source, "--otelc-root", provider,
                              "--workspace-parent", folder, "--config", policy], folder, "plan"))
    plan = project.document(workspace / "plan.json")
    assert [row["otelc_function"] for row in plan["inventory"] if row["status"] == "ready"] == [oracle.FUNCTION]
    assert not any(row["status"] == "blocked" for row in plan["inventory"])
    command([cli, "generate", "--workspace", workspace], folder, "generate")
    return workspace


def suite(workspace: Path, folder: Path, variant: str, label: str) -> int:
    output = command([sys.executable, workspace / "tests/test_equivalence.py"], folder, label,
                     expected=int(variant == "mutation"))
    report, = [json.loads(line)["report"] for line in output.splitlines()]
    return oracle.check_report(Path(report), variant)[0]


def routes(cli: Path, workspace: Path, folder: Path, variant: str) -> int:
    """Run actual direct, fixed replay, generated and detached/exported routes."""
    expected = int(variant == "mutation")
    output = command([cli, "run", "--workspace", workspace, "--report-dir", folder / "comparison"],
                     folder, "direct", expected=expected)
    report_path = Path(json.loads(output)["report"])
    count, report = oracle.check_report(report_path, variant)
    case, = report["cases"]
    replay = json.loads(command([cli, "replay", "--workspace", workspace, "--case", case["case"]],
                                folder, "replay", expected=expected))
    count += oracle.check_report(Path(replay["report"]), variant)[0]
    count += suite(workspace, folder, variant, "framework")
    exported = folder / "exported"
    command([cli, "export-tests", "--workspace", workspace, "--destination", exported, "--apply"], folder, "export")
    source = Path(project.document(workspace / "plan.json")["source"])
    moved = folder / "detached-original"
    dependencies = folder / "dependency classes"
    moved_dependencies = folder / "detached-dependencies"
    source.rename(moved)
    dependencies.rename(moved_dependencies)
    try:
        count += suite(exported, folder, variant, "detached-framework")
    finally:
        moved.rename(source)
        moved_dependencies.rename(dependencies)
    return count


def refusal_controls(cli: Path, workspace: Path, folder: Path) -> int:
    """Changed originals, frozen copies and probe bytes must launch no application."""
    plan = project.document(workspace / "plan.json")
    case, = project.document(workspace / "tests/corpus.json")
    source = Path(plan["source"])
    paths = [source / "src/app/App.java", source / "lib/library.jar",
             folder / "dependency classes/resource.bin", workspace / "java-context/classpath/0001.jar",
             workspace / "java-context/archive-probe/probe/stdout"]
    before = len(commands(folder))
    for index, path in enumerate(paths):
        raw = path.read_bytes()
        try:
            path.write_bytes(raw + b"changed")
            command([cli, "replay", "--workspace", workspace, "--case", case["id"]], folder,
                    "refuse-" + str(index), expected=4)
            assert len(commands(folder)) == before
        finally:
            path.write_bytes(raw)
    return len(paths)


def reductions(cli: Path, workspace: Path, folder: Path) -> int:
    """Keep runtime archive evidence intact while reducing a same-return state defect."""
    case, = project.document(workspace / "tests/corpus.json")
    output = folder / "shrinking"
    command([cli, "shrink", "--workspace", workspace, "--case", case["id"], "--report-dir", output,
             "--trials", "8"], folder, "shrink", expected=1)
    result = project.document(output / "shrink.json")
    assert result["source_preserved"] and result["original_arguments"] == [7] and result["reduced_arguments"] == [0]
    assert result["status"] == "candidate_rule_minimal"
    reports = [output / "original/report.json", output / "confirmation/report.json",
               *(Path(trial["report"]) for trial in result["trials"])]
    count = sum(oracle.check_report(path, "mutation")[0] for path in reports)
    reduced = Path(result["workspace"])
    count += suite(reduced, folder, "mutation", "reduced-framework")
    replay = json.loads(command([cli, "replay", "--workspace", reduced, "--case", case["id"]],
                                folder, "reduced-replay", expected=1))
    return count + oracle.check_report(Path(replay["report"]), "mutation")[0]


def evidence_controls(folder: Path, variant: str) -> int:
    """Alter literal compiler or runtime member identity and repair outer build receipts."""
    source = next((folder / "comparison").rglob("prepared-application.json")).parent
    for fault in ("runtime-member", "runtime-feature", "compiler-member", "loaded-origin"):
        with tempfile.TemporaryDirectory(prefix="archive-evidence-control-", dir=folder) as temporary:
            copied = Path(temporary) / "attempt"
            shutil.copytree(source, copied)
            launch = project.document(copied / "prepared-launch.json")
            if fault in ("runtime-member", "runtime-feature"):
                resolution = launch["application"]["archive_resolution"]
                if fault == "runtime-member":
                    resolution["archives"][0]["classes"]["dep.Library"]["entry"] = "dep/Library.class"
                else:
                    resolution["jdk_feature"] += 1
                (copied / "prepared-launch.json").write_text(json.dumps(launch))
            elif fault == "compiler-member":
                metadata = project.document(copied / "java-compiler.json")
                uri, = [name for name in metadata["class_reads_sha256"] if name.startswith("jar:")]
                digest = metadata["class_reads_sha256"].pop(uri)
                metadata["class_reads_sha256"][uri.replace("META-INF/versions/21/", "")] = digest
                repair_metadata(copied, metadata)
            else:
                log = copied / "sdk-runtime/class-load.log"
                log.write_text(log.read_text().replace("dep.Library source: file:", "dep.Library source: file:/unowned"))
            try:
                oracle.check_build(copied, variant)
            except AssertionError:
                pass
            else:
                raise AssertionError("altered archive evidence passed: " + fault)
            (folder / ("control-" + fault + ".json")).write_text(json.dumps({"refused": True,
                "fault": fault, "original_attempt": str(source), "variant": variant}, indent=2) + "\n")
    return 4


def live_controls(cli: Path, provider: Path, folder: Path, active: Path) -> dict:
    """Exercise all four metric states in each unchanged JVM with real MR dependencies."""
    import qualify_java_controls as controls
    folder.mkdir()
    check = 'try{if(dep.Library.INLINE!=21||dep.Library.value()!=21||dep.Library.resource()!=29||other.More.value()!=11)'
    check += 'throw new IllegalStateException("wrong archive");}catch(Exception e){throw new IllegalStateException(e);}'
    source = controls.SOURCE.replace('private Counter(int start){', 'private Counter(int start){' + check)
    paths = [str(active / "dependency classes"), str(active / "application/lib/library.jar")]
    workspace = controls.prepare(cli, provider, folder / "cases", PROFILE, source_text=source, classpath=paths)
    command([cli, "run", "--workspace", workspace, "--report-dir", folder / "comparison"], folder, "direct", expected=1)
    count = controls.check_report(folder / "comparison/report.json", 6)
    controls.framework(workspace, folder, "framework")
    count += 24
    for path in folder.rglob("prepared-application.json"):
        oracle.check_build(path.parent, "active", control=True)
    return {"application_launches": count, "states_per_jvm": 4, "launches": verify_launches(folder, count),
            "prepared": verify_prepared(folder, controls.verify_receipt), "complete_literal_graphs_verified": True}


def retained(folder: Path, variant: str, count: int) -> dict:
    """Verify all retained builds, actual process identities and decoded telemetry."""
    launches = verify_launches(folder, count)
    manifests = list(folder.rglob("prepared-application.json"))
    for path in manifests:
        oracle.check_build(path.parent, variant)
    receipt = partial(verify_receipt, functions={oracle.FUNCTION})
    prepared = verify_prepared(folder, receipt)
    assert prepared["unique_processes"] == count
    return {"application_launches": count, "launches": launches, "prepared": prepared,
            "retained_builds": len(manifests), "complete_literal_graphs_verified": True}


def run(args: argparse.Namespace) -> None:
    destination = args.report_dir.resolve()
    destination.mkdir(parents=True, exist_ok=False)
    java = Path(os.environ.get("OTELC_JAVA") or shutil.which("java")).resolve()
    version = subprocess.run([java, "-version"], capture_output=True, check=True, timeout=30)
    assert 'version "21.' in version.stderr.decode(), "This fixed corpus requires JDK 21"
    shared = destination / "libraries"
    shared.mkdir()
    compiled = libraries(shared, java)
    results = {}
    for variant in args.variant or oracle.VARIANTS:
        folder = destination / variant
        workspace = prepare(args.cli.resolve(), args.otelc_root.resolve(), folder, variant, compiled, java)
        source = folder / "application"
        before_source = project.inventory(source)
        before_dependencies = project.inventory(folder / "dependency classes")
        count = routes(args.cli.resolve(), workspace, folder, variant)
        refusals = refusal_controls(args.cli.resolve(), workspace, folder) if variant == "active" else 0
        if variant == "mutation":
            count += reductions(args.cli.resolve(), workspace, folder)
        results[variant] = retained(folder, variant, count)
        results[variant]["prelaunch_refusals"] = refusals
        results[variant]["altered_evidence_controls"] = evidence_controls(folder, variant) if variant in ("active", "identical") else 0
        assert project.inventory(source) == before_source
        assert project.inventory(folder / "dependency classes") == before_dependencies
        results[variant]["original_source_and_dependencies_preserved"] = True
        (destination / "progress.json").write_text(json.dumps(results, indent=2) + "\n")
        print(json.dumps({"variant": variant, **results[variant]}), flush=True)
    controls = live_controls(args.cli.resolve(), args.otelc_root.resolve(), destination / "live-controls",
                             destination / "active") if "active" in results else None
    (destination / "qualification.json").write_text(json.dumps({"profile": PROFILE, "variants": results,
        "live_controls": controls,
        "actual_application_jvm_launches": sum(row["application_launches"] for row in results.values())
                                          + (controls["application_launches"] if controls else 0),
        "scope": "JDK21 fixed source-classpath diagnostic workers; no invocation witness or shipping-artefact claim"}, indent=2) + "\n")


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__, allow_abbrev=False)
    parser.add_argument("--otelc-root", type=Path, required=True)
    parser.add_argument("--cli", type=Path, required=True)
    parser.add_argument("--report-dir", type=Path, required=True)
    parser.add_argument("--variant", choices=oracle.VARIANTS, action="append")
    run(parser.parse_args())


if __name__ == "__main__":
    main()
