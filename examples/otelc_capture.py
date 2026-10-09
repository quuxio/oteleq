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
import threading


def digest(data):
    return hashlib.sha256(data).hexdigest()


def file_digest(path):
    with path.open("rb") as stream:
        return hashlib.file_digest(stream, "sha256").hexdigest()


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
    return identities


def stable(root, language, tools, expected):
    if artefacts(root, language, tools) != expected:
        raise ValueError("tool or adapter artefacts changed during capture")


def execute(command, workspace, environment, timeout=180):
    return subprocess.run([str(p) for p in command], cwd=workspace, env=environment,
                          stdin=subprocess.DEVNULL, capture_output=True, timeout=timeout, check=False)


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
    """Never acknowledge truncated, unknown or over-budget telemetry."""
    bodies, errors = [], []

    class Handler(BaseHTTPRequestHandler):
        def do_POST(self):
            self.connection.settimeout(2)
            try:
                size = int(self.headers.get("Content-Length", "-1"))
                if self.path not in ("/v1/traces", "/v1/metrics") or not 0 <= size <= 1024 * 1024 or len(bodies) >= 32:
                    raise ValueError("unexpected path or telemetry budget exceeded")
                body = self.rfile.read(size)
                if len(body) != size:
                    raise ValueError("truncated telemetry body")
                bodies.append((self.path, body))
                self.send_response(200)
                self.send_header("Content-Length", "0")
                self.end_headers()
            except (ValueError, TimeoutError, OSError) as error:
                errors.append(str(error))
                self.send_error(400)

        def log_message(self, *_):
            pass

    server = HTTPServer(("127.0.0.1", 0), Handler)
    worker = threading.Thread(target=server.serve_forever, daemon=True)
    worker.start()
    try:
        yield f"http://127.0.0.1:{server.server_port}", bodies, errors
    finally:
        server.shutdown()
        server.server_close()
        worker.join(timeout=3)


def configure(policy, endpoint):
    text, count = re.subn(r'^endpoint\s*=.*$', "endpoint = " + json.dumps(endpoint), policy.decode(), flags=re.MULTILINE)
    if count != 1:
        raise ValueError("example requires exactly one export endpoint")
    return text.encode()


def decode(bodies, service, decoder):
    """Validate the full local causal graph, without comparing random IDs."""
    names, nodes, raw, errors = Counter(), {}, [], 0
    for path, body in bodies:
        if path != "/v1/traces":
            continue
        raw.append(body)
        message = decoder.FromString(body)
        for resource in message.resource_spans:
            if not any(a.key == "service.name" and a.value.string_value == service for a in resource.resource.attributes):
                raise ValueError("telemetry service identity differs")
            for scope in resource.scope_spans:
                if scope.scope.name != "quux.otelc":
                    raise ValueError("unexpected instrumentation scope")
                for span in scope.spans:
                    key = (span.trace_id, span.span_id)
                    if (len(span.trace_id) != 16 or not any(span.trace_id) or len(span.span_id) != 8
                            or not any(span.span_id) or key in nodes or not span.name
                            or span.start_time_unix_nano <= 0 or span.end_time_unix_nano < span.start_time_unix_nano
                            or (span.parent_span_id and (len(span.parent_span_id) != 8 or not any(span.parent_span_id)))):
                        raise ValueError("invalid or duplicate span")
                    nodes[key] = (span.trace_id, span.parent_span_id) if span.parent_span_id else None
                    names[span.name] += 1
                    errors += int(span.status.code == 2)
    for key, parent in nodes.items():
        seen = {key}
        while parent is not None:
            if parent not in nodes or parent in seen:
                raise ValueError("missing parent or causal cycle")
            seen.add(parent)
            parent = nodes[parent]
    roots = sum(parent is None for parent in nodes.values())
    if len({key[0] for key in nodes}) != roots:
        raise ValueError("local trace must have one root")
    return dict(names), raw, roots, errors


def witness(bodies, report, spec, service, decoder):
    names, raw, roots, errors = decode(bodies, service, decoder)
    if names != spec["functions"] or roots != spec["trees"] or errors != spec["errors"]:
        raise ValueError("decoded telemetry does not match independent fixture expectations")
    traces = report["traces"]
    losses = {"traces." + key: value for key, value in traces["losses"].items()}
    losses.update({"runtime." + key: value for key, value in report["losses"].items()})
    export = [report[key] for key in ("export_loss", "export_dropped_batches") if key in report]
    if not export or report.get("export_finished") is not True or report.get("drained", True) is not True:
        raise ValueError("missing or unfinished export status")
    losses["transport.export"] = sum(export)
    pending = sum(traces.get(key, 0) for key in ("pending_contexts", "active_trees", "queued_trees"))
    if (any(losses.values()) or pending or traces.get("completed_trees") != roots
            or report.get("function_calls") != sum(names.values())):
        raise ValueError("lossy, incomplete or mismatched runtime report")
    return {"decoder": "opentelemetry-proto ExportTraceServiceRequest",
            "raw_otlp_sha256": digest(b"".join(raw)), "functions": names,
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
