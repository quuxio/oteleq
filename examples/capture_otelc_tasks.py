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
import time

MAX_REQUEST_BYTES = 1024 * 1024
MAX_REQUESTS = 16
REQUEST_TIMEOUT = 2


class Receiver(BaseHTTPRequestHandler):
    def send_error(self, code, message=None, explain=None):
        self.server.errors.append(f"HTTP capture rejected request: {code}")
        super().send_error(code, message, explain)

    def do_POST(self):
        self.server.requests += 1
        lengths = self.headers.get_all("Content-Length", [])
        if (len(lengths) != 1 or not lengths[0].isascii() or not lengths[0].isdecimal()
                or self.headers.get("Transfer-Encoding") is not None
                or self.headers.get("Content-Encoding", "identity") != "identity"
                or self.path not in ("/v1/traces", "/v1/metrics")):
            self.send_error(400)
            return
        size = int(lengths[0])
        if size > MAX_REQUEST_BYTES or self.server.requests > MAX_REQUESTS:
            self.send_error(413)
            return
        deadline = time.monotonic() + REQUEST_TIMEOUT
        body = bytearray()
        try:
            while len(body) < size:
                remaining = deadline - time.monotonic()
                if remaining <= 0:
                    raise TimeoutError
                self.connection.settimeout(remaining)
                chunk = self.rfile.read1(min(65536, size - len(body)))
                if not chunk:
                    self.send_error(400)
                    return
                body.extend(chunk)
        except (TimeoutError, OSError):
            self.send_error(408)
            return
        self.server.bodies.append((self.path, bytes(body)))
        self.send_response(200)
        self.send_header("Content-Length", "0")
        self.end_headers()

    def log_message(self, *_):
        # Request failures are retained in the capture status, not application stderr.
        pass

    def log_error(self, *_):
        self.server.errors.append("HTTP capture protocol or connection error")


class CaptureServer(HTTPServer):
    def __init__(self):
        self.bodies = []
        self.errors = []
        self.requests = 0
        super().__init__(("127.0.0.1", 0), Receiver)

    def get_request(self):
        connection, address = super().get_request()
        connection.settimeout(REQUEST_TIMEOUT)
        return connection, address

    def handle_error(self, *_):
        self.errors.append("HTTP capture connection failed")

    def require_complete(self):
        if self.errors:
            raise ValueError("incomplete HTTP capture: " + "; ".join(self.errors))

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
    return identities


def require_same_artefacts(root, interpreter, expected):
    if artefact_identities(root, interpreter) != expected:
        raise ValueError("launcher, interpreter, adapter or observer artefacts changed during capture")


def strict_json(data):
    def unique_object(pairs):
        result = {}
        for key, value in pairs:
            if key in result:
                raise ValueError("duplicate runtime report key")
            result[key] = value
        return result
    return json.loads(data, object_pairs_hook=unique_object)


def runtime_witness(status):
    if (status["schema_version"] != 1 or type(status["schema_version"]) is not int
            or status["language"] != "python" or type(status["export_finished"]) is not bool):
        raise ValueError("unsupported or incomplete runtime report")
    traces = status["traces"]
    runtime_losses = status["losses"]
    trace_losses = traces["losses"]
    required = {"function_capacity", "active_call_capacity", "incomplete", "invalid"}
    if not isinstance(runtime_losses, dict) or not required.issubset(runtime_losses):
        raise ValueError("missing runtime loss diagnostics")
    if (not isinstance(trace_losses, dict)
            or any(not key.strip() for key in (*trace_losses, *runtime_losses))):
        raise ValueError("invalid runtime loss diagnostics")
    losses = {"traces." + key: value for key, value in trace_losses.items()}
    losses["export"] = status["export_loss"]
    losses.update({"runtime." + key: value for key, value in runtime_losses.items()})
    counters = [traces[key] for key in ("pending_contexts", "active_trees", "queued_trees")]
    if (any(type(value) is not int or value < 0 for value in (*losses.values(), *counters))
            or any(not isinstance(key, str) or not key.strip() for key in losses)):
        raise ValueError("invalid runtime loss or pending counter")
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
        for resource in message.resource_spans:
            for scope in resource.scope_spans:
                for span in scope.spans:
                    identity = (span.trace_id, span.span_id)
                    if (len(span.trace_id) != 16 or not any(span.trace_id)
                            or len(span.span_id) != 8 or not any(span.span_id)
                            or span.parent_span_id and (len(span.parent_span_id) != 8 or not any(span.parent_span_id))
                            or not span.name.strip() or span.start_time_unix_nano <= 0
                            or span.end_time_unix_nano < span.start_time_unix_nano
                            or identity in identities):
                        raise ValueError("invalid or duplicate OTLP span")
                    identities.add(identity)
                    names[span.name] += 1
    return raw_digest.hexdigest(), dict(names)


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
            require_same_artefacts(root, interpreter, identities)
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
                server = CaptureServer()
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
                for index, (_, body) in enumerate(server.bodies):
                    (attempt_dir / f"otlp-{index}.protobuf").write_bytes(body)
                (attempt_dir / "http-capture.json").write_text(json.dumps({
                    "requests": server.requests, "errors": server.errors,
                    "bodies": [{"path": path, "file": f"otlp-{index}.protobuf"}
                               for index, (path, _) in enumerate(server.bodies)]}, indent=2) + "\n")
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
                for channel in ("stdout", "stderr"):
                    (attempt_dir / channel).write_bytes(getattr(result, channel))
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
