"""Explicit rebuilt Python negotiation; missing origin evidence stays blocked."""

from collections.abc import Callable
import json
from pathlib import Path
from typing import Any

import otelc_capture as capture
import python_project
import sequences

DIRECTORY = "python-provider"
MAX_METADATA = 256 * 1024
SDK_LANGUAGES = {"c", "cpp", "rust", "python", "java", "javascript", "typescript", "go"}
INPUT_PROFILE = "python-native-inputs-v1"
ORIGIN_PROFILE = "python-native-origins-v2"
PROTOCOLS = {"schema_version": 1, "kind": "otelc.python.protocols",
             "request": 1, "plan": 1, "prepared": 1, "command": 1, "execution": 1,
             "journal": {"schema_version": 1, "record_kinds": [1, 2, 3, 4]},
             "code": {"written": 2, "readable": [2]}, "health": 2, "sdk": 1,
             "code_comparisons": 1, "source_complete": False}
ORIGIN_PROTOCOLS = {"schema_version": 2, "kind": "otelc.python.protocols", "profile": ORIGIN_PROFILE,
                    "request": 2, "plan": 2, "prepared": 2, "command": 2, "execution": 2,
                    "journal": {"schema_version": 2, "record_kinds": [1, 2, 3, 4, 5, 6, 7]},
                    "code": {"written": 2, "readable": [2]}, "health": 2, "sdk": 1,
                    "code_comparisons": None, "source_complete": False,
                    "origin_scope": "native-entry-and-application-root-source-loaders"}
ORIGIN_UNAVAILABLE = "both baseline and instrumented selected-source origin bindings are unavailable"


def require(condition: bool, reason: str) -> None:
    """An explicit rebuilt provider never falls back to a legacy launcher."""
    if not condition:
        raise ValueError("Python prepared provider: " + reason)


def profile_version(profile: str) -> int:
    """Only explicit caller intent selects another protocol; metadata cannot."""
    require(type(profile) is str and profile in (INPUT_PROFILE, ORIGIN_PROFILE), "unknown Python prepared profile")
    return 2 if profile == ORIGIN_PROFILE else 1


def settings(value: Any) -> dict:
    """Keep existing resolved legacy policies byte compatible unless selected."""
    require(type(value) is dict and not set(value) - {"backend", "import_roots", "profile"},
            "adapters.python accepts backend, import_roots and profile")
    backend = value.get("backend", "legacy")
    require(type(backend) is str and backend in ("legacy", "prepared"),
            "adapters.python.backend must be legacy or prepared")
    result = {"import_roots": python_project.import_roots(value.get("import_roots", []))}
    if "backend" in value:
        result["backend"] = backend
    if "profile" in value:
        require(backend == "prepared", "Python profile requires the explicit prepared backend")
        profile_version(value["profile"])
        result["profile"] = value["profile"]
    return result


def enabled(entry: dict) -> bool:
    """Only explicitly selected Python entries use this provider contract."""
    return entry.get("language") == "python" and entry.get("python_backend", "legacy") == "prepared"


def origin(entry: dict) -> bool:
    """Generated origin execution requires an explicit second-profile request."""
    return enabled(entry) and entry.get("python_profile") == ORIGIN_PROFILE


def creator(entry: dict) -> str | None:
    """Include the declared source constructor/factory in origin observations."""
    name = entry.get("receiver_fixture", {}).get("source_function")
    return entry["otelc_function"][:-len(entry["name"])] + name if origin(entry) and name else None


def configuration(entry: dict, endpoint: str, service: str) -> dict:
    """Supply all common schema-3 fields without inheriting producer defaults."""
    require(enabled(entry), "explicit prepared entry required")
    functions = [entry["otelc_function"]]
    creation = creator(entry) if origin(entry) else sequences.creator(entry)
    if creation is not None:
        functions.append(creation)
    return {"schema_version": 3, "languages": ["python"],
            "resource": {"service_name": service},
            "export": {"endpoint": endpoint, "interval_ms": 1000, "timeout_ms": 1000,
                       "shutdown_timeout_ms": 10000},
            "sources": {"include": [entry["path"]], "exclude": []},
            "functions": {"include": functions, "exclude": []},
            "metrics": {"collection": True, "emission": True,
                        "histogram_boundaries_seconds": [1e-6, 1e-5, 1e-4, .001, .01, .1, 1.]},
            "traces": {"enabled": True, "sample_ratio": 1.0},
            "lifetimes": {"enabled": False, "include": [], "exclude": [],
                          "max_live": 4096, "release_methods": ["close"]},
            "context": {"tasks": False, "http": False},
            "benchmark": {"iterations": 10000, "samples": 15, "warmup": 5}}


