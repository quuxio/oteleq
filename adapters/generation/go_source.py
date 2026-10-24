"""Explicit rebuilt Go policy, public negotiation and installed input scope."""

from collections.abc import Callable
import hashlib
import json
import os
from pathlib import Path
import sys

import go_build
import go_context
import go_files as files
import go_project
import go_tooling
from go_provider import PROTOCOLS as BUILD_PROTOCOLS, SCOPE_HELPER_PROFILE, require, same
import otelc_capture as capture
import python_inputs

SOURCE = "source-v1"
SCOPE_SOURCE = "source-scope-v1"
DIRECTORY = "go-source-provider"
PROTOCOLS = {**BUILD_PROTOCOLS, "prepared_tools": 1}
MAX_METADATA = 256 * 1024
SDK_LANGUAGES = {"c", "cpp", "rust", "python", "java", "javascript", "typescript", "go"}
TOOLCHAIN_FILE = "build/go-upstream/toolchain.json"
TOOLCHAIN_FIELDS = {"schema_version", "module", "version", "module_sum", "module_go_sum",
                    "go", "go_sha256", "go_version", "platform", "weaver", "weaver_sha256",
                    "bundle", "bundle_sha256", "build_metadata"}
REQUIRED = {"otelc/cli_bootstrap.py", "otelc/go_build.py", "otelc/go_source.py",
            "otelc/go_supervisor.py", "otelc/prepared_go.py", "otelc/go_context_bundle.py",
            "ci/build_go_upstream.py", "adapters/go-source/main.go", "adapters/go-source/go.mod",
            "adapters/go-source/go.sum", "adapters/go/go.mod", "adapters/go/go.sum"}


def enabled(entry: dict) -> bool:
    """Only the explicit Go backend selects the rebuilt compiler and launcher."""
    return entry.get("language") == "go" and entry.get("go_backend", "legacy") in go_project.SOURCE_BACKENDS


def scope_safe(entry: dict) -> bool:
    """The operator selects the new helper/tool format explicitly."""
    return entry.get("language") == "go" and entry.get("go_backend") == SCOPE_SOURCE


def tooling_directory(root: Path, backend: str) -> Path:
    require(backend in go_project.SOURCE_BACKENDS, "unsupported Go source backend")
    return root / (go_tooling.DIRECTORY if backend == SCOPE_SOURCE else "build/go-upstream")


def configure(entry: dict, options: dict) -> None:
    """Keep legacy names stable and bind rebuilt runtime names to Go packages."""
    if "backend" in options:
        entry["go_backend"] = options["backend"]
    if enabled(entry) and "go_context" in entry:
        entry["otelc_runtime_function"] = entry["go_context"]["import_path"] + "." + entry["name"]


def sequence_profile(entry: dict) -> None:
    """Admit bounded calls with an optional complete, independently controlled schedule."""
    if "sequence_configuration" in entry:
        steps = entry["sequence_configuration"]
        require("receiver_fixture" in entry and type(steps) is list and 1 <= len(steps) <= 32
                and all(type(step) is dict and step.get("action") == "call" for step in steps),
                "Go source provider requires 1..32 receiver calls")
        if any("metrics" in step for step in steps):
            require(all(type(step.get("metrics")) is dict and set(step["metrics"]) == {"collection", "emission"}
                        and all(type(flag) is bool for flag in step["metrics"].values()) for step in steps)
                    and any(all(step["metrics"].values()) for step in steps),
                    "Go live metrics require an explicit state for every call and a positive control")


