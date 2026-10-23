"""Exercise actual metadata-only Python preparation without admitting execution."""

import argparse
from dataclasses import replace
import json
from pathlib import Path
import sys

REPO = Path(__file__).resolve().parents[1]
sys.path[:0] = [str(REPO / "adapters/generation"), str(REPO / "examples")]
import generation
import python_inputs
import python_prepared
import python_provider


def cli_refusal(cli: Path, root: Path, project: Path, report: Path, environment: dict) -> dict:
    """Actual generated and detached strict suites must fail the blocked target."""
    config = report / "project-policy.toml"
    config.write_text('languages = ["python"]\n[adapters.python]\nbackend = "prepared"\n')
    parent = report / "workspaces"
    parent.mkdir()
    environment = {**environment, "OTELEQ_PYTHON": sys.executable}
    command = [cli, "plan", "--source", project, "--otelc-root", root,
               "--config", config, "--workspace-parent", parent]
    planned = generation.execute(command, report, environment, report / "cli-plan", max_output_bytes=65536)
    python_provider.require(planned.returncode == 0, "actual CLI plan failed")
    workspace = Path(planned.stdout.decode().strip())
    python_provider.require(workspace.parent == parent and workspace.is_dir(), "unexpected actual CLI workspace")
    plan = generation.read(workspace / "plan.json")
    selected = [item for item in plan["inventory"] if item["status"] != "excluded"]
    python_provider.require(len(selected) == 1 and selected[0]["otelc_function"] == "entry.add"
                            and selected[0]["status"] == "blocked", "actual CLI lost or admitted the blocked callable")
    generated = generation.execute([cli, "generate", "--workspace", workspace], report, environment,
                                   report / "cli-generate", max_output_bytes=65536)
    python_provider.require(generated.returncode == 0, "blocked suite generation failed")
    destination = report / "cli-result"
    result = generation.execute([cli, "run", "--workspace", workspace, "--report-dir", destination],
                                report, environment, report / "cli-run", max_output_bytes=65536)
    final = generation.read(destination / "report.json")
    python_provider.require(result.returncode == 3 and final["exit_code"] == 3 and final["cases"] == []
                            and len(final["blocked"]) == 1, "blocked CLI run became successful empty evidence")
    suite = generation.execute([sys.executable, "-I", "-B", workspace / "tests/test_equivalence.py"],
                               report, environment, report / "generated-suite", max_output_bytes=65536)
    python_provider.require(suite.returncode == 1, "blocked generated unittest suite did not fail")
    detached = report / "detached"
    exported = generation.execute([cli, "export-tests", "--workspace", workspace, "--destination", detached, "--apply"],
                                   report, environment, report / "cli-export", max_output_bytes=65536)
    python_provider.require(exported.returncode == 0, "blocked suite export failed")
    python_provider.require(generation.manifest(detached / python_provider.DIRECTORY) == plan["python_provider_manifest"],
                            "detached suite lost provider probe evidence")
    detached_suite = generation.execute([sys.executable, "-I", "-B", detached / "tests/test_equivalence.py"],
                                        report, environment, report / "detached-suite", max_output_bytes=65536)
    python_provider.require(detached_suite.returncode == 1, "blocked detached unittest suite did not fail")
    return {"selected_callables": 1, "status": "blocked", "run_exit": result.returncode,
            "generated_suite_exit": suite.returncode, "detached_suite_exit": detached_suite.returncode,
            "provider_probes_exported": True}


