"""Bounded diagnostic capture for the eight ordinary otelc trace workloads."""
from collections import Counter
from collections.abc import Collection, Iterator
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


def raise_walk_error(error: OSError) -> None:
    """An inaccessible or vanished directory is incomplete input evidence."""
    raise error


def walk_tree(root: Path) -> Iterator[tuple[str, list[str], list[str]]]:
    """Keep directory pruning available while refusing incomplete enumeration."""
    return os.walk(root, followlinks=False, onerror=raise_walk_error)


def tree_paths(root: Path, *, excluded: Collection[str] = ()) -> Iterator[Path]:
    """Enumerate entries without following links or inspecting excluded trees."""
    for directory, names, files in walk_tree(root):
        names[:] = sorted(name for name in names if name not in excluded)
        for name in sorted(names + files):
            yield Path(directory) / name


MAX_REQUEST_BYTES = 1024 * 1024
TRACE_PATH = "/v1/traces"
MAX_REQUESTS = 32
MAX_CAPTURE_BYTES = MAX_REQUESTS * MAX_REQUEST_BYTES
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
        if (size > MAX_REQUEST_BYTES or self.server.requests > self.server.max_requests
                or size > self.server.max_bytes - self.server.received_bytes):
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
        self.server.received_bytes += size
        self.send_response(200)
        self.send_header("Content-Length", "0")
        self.end_headers()

    def log_message(self, *_):
        # Request failures are retained in the capture status, not application stderr.
        pass

    def log_error(self, *_):
        self.server.errors.append("HTTP capture protocol or connection error")


class CaptureServer(HTTPServer):
    def __init__(self, max_requests=MAX_REQUESTS, *, max_bytes=MAX_CAPTURE_BYTES):
        self.max_requests = max_requests
        self.max_bytes = max_bytes
        self.received_bytes = 0
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
BUILD_FILENAME = "build.json"
RECIPE_FILENAME = "recipe.json"
GO_MODULE_FILENAME = "go.mod"
GO_ADAPTER_DIRECTORY = "adapters/go"


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


def rust_inputs(root: Path, tools: dict[str, Path], backend: str) -> list[Path]:
    """Enumerate only the explicitly selected Rust profile and its inputs."""
    paths = [root / "target/debug/otelc-rust-adapter", root / "Cargo.lock"]
    if backend == "llvm":
        return paths + rust_llvm_inputs(root, tools)
    rust_flags(backend)
    profile = root / RUST_COMPILER_PROFILE_FILENAME
    if profile.exists() or profile.is_symlink():
        from otelc_rust_build import inputs
        return paths + inputs(root, tools)
    dependencies = root / "target/debug/deps"
    paths += [root / "target/debug/libquux_otelc_rust.rlib"]
    paths += sorted(path for pattern in ("*.rlib", "*.dylib", "*.so", "*.dll")
                    for path in dependencies.glob(pattern))
    return paths


def artefacts(root, language, tools, *, rust_backend="compiler"):
    """Re-enumerate executable adapter inputs so additions/removals are visible."""
    paths = [root / OTELC_CLI_PATH]
    trees = []
    if language in ("c", "cpp"):
        paths += [root / "target/debug/libquux_otelc_runtime.a",
                  root / "target/debug/otelc-llvm-toolchain.json",
                  root / "target/debug/libotelc_pass.dylib"]
    elif language == "rust":
        paths += rust_inputs(root, tools, rust_backend)
    elif language == "java":
        paths += [root / "adapters/java/target/java-agent-0.1.0-agent.jar"]
    elif language == "go":
        paths += [root / "adapters/go/build/otelc-go", root / "adapters/go/go.mod", root / "adapters/go/go.sum"]
        trees += [(root / "adapters/go/runtime", {".go"}), (root / "adapters/go/policy", {".go"})]
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
        paths += [p for p in sorted(tree_paths(tree, excluded={"tests"})) if p.is_file() and p.suffix in suffixes]
    identities = {str(p.relative_to(root)): file_digest(p) for p in paths}
    identities.update({"tool:" + name: file_digest(path) for name, path in tools.items()})
    for name in ("otelc_capture.py", "otelc_rust_build.py", "otelc_collection.py", "otelc_resource.py", "capture_otelc_languages.py", "otelc-workloads.json", "otelc-worker-workloads.json", "otelc-typescript-native-workloads.json", "otelc-collection-workloads.json", "otelc-resource-workloads.json"):
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
RUST_COMPILER_PROFILE_FILENAME = "target/debug/otelc-rust-compiler.json"
PLAN_FILENAME = "plan.json"