def configuration(entry: dict, endpoint: str, service: str) -> dict:
    """Supply the complete common policy, including selected factory declarations."""
    require(enabled(entry) and "go_context" in entry, "explicit source Go module entry required")
    sequence_profile(entry)
    context = entry["go_context"]
    sources = [Path(entry["path"]).relative_to(context["module_root"]).as_posix()]
    functions = [context["import_path"] + "." + entry["name"]]
    fixture = entry.get("receiver_fixture")
    if fixture:
        sources.append(Path(fixture["source_path"]).relative_to(context["module_root"]).as_posix())
        functions.append(context["import_path"] + "." + fixture["factory"])
    flags = entry.get("sequence_configuration", [{}])[0].get("metrics", {"collection": True, "emission": True})
    return {"schema_version": 3, "languages": ["go"],
            "resource": {"service_name": service},
            "export": {"endpoint": endpoint, "interval_ms": 1000, "timeout_ms": 1000,
                       "shutdown_timeout_ms": 10000},
            "sources": {"include": sorted(set(sources)), "exclude": []},
            "functions": {"include": functions, "exclude": []},
            "metrics": {**flags,
                        "histogram_boundaries_seconds": [1e-6, 1e-5, 1e-4, .001, .01, .1, 1.]},
            "traces": {"enabled": True, "sample_ratio": 1.0},
            "lifetimes": {"enabled": False, "include": [], "exclude": [],
                          "max_live": 4096, "release_methods": ["close"]},
            "context": {"tasks": False, "http": False},
            "benchmark": {"iterations": 10000, "samples": 15, "warmup": 5}}


def policy(entry: dict, endpoint: str, service: str) -> str:
    """Encode the exact schema-3 request without SDK defaults or imports."""
    data = configuration(entry, endpoint, service)
    lines = ['schema_version = 3', 'languages = ["go"]']
    for name, values in data.items():
        if type(values) is dict:
            lines.append("[" + name + "]")
            lines.extend(key + " = " + json.dumps(value, ensure_ascii=True) for key, value in values.items())
    return "\n".join(lines) + "\n"


def toolchain(root: Path, tools: dict, *, backend: str = SOURCE) -> dict:
    """Installed metadata qualifies caller-selected tools; it cannot select Go."""
    directory = tooling_directory(root, backend)
    if backend == SCOPE_SOURCE:
        return go_tooling.read(directory, tools["go"]).tools
    value, _ = files.read(root / TOOLCHAIN_FILE)
    require(set(value) == TOOLCHAIN_FIELDS and type(value["schema_version"]) is int
            and value["schema_version"] == 1 and value["module"] == "go.opentelemetry.io/otelc"
            and value["version"] == "v1.0.1" and value["go_version"] == "go1.27.3"
            and value["go"] == str(tools["go"])
            and value["weaver"] == str(root / "build/go-upstream/bin/otelc")
            and value["bundle_sha256"] == go_context.BUNDLE_SHA256,
            "unsupported Go toolchain manifest; prepare matching SDK Go tooling first")
    for name in ("go", "weaver", "bundle"):
        path = Path(value[name])
        require(path.is_absolute() and path.resolve(strict=True) == path,
                "Go tooling input is not canonical")
    go_build.verify_tools(value, value)
    return value


def installed_files(root: Path, suffixes: set[str] | None = None) -> list[Path]:
    """Include executable bytecode caches; isolated -B startup can still read them."""
    require(root.is_dir() and not root.is_symlink(), "missing or linked Go provider input directory")
    result = []
    for directory, children, leaves in os.walk(root, onerror=python_inputs.walk_error):
        require(all(not (Path(directory) / name).is_symlink() for name in children),
                "linked Go provider input directory")
        for name in leaves:
            path = Path(directory) / name
            if suffixes is None or path.suffix in suffixes:
                result.append(path)
                require(len(result) <= python_inputs.MAX_FILES, "Go provider input count exceeds its budget")
    return sorted(result)


