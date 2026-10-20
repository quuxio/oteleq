"""Bounded diagnostic capture for the eight ordinary otelc trace workloads."""
from collections import Counter
from contextlib import contextmanager
import hashlib
from http.server import BaseHTTPRequestHandler, HTTPServer
import json
import os
import platform
from pathlib import Path
import re
import shutil
import subprocess
import sys
import tempfile
import threading
import time
import tomllib

import otelc_collection
import otelc_resource


MAX_REQUEST_BYTES = 1024 * 1024
TRACE_PATH = "/v1/traces"
MAX_REQUESTS = 32
REQUEST_TIMEOUT = 2


class Receiver(BaseHTTPRequestHandler):
    def do_POST(self):
        self.server.requests += 1
        lengths = self.headers.get_all("Content-Length", [])
        if (len(lengths) != 1 or not lengths[0].isascii() or not lengths[0].isdecimal()
                or self.headers.get("Transfer-Encoding") is not None
                or self.headers.get("Content-Encoding", "identity") != "identity"
                or self.path not in (TRACE_PATH, "/v1/metrics")):
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


OTELC_CLI_PATH = "target/debug/quux-otelc"
RUST_BUILD_FILENAME = "build.json"


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


def native_typescript_executables(root):
    return sorted(path for path in (root / "adapters/node/node_modules/@typescript").glob("typescript-*/lib/tsc*")
                  if path.is_file() and path.name in ("tsc", "tsc.exe"))


def typescript_backend(root, language, spec, policy):
    if language != "typescript":
        return None
    selected = spec.get("typescript_backend", "source")
    configured = tomllib.loads(policy.decode()).get("adapters", {}).get("typescript", {}).get("backend", "source")
    if selected not in ("source", "native") or configured != selected:
        raise ValueError("TypeScript compiler backend differs between baseline and instrumented policy")
    if selected == "native":
        operating_system = {"darwin": "darwin", "linux": "linux", "win32": "win32"}.get(sys.platform)
        architecture = {"arm64": "arm64", "aarch64": "arm64", "x86_64": "x64", "amd64": "x64"}.get(platform.machine().lower())
        executable = "tsc.exe" if sys.platform == "win32" else "tsc"
        compiler = root / "adapters/node/node_modules/@typescript" / f"typescript-{operating_system}-{architecture}" / "lib" / executable
        if compiler not in native_typescript_executables(root):
            raise ValueError("native TypeScript requires the installed host compiler executable")
    return selected


def artefacts(root, language, tools, *, rust_backend="compiler"):
    """Re-enumerate executable adapter inputs so additions/removals are visible."""
    paths = [root / OTELC_CLI_PATH]
    trees = []
    if language in ("c", "cpp"):
        paths += [root / "target/debug/libquux_otelc_runtime.a",
                  root / "target/debug/otelc-llvm-toolchain.json",
                  root / "target/debug/libotelc_pass.dylib"]
    elif language == "rust":
        paths += [root / "target/debug/otelc-rust-adapter", root / "Cargo.lock"]
        if rust_backend == "llvm":
            paths += rust_llvm_inputs(root, tools)
        else:
            rust_flags(rust_backend)
            paths += [root / "target/debug/libquux_otelc_rust.rlib"]
            dependencies = root / "target/debug/deps"
            paths += sorted(path for pattern in ("*.rlib", "*.dylib", "*.so", "*.dll")
                            for path in dependencies.glob(pattern))
    elif language == "java":
        paths += [root / "adapters/java/target/java-agent-0.1.0-agent.jar"]
    elif language == "go":
        paths += [root / "adapters/go/build/otelc-go", root / "adapters/go/go.sum"]
        trees += [(root / "adapters/go/runtime", {".go"})]
    elif language in ("javascript", "typescript"):
        paths += [root / "target/debug/otelc_node_observer.node", root / "adapters/node/package-lock.json"]
        paths += native_typescript_executables(root)
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
    for name in ("otelc_capture.py", "otelc_collection.py", "otelc_resource.py", "capture_otelc_languages.py", "otelc-workloads.json", "otelc-worker-workloads.json", "otelc-typescript-native-workloads.json", "otelc-collection-workloads.json", "otelc-resource-workloads.json"):
        identities["observer:" + name] = file_digest(Path(__file__).with_name(name))
    return identities