def rust_flags(backend: str) -> tuple[str, ...]:
    """The caller chooses a qualified recipe; metadata never chooses flags."""
    if backend == "compiler":
        return RUST_BASELINE_FLAGS
    if backend == "llvm":
        return RUST_LLVM_BASELINE_FLAGS
    raise ValueError("unsupported Rust backend")


def build_document(path: Path, *, limit: int = 4 * 1024 * 1024) -> dict:
    """Read fixed, bounded regular files with the shared strict JSON parser."""
    if path.is_symlink() or not path.is_file():
        raise ValueError("Build evidence requires regular files")
    if path.stat().st_size > limit:
        raise ValueError("Build evidence exceeds its size limit")
    document = strict_json(path.read_bytes())
    if not isinstance(document, dict):
        raise ValueError("Build evidence must be an object")
    return document


def rust_profile(root: Path, tools: dict[str, Path]) -> dict[str, Path]:
    """Validate profile data and return only caller-derived asset paths for I/O."""
    profile = build_document(root / RUST_PROFILE_FILENAME)
    expected_keys = {"schema_version", "rustc", "sdk", "sdk_sha256", "plugin", "plugin_sha256", "llvm_version", "protected_source_roots"}
    version = profile.get("schema_version")
    if type(version) is int and version == 2:
        expected_keys |= {"frontend", "frontend_sha256"}
    if (set(profile) != expected_keys or type(version) is not int or version not in (1, 2)
            or profile["rustc"] != str(tools["rustc"])):
        raise ValueError("Rust LLVM profile schema or selected compiler differs")
    suffix = {"darwin": ".dylib", "linux": ".so", "win32": ".dll"}.get(sys.platform)
    if suffix is None:
        raise ValueError("Rust LLVM host profile is unsupported")
    assets = {"sdk": root / "target/rust-llvm-sdk/debug/libquux_otelc_rust.rlib",
              "plugin": root / ("target/debug/otelc_rust_pass" + suffix)}
    if version == 2:
        assets["frontend"] = root / "target/debug/otelc-rust-frontend"
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
    paths = [root / RUST_PROFILE_FILENAME, *assets.values()]
    paths += sorted(path for pattern in ("*.rlib", "*.rmeta", "*.dylib", "*.so", "*.dll")
                    for path in dependencies.glob(pattern))
    if any(path.is_symlink() or not path.is_file() for path in paths):
        raise ValueError("Rust LLVM inputs require regular files")
    return paths


def rust_compiler_fields(metadata: dict) -> None:
    """Legacy and original-source compiler manifests have separate closed fields."""
    fields = {"schema_version", "language", "executable_sha256", "plan_sha256", "adapter_sha256", "sdk_sha256",
              "source", "source_sha256", "source_root", "baseline_flags", "compiler"}
    if metadata["schema_version"] == 3:
        fields |= {"backend", "compiler_driver"}
    if set(metadata) != fields or metadata["schema_version"] == 3 and metadata["backend"] != "compiler":
        raise ValueError("Rust compiler manifest fields or backend are unqualified")


def rust_metadata(bundle: Path, backend: str = "compiler") -> dict:
    """Read only fixed bundle files and reject an unqualified schema/flag contract."""
    for name in ("application", PLAN_FILENAME, BUILD_FILENAME):
        path = bundle / name
        if path.is_symlink() or not path.is_file():
            raise ValueError("Rust build bundle needs regular application/plan/build files")
    metadata_path = bundle / BUILD_FILENAME
    if metadata_path.stat().st_size > 4 * 1024 * 1024:
        raise ValueError("Rust build metadata exceeds its size limit")
    metadata = strict_json(metadata_path.read_text())
    versions = (2,) if backend == "llvm" else (1, 3)
    if (not isinstance(metadata, dict) or type(metadata.get("schema_version")) is not int or metadata["schema_version"] not in versions
            or metadata.get("language") != "rust"
            or metadata.get("baseline_flags") != list(rust_flags(backend))):
        raise ValueError("Rust build flags or manifest schema require separate qualification")
    if backend == "llvm" and (metadata.get("backend") != "llvm" or set(metadata) != {
            "schema_version", "language", "backend", "executable_sha256", "plan_sha256", "adapter_sha256", "sdk_sha256",
            "source", "source_sha256", "source_root", "baseline_flags", "compiler", "compiler_hook"}):
        raise ValueError("Rust LLVM manifest fields or backend are unqualified")
    if backend == "compiler":
        rust_compiler_fields(metadata)
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
    prefix = [source.relative_to(workspace).as_posix(), *RUST_LLVM_BASELINE_FLAGS]
    if "frontend" in assets:
        prefix += ["--sysroot", str(tools["rustc"].parent.parent)]
    prefix += ["-o"]
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


