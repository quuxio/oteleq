"""Bounded diagnostic capture for the eight ordinary otelc trace workloads."""
from collections import Counter
from contextlib import contextmanager
import hashlib
from http.server import BaseHTTPRequestHandler, HTTPServer
import json
import os
from pathlib import Path
import re
import shutil
import subprocess
import sys
import tempfile
import threading
import time


MAX_REQUEST_BYTES = 1024 * 1024
MAX_REQUESTS = 32
REQUEST_TIMEOUT = 2


class Receiver(BaseHTTPRequestHandler):
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
        if size > MAX_REQUEST_BYTES or self.server.requests > self.server.max_requests:
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
        except OSError:
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
    def __init__(self, max_requests=MAX_REQUESTS):
        self.max_requests = max_requests
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


def strict_json(data):
    def unique_object(pairs):
        result = {}
        for key, value in pairs:
            if key in result:
                raise ValueError("duplicate runtime report key")
            result[key] = value
        return result
    return json.loads(data, object_pairs_hook=unique_object)


def digest(data):
    return hashlib.sha256(data).hexdigest()


def file_digest(path):
    with path.open("rb") as stream:
        return hashlib.file_digest(stream, "sha256").hexdigest()


def temporary_parent(*source_roots):
    source_roots = tuple(root.resolve() for root in source_roots)
    # Reject configured source paths before tempfile probes them for writability.
    for variable in ("TMPDIR", "TEMP", "TMP"):
        if value := os.environ.get(variable):
            candidate = Path(value).resolve()
            if any(candidate.is_relative_to(root) for root in source_roots):
                raise ValueError("temporary directory must be outside both repositories; correct TMPDIR")
    parent = Path(tempfile.gettempdir()).resolve()
    if any(parent.is_relative_to(root) for root in source_roots):
        raise ValueError("temporary directory must be outside both repositories; correct TMPDIR")
    return parent


def retain_http(folder, bodies, errors, requests=None):
    for index, (_, body) in enumerate(bodies):
        (folder / f"otlp-{index}.protobuf").write_bytes(body)
    manifest = {"errors": errors, "bodies": [{"path": path, "file": f"otlp-{index}.protobuf"}
                                            for index, (path, _) in enumerate(bodies)]}
    if requests is not None:
        manifest["requests"] = requests
    (folder / "http-capture.json").write_text(json.dumps(manifest, indent=2) + "\n")


def tool_path(name):
    path = shutil.which(name)
    if path is None:
        raise ValueError(f"required tool is missing: {name}")
    return Path(path).absolute()


def artefacts(root, language, tools):
    """Re-enumerate executable adapter inputs so additions/removals are visible."""
    paths = [root / "target/debug/quux-otelc"]
    trees = []
    if language in ("c", "cpp"):
        paths += [root / "target/debug/libquux_otelc_runtime.a",
                  root / "target/debug/otelc-llvm-toolchain.json",
                  root / "target/debug/libotelc_pass.dylib"]
    elif language == "rust":
        paths += [root / "target/debug/otelc-rust-adapter", root / "target/debug/libquux_otelc_rust.rlib",
                  root / "Cargo.lock"]
        paths += sorted((root / "target/debug/deps").glob("*.rlib"))
    elif language == "java":
        paths += [root / "adapters/java/target/java-agent-0.1.0-agent.jar"]
    elif language == "go":
        paths += [root / "adapters/go/build/otelc-go", root / "adapters/go/go.sum"]
        trees += [(root / "adapters/go/runtime", {".go"})]
    elif language in ("javascript", "typescript"):
        paths += [root / "target/debug/otelc_node_observer.node", root / "adapters/node/package-lock.json"]
        trees += [(root / "adapters/node", {".mjs", ".js", ".cjs", ".json", ".node"})]
    elif language == "python":
        paths += [root / "adapters/python/requirements.txt"]
        trees += [(root / "adapters/python", {".py"})]
        trees += [(root / ".venv/lib/python3.12/site-packages", {".py", ".so", ".json"})]
    else:
        raise ValueError("unsupported language")
    for tree, suffixes in trees:
        if not tree.is_dir():
            raise ValueError(f"required adapter directory is missing: {tree}")
        paths += [p for p in sorted(tree.rglob("*")) if p.is_file() and p.suffix in suffixes
                  and "tests" not in p.relative_to(tree).parts]
    identities = {str(p.relative_to(root)): file_digest(p) for p in paths}
    identities.update({"tool:" + name: file_digest(path) for name, path in tools.items()})
    for name in ("otelc_capture.py", "capture_otelc_languages.py", "otelc-workloads.json"):
        identities["observer:" + name] = file_digest(Path(__file__).with_name(name))
    return identities