def stable(root, language, tools, expected, *, rust_backend="compiler"):
    if artefacts(root, language, tools, rust_backend=rust_backend) != expected:
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


RUST_BASELINE_FLAGS = ("--edition=2024", "-O", "-g")
RUST_LLVM_BASELINE_FLAGS = (*RUST_BASELINE_FLAGS, "-Zmir-enable-passes=-Inline,-ForceInline", "-Ccodegen-units=1")
RUST_PROFILE_FILENAME = "target/debug/otelc-rust-llvm.json"
RUST_PLAN_FILENAME = "plan.json"


def rust_flags(backend: str) -> tuple[str, ...]:
    """The caller chooses a qualified recipe; metadata never chooses flags."""
    if backend == "compiler":
        return RUST_BASELINE_FLAGS
    if backend == "llvm":
        return RUST_LLVM_BASELINE_FLAGS
    raise ValueError("unsupported Rust backend")


def rust_document(path: Path) -> dict:
    """Read fixed, bounded regular files with the shared strict JSON parser."""
    if path.is_symlink() or not path.is_file():
        raise ValueError("Rust evidence requires regular files")
    if path.stat().st_size > 4 * 1024 * 1024:
        raise ValueError("Rust evidence exceeds its size limit")
    document = strict_json(path.read_bytes())
    if not isinstance(document, dict):
        raise ValueError("Rust evidence must be an object")
    return document


def rust_profile(root: Path, tools: dict[str, Path]) -> dict[str, Path]:
    """Validate profile data and return only caller-derived asset paths for I/O."""
    profile = rust_document(root / RUST_PROFILE_FILENAME)
    expected_keys = {"schema_version", "rustc", "sdk", "sdk_sha256", "plugin", "plugin_sha256", "llvm_version", "protected_source_roots"}
    if (set(profile) != expected_keys or type(profile["schema_version"]) is not int or profile["schema_version"] != 1
            or profile["rustc"] != str(tools["rustc"])):
        raise ValueError("Rust LLVM profile schema or selected compiler differs")
    suffix = {"darwin": ".dylib", "linux": ".so", "win32": ".dll"}.get(sys.platform)
    if suffix is None:
        raise ValueError("Rust LLVM host profile is unsupported")
    assets = {"sdk": root / "target/rust-llvm-sdk/debug/libquux_otelc_rust.rlib",
              "plugin": root / ("target/debug/otelc_rust_pass" + suffix)}
    for key, path in assets.items():
        if (profile[key] != str(path) or path.resolve() != path or not path.is_file()
                or profile[key + "_sha256"] != file_digest(path)):
            raise ValueError("Rust LLVM fixed " + key + " asset or identity differs")
    prefixes = profile["protected_source_roots"]
    if (not isinstance(prefixes, list) or not prefixes
            or any(type(path) is not str or not Path(path).is_absolute() for path in prefixes)
            or type(profile["llvm_version"]) is not str or not profile["llvm_version"].strip()):
        raise ValueError("Rust LLVM profile metadata is incomplete")
    return assets


def rust_llvm_inputs(root: Path, tools: dict[str, Path]) -> list[Path]:
    """Freeze only compiler-resolvable SDK inputs, including additions/removals."""
    assets = rust_profile(root, tools)
    dependencies = assets["sdk"].parent / "deps"
    if not dependencies.is_dir() or dependencies.resolve() != dependencies:
        raise ValueError("Rust LLVM SDK dependency directory is missing or linked")
    paths = [root / RUST_PROFILE_FILENAME, assets["sdk"], assets["plugin"]]
    paths += sorted(path for pattern in ("*.rlib", "*.rmeta", "*.dylib", "*.so", "*.dll")
                    for path in dependencies.glob(pattern))
    if any(path.is_symlink() or not path.is_file() for path in paths):
        raise ValueError("Rust LLVM inputs require regular files")
    return paths


