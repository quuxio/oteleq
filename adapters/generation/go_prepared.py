"""Independent request, recipe and private metadata checks for prepared Go calls."""

from dataclasses import dataclass
import os
from pathlib import Path
import re
import stat

import go_build
import go_files as files
import go_provider as provider
import python_prepared

CONFIG_VERSION = 1
MAX_CONFIG_BYTES = 4 * 1024 * 1024
DOCUMENTS = ("go-request.json", "go-plan.json", "go-prepared.json")
EXECUTION_FILES = ("go-supervisor-start.json", "go-application-start.json", "go-execution.json", "health.json", "control.json")


@dataclass(frozen=True)
class Intent:
    """Caller-owned build, SDK implementation and literal application arguments."""

    build: go_build.Build
    runtime: Path
    producer: files.Snapshot
    python: Path
    interpreter: dict
    policy: dict
    plain: bool
    arguments: tuple[str, ...] = ()


@dataclass(frozen=True)
class Prepared:
    """Checked pre-execution records; an owned application PID remains separate."""

    intent: Intent
    response: dict
    evidence: dict[str, tuple]

    def verify(self) -> None:
        """Recheck sealed inputs without executing producer code or recorded argv."""
        validate_intent(self.intent)
        for name, expected in self.evidence.items():
            actual, stable, _ = files.file(self.intent.runtime / name, private=True)
            provider.require(provider.same(actual, expected[0]) and stable == expected[1], "Go prepared record changed: " + name)


def private_directory(path: Path) -> None:
    """An existing runtime must already be an owned canonical mode0700 directory."""
    provider.require(isinstance(path, Path) and path.is_absolute()
                     and path.resolve(strict=True) == path, "noncanonical Go runtime directory")
    info = path.lstat()
    provider.require(stat.S_ISDIR(info.st_mode) and info.st_uid == os.getuid()
                     and stat.S_IMODE(info.st_mode) == 0o700, "Go runtime must be owned and mode0700")


def validate_intent(intent: Intent) -> None:
    """Validate original inputs before consulting a producer-selected launch ID."""
    provider.require(type(intent.build) is go_build.Build and type(intent.producer) is files.Snapshot,
                     "Go preparation lacks a caller-checked build or SDK source")
    intent.build.verify()
    intent.producer.verify()
    private_directory(intent.runtime)
    roots = (intent.build.intent.original.root, intent.build.intent.sdk.root,
             intent.build.intent.context.root, intent.producer.root, intent.build.intent.directory)
    provider.require(not any(intent.runtime.is_relative_to(root) or root.is_relative_to(intent.runtime) for root in roots),
                     "Go prepared runtime overlaps source or build inputs")
    provider.require(type(intent.plain) is bool and type(intent.arguments) is tuple and len(intent.arguments) <= 4096
                     and all(type(value) is str and "\0" not in value for value in intent.arguments),
                     "invalid Go lane or literal arguments")
    provider.require(sum(len(os.fsencode(value)) for value in intent.arguments) <= 1024 * 1024,
                     "Go application arguments exceed their byte budget")
    provider.require(isinstance(intent.python, Path) and intent.python.is_absolute()
                     and provider.same(python_prepared.file_identity(intent.python), intent.interpreter),
                     "Go supervisor interpreter differs from caller-owned input")
    provider.require(type(intent.policy) is dict and "go" in intent.policy.get("languages", [])
                     and "go_supervisor.py" in intent.producer.identities, "missing Go policy or fixed supervisor")
    selection = intent.build.receipt["selection"]
    provider.require(provider.same(intent.policy.get("context"), selection["context"]),
                     "Go policy context differs from compiled selection")
    functions = intent.policy.get("functions")
    provider.require(type(functions) is dict and set(functions) == {"include", "exclude"}
                     and all(type(functions[key]) is list and len(functions[key]) <= 4096
                             and all(type(value) is str and 0 < len(value) <= 4096 for value in functions[key])
                             for key in ("include", "exclude")), "invalid Go function policy selectors")
    provider.require(all(name_selected(row["name"], functions) for row in selection["functions"]),
                     "Go selected function is excluded by caller policy")


def name_selected(name: str, selectors: dict) -> bool:
    """The common name glob supports only star/question wildcards; brackets are literal."""
    def matches(patterns: list[str]) -> bool:
        return any(re.fullmatch("".join({"*": ".*", "?": "."}.get(char, re.escape(char))
                                      for char in pattern), name, re.DOTALL) for pattern in patterns)
    return matches(selectors["include"]) and not matches(selectors["exclude"])


def command(intent: Intent) -> list[str]:
    """The fixed caller-owned supervisor is the only executable launch recipe."""
    return [str(intent.python), "-I", "-S", "-B", str(intent.producer.root / "go_supervisor.py"),
            "--runtime", str(intent.runtime)]


def request(intent: Intent, launch_id: object) -> dict:
    """A producer nonce may identify this launch but cannot change caller intent."""
    provider.require(type(launch_id) is str and re.fullmatch("[0-9a-f]{32}", launch_id) is not None,
                     "invalid Go prepared launch ID")
    return {"schema_version": 1, "kind": "otelc.go.request", "profile": provider.PROFILE,
            "build": intent.build.identity, "runtime": str(intent.runtime), "policy": intent.policy,
            "arguments": list(intent.arguments), "plain": intent.plain, "launch_id": launch_id}


