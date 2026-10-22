"""Explicit rebuilt Node policy and complete installed-provider identities."""

import hashlib
import json
import os
from pathlib import Path
import stat
from typing import Callable
from typing import Any

import otelc_capture as capture
import sequences

SOURCE = "source-v1"
LANGUAGES = {"javascript", "typescript"}
SDK_LANGUAGES = {"c", "cpp", "rust", "python", "java", "javascript", "typescript", "go"}
MAX_METADATA = 256 * 1024
DIRECTORY = "node-source-provider"
PROTOCOLS = {"schema_version": 1, "kind": "otelc.node.protocols", "source": 5,
             "execution": 1, "request": 1, "preload": 1, "sdk": 1}


def require(condition: bool, reason: str) -> None:
    """Missing source-profile evidence cannot select the legacy launcher."""
    if not condition:
        raise ValueError("Node source provider: " + reason)


def settings(value: Any) -> dict[str, str]:
    """Keep provider choice separate from the legacy TypeScript emitter setting."""
    require(type(value) is dict and not set(value) - {"backend", "typescript_compiler"},
            "adapters.node accepts backend and typescript_compiler")
    backend = value.get("backend", "legacy")
    require(type(backend) is str and backend in ("legacy", SOURCE),
            "adapters.node.backend must be legacy or source-v1")
    if backend == "legacy":
        require("typescript_compiler" not in value,
                "typescript_compiler requires adapters.node.backend = source-v1")
        return {"backend": backend}
    compiler = value.get("typescript_compiler", "native")
    require(type(compiler) is str and compiler in ("native", "api"),
            "adapters.node.typescript_compiler must be native or api")
    return {"backend": backend, "typescript_compiler": compiler}


def enabled(entry: dict) -> bool:
    """Only an explicit Node entry uses the rebuilt source contract."""
    return entry.get("language") in LANGUAGES and entry.get("node_backend") == SOURCE


def configuration(entry: dict, endpoint: str, service: str) -> dict:
    """Request every common schema-3 field without relying on SDK defaults."""
    require(enabled(entry), "explicit source-v1 entry required")
    functions = [entry["otelc_function"]]
    creator = sequences.creator(entry)
    if creator is not None:
        functions.append(creator)
    collecting = sequences.collects(entry)
    return {"schema_version": 3, "languages": [entry["language"]],
            "resource": {"service_name": service},
            "export": {"endpoint": endpoint, "interval_ms": 1000, "timeout_ms": 1000,
                       "shutdown_timeout_ms": 10000},
            "sources": {"include": [entry["path"]], "exclude": []},
            "functions": {"include": functions, "exclude": []},
            "metrics": {"collection": True, "emission": True,
                        "histogram_boundaries_seconds": [1e-6, 1e-5, 1e-4, .001, .01, .1, 1.]},
            "traces": {"enabled": True, "sample_ratio": 1.0},
            "lifetimes": {"enabled": collecting, "include": [entry["node_class_label"]] if collecting else [], "exclude": [],
                          "max_live": 4096, "release_methods": []},
            "context": {"tasks": False, "http": False},
            "benchmark": {"iterations": 10000, "samples": 15, "warmup": 5}}


def policy(entry: dict, endpoint: str, service: str) -> str:
    """Encode the exact common request, retaining Unicode source identities."""
    data = configuration(entry, endpoint, service)
    result = 'schema_version = 3\nlanguages = ' + json.dumps(data["languages"]) + '\n'
    for section, values in data.items():
        if isinstance(values, dict):
            result += "[" + section + "]\n"
            result += "".join(key + " = " + json.dumps(value, ensure_ascii=False).replace("\x7f", "\\u007f") + "\n"
                              for key, value in values.items())
    return result