def rust_metadata(bundle: Path, backend: str = "compiler") -> dict:
    """Read only fixed bundle files and reject an unqualified schema/flag contract."""
    for name in ("application", RUST_PLAN_FILENAME, RUST_BUILD_FILENAME):
        path = bundle / name
        if path.is_symlink() or not path.is_file():
            raise ValueError("Rust build bundle needs regular application/plan/build files")
    metadata_path = bundle / RUST_BUILD_FILENAME
    if metadata_path.stat().st_size > 4 * 1024 * 1024:
        raise ValueError("Rust build metadata exceeds its size limit")
    metadata = strict_json(metadata_path.read_text())
    version = 2 if backend == "llvm" else 1
    if (not isinstance(metadata, dict) or type(metadata.get("schema_version")) is not int or metadata["schema_version"] != version
            or metadata.get("language") != "rust"
            or metadata.get("baseline_flags") != list(rust_flags(backend))):
        raise ValueError("Rust build flags or manifest schema require separate qualification")
    if backend == "llvm" and (metadata.get("backend") != "llvm" or set(metadata) != {
            "schema_version", "language", "backend", "executable_sha256", "plan_sha256", "adapter_sha256", "sdk_sha256",
            "source", "source_sha256", "source_root", "baseline_flags", "compiler", "compiler_hook"}):
        raise ValueError("Rust LLVM manifest fields or backend are unqualified")
    return metadata


def rust_compiler(metadata: dict, tools: dict[str, Path], backend: str = "compiler") -> dict:
    """Check compiler provenance as text; metadata cannot select an executable."""
    compiler = metadata.get("compiler", {})
    if (not isinstance(compiler, dict) or compiler.get("program") != str(tools["rustc"])
            or not isinstance(compiler.get("argv"), list)
            or not all(isinstance(arg, str) for arg in compiler["argv"])
            or not all(flag in compiler["argv"] for flag in rust_flags(backend))):
        raise ValueError("Rust build compiler provenance does not match the selected compiler")
    return compiler


def rust_llvm_compiler(compiler: dict, source: Path, workspace: Path, tools: dict,
                       assets: dict[str, Path], environment: dict | None) -> Path:
    """Verify the complete driver recipe against the selected compiler itself."""
    if not environment or "TMPDIR" not in environment or set(compiler) != {"program", "argv", "version"}:
        raise ValueError("Rust LLVM compiler context or provenance is incomplete")
    prefix = [source.relative_to(workspace).as_posix(), *RUST_LLVM_BASELINE_FLAGS, "-o"]
    tail = ["-Zllvm-plugins=" + str(assets["plugin"]), "-Zunstable-options", "--extern",
            "noprelude,force,nounused:quux_otelc_rust=" + str(assets["sdk"]), "-L",
            "dependency=" + str(assets["sdk"].parent / "deps")]
    argv = compiler["argv"]
    if len(argv) != len(prefix) + 1 + len(tail) or argv[:len(prefix)] != prefix or argv[len(prefix) + 1:] != tail:
        raise ValueError("Rust LLVM compiler arguments differ from the matched recipe")
    output = Path(argv[len(prefix)])
    if not output.is_absolute() or output.name != "application" or output.parent.parent != Path(environment["TMPDIR"]).resolve():
        raise ValueError("Rust LLVM compiler output is outside the caller scratch directory")
    version = execute([tools["rustc"], "-vV"], workspace, environment, timeout=30)
    if (version.returncode or len(version.stdout) > 32768 or version.stderr
            or compiler.get("version") != version.stdout.decode("utf-8").strip()):
        raise ValueError("Rust LLVM compiler version differs from the selected tool")
    return output.parent