def rust_frontend_rows(inventory: dict) -> None:
    """Only emitted compiler instances have symbols; declaration rows are not witnesses."""
    symbols = set()
    for row in inventory["functions"]:
        symbol = row.get("compiled_symbol")
        if (type(row.get("compiler_name")) is not str or not row["compiler_name"].strip()
                or len(row["compiler_name"]) > 16384
                or type(row.get("compiler_expansion")) is not bool or type(row.get("emitted")) is not bool
                or type(symbol) is not str or len(symbol) > 16384 or row["emitted"] != bool(symbol)
                or symbol and not symbol.strip()):
            raise ValueError("Rust frontend compiler definition is malformed")
        if symbol and symbol in symbols:
            raise ValueError("Rust frontend compiled symbols are not unique")
        if symbol:
            symbols.add(symbol)


def rust_frontend_function(declaration: dict, resolved: dict, name: str, identity: str) -> None:
    """Bind one supported ordinary callable to its exact emitted compiler instance."""
    compiler_name = declaration["compiler_name"].replace("::", ".").replace("r#", "")
    if (name != identity + "." + compiler_name or declaration["compiler_expansion"]
            or not declaration["emitted"] or declaration["compiled_symbol"] != resolved["compiled_symbol"]):
        raise ValueError("Rust frontend expansion, compiler name or emitted symbol differs")


def rust_frontend_records(inventory: dict, resolved: dict, identity: str) -> dict:
    """Require a bijection between this caller's target/startup and their resolved symbols."""
    rust_frontend_rows(inventory)
    symbols = [row["compiled_symbol"] for row in resolved["functions"] if row["selected"] or row["startup"]]
    if len(resolved["functions"]) != 2 or len(set(symbols)) != 2:
        raise ValueError("Rust frontend resolution has unexpected or duplicate instances")
    actual = {row["compiled_symbol"]: row for row in resolved["functions"]}
    selected = None
    for row in inventory["functions"]:
        if row["selected"] or row["startup"]:
            match = actual.get(row["compiled_symbol"])
            if match is None or (row["selected"], row["startup"]) != (match["selected"], match["startup"]):
                raise ValueError("Rust frontend compiled instance does not match its resolved role")
            rust_frontend_function(row, match, row["name"], identity)
            if row["selected"]:
                selected = row["compiler_name"]
    return {"selected_compiler_name": selected, "compiler_expansion": False}


def rust_llvm_records(inventory: dict, resolved: dict, workspace: Path, source: Path, expected_function: str,
                      scratch: Path, *, frontend: bool = False) -> dict:
    """Qualify this standalone entry and reject unsupported multi-source builds."""
    selected, startup = rust_llvm_rows(inventory, 3 if frontend else 2)
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
    provenance = {}
    if frontend:
        provenance = rust_frontend_records(inventory, resolved, main.removesuffix(".main"))
    elif any({"compiler_name", "compiler_expansion", "compiled_symbol", "emitted"} & row.keys()
             for row in inventory["functions"]):
        raise ValueError("Rust legacy inventory cannot carry frontend provenance")
    return {"selected_symbol": actual_selected[0]["compiled_symbol"], "selected_function": expected_function,
            "resolution_phase": resolved["phase"], **provenance}