def plan(intent: Intent, original: dict) -> dict:
    """Bind a lane to its retained binary, original cwd and exact literal arguments."""
    name = "plain" if intent.plain else "instrumented"
    return {"schema_version": 1, "kind": "otelc.go.plan", "profile": provider.PROFILE,
            "request_sha256": provider.metadata_digest(original), "cwd": str(intent.build.intent.original.root),
            "argv": [str(intent.build.intent.directory / name), *intent.arguments],
            "binary": intent.build.receipt[name], "selection_sha256": intent.build.receipt["selection"]["sha256"],
            "source_complete": False}


def configuration(intent: Intent) -> dict:
    """Derive the complete scalar-call SDK configuration from the caller policy."""
    data = intent.policy
    selection = intent.build.receipt["selection"]
    return {"schema_version": CONFIG_VERSION, "service_name": data["resource"]["service_name"],
            "endpoint": data["export"]["endpoint"], "interval_ms": data["export"]["interval_ms"],
            "timeout_ms": data["export"]["timeout_ms"], "shutdown_timeout_ms": data["export"]["shutdown_timeout_ms"],
            "collection": data["metrics"]["collection"], "emission": data["metrics"]["emission"],
            "traces_enabled": data["traces"]["enabled"], "sample_ratio": data["traces"]["sample_ratio"],
            "functions": [row["name"] for row in selection["functions"]], "lifetimes": [],
            "max_live": data["lifetimes"]["max_live"], "boundaries": data["metrics"]["histogram_boundaries_seconds"],
            "policy_sha256": provider.policy_digest(data), "selection_sha256": selection["sha256"]}


def config_manifest(intent: Intent) -> dict | None:
    """Private configuration bytes must consume the complete independently derived policy."""
    path = intent.runtime / "config.json"
    if intent.plain:
        provider.require(not path.exists() and not path.is_symlink(), "plain Go lane unexpectedly has SDK configuration")
        return None
    observed, identity = files.read(path, private=True)
    provider.require(identity["size"] <= MAX_CONFIG_BYTES and provider.same(observed, configuration(intent)),
                     "Go runtime configuration differs from caller policy or byte budget")
    return {"schema_version": 1, "kind": "otelc.go-runtime-config", "directory": str(intent.runtime),
            "config": identity, "health_version": provider.PROTOCOLS["health"],
            "environment": {"OTELC_GO_RUNTIME": str(intent.runtime), "OTELC_GO_CONFIG_SHA256": identity["sha256"]}}


def manifest(intent: Intent, original: dict, resolved: dict, config: dict | None) -> dict:
    """Pin every top-level producer module to independently frozen SDK source bytes."""
    producer = [identity for name, identity in sorted(intent.producer.identities.items())
                if Path(name).parent == Path(".") and name.endswith(".py")]
    return {"schema_version": 1, "kind": "otelc.go.prepared", "profile": provider.PROFILE,
            "request_sha256": provider.metadata_digest(original), "plan_sha256": provider.metadata_digest(resolved),
            "config": config, "interpreter": intent.interpreter, "producer": producer, "source_complete": False}


def verify(response: object, intent: Intent, *, fresh: bool = True) -> Prepared:
    """Compare the whole response and retained documents with a reconstructed recipe."""
    validate_intent(intent)
    provider.require(type(fresh) is bool, "invalid Go runtime freshness request")
    if fresh:
        provider.require(not any((intent.runtime / name).exists() or (intent.runtime / name).is_symlink()
                                 for name in EXECUTION_FILES), "Go prepared runtime was already used")
    records = {name: files.read(intent.runtime / name, private=True) for name in DOCUMENTS}
    original, resolved, prepared = [records[name][0] for name in DOCUMENTS]
    expected_request = request(intent, original.get("launch_id"))
    expected_plan = plan(intent, expected_request)
    expected_manifest = manifest(intent, expected_request, expected_plan, config_manifest(intent))
    provider.require(provider.same(original, expected_request), "Go prepared request differs from caller intent")
    provider.require(provider.same(resolved, expected_plan), "Go prepared plan differs from fixed recipe")
    provider.require(provider.same(prepared, expected_manifest), "Go prepared manifest differs from frozen inputs")
    expected = {"schema_version": 1, "kind": "otelc.go.command", "profile": provider.PROFILE,
                "request": expected_request, "plan": expected_plan, "prepared": expected_manifest,
                "command": command(intent), "source_complete": False}
    provider.require(type(response) is dict and provider.same(response, expected), "Go prepare response differs from checked records")
    names = (*DOCUMENTS, *(("config.json",) if not intent.plain else ()))
    evidence = {name: files.file(intent.runtime / name, private=True)[:2] for name in names}
    expected_files = {name: records[name][1] for name in DOCUMENTS}
    if not intent.plain:
        expected_files["config.json"] = expected_manifest["config"]["config"]
    provider.require(all(provider.same(evidence[name][0], expected) for name, expected in expected_files.items()),
                     "Go prepared files changed during independent verification")
    result = Prepared(intent, response, evidence)
    result.verify()
    return result