def rust_llvm_rows(document: dict, version: int) -> tuple[list[dict], list[dict]]:
    """Selection and startup flags are explicit booleans, never truthy values."""
    rows = document.get("functions")
    if (type(document.get("schema_version")) is not int or document["schema_version"] != version
            or not isinstance(rows, list) or len(rows) > 65536
            or any(not isinstance(row, dict) or type(row.get("selected")) is not bool
                   or type(row.get("startup")) is not bool for row in rows)):
        raise ValueError("Rust LLVM function inventory is malformed")
    selected = [row for row in rows if row["selected"]]
    startup = [row for row in rows if row["startup"]]
    if len(selected) != 1 or len(startup) != 1 or selected[0]["startup"] or startup[0]["selected"]:
        raise ValueError("Rust LLVM requires one selected function and one independent startup")
    return selected, startup


def rust_llvm_function(declaration: dict, resolved: dict, source: Path, name: str) -> None:
    """Require the selected compiler symbol to match its original declaration."""
    coordinates = ("body_start_line", "body_start_column", "body_end_line", "body_end_column")
    for field in coordinates:
        if (type(declaration.get(field)) is not int or declaration[field] < 1
                or type(resolved.get(field)) is not int or resolved[field] != declaration[field]):
            raise ValueError("Rust LLVM resolved source coordinates differ")
    lines = source.read_bytes().splitlines()
    start, end = declaration["body_start_line"], declaration["body_end_line"]
    if (start > end or end > len(lines) or declaration["body_start_column"] > len(lines[start - 1]) + 1
            or declaration["body_end_column"] > len(lines[end - 1]) + 1
            or start == end and declaration["body_start_column"] > declaration["body_end_column"]):
        raise ValueError("Rust LLVM source coordinates exceed the frozen source")
    if (declaration.get("file") != str(source.resolve()) or declaration.get("name") != name
            or declaration.get("unsupported") != "" or resolved.get("file") != declaration["file"]
            or resolved.get("name") != name or resolved.get("kind") != "function"
            or resolved.get("source_sha256") != file_digest(source)
            or type(resolved.get("compiled_symbol")) is not str or not resolved["compiled_symbol"].strip()):
        raise ValueError("Rust LLVM resolved symbol, selection or source identity differs")


def rust_llvm_records(inventory: dict, resolved: dict, workspace: Path, source: Path, expected_function: str,
                      scratch: Path) -> dict:
    """Qualify this standalone entry and reject unsupported multi-source builds."""
    selected, startup = rust_llvm_rows(inventory, 2)
    actual_selected, actual_startup = rust_llvm_rows(resolved, 1)
    relative = source.relative_to(workspace).as_posix()
    discovery = [relative, *RUST_LLVM_BASELINE_FLAGS, "--emit=dep-info=" + str(scratch / "original.d")]
    if (set(inventory) != {"schema_version", "functions", "sources", "discovery_argv"}
            or inventory.get("sources") != {str(source.resolve()): file_digest(source)}
            or inventory.get("discovery_argv") != discovery):
        raise ValueError("Rust LLVM discovery recipe or standalone source set differs")
    if (set(resolved) != {"schema_version", "phase", "module", "functions"}
            or resolved.get("phase") != "llvm-pipeline-start"
            or type(resolved.get("module")) is not str or not resolved["module"].strip()):
        raise ValueError("Rust LLVM resolution phase or module differs")
    main = str(Path(relative).with_suffix("")).replace("/", ".") + ".main"
    rust_llvm_function(selected[0], actual_selected[0], source, expected_function)
    rust_llvm_function(startup[0], actual_startup[0], source, main)
    return {"selected_symbol": actual_selected[0]["compiled_symbol"], "selected_function": expected_function,
            "resolution_phase": resolved["phase"]}