def verify_capabilities(value: Any, requested: dict, language: str) -> None:
    """Candidates are recorded declarations, never automatic adapter admission."""
    fields = {"policy", "implemented", "candidates", "remaining"}
    require(type(value) is dict and set(value) == fields and type(value["policy"]) is dict
            and json.dumps(value["policy"], sort_keys=True, allow_nan=False)
            == json.dumps(requested, sort_keys=True, allow_nan=False),
            "public plan differs from the complete common request")
    groups = {}
    for name in ("implemented", "candidates", "remaining"):
        items = value[name]
        require(type(items) is list and all(type(item) is str for item in items)
                and len(items) == len(set(items)) and set(items) <= SDK_LANGUAGES,
                "invalid public " + name + " language declarations")
        groups[name] = set(items)
    implemented, remaining = groups["implemented"], groups["remaining"]
    require(not implemented & remaining and implemented | remaining == SDK_LANGUAGES,
            "implemented/remaining must partition all eight languages")
    require(groups["candidates"] <= remaining, "candidates must remain unimplemented")
    require(language in LANGUAGES and language in implemented | groups["candidates"],
            "selected Node language has no public implementation or candidate declaration")


def provider_files(directory: Path, *, suffix: str | None = None) -> list[Path]:
    """Inventory installed source, dependencies and products without silent gaps."""
    require(directory.is_dir() and not directory.is_symlink(),
            "missing or linked provider directory: " + str(directory))
    result = []
    for current, directories, files in os.walk(directory, onerror=raise_walk_error):
        for name in directories:
            require(not (Path(current) / name).is_symlink(), "linked provider directory")
        result.extend(Path(current) / name for name in files if suffix is None or name.endswith(suffix))
    return sorted(result)


def raise_walk_error(error: OSError) -> None:
    """An unreadable tooling subtree is incomplete evidence."""
    raise error


def artefacts(root: Path, tools: dict[str, Path]) -> dict[str, str]:
    """Freeze bytes and literal file-link targets in the selected installed closure."""
    require(root.is_dir() and not root.is_symlink(), "provider root must be a real directory")
    paths = [root / "package.json", root / "package-lock.json"]
    paths += provider_files(root / "otelc", suffix=".py")
    paths += provider_files(root / "adapters/node/src")
    paths += provider_files(root / "node_modules")
    paths += provider_files(root / "build/tools")
    required = {"otelc/config.py", "otelc/node.py", "otelc/node_recipe.py",
                "otelc/node_provenance.py", "otelc/node_preloads.py",
                "adapters/node/src/source-bootstrap.ts", "adapters/node/src/plain-source-loader.ts"}
    require(required <= {path.relative_to(root).as_posix() for path in paths},
            "incomplete public source launcher")
    identities = {}
    for path in paths:
        name = path.relative_to(root).as_posix()
        metadata = path.lstat()
        require(stat.S_ISREG(metadata.st_mode) or stat.S_ISLNK(metadata.st_mode),
                "non-regular provider input: " + name)
        if stat.S_ISLNK(metadata.st_mode):
            require(path.resolve(strict=True).is_relative_to(root.resolve()),
                    "provider file link escapes the frozen closure: " + name)
            identities["link-target:" + name] = hashlib.sha256(os.fsencode(os.readlink(path))).hexdigest()
        identities[name] = capture.file_digest(path)
    require(any(name.startswith("build/tools/otelc_node_observer-") and name.endswith(".node")
                for name in identities), "missing prebuilt native observer")
    identities.update({"tool:" + name: capture.file_digest(path) for name, path in tools.items()})
    return identities