def rust_llvm_manifest(root: Path, workspace: Path, source: Path, bundle: Path, metadata: dict,
                       tools: dict, assets: dict[str, Path], expected_function: str | None, environment: dict | None) -> dict:
    """Bind compiler hook evidence to fixed profile assets and the requested target."""
    if type(expected_function) is not str or not expected_function.strip():
        raise ValueError("Rust LLVM needs an explicit expected function identity")
    inventory = build_document(bundle / "inventory.json")
    resolved = build_document(bundle / "resolved.json")
    hook = metadata.get("compiler_hook")
    hashes = {"profile_sha256": file_digest(root / RUST_PROFILE_FILENAME),
              "plugin_sha256": file_digest(assets["plugin"]),
              "inventory_sha256": file_digest(bundle / "inventory.json"),
              "resolved_sha256": file_digest(bundle / "resolved.json")}
    if not isinstance(hook, dict) or hook != hashes:
        raise ValueError("Rust LLVM profile, plugin or compiler evidence identity differs")
    plan = build_document(bundle / PLAN_FILENAME)
    if (type(plan.get("schema_version")) is not int or plan["schema_version"] != 2
            or plan.get("backend") != "llvm" or plan.get("language") != "rust"
            or plan.get("functions") != {"include": [expected_function], "exclude": []}
            or plan.get("sources") != {"include": [source.relative_to(workspace).as_posix()], "exclude": []}
            or plan.get("execution_available") is not True or plan.get("unavailable") != []):
        raise ValueError("Rust LLVM retained selection plan differs from the requested entry")
    scratch = rust_llvm_compiler(metadata["compiler"], source, workspace, tools, assets, environment)
    records = rust_llvm_records(inventory, resolved, workspace, source, expected_function, scratch,
                                frontend="frontend" in assets)
    frontend = {"frontend_sha256": file_digest(assets["frontend"])} if "frontend" in assets else {}
    return {"backend": "llvm", "compiler_hook": hashes, **frontend, **records}


def rust_manifest(root: Path, workspace: Path, source: Path, bundle: Path, tools: dict[str, Path], *,
                  backend: str = "compiler", expected_function: str | tuple[str, ...] | None = None,
                  environment: dict | None = None, requested_selection: dict | None = None,
                  future_functions: tuple[str, ...] = ()) -> dict:
    """Verify all source/build/provider hashes using only caller-selected paths."""
    metadata = rust_metadata(bundle, backend)
    if backend == "compiler":
        profile_path = root / RUST_COMPILER_PROFILE_FILENAME
        if (profile_path.exists() or profile_path.is_symlink()) != (metadata["schema_version"] == 3):
            raise ValueError("Rust compiler profile and manifest versions require separate qualification")
    compiler = rust_compiler(metadata, tools, backend)
    assets = rust_profile(root, tools) if backend == "llvm" else None
    expected = {"executable_sha256": file_digest(bundle / "application"),
                "plan_sha256": file_digest(bundle / PLAN_FILENAME),
                "source_sha256": file_digest(source),
                "sdk_sha256": file_digest(assets["sdk"] if assets else root / "target/debug/libquux_otelc_rust.rlib"),
                "adapter_sha256": file_digest(root / "target/debug/otelc-rust-adapter")}
    if (any(metadata.get(key) != value for key, value in expected.items())
            or metadata.get("source") != str(source.resolve())
            or metadata.get("source_root") != str(workspace.resolve())):
        raise ValueError("Rust build source, executable, policy or provider identity changed")
    hook = rust_llvm_manifest(root, workspace, source, bundle, metadata, tools, assets, expected_function, environment) if assets else {}
    if backend == "compiler" and metadata["schema_version"] == 3:
        from otelc_rust_build import validate
        hook = validate(root, workspace, source, bundle, metadata, tools, expected_function, environment,
                        requested_selection, future_functions)
    return {**expected, "manifest_sha256": file_digest(bundle / BUILD_FILENAME),
            "baseline_flags": list(rust_flags(backend)), "compiler": compiler, **hook}


def rust_command(root, workspace, source, policy, tools, environment, evidence, output, lane, *,
                 backend="compiler", expected_function=None, future_functions=()):
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
        requested = None
        if backend == "compiler" and (root / RUST_COMPILER_PROFILE_FILENAME).exists():
            configured = tomllib.loads(policy.read_text())
            requested = {key: {"include": configured[key]["include"], "exclude": configured[key].get("exclude", [])}
                         for key in ("sources", "functions")}
        identities = rust_manifest(root, workspace, source, bundle, tools, backend=backend,
                                   expected_function=expected_function, environment=environment,
                                   requested_selection=requested, future_functions=future_functions)
        command = prefix + ["rust", "--run", bundle]
    (evidence / (lane + "-build-identities.json")).write_text(json.dumps(identities, indent=2) + "\n")
    return command


