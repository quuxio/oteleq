"""Capture the ordinary otelc Python task example for the Rust comparator.

This diagnostic workload observer is not semantic discovery or generated tests.
Run with otelc's locked Python environment (contains the OTLP protobuf decoder).
"""
import argparse
from collections import Counter
import hashlib
import json
import os
from pathlib import Path
import subprocess
import sys
import tempfile
import threading

from otelc_capture import (CaptureServer, loss_diagnostics, require_counters,
                           require_runtime_identity, retain_http, span_identity,
                           strict_json, temporary_parent)


TASK_SOURCE = Path("examples/apps/python_tasks_app.py")


def digest(data):
    return hashlib.sha256(data).hexdigest()


def file_digest(path):
    with path.open("rb") as stream:
        return hashlib.file_digest(stream, "sha256").hexdigest()


def artefact_identities(root, interpreter):
    identities = {str(path.relative_to(root)): file_digest(path)
                  for path in sorted((root / "adapters/python/quux_otelc_python").rglob("*.py"))}
    for relative in ("target/debug/quux-otelc", "adapters/python/requirements.txt"):
        identities[relative] = file_digest(root / relative)
    identities["python_executable"] = file_digest(interpreter)
    identities["capture_observer"] = file_digest(Path(__file__))
    identities["capture_support"] = file_digest(Path(__file__).with_name("otelc_capture.py"))
    return identities


def require_same_artefacts(root, interpreter, expected):
    if artefact_identities(root, interpreter) != expected:
        raise ValueError("launcher, interpreter, adapter or observer artefacts changed during capture")


def runtime_witness(status):
    require_runtime_identity(status, "python")
    if type(status["export_finished"]) is not bool:
        raise ValueError("unsupported or incomplete runtime report")
    traces = status["traces"]
    losses, export = loss_diagnostics(status, "python")
    losses["export"] = sum(export)
    counters = [traces[key] for key in ("pending_contexts", "active_trees", "queued_trees")]
    require_counters(counters)
    return losses, sum(counters) + int(not status["export_finished"])


def decode_traces(bodies, decode_request):
    raw_digest = hashlib.sha256()
    names = Counter()
    identities = set()
    for path, body in bodies:
        if path != "/v1/traces":
            continue
        raw_digest.update(body)
        message = decode_request(body)
        spans = (span for resource in message.resource_spans for scope in resource.scope_spans for span in scope.spans)
        for span in spans:
            identity = span_identity(span)
            if identity in identities:
                raise ValueError("invalid or duplicate OTLP span")
            identities.add(identity)
            names[span.name] += 1
    return raw_digest.hexdigest(), dict(names)


