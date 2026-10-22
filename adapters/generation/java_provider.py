"""Explicit prepared-Java SDK policy, frozen inputs and public launch contract."""
from collections.abc import Callable
import hashlib
import json
import os
from pathlib import Path
import sys

import java_profiles
import otelc_capture as capture

AGENT = "build/tools/opentelemetry-javaagent-2.32.0.jar"
AGENT_SHA256 = "f787eb6c7f3d18e69a431e108a15278d25ee37f83d68b678f621e063f3988f82"
EXTENSION = "adapters/java/target/java-extension-0.2.0-SNAPSHOT.jar"
HELPER = "adapters/java/target/java-extension-0.2.0-SNAPSHOT-helper-tool.jar"
SDK_MODULES = {"__init__.py", "__main__.py", "config.py", "java.py", "prepared_java.py", "health.py", "control.py"}
SDK_LANGUAGES = {"c", "cpp", "rust", "python", "java", "javascript", "typescript", "go"}
MAX_METADATA = 256 * 1024
MAX_TELEMETRY_REQUESTS = 4096
DIRECTORY = "java-provider"


def require(condition: bool, reason: str) -> None:
    """Unsupported provider inputs or identities never select a fallback launcher."""
    if not condition:
        raise ValueError("Java prepared provider: " + reason)


def backend(value: object) -> str:
    """Keep the legacy and prepared APIs explicitly selected in the frozen plan."""
    require(type(value) is str and value in ("legacy", "prepared"),
            "adapters.java.backend must be legacy or prepared")
    return value


def prepared(entry: dict) -> bool:
    """Other language and existing Java plans retain their own provider contract."""
    return entry.get("language") == "java" and entry.get("java_backend", "legacy") == "prepared"


def artefacts(root: Path, tools: dict, profile: str = java_profiles.STOCK) -> dict:
    """Bind prebuilt SDK products and every source module without installing them."""
    require(os.name == "posix", "prepared provider requires qualified POSIX control sockets")
    package = root / "otelc"
    require(package.is_dir() and not package.is_symlink(), "missing SDK Python package")
    paths = [root / AGENT, root / EXTENSION, root / "adapters/java/pom.xml"]
    if java_profiles.corrected(profile):
        paths.extend(java_profiles.patch_inputs(root))
    if profile == java_profiles.ARCHIVES:
        paths.append(root / HELPER)
    for tree in (package, root / "adapters/java/src/main"):
        require(tree.is_dir() and not tree.is_symlink(), "missing SDK source tree: " + str(tree))
        for path in sorted(tree.rglob("*")):
            require(not path.is_symlink(), "symlink in SDK inputs: " + str(path))
            if path.is_file() and (tree != package or path.suffix == ".py"):
                paths.append(path)
    require(all((package / name).is_file() for name in SDK_MODULES), "incomplete public prepared/health API")
    require(all(path.is_file() and not path.is_symlink() for path in paths), "missing prebuilt SDK product or source")
    require(capture.file_digest(root / AGENT) == AGENT_SHA256, "official Java agent digest differs")
    result = {path.relative_to(root).as_posix(): capture.file_digest(path) for path in paths}
    result.update({"tool:" + name: capture.file_digest(path) for name, path in tools.items()})
    return result


def configuration(entry: dict, endpoint: str, service: str) -> dict:
    """Supply every schema-3 field so producer defaults cannot change the recipe."""
    result = {"schema_version": 3, "languages": ["java"], "resource": {"service_name": service},
            "export": {"endpoint": endpoint, "interval_ms": 1000, "timeout_ms": 1000, "shutdown_timeout_ms": 10000},
            "sources": {"include": [entry["path"]], "exclude": []},
            "functions": {"include": [entry["otelc_function"]], "exclude": []},
            "metrics": {"collection": True, "emission": True,
                        "histogram_boundaries_seconds": [1e-6, 1e-5, 1e-4, .001, .01, .1, 1.]},
            "traces": {"enabled": True, "sample_ratio": 1.0},
            "lifetimes": {"enabled": False, "include": [], "exclude": [], "max_live": 4096, "release_methods": ["close"]},
            "benchmark": {"iterations": 10000, "samples": 15, "warmup": 5}}
    if entry.get("java_profile") == java_profiles.ARCHIVES:
        result["context"] = {"tasks": False, "http": False}
    return result


