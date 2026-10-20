"""Bind explicit TypeScript emitters and requested collection to public resolution."""
from collections.abc import Callable
from pathlib import Path
from typing import Any

import otelc_capture as capture
import sequences


def backend(value: Any) -> str:
    """A compiler selection never falls back to a different emitter."""
    if type(value) is not str or value not in ("source", "native"):
        raise ValueError("adapters.typescript.backend must be source or native")
    return value


def validate(expected: Any, entry: dict, status: int) -> None:
    """Require schema-2 acknowledgement of the actual requested execution recipe."""
    if (not isinstance(expected, dict) or type(expected.get("schema_version")) is not int
            or expected["schema_version"] != 2 or expected.get("language") != "typescript"
            or expected.get("backend") != entry["typescript_backend"]):
        raise ValueError("invalid TypeScript provider resolution identity")
    if status != 0 or expected.get("execution_available") is not True:
        raise ValueError("provider cannot execute the requested TypeScript backend/collection policy")
    functions = [entry["otelc_function"]]
    if sequences.creator(entry) is not None:
        functions.append(sequences.creator(entry))
    if (expected.get("functions") != {"include": functions, "exclude": []}
            or not isinstance(expected.get("traces"), dict) or expected["traces"].get("enabled") is not True):
        raise ValueError("TypeScript provider changed the requested function/trace policy")
    lifetime = expected.get("lifetimes", {})
    if not sequences.collects(entry) and (not isinstance(lifetime, dict) or lifetime.get("enabled") is not False):
        raise ValueError("TypeScript provider enabled unrequested lifetime recording")
    if sequences.collects(entry) and lifetime != {"enabled": True, "boundary": "collection",
                                                "include": [entry["node_class_label"]], "exclude": [], "resources": []}:
        raise ValueError("TypeScript provider changed the requested collection policy")


def bind(entry: dict, root: Path, workspace: Path, tools: dict, execute: Callable, policy: Callable) -> None:
    """Retain a public config-only probe before any requested application launch."""
    if (entry["status"] != "ready" or entry["language"] != "typescript"
            or not (sequences.collects(entry) or entry["typescript_backend"] == "native")):
        return
    folder = workspace / "typescript-provider" / entry["id"]
    folder.mkdir(parents=True)
    text = policy(entry, "http://127.0.0.1:4318")
    config = folder / "policy.toml"
    config.write_text(text)
    command = [root / capture.OTELC_CLI_PATH, "--config", config, "--language", "typescript",
               "config", "--json", "--require-supported"]
    environment = capture.environment(workspace, tools, "oteleq-typescript-profile", root)
    try:
        capture.typescript_backend(root, "typescript", entry, text.encode())
        result = execute(command, workspace, environment, folder)
        entry["typescript_provider"] = {"request": text, "command": [str(item) for item in command],
                                        "status": result.returncode, "stdout": result.stdout.decode(),
                                        "stderr": result.stderr.decode()}
        resolved = capture.strict_json(result.stdout)
        validate(resolved, entry, result.returncode)
        entry["typescript_provider"]["resolved"] = resolved
    except (ValueError, OSError, KeyError, UnicodeError) as error:
        entry["reason"], entry["status"] = str(error), "blocked"
