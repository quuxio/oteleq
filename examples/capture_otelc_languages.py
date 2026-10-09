"""Apply oteleq's diagnostic workload comparison to every current otelc language."""
import argparse
import json
from pathlib import Path
import tempfile
import uuid
import subprocess

import otelc_capture as capture


BUNDLE_FILENAME = "bundle.json"


def attempt(root, spec, language, destination, lane, repeat, originals, tools, identities, decoder):
    capture.stable(root, language, tools, identities)
    folder = destination / f"{lane}-{repeat}"
    folder.mkdir(mode=0o700)
    temporary_directory = capture.temporary_parent(root, Path(__file__).resolve().parents[1])
    with tempfile.TemporaryDirectory(prefix="oteleq-" + language + "-", dir=temporary_directory) as temporary:
        workspace = Path(temporary).resolve() / "project"
        workspace.mkdir()
        source = workspace / spec["source"]
        source.parent.mkdir(parents=True)
        source.write_bytes(originals["source"])
        service = "oteleq-" + language + "-" + uuid.uuid4().hex
        env = capture.environment(workspace, tools, service, root)
        backend = capture.typescript_backend(root, language, spec, originals["policy"])
        if backend is not None:
            env["OTELC_TYPESCRIPT_BACKEND"] = backend
        report_path = workspace / "runtime.json"
        with capture.receiver() as (endpoint, bodies, errors):
            policy = workspace / "policy.toml"
            configured = capture.configure(originals["policy"], endpoint)
            policy.write_bytes(configured)
            baseline, instrumented = capture.commands(root, workspace, language, source, policy, tools, env, folder)
            if lane == "instrumented_on":
                env["OTELC_REPORT_PATH"] = str(report_path)
            command = baseline if lane == "baseline" else instrumented
            result = capture.execute(command, workspace, env)
        capture.retain_http(folder, bodies, errors)
        for channel in ("stdout", "stderr"):
            (folder / channel).write_bytes(getattr(result, channel))
        capture.stable(root, language, tools, identities)
        if source.read_bytes() != originals["source"] or policy.read_bytes() != configured:
            raise ValueError("private source or policy changed during execution")
        if (root / spec["source"]).read_bytes() != originals["source"] or (root / spec["policy"]).read_bytes() != originals["policy"]:
            raise ValueError("original source or policy changed during execution")
        if errors:
            raise ValueError("OTLP capture failed: " + "; ".join(errors))
        observed = {"source_sha256_before": capture.digest(originals["source"]),
                    "source_sha256_after": capture.file_digest(source),
                    "termination": {"kind": "exit", "code": result.returncode} if result.returncode >= 0
                                   else {"kind": "signal", "number": -result.returncode},
                    "channels": {"stdout": list(result.stdout), "stderr": list(result.stderr)},
                    "capture_complete": True, "witness": None}
        if lane == "instrumented_on":
            if not report_path.is_file():
                raise ValueError(f"runtime report missing; inspect {folder / 'stderr'}")
            report = capture.strict_json(report_path.read_text())
            (folder / "runtime.json").write_text(json.dumps(report, indent=2) + "\n")
            observed["witness"] = capture.witness(bodies, report, spec, service, decoder, language)
        elif bodies:
            raise ValueError("uninstrumented baseline unexpectedly exported telemetry")
        (folder / "attempt.json").write_text(json.dumps(observed, indent=2) + "\n")
        (folder / "commands.json").write_text(json.dumps({"executed": [str(p) for p in command], "service": service,
                                                          "working_directory": str(workspace), "typescript_backend": backend}, indent=2) + "\n")
        return observed