def rust_llvm_manifest(root: Path, workspace: Path, source: Path, bundle: Path, metadata: dict,
                       tools: dict, assets: dict[str, Path], expected_function: str | None, environment: dict | None) -> dict:
    """Bind compiler hook evidence to fixed profile assets and the requested target."""
    if type(expected_function) is not str or not expected_function.strip():
        raise ValueError("Rust LLVM needs an explicit expected function identity")
    inventory = rust_document(bundle / "inventory.json")
    resolved = rust_document(bundle / "resolved.json")
    hook = metadata.get("compiler_hook")
    hashes = {"profile_sha256": file_digest(root / RUST_PROFILE_FILENAME),
              "plugin_sha256": file_digest(assets["plugin"]),
              "inventory_sha256": file_digest(bundle / "inventory.json"),
              "resolved_sha256": file_digest(bundle / "resolved.json")}
    if not isinstance(hook, dict) or hook != hashes:
        raise ValueError("Rust LLVM profile, plugin or compiler evidence identity differs")
    plan = rust_document(bundle / RUST_PLAN_FILENAME)
    if (type(plan.get("schema_version")) is not int or plan["schema_version"] != 2
            or plan.get("backend") != "llvm" or plan.get("language") != "rust"
            or plan.get("functions") != {"include": [expected_function], "exclude": []}
            or plan.get("sources") != {"include": [source.relative_to(workspace).as_posix()], "exclude": []}
            or plan.get("execution_available") is not True or plan.get("unavailable") != []):
        raise ValueError("Rust LLVM retained selection plan differs from the requested entry")
    scratch = rust_llvm_compiler(metadata["compiler"], source, workspace, tools, assets, environment)
    records = rust_llvm_records(inventory, resolved, workspace, source, expected_function, scratch)
    return {"backend": "llvm", "compiler_hook": hashes, **records}


def rust_manifest(root: Path, workspace: Path, source: Path, bundle: Path, tools: dict[str, Path], *,
                  backend: str = "compiler", expected_function: str | None = None, environment: dict | None = None) -> dict:
    """Verify all source/build/provider hashes using only caller-selected paths."""
    metadata = rust_metadata(bundle, backend)
    compiler = rust_compiler(metadata, tools, backend)
    assets = rust_profile(root, tools) if backend == "llvm" else None
    expected = {"executable_sha256": file_digest(bundle / "application"),
                "plan_sha256": file_digest(bundle / RUST_PLAN_FILENAME),
                "source_sha256": file_digest(source),
                "sdk_sha256": file_digest(assets["sdk"] if assets else root / "target/debug/libquux_otelc_rust.rlib"),
                "adapter_sha256": file_digest(root / "target/debug/otelc-rust-adapter")}
    if (any(metadata.get(key) != value for key, value in expected.items())
            or metadata.get("source") != str(source.resolve())
            or metadata.get("source_root") != str(workspace.resolve())):
        raise ValueError("Rust build source, executable, policy or provider identity changed")
    hook = rust_llvm_manifest(root, workspace, source, bundle, metadata, tools, assets, expected_function, environment) if assets else {}
    return {**expected, "manifest_sha256": file_digest(bundle / RUST_BUILD_FILENAME),
            "baseline_flags": list(rust_flags(backend)), "compiler": compiler, **hook}


def rust_command(root, workspace, source, policy, tools, environment, evidence, output, lane, *,
                 backend="compiler", expected_function=None):
    """Build only the selected lane; application launch never invokes rustc."""
    prefix = [root / OTELC_CLI_PATH, "--config", policy, "--language", "rust"]
    relative = source.relative_to(workspace)
    if lane == "baseline":
        binary = output / "plain"
        build([tools["rustc"], *rust_flags(backend), relative, "-o", binary], workspace,
              environment, evidence / "plain-build.log")
        command = [binary]
        identities = {"application": file_digest(binary), "baseline_flags": list(rust_flags(backend))}
    else:
        bundle = output / "rust-bundle"
        build(prefix + ["rust", "--build", relative, "--output-dir", bundle], workspace,
              environment, evidence / "instrumented-build.log")
        identities = rust_manifest(root, workspace, source, bundle, tools, backend=backend,
                                   expected_function=expected_function, environment=environment)
        command = prefix + ["rust", "--run", bundle]
    (evidence / (lane + "-build-identities.json")).write_text(json.dumps(identities, indent=2) + "\n")
    return command


