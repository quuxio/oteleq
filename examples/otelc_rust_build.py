"""Bind original-source Rust compiler bundles to the caller's fixed recipe."""
from collections import Counter
from pathlib import Path

from otelc_capture import (RUST_BASELINE_FLAGS, RUST_COMPILER_PROFILE_FILENAME,
                           build_document, execute,
                           file_digest, rust_frontend_function,
                           rust_frontend_rows, rust_llvm_function)


PROFILE_FILENAME = RUST_COMPILER_PROFILE_FILENAME
COMPILER_COMMIT = "48a229ceaefd4985c50990b14116b6d856af0985"
POLICY_FIELDS = {"language", "backend", "execution_available", "sources",
                 "functions", "annotations", "runtime", "metrics", "traces",
                 "trace_export", "export", "resource", "metrics_endpoint"}
REQUEST_FIELDS = {"schema_version", "root", "entry", "policy", "sources",
                  "declarations", "protected_source_roots", "discovery_argv"}
INSTANCE_FIELDS = {"compiler_name", "compiler_expansion", "compiled_symbol",
                   "emitted"}
ASYNC_UNSUPPORTED = "async compiler bodies require future-completion qualification"


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


def selection(plan: dict, source: Path, workspace: Path, functions: tuple[str, ...],
              requested: dict | None) -> None:
    """Freeze caller-owned selectors alongside the exact expected emitted set."""
    relative = source.relative_to(workspace).as_posix()
    if requested is None:
        requested = {"functions": {"include": list(functions), "exclude": []},
                     "sources": plan.get("sources")}
        require(requested["sources"] in ({"include": [relative], "exclude": []},
                                          {"include": ["**"], "exclude": []}),
                "standalone source selection differs")
    require(type(plan.get("schema_version")) is int and plan["schema_version"] == 2
            and plan.get("language") == "rust" and plan.get("backend") == "compiler"
            and plan.get("execution_available") is True and plan.get("unavailable") == []
            and set(requested) == {"functions", "sources"}
            and all(plan.get(key) == value for key, value in requested.items())
            and POLICY_FIELDS <= plan.keys(),
            "retained plan differs from the requested standalone selection")


def emitted_roles(inventory: dict, functions: tuple[str, ...],
                  futures: tuple[str, ...] = ()) -> tuple[list[dict], dict]:
    """Bind ordinary instances and all constructor/poll symbols of fixed futures."""
    rows = inventory.get("functions")
    require(type(inventory.get("schema_version")) is int and inventory["schema_version"] == 3
            and type(rows) is list and len(rows) <= 65536
            and all(type(row) is dict and type(row.get("selected")) is bool
                    and type(row.get("startup")) is bool for row in rows),
            "compiler inventory roles are malformed")
    selected = [row for row in rows if row["selected"]]
    startup = [row for row in rows if row["startup"]]
    require(all(type(row.get("name")) is str for row in selected), "selected owner names are malformed")
    counts, future_names = Counter(row["name"] for row in selected), set(futures)
    require(len(startup) == 1 and not startup[0]["selected"]
            and not any(row["startup"] for row in selected) and set(counts) == set(functions)
            and all(count == 1 for name, count in counts.items() if name not in future_names),
            "expected target set or independent startup differs")
    rust_frontend_rows(inventory)
    return selected, startup[0]


def bind_declarations(request: dict, selected: list[dict], startup: dict, source: Path,
                      workspace: Path, source_sha256: str, futures: tuple[str, ...]) -> None:
    """Bind original declaration records, including explicitly curated futures."""
    declarations = request["declarations"]
    require(type(declarations) is list and 0 < len(declarations) <= 65536
            and all(type(row) is dict for row in declarations),
            "request declarations are missing or exceed their bound")
    identity = str(source.relative_to(workspace).with_suffix("")).replace("/", ".")
    for row in [*selected, startup]:
        name = identity + ".main" if row["startup"] else row["name"]
        original = {key: value for key, value in row.items() if key not in INSTANCE_FIELDS}
        candidates = declarations
        if name in futures:
            candidates = [{**item, "unsupported": ""} for item in declarations
                          if item.get("name") == name and item.get("unsupported") == ASYNC_UNSUPPORTED]
        require(sum(item == original for item in candidates) == 1,
                "emitted callable lacks one exact original declaration")
        rust_llvm_function(original, {**row, "kind": "function", "source_sha256": source_sha256}, source, name)
        rust_frontend_function(row, row, name, identity)


def records(request: dict, inventory: dict, plan: dict, descriptor: dict,
            workspace: Path, source: Path, functions: tuple[str, ...], discovery: list[str],
            futures: tuple[str, ...]) -> dict:
    """Bind the compiler request and emitted roles to the original source."""
    source_sha256 = regular_digest(source.resolve())
    sources = {str(source.resolve()): source_sha256}
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
    selected, startup = emitted_roles(inventory, functions, futures)
    bind_declarations(request, selected, startup, source, workspace, source_sha256, futures)
    common = {"compiler_expansion": False, "resolution_phase": "mir", "loaded_sources": sources}
    if len(selected) == 1 and not futures:
        return {"selected_function": selected[0]["name"], "selected_symbol": selected[0]["compiled_symbol"],
                "selected_compiler_name": selected[0]["compiler_name"], **common}
    symbols = {name: [] for name in functions}
    for row in selected:
        symbols[row["name"]].append(row["compiled_symbol"])
    return {"selected_functions": sorted(functions), "selected_symbols": symbols, **common}


def validate(root: Path, workspace: Path, source: Path, bundle: Path, metadata: dict,
             tools: dict[str, Path], function: str | tuple[str, ...] | None, environment: dict | None,
             requested: dict | None = None, futures: tuple[str, ...] = ()) -> dict:
    """Verify schema3 without relaxing legacy compiler or LLVM evidence contracts."""
    functions = (function,) if type(function) is str else function
    require(type(functions) is tuple and 0 < len(functions) <= 65536
            and all(type(name) is str and 0 < len(name) <= 1024 and bool(name.strip()) for name in functions)
            and len(set(functions)) == len(functions),
            "an explicit unique expected callable set is required")
    require(type(futures) is tuple and all(type(name) is str for name in futures)
            and len(set(futures)) == len(futures) and set(futures) <= set(functions),
            "fixed future declarations differ from the expected callable set")
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
    selection(plan, source, workspace, functions, requested)
    request = build_document(bundle / "compiler-request.json", limit=8 * 1024 * 1024)
    inventory = build_document(bundle / "inventory.json")
    observed = records(request, inventory, plan, descriptor, workspace, source, functions, discovery, futures)
    return {"backend": "compiler", "compiler_driver": hashes, **observed}
