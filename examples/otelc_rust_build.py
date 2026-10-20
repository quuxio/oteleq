"""Bind original-source Rust compiler bundles to the caller's fixed recipe."""
from pathlib import Path

from otelc_capture import (RUST_BASELINE_FLAGS, RUST_COMPILER_PROFILE_FILENAME,
                           build_document, execute,
                           file_digest, rust_frontend_function,
                           rust_frontend_rows, rust_llvm_function,
                           rust_llvm_rows)


PROFILE_FILENAME = RUST_COMPILER_PROFILE_FILENAME
COMPILER_COMMIT = "48a229ceaefd4985c50990b14116b6d856af0985"
POLICY_FIELDS = {"language", "backend", "execution_available", "sources",
                 "functions", "annotations", "runtime", "metrics", "traces",
                 "trace_export", "export", "resource", "metrics_endpoint"}
REQUEST_FIELDS = {"schema_version", "root", "entry", "policy", "sources",
                  "declarations", "protected_source_roots", "discovery_argv"}
INSTANCE_FIELDS = {"compiler_name", "compiler_expansion", "compiled_symbol",
                   "emitted"}


def require(condition: bool, reason: str) -> None:
    """Refuse incomplete evidence before selecting an application launch."""
    if not condition:
        raise ValueError("Rust compiler evidence: " + reason)


def regular_digest(path: Path) -> str:
    """Caller-selected assets cannot redirect reads through symbolic links."""
    require(path.is_absolute() and path.resolve() == path and path.is_file()
            and not path.is_symlink(), "input must be a fixed regular file")
    return file_digest(path)


def profile(root: Path, tools: dict[str, Path]) -> tuple[dict, dict[str, Path]]:
    """Only fixed provider assets and the selected compiler may be used."""
    document = build_document(root / PROFILE_FILENAME, limit=65536)
    fields = {"schema_version", "backend", "commit_hash", "rustc", "sdk",
              "driver", "rustc_sha256", "sdk_sha256", "driver_sha256",
              "protected_source_roots"}
    require(set(document) == fields and type(document["schema_version"]) is int
            and document["schema_version"] == 1
            and document["backend"] == "compiler"
            and document["commit_hash"] == COMPILER_COMMIT,
            "unsupported original-source profile")
    assets = {"rustc": tools["rustc"],
              "sdk": root / "target/debug/libquux_otelc_rust.rlib",
              "driver": root / "target/debug/otelc-rust-mir"}
    for key, path in assets.items():
        require(document[key] == str(path)
                and document[key + "_sha256"] == regular_digest(path),
                "selected " + key + " path or bytes differ")
    protected = [str(root / "crates" / name)
                 for name in ("config", "export", "rust-probes")]
    require(document["protected_source_roots"] == protected,
            "protected provider source roots differ")
    return document, assets


def inputs(root: Path, tools: dict[str, Path]) -> list[Path]:
    """Freeze the profile, MIR driver and compiler-resolvable SDK products."""
    _, assets = profile(root, tools)
    dependencies = assets["sdk"].parent / "deps"
    require(dependencies.is_dir() and dependencies.resolve() == dependencies,
            "SDK dependency directory is missing or linked")
    paths = [root / PROFILE_FILENAME, assets["sdk"], assets["driver"]]
    paths += sorted(path for pattern in ("*.rlib", "*.rmeta", "*.dylib", "*.so", "*.dll")
                    for path in dependencies.glob(pattern))
    for path in paths:
        regular_digest(path)
    return paths


def recipe(compiler: dict, source: Path, workspace: Path,
           assets: dict[str, Path], environment: dict | None) -> list[str]:
    """Metadata describes the recipe; it cannot choose tools, flags or outputs."""
    require(type(environment) is dict and type(environment.get("TMPDIR")) is str
            and set(compiler) == {"program", "argv", "version"},
            "compiler context or provenance is incomplete")
    relative = source.relative_to(workspace).as_posix()
    dependencies = "dependency=" + str(assets["sdk"].parent / "deps")
    prefix = [relative, *RUST_BASELINE_FLAGS, "-o"]
    tail = ["-L", dependencies, "--sysroot", str(assets["rustc"].parent.parent),
            "--extern", "quux_otelc_rust=" + str(assets["sdk"]),
            "-L", dependencies]
    argv = compiler["argv"]
    require(len(argv) == len(prefix) + 1 + len(tail)
            and argv[:len(prefix)] == prefix and argv[len(prefix) + 1:] == tail,
            "compiler arguments differ from the matched recipe")
    output = Path(argv[len(prefix)])
    require(output.is_absolute() and output.name == "application"
            and output.parent.parent == Path(environment["TMPDIR"]).resolve()
            and ".." not in output.parts,
            "compiler output is outside the caller scratch directory")
    actual = execute([assets["rustc"], "-vV"], workspace, environment, timeout=30)
    require(actual.returncode == 0 and len(actual.stdout) <= 32768 and not actual.stderr,
            "selected compiler version query failed")
    version = actual.stdout.decode("utf-8").strip()
    require(compiler["program"] == str(assets["rustc"])
            and compiler["version"] == version
            and version.startswith("rustc 1.98.1 ")
            and {"commit-hash: " + COMPILER_COMMIT, "host: aarch64-apple-darwin",
                 "LLVM version: 22.1.8"} <= set(version.splitlines()),
            "selected compiler version differs from the qualified profile")
    discovery = [relative, *RUST_BASELINE_FLAGS, "-L", dependencies,
                 "--emit=dep-info=" + str(output.parent / "original.d")]
    return discovery