GO_COMPILER_ENV = ("GOVERSION", "GOROOT", "GOTOOLDIR", "GOOS", "GOARCH", "GOAMD64", "GOARM64",
                   "GOEXPERIMENT", "GOFLAGS", "CGO_ENABLED", "GOWORK")
GO_REQUIRED_FILES = {"baseline", "application", PLAN_FILENAME, RECIPE_FILENAME, "baseline.mod", GO_MODULE_FILENAME,
                     "overlay.json", "modules-original.json", "modules-instrumented.json",
                     "baseline-build.stdout", "baseline-build.stderr", "baseline-build.status",
                     "instrumented-build.stdout", "instrumented-build.stderr", "instrumented-build.status"}


def go_require(condition: bool, reason: str) -> None:
    """Incomplete build evidence cannot select an application launch."""
    if not condition:
        raise ValueError("Go build evidence: " + reason)


def go_compiler(workspace: Path, tools: dict, environment: dict, evidence: Path) -> dict:
    """Obtain provenance from the selected compiler, never a metadata-selected tool."""
    result = execute([tools["go"], "env", "-json", *GO_COMPILER_ENV], workspace, environment)
    (evidence / "go-compiler.stdout").write_bytes(result.stdout)
    (evidence / "go-compiler.stderr").write_bytes(result.stderr)
    go_require(result.returncode == 0, "selected compiler environment failed")
    selected = strict_json(result.stdout)
    go_require(type(selected) is dict and set(selected) == set(GO_COMPILER_ENV), "compiler environment fields differ")
    go_require(all(type(value) is str for value in selected.values()), "invalid compiler environment")
    directory = Path(selected["GOTOOLDIR"])
    go_require(directory.is_absolute() and bool(selected["GOVERSION"]), "missing compiler tool/version identity")
    return {"program": str(tools["go"].resolve()), "sha256": file_digest(tools["go"]),
            "version": selected["GOVERSION"], "environment": selected,
            "tools": {str(directory / name): file_digest(directory / name) for name in ("compile", "asm", "link")}}


def go_bundle_file(bundle: Path, name: str, expected: str) -> None:
    """Read bounded regular bundle files; names never become launch arguments."""
    go_require(type(name) is str and 0 < len(name) <= 200 and name not in (".", "..", BUILD_FILENAME)
               and not any(char in name for char in ("/", "\\", "\x00")), "unsafe bundle file name")
    go_require(type(expected) is str and re.fullmatch("[0-9a-f]{64}", expected), "invalid bundle file digest")
    path = bundle / name
    go_require(not path.is_symlink() and path.is_file(), "bundle needs regular files")
    limit = 256 * 1024 * 1024 if name in ("baseline", "application") else 4 * 1024 * 1024
    go_require(path.stat().st_size <= limit, "bundle file exceeds size limit")
    go_require(file_digest(path) == expected, "bundle file changed: " + name)


def go_files(root: Path, bundle: Path) -> dict:
    """Check the fixed versioned manifest and retain both executable identities."""
    metadata = build_document(bundle / BUILD_FILENAME)
    go_require(set(metadata) == {"schema_version", "language", "backend", "adapter_sha256", "files"}, "manifest fields differ")
    go_require(type(metadata["schema_version"]) is int and metadata["schema_version"] == 1
               and metadata["language"] == "go" and metadata["backend"] == "compile", "unsupported manifest schema/backend")
    go_require(metadata["adapter_sha256"] == file_digest(root / "adapters/go/build/otelc-go"), "adapter identity differs")
    files = metadata["files"]
    go_require(type(files) is dict and GO_REQUIRED_FILES <= set(files) and len(files) <= 65536, "incomplete bundle inventory")
    go_require({path.name for path in bundle.iterdir()} == set(files) | {BUILD_FILENAME}, "unlisted bundle contents")
    for name, expected in files.items():
        go_bundle_file(bundle, name, expected)
    for lane in ("baseline", "instrumented"):
        go_require((bundle / (lane + "-build.status")).read_bytes() == b"0\n", "compiler build did not succeed")
    return metadata