def run(root, destination, language, spec, decoder):
    destination.mkdir(mode=0o700)
    originals = {key: (root / spec[key]).read_bytes() for key in ("source", "policy")}
    capture.typescript_backend(root, language, spec, originals["policy"])
    tools = capture.selected_tools(root, language)
    identities = capture.artefacts(root, language, tools)
    source_hash = capture.digest(originals["source"])
    corpus = {"language": language, "fixture": spec, "arguments": [], "stdin": "closed",
              "state": "fresh process/private source copy per attempt"}
    case = {"case_id": spec.get("case_id", language + "-trace-example"), "corpus_sha256": capture.digest(json.dumps(corpus, sort_keys=True).encode()),
            "expected_functions": spec["functions"], "expected_spans": sum(spec["functions"].values()),
            "baseline": [], "instrumented_on": []}
    scope = {"language": language, "artefact_class": "diagnostic", "source_sha256": source_hash,
             "baseline_artefact_sha256": capture.digest(json.dumps({"source": source_hash, "tools": {k: str(v) for k, v in tools.items()}, "identities": identities}, sort_keys=True).encode()),
             "instrumented_artefact_sha256": capture.digest(json.dumps(identities, sort_keys=True).encode()),
             "policy_sha256": capture.digest(originals["policy"]), "observer": "oteleq eight-language diagnostic observer v2; hashes in artefacts.json",
             "channels": ["stdout", "stderr"],
             "gaps": ["fixed trusted workload; no function discovery or generated inputs",
                      "no typed receiver/global/argument, filesystem or network state comparison",
                      "diagnostic build recipe identity, not shipping artefact qualification",
                      "system libraries and compiler sysroot are outside the content identity manifest",
                      "no instrumented-off lane or hostile-target sandbox qualification"]}
    for lane in ("baseline", "instrumented_on"):
        for repeat in range(2):
            case[lane].append(attempt(root, spec, language, destination, lane, repeat, originals, tools, identities, decoder))
    for key, content in originals.items():
        (destination / ("source" + Path(spec["source"]).suffix if key == "source" else "policy.toml")).write_bytes(content)
    for filename, document in (("artefacts.json", identities), ("corpus.json", corpus),
                               (BUNDLE_FILENAME, {"workload_schema_version": 1, "scope": scope, "cases": [case]})):
        (destination / filename).write_text(json.dumps(document, indent=2) + "\n")


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--otelc-root", required=True, type=Path)
    parser.add_argument("--report-dir", required=True, type=Path)
    parser.add_argument("--comparator", type=Path, default=Path(__file__).resolve().parents[1] / "target/debug/quux-oteleq")
    parser.add_argument("--workload", choices=("functions", "python-workers", "java-workers", "typescript-native"), default="functions")
    parser.add_argument("--language", action="append", choices=("c", "cpp", "rust", "python", "java", "javascript", "typescript", "go"))
    args = parser.parse_args()
    filenames = {"functions": "otelc-workloads.json", "typescript-native": "otelc-typescript-native-workloads.json"}
    filename = filenames.get(args.workload, "otelc-worker-workloads.json")
    manifest = capture.strict_json(Path(__file__).with_name(filename).read_text())
    if args.workload != "functions":
        selected = args.workload.split("-")[0]
        manifest = {selected: manifest[selected]}
    if any(language not in manifest for language in args.language or []):
        parser.error("requested language is unavailable for the selected workload")
    root = args.otelc_root.resolve(strict=True)
    destination = args.report_dir.resolve()
    if any(destination.is_relative_to(p) for p in (root, Path(__file__).resolve().parents[1])):
        parser.error("report directory must be outside both repositories")
    try:
        capture.temporary_parent(root, Path(__file__).resolve().parents[1])
    except ValueError as error:
        parser.error(str(error))
    comparator = args.comparator.resolve(strict=True)
    # The locked otelc Python environment supplies the protobuf decoder.
    from opentelemetry.proto.collector.trace.v1.trace_service_pb2 import ExportTraceServiceRequest
    destination.mkdir(mode=0o700, parents=False, exist_ok=False)
    for language in dict.fromkeys(args.language or manifest):
        run(root, destination / language, language, manifest[language], ExportTraceServiceRequest)
        result = subprocess.run([str(comparator), "compare-workload", str(destination / language / BUNDLE_FILENAME)],
                                capture_output=True, timeout=30, check=False)
        (destination / language / "comparison.json").write_bytes(result.stdout)
        if result.returncode:
            raise ValueError(f"{language} comparison failed; inspect comparison.json")
        print(destination / language / BUNDLE_FILENAME, flush=True)


if __name__ == "__main__":
    main()