def artefacts(root: Path, tools: dict, *, backend: str = SOURCE) -> dict:
    """Freeze SDK/inspector/tooling inputs and the isolated host's installed wheels."""
    require(root.is_dir() and root.resolve(strict=True) == root, "Go provider root must be canonical")
    require(tools["python-host"] == Path(sys.executable).absolute(), "Go CLI must use the selected host spelling")
    directory = tooling_directory(root, backend)
    selected = [root / name for name in ("bin/quux-otelc", "requirements.txt", "requirements-dev.txt")]
    selected.append(directory / "toolchain.json")
    if backend == SCOPE_SOURCE:
        source = go_tooling.source_snapshot(directory / "source")
        selected += [directory / go_tooling.MANIFEST, *[source.root / name for name in source.identities]]
    selected += installed_files(root / "otelc")
    selected += installed_files(root / "ci", {".py", ".pyc"})
    selected += installed_files(root / "adapters/go")
    selected += installed_files(root / "adapters/go-source")
    required = REQUIRED | ({"ci/go_scope_patch.py", "otelc/go_prepared_tools.py"} if backend == SCOPE_SOURCE else set())
    require(required <= {path.relative_to(root).as_posix() for path in selected}, "incomplete Go provider installation")
    paths = [(path.relative_to(root).as_posix(), path, root) for path in selected]
    for installed in python_inputs.dependency_roots(tools["python-host"]):
        paths.extend(("installed:" + str(installed) + ":" + path.relative_to(installed).as_posix(), path, installed)
                     for path in installed_files(installed))
    result = python_inputs.catalogue(paths)
    for name, path in tools.items():
        result["tool:" + name] = capture.file_digest(path)
        if path.is_symlink():
            result["tool-link:" + name] = hashlib.sha256(os.fsencode(os.readlink(path))).hexdigest()
    result["host-python-identity"] = capture.file_digest(tools["python-host"].resolve(strict=True))
    selected_tools = toolchain(root, tools, backend=backend)
    for name in ("go", "weaver", "bundle"):
        result["toolchain:" + name] = files.identity(Path(selected_tools[name]))["sha256"]
    return result


def cli(root: Path, tools: dict) -> list:
    """Use the fixed public isolated host, never argv from returned records."""
    return [tools["python-host"], "-I", "-S", "-B", root / "otelc/cli_bootstrap.py"]


def verify_capabilities(value: object, expected: dict) -> None:
    """Require the complete common request and all eight capability declarations."""
    require(type(value) is dict and set(value) == {"policy", "implemented", "candidates", "remaining"}
            and same(value["policy"], expected), "public Go plan differs from the complete policy")
    groups = {}
    for name in ("implemented", "candidates", "remaining"):
        items = value[name]
        require(type(items) is list and all(type(item) is str for item in items)
                and len(items) == len(set(items)) and set(items) <= SDK_LANGUAGES,
                "invalid public Go capability declaration")
        groups[name] = set(items)
    require(not groups["implemented"] & groups["remaining"]
            and groups["implemented"] | groups["remaining"] == SDK_LANGUAGES
            and groups["candidates"] <= groups["remaining"]
            and "go" in groups["implemented"] | groups["candidates"], "Go capability partition is unavailable")


def probe_protocols(root: Path, workspace: Path, tools: dict, execute: Callable, *, build_tags: tuple[str, ...] = (),
                    backend: str = SOURCE) -> dict:
    """Retain one public descriptor probe before any target compilation or launch."""
    folder = workspace / DIRECTORY / "protocol"
    receipt = folder / "response.json"
    require(backend in go_project.SOURCE_BACKENDS, "unsupported Go protocol backend")
    command = cli(root, tools) + ["go-protocols", *(["--scope-safe"] if backend == SCOPE_SOURCE else []), "--prepared-tools"]
    expected = PROTOCOLS
    if build_tags:
        command.append("--build-tags")
        expected = {**PROTOCOLS, "build": 5, "inspection": 2}
    if backend == SCOPE_SOURCE:
        expected = {**expected, "build": 7 if build_tags else 6, "inspection": 2 if build_tags else 1,
                    "helper_profile": SCOPE_HELPER_PROFILE, "prepared_tools": 2}
    require(not (workspace / DIRECTORY).is_symlink() and not folder.is_symlink(), "linked Go protocol directory")
    if receipt.exists() or receipt.is_symlink():
        require(receipt.is_file() and not receipt.is_symlink() and receipt.stat().st_size <= MAX_METADATA,
                "invalid cached Go protocol response")
        record = capture.strict_json(receipt.read_bytes())
    else:
        folder.mkdir(parents=True, exist_ok=False)
        environment = capture.environment(workspace, tools, "oteleq-go-protocol", root)
        result = execute(command, root, environment, folder / "probe", max_output_bytes=MAX_METADATA)
        record = {"command": list(map(str, command)), "status": result.returncode,
                  "stdout": result.stdout.decode(), "stderr": result.stderr.decode()}
        encoded = json.dumps(record, sort_keys=True) + "\n"
        require(len(encoded.encode()) <= MAX_METADATA, "Go protocol receipt exceeds its budget")
        receipt.write_text(encoded)
    require(type(record) is dict and set(record) == {"command", "status", "stdout", "stderr"}
            and record["command"] == list(map(str, command)) and type(record["status"]) is int
            and record["status"] == 0 and type(record["stdout"]) is str and type(record["stderr"]) is str,
            "public Go protocol probe failed")
    value = capture.strict_json(record["stdout"])
    require(type(value) is dict and same(value, expected), "unsupported prepared-tool Go protocols")
    return value