def run(root: Path, report: Path, cli: Path) -> dict:
    """Retain genuine public responses, independent checks and refusal controls."""
    report.mkdir(mode=0o700)
    report = report.resolve(strict=True)
    project = report / "application"
    project.mkdir()
    marker = report / "application-was-executed"
    (project / "entry.py").write_text("from pathlib import Path\nPath(" + repr(str(marker))
                                    + ").write_text('unexpected execution')\ndef add(value: int) -> int:\n    return value + 1\n")
    source_hash = generation.manifest(project)
    tools = {"python": Path(sys.executable).absolute()}
    entry = {"language": "python", "python_backend": "prepared", "path": "entry.py",
             "otelc_function": "entry.add", "id": "metadata", "status": "ready"}
    config = report / "policy.toml"
    config.write_text(python_provider.policy(entry, "http://127.0.0.1:4318", "oteleq-python-metadata"))
    requested = python_provider.configuration(entry, "http://127.0.0.1:4318", "oteleq-python-metadata")
    environment = generation.capture.environment(report, tools, "oteleq-python-metadata", root)
    protocols = python_provider.probe_protocols(root, report, tools, generation.execute)
    metadata_command = [tools["python"], "-I", "-S", "-B", "-c",
                        "import json,sys;print(json.dumps({'version':sys.version,'cache_tag':sys.implementation.cache_tag,'argv0':sys.orig_argv[0]}))"]
    metadata = generation.execute(metadata_command, root, environment, report / "interpreter-probe", max_output_bytes=4096)
    python_provider.require(metadata.returncode == 0, "independent interpreter probe failed")
    interpreter = generation.capture.strict_json(metadata.stdout)
    attempts = []
    for plain in (True, False):
        folder = report / ("baseline" if plain else "instrumented")
        folder.mkdir()
        runtime = folder / "runtime"
        command = [tools["python"], "-I", "-S", "-B", root / "otelc/cli_bootstrap.py", "--config", config,
                   "python", "--root", project, "--entry", "entry.py", "--runtime", runtime, "--prepare-only"]
        if plain:
            command.append("--plain")
        arguments = ("--", "-c", "", "\U0001f680")
        command.extend(("--", *arguments))
        result = generation.execute(command, root, environment, folder / "prepare", timeout=180,
                                    max_output_bytes=python_prepared.MAX_METADATA)
        generation.write(folder / "command.json", list(map(str, command)))
        python_provider.require(result.returncode == 0, "actual prepare-only command failed; see " + str(folder))
        value = generation.capture.strict_json(result.stdout)
        # Preparation builds only this owned provider copy. Freeze the resulting
        # prebuilt products and installed bytes before reading its response.
        catalogue = python_inputs.artefacts(root, tools)
        intent = python_prepared.Intent(root, project, runtime, Path("entry.py"), root, tools["python"],
                                        interpreter, requested, config, environment, plain, arguments)
        python_prepared.verify(value, intent, catalogue)
        refused = []
        controls = {"command": {**value, "command": ["untrusted executable"]},
                    "source_complete": {**value, "source_complete": True},
                    "plan": {**value, "plan": {**value["plan"], "native_arguments": ["-c", "print(1)"]}}}
        for name, altered in controls.items():
            try:
                python_prepared.verify(altered, intent, catalogue)
            except ValueError:
                refused.append(name)
            else:
                raise ValueError("altered actual prepared response passed: " + name)
        try:
            python_prepared.verify(value, replace(intent, plain=not plain), catalogue)
        except ValueError:
            refused.append("lane")
        else:
            raise ValueError("opposite lane passed actual prepared response")
        python_provider.require({path.name for path in runtime.iterdir()} == {
            "python-request.json", "python-resolved-plan.json", "python-prepared.json"},
            "prepare-only produced unexpected execution/runtime files")
        attempts.append({"lane": "baseline" if plain else "instrumented", "prepared_checked": True,
                         "source_complete": value["source_complete"], "refused": refused,
                         "catalogue_files": len(catalogue), "catalogue_sha256": generation.identity(catalogue)})
    python_provider.bind(entry, root, report, tools, generation.execute)
    python_provider.require(entry["status"] == "blocked", "negotiation admitted a missing-origin profile")
    negotiated = entry["python_provider"]
    public = generation.capture.strict_json(negotiated["stdout"])
    if "python" in set(public["implemented"]) | set(public["candidates"]):
        python_provider.require(python_provider.ORIGIN_UNAVAILABLE in entry["reason"],
                                "declared candidate did not reach the origin blocker")
    else:
        python_provider.require("Python has no public implementation or candidate declaration" in entry["reason"]
                                and "resolved" not in negotiated, "undeclared Python candidate was admitted")
    cli_evidence = cli_refusal(cli, root, project, report, environment)
    python_provider.require(not marker.exists() and generation.manifest(project) == source_hash,
                            "metadata preparation executed or changed the application")
    result = {"schema_version": 1, "kind": "oteleq.python-prepared-metadata-qualification",
              "protocols": protocols, "interpreter": interpreter, "attempts": attempts,
              "application_body_executed": False, "application_source_unchanged": True,
              "source_profile_status": "blocked", "source_profile_reason": entry["reason"],
              "public_python_candidate": "python" in public["candidates"],
              "cli_refusal": cli_evidence,
              "scope": "Metadata and fixed transport only; no generated execution, source-origin or shipping qualification."}
    generation.write(report / "report.json", result)
    return result


def main() -> None:
    """Require a new external report and an independently owned provider copy."""
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--otelc-root", type=Path, required=True)
    parser.add_argument("--report-dir", type=Path, required=True)
    parser.add_argument("--cli", type=Path, required=True)
    args = parser.parse_args()
    root = args.otelc_root.resolve(strict=True)
    generation.source_outside(args.report_dir, root)
    result = run(root, args.report_dir, args.cli.resolve(strict=True))
    print(json.dumps({"report": str(args.report_dir / "report.json"), "lanes": len(result["attempts"]),
                      "source_profile_status": result["source_profile_status"]}))


if __name__ == "__main__":
    main()