def policy(entry: dict, endpoint: str, service: str) -> str:
    """Keep exact selected paths/functions and safe TOML string escapes."""
    data = configuration(entry, endpoint, service)
    text = 'schema_version = 3\nlanguages = ["python"]\n'
    for section, values in data.items():
        if type(values) is dict:
            text += "[" + section + "]\n"
            text += "".join(name + " = " + json.dumps(value, ensure_ascii=False).replace("\x7f", "\\u007f") + "\n"
                            for name, value in values.items())
    return text


def same(value: Any, expected: Any) -> bool:
    """Canonical JSON equality keeps booleans distinct from protocol integers."""
    return json.dumps(value, sort_keys=True, allow_nan=False) == json.dumps(expected, sort_keys=True, allow_nan=False)


def verify_protocols(value: Any, profile: str = INPUT_PROFILE) -> None:
    """Static journal/descriptor formats do not establish selected-code origin."""
    expected = ORIGIN_PROTOCOLS if profile_version(profile) == 2 else PROTOCOLS
    require(type(value) is dict and same(value, expected), "unsupported public Python protocols")


def verify_capabilities(value: Any, requested: dict) -> None:
    """Record candidates without promoting them to implemented language support."""
    require(type(value) is dict and set(value) == {"policy", "implemented", "candidates", "remaining"}
            and type(value["policy"]) is dict and same(value["policy"], requested),
            "public plan differs from the complete common request")
    groups = {}
    for name in ("implemented", "candidates", "remaining"):
        items = value[name]
        require(type(items) is list and all(type(item) is str for item in items)
                and len(items) == len(set(items)) and set(items) <= SDK_LANGUAGES,
                "invalid public " + name + " language declarations")
        groups[name] = set(items)
    implemented, remaining = groups["implemented"], groups["remaining"]
    require(not implemented & remaining and implemented | remaining == SDK_LANGUAGES
            and groups["candidates"] <= remaining, "invalid eight-language capability partition")
    require("python" in implemented | groups["candidates"], "Python has no public implementation or candidate declaration")


def probe_protocols(root: Path, workspace: Path, tools: dict, execute: Callable,
                    profile: str = INPUT_PROFILE) -> dict:
    """Probe once with site hooks disabled, without build or application startup."""
    selected = profile_version(profile)
    folder = workspace / DIRECTORY / ("protocol-origins-v2" if selected == 2 else "protocol")
    receipt = folder / "response.json"
    require(not (workspace / DIRECTORY).is_symlink() and not folder.is_symlink(), "linked protocol directory")
    argument = "profile=" + repr(profile) if selected == 2 else ""
    bootstrap = ("import json,sys;sys.path.insert(0,sys.argv[1]);from otelc import prepared_python;"
                 "print(json.dumps(prepared_python.protocols(" + argument + "),sort_keys=True))")
    command = [tools["python"], "-I", "-S", "-B", "-c", bootstrap, root]
    if receipt.exists() or receipt.is_symlink():
        require(receipt.is_file() and not receipt.is_symlink() and receipt.stat().st_size <= MAX_METADATA,
                "invalid cached public protocol response")
        record = capture.strict_json(receipt.read_bytes())
    else:
        folder.mkdir(parents=True, exist_ok=False)
        environment = capture.environment(workspace, tools, "oteleq-python-protocol", root)
        result = execute(command, root, environment, folder / "probe", max_output_bytes=MAX_METADATA)
        record = {"command": list(map(str, command)), "status": result.returncode,
                  "stdout": result.stdout.decode(), "stderr": result.stderr.decode()}
        encoded = json.dumps(record, sort_keys=True) + "\n"
        require(len(encoded.encode()) <= MAX_METADATA, "public protocol receipt exceeds its budget")
        receipt.write_text(encoded)
    require(type(record) is dict and set(record) == {"command", "status", "stdout", "stderr"}
            and record["command"] == list(map(str, command)) and type(record["status"]) is int
            and record["status"] == 0 and type(record["stdout"]) is str and type(record["stderr"]) is str,
            "public Python protocol probe failed")
    value = capture.strict_json(record["stdout"])
    verify_protocols(value, profile)
    return value