def stable(root, language, tools, expected):
    if artefacts(root, language, tools) != expected:
        raise ValueError("tool or adapter artefacts changed during capture")


def execute(command, workspace, environment, timeout=180):
    """Run trusted selected artefacts; this diagnostic executor is not a sandbox."""
    return subprocess.run([str(p) for p in command], cwd=workspace, env=environment,
                          stdin=subprocess.DEVNULL, capture_output=True, timeout=timeout, check=False, shell=False)


def build(command, workspace, environment, output):
    result = execute(command, workspace, environment)
    output.write_bytes(result.stdout + result.stderr)
    if result.returncode != 0:
        raise ValueError(f"build failed; inspect {output}")


def commands(root, workspace, language, source, policy, tools, environment, evidence):
    prefix = [root / "target/debug/quux-otelc", "--config", policy, "--language", language]
    if language in ("c", "cpp"):
        tool = "clang++" if language == "cpp" else "clang"
        flags = ["-O2", "-pthread", "-std=c++17"] if language == "cpp" else ["-O1", "-pthread"]
        plain, instrumented = workspace / "plain", workspace / "instrumented"
        build([tools[tool], *flags, source, "-o", plain], workspace, environment, evidence / "plain-build.log")
        build(prefix + [tool, *flags, source, "-o", instrumented], workspace, environment, evidence / "instrumented-build.log")
        return [plain], prefix + ["run", instrumented]
    if language == "rust":
        plain = workspace / "plain"
        build([tools["rustc"], "--edition=2024", source, "-o", plain], workspace, environment, evidence / "plain-build.log")
        return [plain], prefix + ["rust", source]
    interpreter = tools[language]
    plain = [interpreter, source]
    if language == "go":
        plain = [interpreter, "run", source]
    elif language == "typescript":
        plain = [interpreter, "--import", root / "adapters/node/plain.mjs", source]
    adapter = {"javascript": "node", "typescript": "ts"}.get(language, language)
    return plain, prefix + [adapter, source]


@contextmanager
def receiver():
    """Expose exact received bytes and every transport failure to the observer."""
    server = CaptureServer()
    worker = threading.Thread(target=server.serve_forever, kwargs={"poll_interval": 0.05}, daemon=True)
    worker.start()
    try:
        yield f"http://127.0.0.1:{server.server_port}", server.bodies, server.errors
    finally:
        server.shutdown()
        server.server_close()
        worker.join(timeout=3)


def configure(policy, endpoint):
    text, count = re.subn(r'^endpoint\s*=.*$', "endpoint = " + json.dumps(endpoint), policy.decode(), flags=re.MULTILINE)
    if count != 1:
        raise ValueError("example requires exactly one export endpoint")
    return text.encode()


def span_identity(span):
    if (len(span.trace_id) != 16 or not any(span.trace_id)
            or len(span.span_id) != 8 or not any(span.span_id)
            or not span.name.strip() or span.start_time_unix_nano <= 0
            or span.end_time_unix_nano < span.start_time_unix_nano
            or (span.parent_span_id and (len(span.parent_span_id) != 8 or not any(span.parent_span_id)))):
        raise ValueError("invalid or duplicate OTLP span")
    return span.trace_id, span.span_id


def service_spans(message, service):
    for resource in message.resource_spans:
        if not any(a.key == "service.name" and a.value.string_value == service for a in resource.resource.attributes):
            raise ValueError("telemetry service identity differs")
        for scope in resource.scope_spans:
            if scope.scope.name != "quux.otelc":
                raise ValueError("unexpected instrumentation scope")
            yield from scope.spans


def trace_roots(nodes):
    resolved = set()
    for key in nodes:
        current, seen = key, set()
        while current is not None and current not in resolved:
            if current not in nodes or current in seen:
                raise ValueError("missing parent or causal cycle")
            seen.add(current)
            current = nodes[current]
        resolved.update(seen)
    roots = sum(parent is None for parent in nodes.values())
    if len({key[0] for key in nodes}) != roots:
        raise ValueError("local trace must have one root")
    return roots


def decode(bodies, service, decoder):
    """Validate the full local causal graph, without comparing random IDs."""
    names, nodes, raw, errors = Counter(), {}, [], 0
    for path, body in bodies:
        if path != "/v1/traces":
            continue
        raw.append(body)
        for span in service_spans(decoder.FromString(body), service):
            key = span_identity(span)
            if key in nodes:
                raise ValueError("invalid or duplicate span")
            nodes[key] = (span.trace_id, span.parent_span_id) if span.parent_span_id else None
            names[span.name] += 1
            errors += int(span.status.code == 2)
    roots = trace_roots(nodes)
    return dict(names), raw, roots, errors