def go_inputs(recipe: dict, original: dict, root: Path) -> None:
    """Bind loaded source/dependency inputs while the private build source exists."""
    inputs = recipe.get("inputs")
    go_require(type(inputs) is dict and 0 < len(inputs) <= 65536, "missing source/dependency inputs")
    required = dict(original)
    for name in (GO_MODULE_FILENAME, "go.sum", "policy/policy.go"):
        path = root / GO_ADAPTER_DIRECTORY / name
        required[str(path.resolve())] = file_digest(path)
    go_require(all(inputs.get(name) == {"sha256": expected} for name, expected in required.items()), "source or SDK input binding differs")
    for name, identity in inputs.items():
        go_require(type(name) is str and Path(name).is_absolute() and type(identity) is dict, "invalid input identity")
        path = Path(name)
        if identity == {"absent": True} and type(identity["absent"]) is bool:
            go_require(not path.exists() and not path.is_symlink(), "previously absent input appeared")
        else:
            expected = identity.get("sha256")
            go_require(set(identity) == {"sha256"} and type(expected) is str
                       and re.fullmatch("[0-9a-f]{64}", expected), "invalid input digest")
            go_require(path.is_file() and not path.is_symlink() and path.stat().st_size <= 256 * 1024 * 1024
                       and file_digest(path) == expected, "loaded input changed or exceeds limit: " + name)


def go_recipe(root: Path, request: dict, bundle: Path, compiler: dict, original: dict) -> dict:
    """Cross-check recipe identity; paths/flags in evidence never select execution."""
    recipe = build_document(bundle / RECIPE_FILENAME)
    go_require(type(recipe.get("schema_version")) is int and recipe["schema_version"] == 1, "unsupported recipe schema")
    source = request["target"].resolve()
    go_require(recipe.get("source_root") == str(request["workspace"].resolve())
               and recipe.get("target") == str(source)
               and recipe.get("sdk_root") == str((root / GO_ADAPTER_DIRECTORY).resolve()), "source/root/SDK binding differs")
    go_require(recipe.get("compiler") == compiler, "selected compiler provenance differs")
    baseline = recipe.get("baseline_argv")
    go_require(type(baseline) is list and len(baseline) == 6 and all(type(arg) is str for arg in baseline), "missing compiler recipe")
    private = Path(baseline[4]).parent
    go_require(private.is_absolute(), "compiler output provenance must be absolute")
    go_require(baseline == ["build", "-mod=readonly", "-modfile=" + str(private / "baseline.mod"), "-o", str(private / "baseline"), str(source.resolve())], "baseline compiler flags differ")
    go_require(recipe.get("instrumented_argv") == ["build", "-mod=mod", "-modfile=" + str(private / GO_MODULE_FILENAME), "-overlay=" + str(private / "overlay.json"), "-o", str(private / "application"), str(source.resolve())], "instrumented compiler flags differ")
    go_inputs(recipe, original, root)
    for name in ("baseline_build_info", "instrumented_build_info"):
        info = recipe.get(name)
        go_require(type(info) is dict and info.get("GoVersion") == compiler["version"], "missing embedded compiler identity")
    return recipe


def go_plan(bundle: Path, requested: dict) -> None:
    """Bind the resolved selection and build-time tracing to the caller's policy."""
    resolved = build_document(bundle / PLAN_FILENAME)
    go_require(type(resolved.get("schema_version")) is int and resolved["schema_version"] == 2
               and resolved.get("language") == "go" and resolved.get("backend") == "compile", "resolved policy is unsupported")
    for section in ("sources", "functions"):
        expected = {key: requested.get(section, {}).get(key, []) for key in ("include", "exclude")}
        go_require(resolved.get(section) == expected, "resolved " + section + " selection differs")
    annotations = {key: requested.get("annotations", {}).get(key, False) for key in ("read_existing", "inject_generated")}
    go_require(resolved.get("annotations") == annotations, "resolved annotations differ")
    traces = resolved.get("traces")
    go_require(type(traces) is dict and traces.get("enabled") == requested.get("traces", {}).get("enabled", False), "trace weaving differs")


def go_graphs(root: Path, bundle: Path) -> None:
    """Require real module denominators, not two matching empty snapshots."""
    graphs = [build_document(bundle / name) for name in ("modules-original.json", "modules-instrumented.json")]
    mains = []
    for graph in graphs:
        modules = graph.get("Modules")
        go_require(type(modules) is dict and bool(modules) and type(graph.get("Settings")) is dict, "empty or invalid module graph")
        go_require(type(graph["Settings"].get("Go")) is str and bool(graph["Settings"]["Go"]), "missing module language identity")
        go_require(all(type(record) is dict and record.get("Path") == name for name, record in modules.items()), "inconsistent module identities")
        main = [name for name, record in modules.items() if record.get("Main") is True]
        go_require(len(main) == 1, "module graph requires one main module")
        mains.append(main[0])
    go_require(mains[0] == mains[1] and graphs[0]["Settings"] == graphs[1]["Settings"], "module or language defaults changed")
    sdk = graphs[1]["Modules"].get("io.quux.otelc/go", {})
    replacement = sdk.get("Replace") if type(sdk) is dict else None
    go_require(type(replacement) is dict and replacement.get("Path") == str((root / GO_ADAPTER_DIRECTORY).resolve())
               and replacement.get("ModHash") == file_digest(root / "adapters/go/go.mod"), "SDK module replacement differs")


