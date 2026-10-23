"""Independently check prepared Python intent and fixed supervisor transport.

These checks admit metadata, not an execution profile or selected-code origin.
Native compiler/input qualification and both-lane origin binding are separate.
"""

from dataclasses import dataclass
import hashlib
import json
import os
from pathlib import Path
import re
import stat
from typing import Any

import otelc_capture as capture
import python_provider as provider

MAX_METADATA = 64 * 1024 * 1024
ENVIRONMENT_KEYS = (
    "PYTHONHOME", "PYTHONPATH", "PYTHONPLATLIBDIR", "PYTHONSAFEPATH",
    "PYTHONNOUSERSITE", "PYTHONUSERBASE", "PYTHONUTF8", "PYTHONCOERCECLOCALE",
    "PYTHONIOENCODING", "PYTHONUNBUFFERED", "PYTHONDONTWRITEBYTECODE",
    "PYTHONPYCACHEPREFIX", "PYTHONOPTIMIZE", "PYTHONVERBOSE", "PYTHONINSPECT",
    "PYTHONWARNINGS", "PYTHONHASHSEED", "PYTHONDEVMODE", "PYTHONFAULTHANDLER",
    "PYTHONPROFILEIMPORTTIME", "PYTHONMALLOC", "PYTHONMALLOCSTATS",
    "PYTHONTRACEMALLOC", "PYTHONASYNCIODEBUG", "PYTHONBREAKPOINT",
    "LANG", "LC_ALL", "LC_CTYPE", "TZ", "TMPDIR", "TEMP", "TMP",
)


@dataclass(frozen=True)
class Intent:
    """Caller-owned expected inputs; none are taken from a launch response."""

    provider_root: Path
    project: Path
    runtime: Path
    entry: Path
    caller: Path
    python: Path
    interpreter: dict
    policy: dict
    policy_file: Path
    environment: dict[str, str]
    plain: bool
    arguments: tuple[str, ...] = ()


def encoded(value: Any) -> bytes:
    """Prepared request/plan digests include the canonical terminal newline."""
    return (json.dumps(value, sort_keys=True, allow_nan=False) + "\n").encode()


def digest(value: Any) -> str:
    """Keep producer recipe hashing separate from compact SDK policy hashing."""
    return hashlib.sha256(encoded(value)).hexdigest()


def file_identity(path: Path) -> dict:
    """Observe stable actual bytes and preserve the interpreter's venv symlink."""
    before = path.stat()
    provider.require(stat.S_ISREG(before.st_mode), "prepared input is not a regular file")
    value = {"path": str(path.absolute()), "resolved_path": str(path.resolve(strict=True)),
             "sha256": capture.file_digest(path), "size": before.st_size}
    if path.is_symlink():
        value["symlink"] = os.readlink(path)
    after = path.stat()
    provider.require((before.st_dev, before.st_ino, before.st_size, before.st_mtime_ns, before.st_ctime_ns)
                     == (after.st_dev, after.st_ino, after.st_size, after.st_mtime_ns, after.st_ctime_ns),
                     "prepared input changed while reading")
    return value


def read(path: Path) -> tuple[dict, bytes]:
    """Read completed owned regular metadata without following links or FIFOs."""
    descriptor = os.open(path, os.O_RDONLY | os.O_NOFOLLOW | os.O_NONBLOCK)
    try:
        before = os.fstat(descriptor)
        provider.require(stat.S_ISREG(before.st_mode) and before.st_uid == os.getuid()
                         and stat.S_IMODE(before.st_mode) == 0o600 and before.st_nlink == 1
                         and before.st_size <= MAX_METADATA, "invalid completed private Python metadata")
        with os.fdopen(descriptor, "rb", closefd=False) as stream:
            raw = stream.read(MAX_METADATA + 1)
        def signature(info):
            return (info.st_dev, info.st_ino, info.st_size, info.st_mtime_ns, info.st_ctime_ns,
                    info.st_mode, info.st_uid, info.st_gid, info.st_nlink)
        provider.require(len(raw) == before.st_size
                         and signature(before) == signature(os.fstat(descriptor)) == signature(path.lstat()),
                         "private Python metadata changed while reading")
    finally:
        os.close(descriptor)
    value = capture.strict_json(raw)
    provider.require(type(value) is dict, "private Python metadata must be an object")
    encoded(value)  # Refuse non-finite numbers accepted by the shared JSON reader.
    return value, raw