def bind(entry: dict, root: Path, workspace: Path, tools: dict, execute: Callable) -> None:
    """Admit only explicit origin execution after complete public negotiation."""
    if entry["status"] != "ready" or not enabled(entry):
        return
    require(not (workspace / DIRECTORY).is_symlink()
            and not (workspace / DIRECTORY / "capabilities").is_symlink(), "linked capability directory")
    folder = workspace / DIRECTORY / "capabilities" / entry["id"]
    folder.mkdir(parents=True)
    endpoint, service = "http://127.0.0.1:4318", "oteleq-python-provider"
    text = policy(entry, endpoint, service)
    config = folder / "policy.toml"
    config.write_text(text, encoding="utf-8")
    command = [tools["python"], "-I", "-S", "-B", root / "otelc/cli_bootstrap.py",
               "--config", config, "plan"]
    try:
        protocols = probe_protocols(root, workspace, tools, execute, entry.get("python_profile", INPUT_PROFILE))
        environment = capture.environment(workspace, tools, service, root)
        result = execute(command, root, environment, folder / "probe", max_output_bytes=MAX_METADATA)
        entry["python_provider"] = {"request": text, "command": list(map(str, command)),
                                    "status": result.returncode, "stdout": result.stdout.decode(), "stderr": result.stderr.decode(),
                                    "protocols": protocols}
        require(result.returncode == 0, "public configuration probe failed")
        value = capture.strict_json(result.stdout)
        verify_capabilities(value, configuration(entry, endpoint, service))
        entry["python_provider"]["resolved"] = value
        if not origin(entry):
            raise ValueError(ORIGIN_UNAVAILABLE)
    except (ValueError, OSError, KeyError) as error:
        entry["status"], entry["reason"] = "blocked", "Python prepared provider unavailable: " + str(error)


def verify_probes(workflow, workspace: Path, data: dict) -> None:
    """Policy, selection, complete capability response and raw probes stay sealed."""
    configured_python = data.get("configuration", {}).get("adapters", {}).get("python", {})
    configured = configured_python.get("backend", "legacy")
    profile = configured_python.get("profile", INPUT_PROFILE)
    profile_version(profile)
    require("profile" not in configured_python or configured == "prepared", "Python profile requires prepared backend")
    for entry in data.get("inventory", []):
        if entry.get("language") == "python":
            require(entry.get("python_backend", "legacy") == configured, "entry provider differs from frozen policy")
            require(entry.get("python_profile", INPUT_PROFILE) == profile, "entry profile differs from frozen policy")
            if enabled(entry):
                if entry["status"] == "ready":
                    refuse_unbound(entry)
    folder = workspace / DIRECTORY
    expected = data.get("python_provider_manifest")
    if expected is None:
        require(not folder.exists() and not folder.is_symlink(), "unowned Python provider directory")
    else:
        require(folder.is_dir() and not folder.is_symlink() and workflow.manifest(folder) == expected,
                "frozen Python provider probes changed")


def refuse_unbound(entry: dict) -> None:
    """A hand-edited or direct attempt cannot reach the legacy Python launcher."""
    if enabled(entry):
        require(origin(entry), ORIGIN_UNAVAILABLE)
        probe = entry.get("python_provider")
        require(type(probe) is dict and probe.get("status") == 0
                and type(probe.get("status")) is int, "missing successful frozen origin negotiation")
        verify_protocols(probe.get("protocols"), ORIGIN_PROFILE)
        endpoint, service = "http://127.0.0.1:4318", "oteleq-python-provider"
        require(probe.get("request") == policy(entry, endpoint, service), "frozen origin request differs")
        require(type(probe.get("stdout")) is str, "invalid frozen capability output")
        resolved = capture.strict_json(probe.get("stdout", ""))
        verify_capabilities(resolved, configuration(entry, endpoint, service))
        require(same(resolved, probe.get("resolved")), "frozen origin capability response differs")