def go_caches(root: Path, workspace: Path, environment: dict, evidence: Path) -> None:
    """Keep reused caches outside source/provider trees and refuse redirected roots."""
    cache = evidence.parent / "go-cache"
    for variable, name in (("GOCACHE", "build"), ("GOMODCACHE", "modules")):
        environment.setdefault(variable, str(cache / name))
        path = Path(environment[variable])
        go_require(path.is_absolute() and path.resolve() == path and not path.is_symlink(), "cache location is linked or noncanonical")
        go_require(not path.is_relative_to(workspace.resolve()) and not path.is_relative_to(root.resolve()), "cache must be outside application/provider sources")
        go_require(not path.exists() or path.is_dir(), "cache location must be a directory")
    environment["GOTOOLCHAIN"] = "local"


def go_dependency_identity(recipe: dict, compiler: dict, workspace: Path, evidence: Path) -> str:
    """Different compiler/dependency bytes between attempts invalidate the experiment."""
    inputs = {str(Path(name).resolve()): identity for name, identity in recipe["inputs"].items()
              if not Path(name).resolve().is_relative_to(workspace.resolve())}
    fingerprint = digest(json.dumps({"compiler": compiler, "inputs": inputs}, sort_keys=True).encode())
    marker = evidence.parent / "go-input-identity.json"
    if marker.exists() or marker.is_symlink():
        go_require(build_document(marker) == {"sha256": fingerprint}, "compiler or dependency inputs changed between attempts")
    else:
        marker.write_text(json.dumps({"sha256": fingerprint}) + "\n")
    return fingerprint


def go_commands(root, request, policy, tools, environment, evidence):
    """Build and retain one matched pair; both returned launches are compiler-free."""
    workspace, source, project = request["workspace"], request["target"], request["project"]
    go_require(workspace.resolve().is_relative_to(project.resolve()) and source.resolve().is_relative_to(workspace.resolve()),
               "requested module and target must remain inside the private project")
    go_require(bool(request["sources"]) and all(path.resolve().is_relative_to(project.resolve())
               and path.is_file() and not path.is_symlink() for path in request["sources"]), "invalid requested source inputs")
    go_caches(root, project, environment, evidence)
    compiler = go_compiler(workspace, tools, environment, evidence)
    original = {str(path.resolve()): file_digest(path) for path in request["sources"]}
    policy_bytes = policy.read_bytes()
    bundle = evidence / "go-bundle"
    prefix = [root / OTELC_CLI_PATH, "--config", policy, "--language", "go"]
    build(prefix + ["go", "--build", source.resolve(), "--output-dir", bundle], workspace, environment, evidence / "go-build.log")
    metadata = go_files(root, bundle)
    recipe = go_recipe(root, request, bundle, compiler, original)
    go_require(policy.read_bytes() == policy_bytes, "requested policy changed during compilation")
    go_plan(bundle, tomllib.loads(policy_bytes.decode()))
    go_graphs(root, bundle)
    dependencies = go_dependency_identity(recipe, compiler, project, evidence)
    identities = {"baseline": metadata["files"]["baseline"], "application": metadata["files"]["application"],
                  "manifest_sha256": file_digest(bundle / BUILD_FILENAME), "recipe_sha256": file_digest(bundle / RECIPE_FILENAME),
                  "plan_sha256": metadata["files"][PLAN_FILENAME], "compiler": compiler, "source_inputs": original,
                  "policy_sha256": digest(policy_bytes), "loaded_input_count": len(recipe["inputs"]),
                  "dependency_sha256": dependencies}
    (evidence / "go-build-identities.json").write_text(json.dumps(identities, indent=2) + "\n")
    return prefix + ["go", "--run-baseline", bundle], prefix + ["go", "--run", bundle]