def require_runtime_identity(report, language):
    if language in ("c", "cpp"):
        if report.get("drained") is not True:
            raise ValueError("missing or unfinished native drain status")
    elif (type(report.get("schema_version")) is not int or report["schema_version"] != 1
          or report.get("language") != language):
        raise ValueError("unsupported or mismatched runtime report")


def loss_diagnostics(report, language):
    traces = report["traces"]
    runtime_losses = report["losses"]
    required = {"active_call_capacity", "incomplete"}
    if language in ("c", "cpp"):
        required |= {"invalid_exit", "object_capacity", "object_incomplete", "queue", "stack", "thread_admission"}
        export_key = "export_dropped_batches"
    else:
        required |= {"function_capacity", "invalid"}
        export_key = "export_loss"
    if (not isinstance(runtime_losses, dict)
            or not required.issubset(runtime_losses)
            or not isinstance(traces["losses"], dict)
            or any(not isinstance(key, str) or not key.strip() for key in (*traces["losses"], *runtime_losses))):
        raise ValueError("missing or invalid runtime loss diagnostics")
    losses = {"traces." + key: value for key, value in traces["losses"].items()}
    losses.update({"runtime." + key: value for key, value in runtime_losses.items()})
    export = [report[key] for key in ("export_loss", "export_dropped_batches") if key in report]
    if export_key not in report:
        raise ValueError("missing export status")
    require_counters([*losses.values(), *export])
    return losses, export


def require_counters(values):
    if any(type(value) is not int or value < 0 for value in values):
        raise ValueError("invalid runtime counter")


def witness(bodies, report, spec, service, decoder, language):
    require_runtime_identity(report, language)
    names, raw, roots, errors = decode(bodies, service, decoder)
    if names != spec["functions"] or roots != spec["trees"] or errors != spec["errors"]:
        raise ValueError("decoded telemetry does not match independent fixture expectations")
    losses, export = loss_diagnostics(report, language)
    if report.get("export_finished") is not True or report.get("drained", True) is not True:
        raise ValueError("missing or unfinished export status")
    traces = report["traces"]
    try:
        pending_counters = [traces[key] for key in ("active_trees", "queued_trees")]
        if language == "python" or "pending_contexts" in traces:
            pending_counters.append(traces["pending_contexts"])
        counters = [*pending_counters, traces["completed_trees"], report["function_calls"]]
    except KeyError as error:
        raise ValueError("missing runtime counter") from error
    require_counters(counters)
    losses["transport.export"] = sum(export)
    pending = sum(pending_counters)
    if (any(losses.values()) or pending or traces.get("completed_trees") != roots
            or report.get("function_calls") != sum(names.values())):
        raise ValueError("lossy, incomplete or mismatched runtime report")
    raw_digest = hashlib.sha256()
    for body in raw:
        raw_digest.update(body)
    return {"decoder": "opentelemetry-proto ExportTraceServiceRequest",
            "raw_otlp_sha256": raw_digest.hexdigest(), "functions": names,
            "spans": sum(names.values()), "losses": losses, "pending": pending}


def environment(workspace, tools, service, root):
    # No inherited telemetry headers, loader flags, agents or compiler wrappers.
    env = {"PATH": os.environ.get("PATH", ""), "HOME": str(workspace.parent), "TMPDIR": str(workspace.parent),
           "LANG": "C.UTF-8", "PYTHONDONTWRITEBYTECODE": "1", "OTEL_SERVICE_NAME": service,
           "OTELC_ADAPTER_ROOT": str(root / "adapters"), "OTELC_PYTHON": sys.executable}
    for language, variable in (("javascript", "OTELC_NODE"), ("java", "OTELC_JAVA"),
                               ("go", "OTELC_GO"), ("rustc", "OTELC_RUSTC")):
        if language in tools:
            env[variable] = str(tools[language])
    if "rustc" in tools:
        # A rustup proxy needs its installed toolchain, not a fresh HOME.
        for variable in ("RUSTUP_HOME", "CARGO_HOME"):
            if variable in os.environ:
                env[variable] = os.environ[variable]
    return env


def selected_tools(root, language):
    if language in ("c", "cpp"):
        llvm = json.loads((root / "target/debug/otelc-llvm-toolchain.json").read_text())
        compiler = "clang++" if language == "cpp" else "clang"
        return {compiler: Path(llvm["bindir"]) / compiler}
    if language == "rust":
        return {"rustc": tool_path(os.environ.get("OTELC_RUSTC", "rustc"))}
    names = {"python": sys.executable, "java": os.environ.get("OTELC_JAVA", "java"),
             "go": os.environ.get("OTELC_GO", "go"),
             "javascript": os.environ.get("OTELC_NODE", "node"),
             "typescript": os.environ.get("OTELC_NODE", "node")}
    tools = {language: tool_path(names[language])}
    if language == "typescript":
        tools["javascript"] = tools[language]
    return tools
