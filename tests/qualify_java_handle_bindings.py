"""Qualify generated private-handle bytecode and offline binding refusal controls."""

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
import java_handle_callers as callers
import java_launch
import java_provider
import java_witness as witness

INITIALIZER = '''static {
try{java.nio.file.Files.writeString(java.nio.file.Path.of(java.lang.System.getenv("OTELEQ_BINDING_SENTINEL")),"started");}
catch(java.lang.Exception failure){throw new java.lang.AssertionError("application initialised");}
}
'''


def run(sdk: Path, report: Path) -> dict:
    """Compile typed private callers without starting their application classes."""
    sdk = sdk.resolve(strict=True);report = generation.source_outside(report, sdk, REPO)
    report.mkdir(mode=0o700)
    selected = shutil.which(os.environ.get("OTELC_JAVA", "java"))
    witness.require(selected is not None, "selected full JDK is unavailable")
    tools = {"java": Path(selected).resolve(strict=True)}
    environment = {**os.environ, "PYTHONDONTWRITEBYTECODE": "1",
                   "OTELEQ_BINDING_SENTINEL": str(report / "application-started")}
    before, consumer = bindings.inputs(sdk, tools), generation.generator_identity()
    qualifier = hashlib.sha256(Path(__file__).read_bytes()).hexdigest()
    rows = []
    cases = [(name, [name], name, False) for name in callers.PRIMITIVES if name != "void"]
    cases += [("string", ["String"], "String", False), ("void", [], "void", False),
              ("instance-array", ["int[]", "long", "double"], "int[]", True),
              ("instance-wide", ["long", "double"], "long", True)]
    for name, parameters, output, instance in cases:
        folder = report / name;folder.mkdir()
        project, build = folder / "project", folder / "build";project.mkdir();build.mkdir()
        package = "example"
        members, declarations, route = callers.members("example.Work", "example/Work", "target", parameters, output,
            caller_owner="example/OteleqDriver", instance=instance)
        returned = "" if output == "void" else "return p0;"
        signature = ",".join(value + " p" + str(index) for index, value in enumerate(parameters))
        original = "package example;\nclass Work {" + INITIALIZER + "private " + ("" if instance else "static ") \
            + output + " target(" + signature + "){" + returned + "}}\n"
        sources = {"Work.java": original, "OteleqDriver.java": "package example;\nclass OteleqDriver {" + members
                   + "public static void main(String[] ignored){throw new AssertionError(\"application started\");}}\n",
                   "OteleqRendezvous.java": callers.helper_source(package)}
        for filename, text in sources.items():(project / filename).write_text(text)
        hashes = {filename: hashlib.sha256((project / filename).read_bytes()).hexdigest() for filename in sources}
        classes = build / java_launch.CLASSES
        java_build.build(project, [project / filename for filename in sources], "example.OteleqDriver", tools["java"],
                         classes, build, environment, generation.execute)
        result = bindings.compile(sdk, project, build, folder / "accepted", tools, declarations, environment,
                                  generation.execute, profile=witness.HANDLE_PROFILE, route=route)
        rows.append({"case": name, "accepted": True, "bindings": result})
        if name == "int":
            negatives = [("wrong-field", witness.HANDLE_PROFILE, bindings.HandleRoute("OTHER", 6), declarations),
                         ("v2-wrapper-refused", witness.PROFILE, None, declarations),
                         ("wrong-descriptor", witness.HANDLE_PROFILE, route,
                          {**declarations, "target": {**declarations["target"], "descriptor": "(J)I"}})]
            for label, profile, expected_route, requested in negatives:
                try:
                    bindings.compile(sdk, project, build, folder / label, tools, requested, environment,
                                     generation.execute, profile=profile, route=expected_route)
                except ValueError as error:
                    message = str(error)
                    expected = ("compiler changed the independently expected handle route" if label == "wrong-field"
                                else "offline binding compilation failed; inspect compiler/stderr")
                    witness.require(message.endswith(expected), "unexpected refusal: " + message)
                    rows.append({"case": label, "accepted": False, "refusal": message})
                else:
                    raise AssertionError("unsupported handle bindings passed: " + label)
        java_build.verify(project, classes, build)
        witness.require(not (report / "application-started").exists(), "offline compiler started application code")
        witness.require(all(hashlib.sha256((project / filename).read_bytes()).hexdigest() == digest
                            for filename, digest in hashes.items()), "application sources changed")
    witness.require(bindings.inputs(sdk, tools) == before and generation.generator_identity() == consumer
                    and hashlib.sha256(Path(__file__).read_bytes()).hexdigest() == qualifier,
                    "offline compiler or consumer inputs changed")
    record = {"schema_version": 1, "kind": "oteleq.java-handle-bindings-qualification", "profile": witness.HANDLE_PROFILE,
              "python": sys.version, "qualifier_sha256": qualifier, "consumer_inputs_sha256": consumer,
              "sdk_inputs_sha256": before, "cases": rows, "application_started": False, "sources_preserved": True,
              "scope": "generated caller bytecode and offline metadata only; generated runtime/shipping admission remain open"}
    (report / "qualification.json").write_text(json.dumps(record, indent=2) + "\n")
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