def bind(entry: dict, root: Path, workspace: Path, tools: dict, execute: Callable) -> None:
    """Probe complete public policy before any application process can start."""
    if entry["status"] != "ready" or not enabled(entry):
        return
    folder = workspace / DIRECTORY / "capabilities" / entry["id"]
    folder.mkdir(parents=True)
    endpoint, service = "http://127.0.0.1:4318", "oteleq-node-provider"
    text = policy(entry, endpoint, service)
    config = folder / "policy.toml"
    config.write_text(text, encoding="utf-8")
    command = [tools["python-host"], "-B", "-m", "otelc", "--config", config, "plan"]
    environment = capture.environment(workspace, tools, service, root)
    environment["PYTHONDONTWRITEBYTECODE"] = "1"
    try:
        protocols = probe_protocols(root, workspace, tools, execute)
        result = execute(command, root, environment, folder / "probe", max_output_bytes=MAX_METADATA)
        entry["node_provider"] = {"request": text, "command": list(map(str, command)),
                                  "status": result.returncode, "stdout": result.stdout.decode(), "stderr": result.stderr.decode()}
        require(result.returncode == 0, "public configuration probe failed")
        value = capture.strict_json(result.stdout)
        verify_capabilities(value, configuration(entry, endpoint, service), entry["language"])
        entry["node_provider"]["resolved"] = value
        entry["node_provider"]["protocols"] = protocols
    except (ValueError, OSError, KeyError) as error:
        entry["status"], entry["reason"] = "blocked", "Node source provider unavailable: " + str(error)


def verify_protocols(value: Any) -> None:
    """Only the requested closed source/execution protocol can launch this profile."""
    require(type(value) is dict and json.dumps(value, sort_keys=True, allow_nan=False) == json.dumps(PROTOCOLS, sort_keys=True),
            "public Node source/execution protocols are unavailable or unsupported")


def probe_protocols(root: Path, workspace: Path, tools: dict, execute: Callable) -> dict:
    """Probe once per frozen workspace; no Node process or application is prepared."""
    folder = workspace / DIRECTORY / "protocol"
    receipt = folder / "response.json"
    bootstrap = "import json,sys;sys.path.insert(0,sys.argv[1]);from otelc import node;print(json.dumps(node.protocols(),sort_keys=True))"
    command = [tools["python-host"], "-I", "-B", "-c", bootstrap, root]
    if receipt.exists():
        require(receipt.is_file() and not receipt.is_symlink() and receipt.stat().st_size <= MAX_METADATA,
                "invalid cached public protocol response")
        record = capture.strict_json(receipt.read_bytes())
    else:
        folder.mkdir(parents=True, exist_ok=False)
        environment = capture.environment(workspace, tools, "oteleq-node-protocol", root)
        result = execute(command, root, environment, folder / "probe", max_output_bytes=MAX_METADATA)
        record = {"command": list(map(str, command)), "status": result.returncode,
                  "stdout": result.stdout.decode(), "stderr": result.stderr.decode()}
        receipt.write_text(json.dumps(record, sort_keys=True) + "\n")
    require(type(record) is dict and set(record) == {"command", "status", "stdout", "stderr"}
            and record["command"] == list(map(str, command))
            and type(record["stdout"]) is str and type(record["stderr"]) is str
            and type(record["status"]) is int and record["status"] == 0,
            "public Node protocol probe failed")
    value = capture.strict_json(record["stdout"])
    verify_protocols(value)
    return value


def verify_probes(workflow, workspace: Path, data: dict) -> None:
    """Context/compiler artifacts and capability probes share a sealed directory."""
    verify_entry_settings(data)
    root = workspace / DIRECTORY
    expected = data.get("node_provider_manifest")
    if expected is None:
        require(not root.exists() and not root.is_symlink(), "unowned Node provider directory")
        return
    require(root.is_dir() and not root.is_symlink() and workflow.manifest(root) == expected,
            "frozen Node compiler context or public probes changed")


def verify_entry_settings(data: dict) -> None:
    """Resealing a plan cannot silently select another provider, compiler or budget."""
    configuration = data.get("configuration", {})
    options = configuration.get("adapters", {}).get("node", {"backend": "legacy"})
    source = options.get("backend") == SOURCE
    for entry in data.get("inventory", []):
        if entry.get("language") not in LANGUAGES:
            continue
        require(enabled(entry) == source, "entry provider differs from the frozen project policy")
        if source:
            require(entry.get("node_compiler") == options["typescript_compiler"]
                    and type(entry.get("node_timeout_ms")) is int
                    and entry["node_timeout_ms"] == configuration["limits"]["case_timeout_ms"],
                    "entry compiler or budget differs from the frozen project policy")
