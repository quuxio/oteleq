"""Qualify the public offline action compiler without starting application code."""

import argparse
import hashlib
import json
import os
from pathlib import Path
import shutil
import sys

REPO = Path(__file__).resolve().parents[1]
sys.path[:0] = [str(REPO / "adapters/generation"), str(REPO / "examples")]
import generation
import java_action_bindings as bindings
import java_build
import java_provider

SOURCE = '''public final class OfflineFixture {
  static {
    try { java.nio.file.Files.writeString(java.nio.file.Path.of(
        java.lang.System.getenv("OTELEQ_BINDING_SENTINEL")), "application initialised"); }
    catch (java.lang.Exception error) { throw new java.lang.AssertionError("application initialised"); }
  }
  private static int target(int seed) { return seed + 1; }
  private static void rendezvous() {}
  private static int wrapper(int seed) throws java.lang.Exception { return target(seed); }
  private static int envelope(int seed) throws java.lang.Exception { rendezvous(); return wrapper(seed); }
  public static void main(java.lang.String[] arguments) { target(1); }
}
'''


def write(path: Path, value: object) -> None:
    path.write_text(json.dumps(value, indent=2) + "\n")


def run(sdk: Path, report: Path) -> dict:
    """Retain positive bindings and explicit descriptor/reflection refusal controls."""
    sdk = sdk.resolve(strict=True)
    report = generation.source_outside(report, sdk, REPO)
    report.mkdir(mode=0o700)
    executable = shutil.which(os.environ.get("OTELC_JAVA", "java"))
    java_provider.require(executable is not None, "selected full JDK is unavailable")
    tools = {"java": Path(executable).resolve(strict=True)}
    environment = {**os.environ, "PYTHONDONTWRITEBYTECODE": "1",
                   "OTELEQ_BINDING_SENTINEL": str(report / "application-started")}
    before = bindings.inputs(sdk, tools)
    consumer = generation.generator_identity()
    qualifier = hashlib.sha256(Path(__file__).read_bytes()).hexdigest()
    expected = {role: {"owner": "OfflineFixture", "name": role,
                      "descriptor": "()V" if role == "rendezvous" else "(I)I"} for role in bindings.ROLES}
    rows = []
    for name, reflection in (("direct", False), ("reflection", True)):
        folder = report / name;folder.mkdir()
        project, build = folder / "project", folder / "build"
        project.mkdir();build.mkdir()
        source = SOURCE
        if reflection:
            source = source.replace("return target(seed);", "return ((java.lang.Integer)OfflineFixture.class"
                ".getDeclaredMethod(\"target\", int.class).invoke(null, seed)).intValue();")
        application = project / "OfflineFixture.java";application.write_text(source)
        classes = build / "scratch/classes"
        java_build.build(project, [application], "OfflineFixture", tools["java"], classes, build,
                         environment, generation.execute)
        source_hash = hashlib.sha256(application.read_bytes()).hexdigest()
        for case, requested, accepted in (
            [("reflection-refused", expected, False)] if reflection else
            [("direct", expected, True), ("wrong-descriptor", {**expected,
                "target": {**expected["target"], "descriptor": "(J)I"}}, False)]):
            destination = folder / case
            try:
                value = bindings.compile(sdk, project, build, destination, tools, requested, environment, generation.execute)
            except ValueError as error:
                if accepted or not str(error).endswith("offline binding compilation failed; inspect compiler/stderr"):
                    raise
                row = {"case": case, "accepted": False, "refusal": str(error)}
            else:
                if not accepted:
                    raise AssertionError("unsupported offline request passed: " + case)
                row = {"case": case, "accepted": True, "bindings": value}
            java_build.verify(project, classes, build)
            assert hashlib.sha256(application.read_bytes()).hexdigest() == source_hash
            assert not (report / "application-started").exists()
            rows.append(row)
    assert bindings.inputs(sdk, tools) == before and generation.generator_identity() == consumer
    assert hashlib.sha256(Path(__file__).read_bytes()).hexdigest() == qualifier
    record = {"schema_version": 1, "kind": "oteleq.java-action-bindings-qualification",
              "profile": bindings.witness.PROFILE, "python": sys.version, "qualifier_sha256": qualifier,
              "consumer_inputs_sha256": consumer, "sdk_inputs_sha256": before,
              "cases": rows, "application_started": False, "sources_preserved": True,
              "scope": "offline binding metadata only; generated runtime and shipping admission remain unavailable"}
    write(report / "qualification.json", record)
    return record


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--otelc-root", required=True, type=Path)
    parser.add_argument("--report-dir", required=True, type=Path)
    args = parser.parse_args()
    result = run(args.otelc_root, args.report_dir)
    print(json.dumps({"report": str(args.report_dir), "cases": len(result["cases"]),
                      "application_started": result["application_started"]}))


if __name__ == "__main__":
    main()