def policy(entry: dict, endpoint: str, service: str) -> str:
    """Emit the complete requested SDK policy without changing application inputs."""
    data = configuration(entry, endpoint, service)
    text = 'schema_version = 3\nlanguages = ["java"]\n'
    for section, values in data.items():
        if isinstance(values, dict):
            text += "[" + section + "]\n"
            text += "".join(name + " = " + json.dumps(value, ensure_ascii=False) + "\n" for name, value in values.items())
    return text


def digest(value: dict) -> str:
    """The public SDK hashes normalised JSON with default separators/ASCII escaping."""
    return hashlib.sha256(json.dumps(value, sort_keys=True).encode()).hexdigest()


def environment(root: Path, tools: dict, folder: Path, original: dict) -> dict:
    """Select the actual planned JDK and isolate SDK module imports and bytecode."""
    java = tools["java"].resolve(strict=True)
    cache = folder / "sdk-python-cache"
    cache.mkdir(parents=True, exist_ok=True)
    return {**original, "JAVA_HOME": str(java.parent.parent), "PYTHONPATH": str(root),
            "PYTHONPYCACHEPREFIX": str(cache), "PYTHONNOUSERSITE": "1", "PYTHONDONTWRITEBYTECODE": "1"}


def bind(entry: dict, root: Path, workspace: Path, tools: dict, execute: Callable) -> None:
    """Retain a public config-only capability response before any application call."""
    if entry["status"] != "ready" or not prepared(entry):
        return
    folder = workspace / DIRECTORY / entry["id"]
    folder.mkdir(parents=True)
    endpoint, service = "http://127.0.0.1:4318", "oteleq-java-provider"
    config = folder / "policy.toml"
    text = policy(entry, endpoint, service)
    config.write_text(text, encoding="utf-8")
    command = [sys.executable, "-m", "otelc", "--config", config, "plan"]
    env = environment(root, tools, folder, capture.environment(workspace, tools, service, root))
    try:
        result = execute(command, root, env, folder / "probe", max_output_bytes=MAX_METADATA)
        entry["java_provider"] = {"request": text, "command": list(map(str, command)),
                                  "status": result.returncode, "stdout": result.stdout.decode(), "stderr": result.stderr.decode()}
        require(result.returncode == 0, "public configuration probe failed")
        value = capture.strict_json(result.stdout)
        require(type(value) is dict and set(value) == {"policy", "implemented", "remaining"}
                and type(value["policy"]) is dict
                and digest(value["policy"]) == digest(configuration(entry, endpoint, service)),
                "provider changed the complete requested policy")
        implemented, remaining = value["implemented"], value["remaining"]
        require(type(implemented) is list and type(remaining) is list
                and all(type(name) is str for name in implemented + remaining)
                and len(set(implemented + remaining)) == len(implemented + remaining)
                and set(implemented + remaining) == SDK_LANGUAGES
                and "java" in implemented, "public provider has no supported Java capability")
        entry["java_provider"]["resolved"] = value
    except (ValueError, OSError, KeyError) as error:
        entry["status"], entry["reason"] = "blocked", "Java prepared provider unavailable: " + str(error)


def verify_probes(workflow, workspace: Path, data: dict) -> None:
    """Retained capability probes are sealed evidence, not unowned cleanup debris."""
    root = workspace / DIRECTORY
    expected = data.get("java_provider_manifest")
    if expected is None:
        require(not root.exists() and not root.is_symlink(), "unowned provider probe directory")
    else:
        require(root.is_dir() and not root.is_symlink() and workflow.manifest(root) == expected,
                "frozen provider probes changed")
