"""Bind generated Node callers to actual private source/package loader context."""
import hashlib
import json
from pathlib import Path, PurePosixPath
from typing import Callable


def context(path: Path, snapshot: Path, language: str, provider: Path,
            node: Path, execute: Callable) -> dict:
    """Read the selected loader's module format without evaluating application code."""
    source_digest = hashlib.sha256(path.read_bytes()).hexdigest()
    command = [node]
    if language == "typescript":
        command.extend(["--import", provider / "adapters/node/plain.mjs"])
    command.append(Path(__file__).with_name("node_context.mjs"))
    request = {"filename": str(path.resolve()), "root": str(snapshot.resolve()),
               "source_sha256": source_digest}
    result = execute(command, snapshot, input_data=json.dumps(request).encode(), max_output_bytes=16384)
    if result.returncode:
        raise ValueError("Node source/package context is unavailable: " + result.stderr.decode(errors="replace")[-2000:])
    value = json.loads(result.stdout)
    _receipt(value, source_digest)
    if hashlib.sha256(path.read_bytes()).hexdigest() != source_digest:
        raise ValueError("Node source changed during context inspection")
    _package(snapshot, value["package"])
    return value


def _receipt(value: object, source_digest: str) -> None:
    fields = {"schema_version", "format", "loader_hint", "source_sha256", "package", "node_version"}
    if (not isinstance(value, dict) or set(value) != fields
            or type(value.get("schema_version")) is not int or value["schema_version"] != 1
            or value.get("source_sha256") != source_digest
            or value.get("format") not in ("module", "commonjs")
            or value["loader_hint"] is not None and not isinstance(value["loader_hint"], str)
            or not isinstance(value.get("node_version"), str)):
        raise ValueError("Node source/package context receipt differs from the request")


def _package(snapshot: Path, package: object) -> None:
    if package is not None:
        if (not isinstance(package, dict) or set(package) != {"path", "sha256"}
                or not isinstance(package["path"], str) or not isinstance(package["sha256"], str)):
            raise ValueError("Node package context receipt is invalid")
        relative = PurePosixPath(package["path"])
        package_path = snapshot / relative
        if (relative.is_absolute() or ".." in relative.parts or str(relative) != package["path"]
                or relative.name != "package.json"
                or not package_path.resolve().is_relative_to(snapshot.resolve())
                or hashlib.sha256(package_path.read_bytes()).hexdigest() != package["sha256"]):
            raise ValueError("Node package context identity differs")


def inventory_context(path: Path, snapshot: Path, original_source: Path | None,
                      language: str, provider: Path, node: Path, execute: Callable) -> dict:
    """Keep original/private loader receipts or one explicit named inventory blocker."""
    try:
        value = context(path, snapshot, language, provider, node, execute)
        result = {"node_context": value}
        if original_source is not None:
            original = context(original_source / path.relative_to(snapshot), original_source,
                               language, provider, node, execute)
            if any(original[key] != value[key] for key in ("format", "package", "node_version")):
                raise ValueError("private Node source/package context differs from the original application")
            result["node_original_context"] = original
        return result
    except (ValueError, OSError, KeyError) as error:
        return {"node_context_error": str(error)}


def commonjs(entry: dict) -> bool:
    """Use a retained loader context, with explicit-extension support for unit callers."""
    if "node_context" in entry:
        if entry["node_context"]["format"] not in ("commonjs", "module"):
            raise ValueError("unknown Node module context")
        return entry["node_context"]["format"] == "commonjs"
    return Path(entry["path"]).suffix in (".cjs", ".cts")


def bind_entry(entry: dict, discovered: dict) -> None:
    """Retain the file's loader evidence and declared CommonJS access restrictions."""
    for key in ("node_context", "node_original_context", "node_context_error"):
        if key in discovered:
            entry[key] = discovered[key]
    if entry.get("node_context_error"):
        entry["reason"] = entry["reason"] or entry["node_context_error"]
    entry["node_require_shadowed"] = any(item["name"] == "require"
                                         for item in (*discovered["functions"], *discovered["globals"]))


def require_callable(entry: dict) -> None:
    """Refuse unresolved context or an application-defined CommonJS require."""
    if entry.get("node_context_error"):
        raise ValueError(entry["node_context_error"])
    if entry.get("node_require_shadowed") and commonjs(entry):
        raise ValueError("CommonJS bootstrap requires an unshadowed module require binding")


def verify_attempt(project: Path, entry: dict, provider: Path, node: Path,
                   execute: Callable, folder: Path) -> None:
    """Recheck the materialised caller's actual format and unchanged package bytes."""
    expected = entry["node_context"]
    actual = context(project / entry["path"], project, entry["language"], provider, node, execute)
    receipt = {"original": expected, "caller": actual}
    (folder / "node-context.json").write_text(json.dumps(receipt, indent=2) + "\n")
    if any(actual[key] != expected[key] for key in ("format", "package", "node_version")):
        raise ValueError("generated Node caller changed its source/package module context")