def commands(root, workspace, language, source, policy, tools, environment, evidence):
    prefix = [root / OTELC_CLI_PATH, "--config", policy, "--language", language]
    if language in ("c", "cpp"):
        tool = "clang++" if language == "cpp" else "clang"
        flags = ["-O2", "-pthread", "-std=c++17"] if language == "cpp" else ["-O1", "-pthread"]
        plain, instrumented = workspace / "plain", workspace / "instrumented"
        build([tools[tool], *flags, source, "-o", plain], workspace, environment, evidence / "plain-build.log")
        build(prefix + [tool, *flags, source, "-o", instrumented], workspace, environment, evidence / "instrumented-build.log")
        return [plain], prefix + ["run", instrumented]
    if language == "rust":
        return tuple(rust_command(root, workspace, source, policy, tools, environment, evidence, workspace, lane)
                     for lane in ("baseline", "instrumented_on"))
    interpreter = tools[language]
    plain = [interpreter, source]
    if language == "go":
        plain = [interpreter, "run", source]
    elif language == "java":
        plain = [interpreter, "-Xshare:off", source]
    elif language == "typescript":
        plain = [interpreter, "--import", root / "adapters/node/plain.mjs", source]
    adapter = {"javascript": "node", "typescript": "ts"}.get(language, language)
    arguments = ["-Xshare:off", source] if language == "java" else [source]
    return plain, prefix + [adapter, *arguments]


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
    original = policy.decode()
    expected = tomllib.loads(original)
    export = expected.get("export", {})
    if "endpoint" in export:
        text, count = re.subn(r'^endpoint\s*=.*$', "endpoint = " + json.dumps(endpoint), original, flags=re.MULTILINE)
    else:
        text, count = re.subn(r'^\[export\][ \t]*(?:#.*)?$', "[export]\nendpoint = " + json.dumps(endpoint),
                             original, flags=re.MULTILINE)
    if count != 1:
        raise ValueError("example requires one explicit export table or endpoint")
    expected["export"] = {**export, "endpoint": endpoint}
    if tomllib.loads(text) != expected:
        raise ValueError("private override must change only the export endpoint")
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
        if path != TRACE_PATH:
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


def lifetime_diagnostics(bodies, report, spec, service, decoder, language):
    """Keep lifetime events separate from ordinary function call accounting."""
    selected = [kind for kind in ("collection", "resource") if kind in spec]
    if not selected:
        return {}, 0
    kind = selected[0]
    if len(selected) != 1 or language != "python":
        raise ValueError(f"{kind} qualification requires Python and a distinct workload")
    spans = [span for path, body in bodies if path == TRACE_PATH
             for span in service_spans(decoder.FromString(body), service)]
    verify = {"collection": otelc_collection.verify, "resource": otelc_resource.verify}[kind]
    if kind == "resource":
        otelc_resource.metric_values(bodies, service, spec[kind], otelc_resource.metric_decoder())
    return verify(spans, report, spec[kind]), spec[kind]["count"]


def witness(bodies, report, spec, service, decoder, language):
    require_runtime_identity(report, language)
    names, raw, roots, errors = decode(bodies, service, decoder)
    if names != spec["functions"] or roots != spec["trees"] or errors != spec["errors"]:
        raise ValueError("decoded telemetry does not match independent fixture expectations")
    losses, export = loss_diagnostics(report, language)
    lifetime_losses, lifetime_count = lifetime_diagnostics(bodies, report, spec, service, decoder, language)
    losses.update(lifetime_losses)
    function_calls = sum(names.values()) - lifetime_count
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
            or report.get("function_calls") != function_calls):
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
        llvm = strict_json((root / "target/debug/otelc-llvm-toolchain.json").read_text())
        compiler = "clang++" if language == "cpp" else "clang"
        variable = "OTELC_CLANGXX" if language == "cpp" else "OTELC_CLANG"
        # Metadata qualifies an explicitly selected compiler; it cannot select code to execute.
        directory = "/opt/homebrew/opt/llvm@22/bin" if sys.platform == "darwin" else "/usr/lib/llvm-22/bin"
        selected = tool_path(os.environ.get(variable, directory + "/" + compiler))
        configured = llvm["bindir"]
        if not isinstance(configured, str) or str(selected.parent.resolve()) != configured:
            raise ValueError("selected compiler does not match otelc LLVM metadata; set " + variable)
        return {compiler: selected}
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