def native_flags(language: str) -> list[str]:
    """Inventory and paired native builds share language mode and feature macros."""
    return ["-O2", "-pthread", "-std=c++17"] if language == "cpp" else ["-O1", "-pthread"]


def commands(root, workspace, language, source, policy, tools, environment, evidence, *,
             expected_functions=None, future_functions=()):
    prefix = [root / OTELC_CLI_PATH, "--config", policy, "--language", language]
    if language in ("c", "cpp"):
        tool = "clang++" if language == "cpp" else "clang"
        flags = native_flags(language)
        plain, instrumented = workspace / "plain", workspace / "instrumented"
        build([tools[tool], *flags, source, "-o", plain], workspace, environment, evidence / "plain-build.log")
        build(prefix + [tool, *flags, source, "-o", instrumented], workspace, environment, evidence / "instrumented-build.log")
        return [plain], prefix + ["run", instrumented]
    if language == "rust":
        return tuple(rust_command(root, workspace, source, policy, tools, environment, evidence, workspace, lane,
                                  expected_function=expected_functions, future_functions=future_functions)
                     for lane in ("baseline", "instrumented_on"))
    if language == "go":
        request = {"workspace": workspace, "target": source, "sources": [source], "project": workspace}
        return go_commands(root, request, policy, tools, environment, evidence)
    interpreter = tools[language]
    plain = [interpreter, source]
    if language == "java":
        plain = [interpreter, "-Xshare:off", source]
    elif language == "typescript":
        plain = [interpreter, "--import", root / "adapters/node/plain.mjs", source]
    adapter = {"javascript": "node", "typescript": "ts"}.get(language, language)
    arguments = ["-Xshare:off", source] if language == "java" else [source]
    return plain, prefix + [adapter, *arguments]


@contextmanager
def receiver(*, max_requests=MAX_REQUESTS, max_bytes=MAX_CAPTURE_BYTES):
    """Expose exact received bytes and every transport failure to the observer."""
    server = CaptureServer(max_requests, max_bytes=max_bytes)
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


def rust_future_health(report: dict) -> None:
    """The MIR registry must finish even when trace counters appear drained."""
    future = report.get("future_observers")
    if (type(future) is not dict or set(future) != {"pending", "admission_exhausted"}
            or type(future["pending"]) is not int or future["pending"] != 0
            or future["admission_exhausted"] is not False):
        raise ValueError("Rust compiler future observers are missing, pending or exhausted")


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
    if len(selected) != 1 or language not in ("python", "javascript", "typescript") or language != "python" and kind != "collection":
        raise ValueError(f"{kind} qualification requires Python and a distinct workload")
    spans = [span for path, body in bodies if path == TRACE_PATH
             for span in service_spans(decoder.FromString(body), service)]
    if language in ("javascript", "typescript"):
        return otelc_collection.javascript(spans, report, spec[kind])
    verify = {"collection": otelc_collection.verify, "resource": otelc_resource.verify}[kind]
    if kind == "resource":
        otelc_resource.metric_values(bodies, service, spec[kind], otelc_resource.metric_decoder())
    return verify(spans, report, spec[kind]), spec[kind]["count"]


def witness(bodies, report, spec, service, decoder, language, *, allow_incomplete=False):
    require_runtime_identity(report, language)
    names, raw, roots, errors = decode(bodies, service, decoder)
    if names != spec["functions"] or roots != spec["trees"] or errors != spec["errors"]:
        raise ValueError("decoded telemetry does not match independent fixture expectations")
    losses, export = loss_diagnostics(report, language)
    lifetime_losses, lifetime_count = lifetime_diagnostics(bodies, report, spec, service, decoder, language)
    losses.update(lifetime_losses)
    function_calls = sum(names.values()) - lifetime_count
    if report.get("export_finished") is not True or report.get("drained", True) is not True:
        if not allow_incomplete:
            raise ValueError("missing or unfinished export status")
        losses["transport.unfinished"] = 1
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
    if traces.get("completed_trees") != roots:
        losses["runtime.completed_trees"] = 1
    if report.get("function_calls") != function_calls:
        losses["runtime.function_calls"] = 1
    if (any(losses.values()) or pending) and not allow_incomplete:
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
        tools = {compiler: selected}
        if language == "cpp":
            tools["cpp-demangler"] = tool_path(str(selected.parent / "llvm-cxxfilt"))
        return tools
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
