"""Capture the ordinary otelc Python task example for the Rust comparator.

This diagnostic workload observer is not semantic discovery or generated tests.
Run with otelc's locked Python environment (contains the OTLP protobuf decoder).
"""
import argparse
from collections import Counter
import hashlib
from http.server import BaseHTTPRequestHandler, HTTPServer
import json
import os
from pathlib import Path
import subprocess
import sys
import tempfile
import threading

from opentelemetry.proto.collector.trace.v1.trace_service_pb2 import ExportTraceServiceRequest


def digest(data):
    return hashlib.sha256(data).hexdigest()


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
    destination.mkdir(mode=0o700, parents=False, exist_ok=False)
    source = root / "examples/apps/python_tasks_app.py"
    policy = root / "examples/python-task-context.toml"
    cli = root / "target/debug/quux-otelc"
    originals = {path: path.read_bytes() for path in (source, policy)}
    source_hash = digest(originals[source])
    # Record concrete artefacts, including the adapter used by this CLI.
    identities = {str(path.relative_to(root)): digest(path.read_bytes())
                  for path in sorted((root / "adapters/python/quux_otelc_python").glob("*.py"))}
    identities["target/debug/quux-otelc"] = digest(cli.read_bytes())
    identities["adapters/python/requirements.txt"] = digest((root / "adapters/python/requirements.txt").read_bytes())
    identities["python_executable"] = digest(Path(sys.executable).read_bytes())
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
                        "observer": "oteleq Python task subprocess/OTLP observer v1",
                        "channels": ["stdout", "stderr"],
                        "gaps": ["no function discovery or generated corpus",
                                 "globals, receivers, filesystem and network effects not captured",
                                 "no instrumented-off lane; no production artefact qualification"]},
              "cases": [{"case_id": corpus["case_id"], "corpus_sha256": digest(json.dumps(corpus, sort_keys=True).encode()),
                         "expected_functions": expected, "expected_spans": 8,
                         "baseline": [], "instrumented_on": []}]}
    for lane in ("baseline", "instrumented_on"):
        for repeat in range(2):
            attempt_dir = destination / f"{lane}-{repeat}"
            attempt_dir.mkdir(mode=0o700)
            with tempfile.TemporaryDirectory(prefix="oteleq-task-") as temporary:
                workspace = Path(temporary).resolve()
                if workspace.is_relative_to(root):
                    raise ValueError("temporary workspace is inside target repository")
                app = workspace / "examples/apps/python_tasks_app.py"
                app.parent.mkdir(parents=True)
                app.write_bytes(originals[source])
                local_policy = workspace / "policy.toml"
                local_policy.write_bytes(originals[policy])
                env = {"PATH": os.environ.get("PATH", ""), "HOME": str(workspace),
                       "TMPDIR": str(workspace), "LANG": "C.UTF-8",
                       "PYTHONDONTWRITEBYTECODE": "1", "OTELC_PYTHON": sys.executable}
                bodies = []
                class Receiver(BaseHTTPRequestHandler):
                    def do_POST(self):
                        self.connection.settimeout(2)
                        size = int(self.headers.get("Content-Length", "0"))
                        if not 0 <= size <= 1024 * 1024 or len(bodies) >= 16:
                            self.send_error(413)
                            return
                        body = self.rfile.read(size)
                        bodies.append((self.path, body))
                        self.send_response(200)
                        self.send_header("Content-Length", "0")
                        self.end_headers()
                    def log_message(self, *_):
                        pass
                server = HTTPServer(("127.0.0.1", 0), Receiver)
                server.timeout = 2
                worker = threading.Thread(target=server.serve_forever, daemon=True)
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
                attempt = {"source_sha256_before": source_hash, "source_sha256_after": digest(app.read_bytes()),
                           "termination": {"kind": "exit", "code": result.returncode} if result.returncode >= 0
                                          else {"kind": "signal", "number": -result.returncode},
                           "channels": {"stdout": list(result.stdout), "stderr": list(result.stderr)},
                           "capture_complete": True, "witness": None}
                if any(path.read_bytes() != content for path, content in originals.items()):
                    raise ValueError("original target source or policy changed")
                if local_policy.read_bytes() != originals[policy]:
                    raise ValueError("private policy changed")
                for channel in ("stdout", "stderr"):
                    (attempt_dir / channel).write_bytes(getattr(result, channel))
                if lane == "instrumented_on":
                    raw = []
                    names = Counter()
                    for index, (path, body) in enumerate(bodies):
                        (attempt_dir / f"otlp-{index}.protobuf").write_bytes(body)
                        if path == "/v1/traces":
                            raw.append(body)
                            message = ExportTraceServiceRequest.FromString(body)
                            for resource in message.resource_spans:
                                for scope in resource.scope_spans:
                                    for span in scope.spans:
                                        names[span.name] += 1
                    status = json.loads(runtime_report.read_text())
                    (attempt_dir / "runtime.json").write_text(json.dumps(status, indent=2) + "\n")
                    losses = dict(status["traces"]["losses"])
                    losses["export"] = status["export_loss"]
                    losses.update({"runtime." + key: value for key, value in status["losses"].items()})
                    attempt["witness"] = {"decoder": "opentelemetry-proto ExportTraceServiceRequest",
                                          "raw_otlp_sha256": digest(b"".join(raw)), "functions": dict(names),
                                          "spans": sum(names.values()), "losses": losses,
                                          "pending": status["traces"]["pending_contexts"] + status["traces"]["active_trees"] + int(not status["export_finished"])}
                bundle["cases"][0][lane].append(attempt)
                (attempt_dir / "attempt.json").write_text(json.dumps(attempt, indent=2) + "\n")
    (destination / "source.py").write_bytes(originals[source])
    (destination / "policy.toml").write_bytes(originals[policy])
    (destination / "bundle.json").write_text(json.dumps(bundle, indent=2) + "\n")
    (destination / "corpus.json").write_text(json.dumps(corpus, indent=2) + "\n")
    (destination / "artefacts.json").write_text(json.dumps(identities, indent=2) + "\n")
    print(destination / "bundle.json")


if __name__ == "__main__":
    main()