def bind(entry: dict, root: Path, workspace: Path, tools: dict, execute: Callable) -> None:
    """Negotiate an explicit candidate; unsupported requests stay visible blockers."""
    if entry["status"] != "ready" or not enabled(entry):
        return
    try:
        require("go_context" in entry, "Go source provider requires explicit module_roots")
        sequence_profile(entry)
        tags = go_project.canonical_tags(entry["go_options"]["build_tags"])
        protocols = probe_protocols(root, workspace, tools, execute, build_tags=tags, backend=entry["go_backend"])
        folder = workspace / DIRECTORY / "capabilities" / entry["id"]
        require(not folder.parent.is_symlink(), "linked Go capability directory")
        folder.mkdir(parents=True)
        endpoint, service = "http://127.0.0.1:4318", "oteleq-go-provider"
        text = policy(entry, endpoint, service)
        config = folder / "policy.toml"
        config.write_text(text, encoding="utf-8")
        command = cli(root, tools) + ["--config", config, "plan"]
        result = execute(command, root, capture.environment(workspace, tools, service, root),
                         folder / "probe", max_output_bytes=MAX_METADATA)
        entry["go_provider"] = {"request": text, "command": list(map(str, command)),
                                "status": result.returncode, "stdout": result.stdout.decode(),
                                "stderr": result.stderr.decode(), "protocols": protocols}
        require(result.returncode == 0, "public Go policy probe failed")
        value = capture.strict_json(result.stdout)
        verify_capabilities(value, configuration(entry, endpoint, service))
        entry["go_provider"]["resolved"] = value
    except (ValueError, OSError, KeyError) as error:
        entry["status"], entry["reason"] = "blocked", "Go source provider unavailable: " + str(error)


def verify_probes(workflow, workspace: Path, data: dict) -> None:
    """Retained probes cannot change provider selection or package/runtime names."""
    options = data["configuration"]["adapters"]["go"]
    source = options.get("backend", "legacy") in go_project.SOURCE_BACKENDS
    for entry in data["inventory"]:
        if entry.get("language") == "go":
            require(entry.get("go_backend", "legacy") == options.get("backend", "legacy")
                    and enabled(entry) == source, "Go entry backend differs from project policy")
            if enabled(entry) and "go_context" in entry:
                require(same(entry.get("go_options"), options)
                        and entry.get("otelc_runtime_function") == entry["go_context"]["import_path"] + "." + entry["name"],
                        "Go entry context or runtime name differs from project policy")
    directory = workspace / DIRECTORY
    expected = data.get("go_provider_manifest")
    if expected is None:
        require(not directory.exists() and not directory.is_symlink(), "unowned Go provider directory")
    else:
        require(directory.is_dir() and not directory.is_symlink() and workflow.manifest(directory) == expected,
                "frozen Go provider probes changed")