def capture_attempt(root, lane, attempt_dir, originals, identities, temporary_directory):
    source = root / TASK_SOURCE
    policy = root / "examples/python-task-context.toml"
    cli = root / "target/debug/quux-otelc"
    checker_root = Path(__file__).resolve().parents[1]
    interpreter = Path(sys.executable)
    source_hash = digest(originals[source])
    require_same_artefacts(root, interpreter, identities)
    attempt_dir.mkdir(mode=0o700)
    with tempfile.TemporaryDirectory(prefix="oteleq-task-", dir=temporary_directory) as temporary:
        workspace = Path(temporary).resolve()
        if any(workspace.is_relative_to(path) for path in (root, checker_root)):
            raise ValueError("temporary workspace is inside a source repository")
        app = workspace / TASK_SOURCE
        app.parent.mkdir(parents=True)
        app.write_bytes(originals[source])
        local_policy = workspace / "policy.toml"
        local_policy.write_bytes(originals[policy])
        env = {"PATH": os.environ.get("PATH", ""), "HOME": str(workspace),
               "TMPDIR": str(workspace), "LANG": "C.UTF-8",
               "PYTHONDONTWRITEBYTECODE": "1", "OTELC_PYTHON": sys.executable}
        server = CaptureServer(max_requests=16)
        worker = threading.Thread(target=server.serve_forever, kwargs={"poll_interval": 0.05}, daemon=True)
        worker.start()
        command = [sys.executable, str(app)]
        runtime_report = workspace / "runtime.json"
        if lane == "instrumented_on":
            command = [str(cli), "--config", str(local_policy), "python", str(app)]
            env.update(OTEL_EXPORTER_OTLP_ENDPOINT=f"http://127.0.0.1:{server.server_port}",
                       OTELC_REPORT_PATH=str(runtime_report))
        try:
            result = subprocess.run(command, cwd=workspace, env=env, stdin=subprocess.DEVNULL,
                                    capture_output=True, timeout=30, check=False)
        finally:
            server.shutdown()
            server.server_close()
            worker.join(timeout=3)
        retain_http(attempt_dir, server.bodies, server.errors, server.requests)
        for channel in ("stdout", "stderr"):
            (attempt_dir / channel).write_bytes(getattr(result, channel))
        server.require_complete()
        require_same_artefacts(root, interpreter, identities)
        attempt = {"source_sha256_before": source_hash, "source_sha256_after": digest(app.read_bytes()),
                   "termination": {"kind": "exit", "code": result.returncode} if result.returncode >= 0
                                  else {"kind": "signal", "number": -result.returncode},
                   "channels": {"stdout": list(result.stdout), "stderr": list(result.stderr)},
                   "capture_complete": True, "witness": None}
        if any(path.read_bytes() != content for path, content in originals.items()):
            raise ValueError("original target source or policy changed")
        if local_policy.read_bytes() != originals[policy]:
            raise ValueError("private policy changed")
        if lane == "instrumented_on":
            from opentelemetry.proto.collector.trace.v1.trace_service_pb2 import ExportTraceServiceRequest
            raw_hash, names = decode_traces(server.bodies, ExportTraceServiceRequest.FromString)
            status = strict_json(runtime_report.read_text())
            (attempt_dir / "runtime.json").write_text(json.dumps(status, indent=2) + "\n")
            losses, pending = runtime_witness(status)
            attempt["witness"] = {"decoder": "opentelemetry-proto ExportTraceServiceRequest",
                                  "raw_otlp_sha256": raw_hash, "functions": names,
                                  "spans": sum(names.values()), "losses": losses,
                                  "pending": pending}
        elif server.bodies:
            raise ValueError("uninstrumented baseline unexpectedly exported telemetry")
        (attempt_dir / "attempt.json").write_text(json.dumps(attempt, indent=2) + "\n")
        return attempt


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--otelc-root", required=True, type=Path)
    parser.add_argument("--report-dir", required=True, type=Path)
    args = parser.parse_args()
    root = args.otelc_root.resolve(strict=True)
    destination = args.report_dir.resolve()
    checker_root = Path(__file__).resolve().parents[1]
    if any(destination.is_relative_to(path) for path in (root, checker_root)):
        parser.error("report directory must be outside both repositories")
    try:
        temporary_directory = temporary_parent(root, checker_root)
    except ValueError as error:
        parser.error(str(error))
    destination.mkdir(mode=0o700, parents=False, exist_ok=False)
    source = root / TASK_SOURCE
    policy = root / "examples/python-task-context.toml"
    originals = {path: path.read_bytes() for path in (source, policy)}
    source_hash = digest(originals[source])
    # Record concrete artefacts, including the adapter used by this CLI.
    interpreter = Path(sys.executable)
    identities = artefact_identities(root, interpreter)
    baseline_hash = digest((source_hash + identities["python_executable"]).encode())
    instrumented_hash = digest(json.dumps(identities, sort_keys=True).encode())
    corpus = {"case_id": "python-tasks-example", "arguments": [], "stdin": "closed", "fixture": "fresh process and private source copy"}
    expected = {"examples.apps.python_tasks_app.group": 2,
                "examples.apps.python_tasks_app.detached": 1,
                "examples.apps.python_tasks_app.leaf": 5}
    bundle = {"workload_schema_version": 1,
              "scope": {"language": "python", "artefact_class": "diagnostic",
                        "source_sha256": source_hash, "baseline_artefact_sha256": baseline_hash,
                        "instrumented_artefact_sha256": instrumented_hash,
                        "policy_sha256": digest(originals[policy]),
                        "observer": "oteleq Python task subprocess/OTLP observer v2 sha256:" + identities["capture_observer"],
                        "channels": ["stdout", "stderr"],
                        "gaps": ["no function discovery or generated corpus",
                                 "globals, receivers, filesystem and network effects not captured",
                                 "installed dependency and standard-library contents not fingerprinted",
                                 "span parent graphs and resource attributes not qualified",
                                 "no instrumented-off lane; no production artefact qualification"]},
              "cases": [{"case_id": corpus["case_id"], "corpus_sha256": digest(json.dumps(corpus, sort_keys=True).encode()),
                         "expected_functions": expected, "expected_spans": 8,
                         "baseline": [], "instrumented_on": []}]}
    for lane in ("baseline", "instrumented_on"):
        for repeat in range(2):
            attempt_dir = destination / f"{lane}-{repeat}"
            bundle["cases"][0][lane].append(capture_attempt(root, lane, attempt_dir, originals, identities, temporary_directory))
    (destination / "source.py").write_bytes(originals[source])
    (destination / "policy.toml").write_bytes(originals[policy])
    (destination / "bundle.json").write_text(json.dumps(bundle, indent=2) + "\n")
    (destination / "corpus.json").write_text(json.dumps(corpus, indent=2) + "\n")
    (destination / "artefacts.json").write_text(json.dumps(identities, indent=2) + "\n")
    print(destination / "bundle.json")


if __name__ == "__main__":
    main()