def selection(plan: dict, source: Path, workspace: Path, function: str) -> None:
    """A diagnostic bundle selects one requested callable in the original file."""
    relative = source.relative_to(workspace).as_posix()
    require(type(plan.get("schema_version")) is int and plan["schema_version"] == 2
            and plan.get("language") == "rust" and plan.get("backend") == "compiler"
            and plan.get("execution_available") is True and plan.get("unavailable") == []
            and plan.get("functions") == {"include": [function], "exclude": []}
            and plan.get("sources") in ({"include": [relative], "exclude": []},
                                        {"include": ["**"], "exclude": []})
            and POLICY_FIELDS <= plan.keys(),
            "retained plan differs from the requested standalone selection")


def records(request: dict, inventory: dict, plan: dict, descriptor: dict,
            workspace: Path, source: Path, function: str, discovery: list[str]) -> dict:
    """Bind the compiler request and both emitted roles to original source."""
    sources = {str(source.resolve()): regular_digest(source.resolve())}
    require(set(request) == REQUEST_FIELDS and type(request["schema_version"]) is int
            and request["schema_version"] == 1 and request["root"] == str(workspace.resolve())
            and request["entry"] == str(source.resolve()) and request["sources"] == sources
            and request["policy"] == {key: plan[key] for key in POLICY_FIELDS}
            and request["protected_source_roots"] == descriptor["protected_source_roots"]
            and request["discovery_argv"] == discovery,
            "request source, policy or discovery binding differs")
    require(set(inventory) == {"schema_version", "functions", "sources", "discovery_argv"}
            and inventory["sources"] == sources and inventory["discovery_argv"] == discovery,
            "compiler inventory source or discovery binding differs")
    selected, startup = rust_llvm_rows(inventory, 3)
    rust_frontend_rows(inventory)
    declarations = request["declarations"]
    require(type(declarations) is list and 0 < len(declarations) <= 65536
            and all(type(row) is dict for row in declarations),
            "request declarations are missing or exceed their bound")
    identity = str(source.relative_to(workspace).with_suffix("")).replace("/", ".")
    for row, name in ((selected[0], function), (startup[0], identity + ".main")):
        original = {key: value for key, value in row.items() if key not in INSTANCE_FIELDS}
        require(sum(item == original for item in declarations) == 1,
                "emitted callable lacks one exact original declaration")
        rust_llvm_function(original, {**row, "kind": "function", "source_sha256": sources[str(source.resolve())]}, source, name)
        rust_frontend_function(row, row, name, identity)
    require(selected[0]["compiled_symbol"] != startup[0]["compiled_symbol"],
            "target and startup cannot share an emitted symbol")
    return {"selected_function": function, "selected_symbol": selected[0]["compiled_symbol"],
            "selected_compiler_name": selected[0]["compiler_name"], "compiler_expansion": False,
            "resolution_phase": "mir", "loaded_sources": sources}


def validate(root: Path, workspace: Path, source: Path, bundle: Path, metadata: dict,
             tools: dict[str, Path], function: str | None, environment: dict | None) -> dict:
    """Verify schema3 without relaxing legacy compiler or LLVM evidence contracts."""
    require(type(function) is str and bool(function.strip()),
            "an explicit expected callable identity is required")
    descriptor, assets = profile(root, tools)
    retained = build_document(bundle / "profile.json", limit=65536)
    hashes = {"profile_sha256": regular_digest(root / PROFILE_FILENAME),
              "driver_sha256": regular_digest(assets["driver"]),
              "request_sha256": regular_digest(bundle / "compiler-request.json"),
              "inventory_sha256": regular_digest(bundle / "inventory.json")}
    require(metadata.get("compiler_driver") == hashes and retained == descriptor
            and regular_digest(bundle / "profile.json") == hashes["profile_sha256"],
            "retained profile, driver or compiler evidence identity differs")
    discovery = recipe(metadata["compiler"], source, workspace, assets, environment)
    plan = build_document(bundle / "plan.json")
    selection(plan, source, workspace, function)
    request = build_document(bundle / "compiler-request.json", limit=8 * 1024 * 1024)
    inventory = build_document(bundle / "inventory.json")
    observed = records(request, inventory, plan, descriptor, workspace, source, function, discovery)
    return {"backend": "compiler", "compiler_driver": hashes, **observed}