def expected_request(intent: Intent) -> dict:
    """Resolve only independently supplied script intent, with literal arguments."""
    provider.require(type(intent.plain) is bool and type(intent.arguments) is tuple
                     and all(type(item) is str and "\0" not in item for item in intent.arguments),
                     "invalid caller-owned Python lane or arguments")
    for path in (intent.provider_root, intent.project, intent.runtime, intent.caller, intent.python, intent.policy_file):
        provider.require(path.is_absolute(), "caller-owned Python paths must be absolute")
    actual_entry = intent.entry if intent.entry.is_absolute() else intent.project / intent.entry
    provider.require(not str(intent.entry).startswith("-") and actual_entry.suffix == ".py"
                     and actual_entry.resolve(strict=True).is_relative_to(intent.project.resolve(strict=True)),
                     "prepared entry must be source inside the private project")
    provider.require(type(intent.interpreter) is dict and set(intent.interpreter) == {"version", "cache_tag", "argv0"}
                     and all(type(item) is str and item and "\0" not in item for item in intent.interpreter.values()),
                     "invalid caller-owned interpreter metadata")
    policy_identity = file_identity(intent.policy_file)
    provider.require(policy_identity["size"] <= 1024 * 1024, "prepared policy exceeds its budget")
    policy_bytes = intent.policy_file.read_bytes()
    provider.require(hashlib.sha256(policy_bytes).hexdigest() == policy_identity["sha256"], "prepared policy changed while reading")
    policy_source = {**policy_identity, "text": policy_bytes.decode("utf-8")}
    return {"schema_version": 1, "profile": "python-native-inputs-v1", "policy": intent.policy,
            "policy_source": policy_source, "cwd": str(intent.caller.resolve(strict=True)),
            "paths": {"root": {"requested": str(intent.project), "resolved": str(intent.project.resolve(strict=True))},
                      "runtime": {"requested": str(intent.runtime), "resolved": str(intent.runtime.resolve(strict=True))},
                      "entry": {"requested": str(intent.entry), "resolved": str(actual_entry.resolve(strict=True))}},
            "module": None, "arguments": list(intent.arguments), "flags": [], "plain": intent.plain,
            "interpreter": {"file": file_identity(intent.python), **intent.interpreter},
            "environment": {key: intent.environment.get(key) for key in ENVIRONMENT_KEYS}}


def expected_plan(original: dict) -> dict:
    """Derive fixed native script arguments from the checked original request."""
    return {"schema_version": 1, "profile": "python-native-inputs-v1", "policy": original["policy"],
            "plain": original["plain"], "cwd": original["paths"]["root"]["resolved"],
            "runtime": original["paths"]["runtime"]["resolved"], "python": original["interpreter"]["file"]["path"],
            "argv0": original["interpreter"]["argv0"],
            "native_arguments": [original["paths"]["entry"]["requested"], *original["arguments"]],
            "input_scope": "native-source-entry-only", "source_complete": False}


def expected_command(intent: Intent) -> list[str]:
    """Receipts cannot select an executable, supervisor, option or runtime path."""
    return [str(intent.python), "-I", "-S", "-B", str(intent.provider_root / "otelc/python_supervisor.py"),
            "--runtime", str(intent.runtime.resolve(strict=True))]


def verify_products(prepared: dict, intent: Intent, catalogue: dict) -> None:
    """Bind native metadata to already frozen products; never run its commands."""
    driver = prepared.get("driver")
    provider.require(type(driver) is dict and type(driver.get("path")) is str, "missing native driver identity")
    path = Path(driver["path"])
    prefix = intent.provider_root / "build/tools/python-inputs"
    provider.require(path.parent.parent == prefix and re.fullmatch("[0-9a-f]{64}", path.parent.name) is not None
                     and path.name == "otelc-python-inputs", "native driver is outside the fixed product namespace")
    manifest = path.parent / "build.json"
    for selected in (path, manifest):
        key = selected.relative_to(intent.provider_root).as_posix()
        provider.require(key in catalogue and not selected.is_symlink()
                         and capture.file_digest(selected) == catalogue[key], "native product differs from frozen inputs")
    provider.require(provider.same(driver, file_identity(path))
                     and provider.same(prepared.get("build_manifest"), file_identity(manifest)),
                     "native prepared identities differ from actual frozen files")


def verify(value: Any, intent: Intent, catalogue: dict) -> None:
    """Check exact public response and private files against independent intent."""
    info = intent.runtime.lstat()
    provider.require(stat.S_ISDIR(info.st_mode) and info.st_uid == os.getuid() and stat.S_IMODE(info.st_mode) == 0o700,
                     "Python runtime must be an owned private directory")
    fields = {"schema_version", "kind", "request", "plan", "prepared", "command", "source_complete"}
    provider.require(type(value) is dict and set(value) == fields, "invalid prepared command fields")
    original = expected_request(intent)
    plan = expected_plan(original)
    prepared = value["prepared"]
    provider.require(type(prepared) is dict and set(prepared) == {
        "schema_version", "kind", "request_sha256", "plan_sha256", "driver", "build_manifest", "producer", "entry", "source_complete"},
        "invalid prepared manifest fields")
    verify_products(prepared, intent, catalogue)
    root = intent.provider_root
    maintained = [root / "bin/quux-otelc", *sorted((root / "otelc").glob("*.py")),
                  root / "ci/build_python_inputs.py", root / "requirements.txt", root / "requirements-dev.txt"]
    expected = {"schema_version": 1, "kind": "otelc.python.prepared",
                "request_sha256": digest(original), "plan_sha256": digest(plan),
                "driver": prepared["driver"], "build_manifest": prepared["build_manifest"],
                "producer": [file_identity(path) for path in maintained],
                "entry": file_identity(Path(original["paths"]["entry"]["resolved"])), "source_complete": False}
    response = {"schema_version": 1, "kind": "otelc.python.command", "request": original,
                "plan": plan, "prepared": expected, "command": expected_command(intent), "source_complete": False}
    provider.require(provider.same(value, response), "public Python command differs from independent intent or fixed recipe")
    for name, document in (("python-request.json", original), ("python-resolved-plan.json", plan), ("python-prepared.json", expected)):
        actual, raw = read(intent.runtime / name)
        provider.require(provider.same(actual, document) and raw == encoded(document), "private Python prepared file differs: " + name)
