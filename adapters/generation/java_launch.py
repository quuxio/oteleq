"""Prepare only fixed Java argv, verify inputs, and retain the short owned runtime."""
from collections.abc import Callable, Iterator
from contextlib import contextmanager
import json
import os
from pathlib import Path
import re
import shutil
import stat
import sys
import tempfile
from urllib.parse import unquote

import java_provider as provider
import java_profiles
import otelc_capture as capture

MAX_RUNTIME_BYTES = 32 * 1024 * 1024
MAX_RUNTIME_FILES = 64
LAUNCH_FILE = "prepared-launch.json"
CLASS_LOG = "class-load.log"
AGENT_CONFIG = "agent.properties"
PLAN_CONFIG = "plan.properties"
APPLICATION_FILE = "prepared-application.json"
CONTROL_SOCKET = "control.sock"
IDENTITY_FIELDS = {"path", "sha256", "size", "inode", "device", "mtime_ns"}
LAUNCH_FIELDS = {"schema_version", "language", "plain", "jvm_profile", "agent_diagnostics", "health_report",
                 "selection_sha256", "argv", "main_class", "ordered_classpath", "application", "tooling",
                 "java_version", "policy_sha256", "loaded_origins", "control_socket"}


def identity(path: Path) -> dict:
    """Check the actual regular file; metadata cannot choose a different input."""
    info = path.lstat()
    provider.require(stat.S_ISREG(info.st_mode), "input is not a regular file: " + str(path))
    result = {"path": str(path), "sha256": capture.file_digest(path), "size": info.st_size,
              "inode": info.st_ino, "device": info.st_dev, "mtime_ns": info.st_mtime_ns}
    after = path.lstat()
    provider.require((info.st_dev, info.st_ino, info.st_size, info.st_mtime_ns, info.st_ctime_ns)
                     == (after.st_dev, after.st_ino, after.st_size, after.st_mtime_ns, after.st_ctime_ns),
                     "input changed while reading: " + str(path))
    return result


def files(records: list, expected: set[Path]) -> None:
    """Validate complete declared file identities before querying those known paths."""
    provider.require(type(records) is list and all(type(row) is dict and set(row) == IDENTITY_FIELDS
                     and type(row["path"]) is str for row in records), "invalid input identities")
    paths = [row["path"] for row in records]
    provider.require(len(set(paths)) == len(paths) and set(paths) == {str(path) for path in expected},
                     "missing, duplicate or unexpected prepared input")
    for row in records:
        provider.require(all(type(row[key]) is int for key in ("size", "inode", "device", "mtime_ns"))
                         and row == identity(Path(row["path"])), "prepared input changed: " + row["path"])


def agent_values(data: dict, owner: str, method: str, profile: str = java_profiles.STOCK) -> dict:
    """The generated profile enables one source-bound method and no lifetimes."""
    values = {"otel.javaagent.enabled": "true", "otel.sdk.disabled": "false",
            "otel.service.name": data["resource"]["service_name"], "otel.resource.attributes": "otelc.language=java",
            "otel.exporter.otlp.endpoint": data["export"]["endpoint"], "otel.exporter.otlp.protocol": "http/protobuf",
            "otel.exporter.otlp.timeout": str(data["export"]["timeout_ms"]),
            "otel.metric.export.interval": str(data["export"]["interval_ms"]), "otel.metrics.exporter": "otlp",
            "otel.logs.exporter": "none", "otel.traces.exporter": "otlp",
            "otel.traces.sampler": "parentbased_traceidratio", "otel.traces.sampler.arg": "1.0",
            "otel.instrumentation.common.default-enabled": "false", "otel.instrumentation.methods.enabled": "true",
            "otel.instrumentation.otelc-lifetimes.enabled": "true",
            "otel.instrumentation.opentelemetry-api.enabled": "true",
            "otel.instrumentation.methods.include": owner + "[" + method + "]"}
    if java_profiles.name(profile) == java_profiles.SAFE:
        values["otel.instrumentation.methods.enabled"] = "false"
        values["otel.instrumentation.otelc-methods.enabled"] = "true"
    return values


def properties(values: dict) -> str:
    """Encode the public fixed Java properties profile, including Unicode units."""
    def escape(value):
        output = ""
        for unit in value:
            if unit in "\\:=#! \n\r\t":
                output += {"\n": "\\n", "\r": "\\r", "\t": "\\t"}.get(unit, "\\" + unit)
            elif ord(unit) > 126:
                encoded = unit.encode("utf-16-be")
                output += "".join("\\u" + encoded[i:i + 2].hex() for i in range(0, len(encoded), 2))
            else:
                output += unit
        return output
    return "".join(escape(key) + "=" + escape(value) + "\n" for key, value in sorted(values.items()))


def target(entry: dict, application: dict, project: Path) -> tuple[str, str]:
    """The declared source owner must have an actual compiler class binding."""
    owner, method = entry["otelc_function"].split("(", 1)[0].rsplit(".", 1)
    binding = application["bindings"].get(owner)
    provider.require(type(binding) is dict and binding["source"] == str(project / entry["path"])
                     and binding["policy_path"] == entry["path"], "selected method has no compiler-owned source binding")
    return owner, method


def expected_argv(root: Path, java: Path, classes: Path, main: str, runtime: Path,
                  data: dict, owner: str, method: str, plain: bool, profile: str = java_profiles.STOCK) -> list[str]:
    """SDK metadata may verify this recipe; it cannot choose executables or flags."""
    args = [str(java), "-Xshare:off", "-Xlog:class+load=info:file=" + str(runtime / CLASS_LOG)]
    if not plain:
        args[1:1] = ["-Dotel.javaagent.logging=simple",
                     "-Dio.opentelemetry.javaagent.slf4j.simpleLogger.logFile=" + str(runtime / "agent.log")]
        if java_profiles.name(profile) == java_profiles.SAFE:
            args += ["-Xbootclasspath/a:" + str(root / java_profiles.PATCH)]
        args += ["-javaagent:" + str(root / provider.AGENT), "-Dotel.javaagent.extensions=" + str(root / provider.EXTENSION),
                 "-Dotel.javaagent.configuration-file=" + str(runtime / AGENT_CONFIG),
                 "-Dotelc.plan=" + str(runtime / PLAN_CONFIG), "-Dotelc.traces.enabled=true",
                 "-Dotelc.lifetime.types=", "-Dotelc.lifetime.resources=", "-Dotelc.lifetime.max-live=4096",
                 "-Dotelc.lifetime.release=close"]
        args += ["-D" + key + "=" + value for key, value in sorted(agent_values(data, owner, method, profile).items())]
    return args + ["-cp", str(classes), main]


def plan_values(runtime: Path, data: dict, selection: dict) -> dict:
    """Verify policy-owned controls, hashes and shutdown budget independently."""
    return {"control.socket": str(runtime / CONTROL_SOCKET), "metrics.collection": "true", "metrics.emission": "true",
            "metrics.buckets": ",".join(map(str, data["metrics"]["histogram_boundaries_seconds"])),
            "health.report": str(runtime / "health.json"), "health.policy-sha256": provider.digest(data),
            "health.selection-sha256": provider.digest(selection),
            "health.shutdown-timeout-ms": str(data["export"]["shutdown_timeout_ms"])}


def verify(launch: dict, *, root: Path, project: Path, folder: Path, tools: dict,
           runtime: Path, entry: dict, data: dict, plain: bool) -> None:
    """Bind the full public response, argv and loaded inputs before and after Java."""
    application_path = folder / APPLICATION_FILE
    application = capture.strict_json(application_path.read_bytes())
    classes = folder / "scratch/classes"
    java = tools["java"].resolve(strict=True)
    owner, method = target(entry, application, project)
    profile = java_profiles.name(entry.get("java_profile", java_profiles.STOCK))
    provider.require(type(launch) is dict and set(launch) == LAUNCH_FIELDS
                     and type(launch["schema_version"]) is int and launch["schema_version"] == 1
                     and launch["language"] == "java" and launch["plain"] is plain
                     and launch["jvm_profile"] == "diagnostic-no-cds", "unsupported prepared launch identity")
    provider.require(launch["argv"] == expected_argv(root, java, classes, application["main_class"], runtime,
                                                   data, owner, method, plain, profile), "SDK changed the fixed Java launch recipe")
    provider.require(launch["main_class"] == application["main_class"] and launch["ordered_classpath"] == [str(classes)]
                     and type(launch["java_version"]) is str and launch["java_version"], "prepared main/classpath/version differs")
    provider.require(launch["policy_sha256"] == provider.digest(data)
                     and launch["loaded_origins"] == str(runtime / CLASS_LOG), "prepared policy/origin identity differs")
    for key, filename in (("agent_diagnostics", "agent.log"), ("health_report", "health.json"), ("control_socket", CONTROL_SOCKET)):
        provider.require(launch[key] == (None if plain else str(runtime / filename)), "prepared runtime path differs: " + key)
    verify_application(launch["application"], application, application_path, classes)
    tooling = {java}
    if plain:
        provider.require(launch["selection_sha256"] is None, "plain launch has an instrumented selection")
    else:
        selection = {"methods": {owner: [method]}, "types": [], "resources": []}
        provider.require(launch["selection_sha256"] == provider.digest(selection)
                         and capture.strict_json((runtime / "selection.json").read_bytes()) == selection,
                         "SDK changed resolved method selection")
        provider.require((runtime / AGENT_CONFIG).read_text() == properties(agent_values(data, owner, method, profile))
                         and (runtime / PLAN_CONFIG).read_text() == properties(plan_values(runtime, data, selection)),
                         "SDK changed agent configuration or live controls")
        tooling |= {root / provider.AGENT, root / provider.EXTENSION,
                    runtime / AGENT_CONFIG, runtime / PLAN_CONFIG, runtime / "selection.json"}
        if profile == java_profiles.SAFE:
            tooling.add(root / java_profiles.PATCH)
    files(launch["tooling"], tooling)


def verify_application(value: dict, application: dict, manifest: Path, classes: Path) -> None:
    """Require the actual complete compiler product inventory and source bindings."""
    provider.require(type(value) is dict and set(value) == {"manifest", "classpath", "main_class", "ordered_classpath", "sources", "bindings"}
                     and value["bindings"] == application["bindings"] and value["main_class"] == application["main_class"]
                     and value["ordered_classpath"] == [str(classes)], "prepared compiler application binding differs")
    files([value["manifest"]], {manifest})
    files(value["classpath"], {path for path in classes.rglob("*") if path.is_file()})
    files(value["sources"], {Path(binding["source"]) for binding in application["bindings"].values()})


def prepare(root: Path, project: Path, folder: Path, tools: dict, runtime: Path,
            entry: dict, data: dict, plain: bool, env: dict, execute: Callable) -> list[str]:
    """Use the public prepare-only API, then accept only the independently fixed argv."""
    config = folder / "policy.toml"
    command = [sys.executable, "-m", "otelc", "--config", config, "java", "--manifest",
               folder / APPLICATION_FILE, "--runtime", runtime, "--prepare-only", "--diagnostic-profile"]
    if plain:
        command.append("--plain")
    result = execute(command, root, provider.environment(root, tools, folder, env), folder / "sdk-prepare",
                     max_output_bytes=provider.MAX_METADATA)
    provider.require(result.returncode == 0, "public SDK preparation failed; inspect sdk-prepare/stderr")
    launch = capture.strict_json(result.stdout)
    verify(launch, root=root, project=project, folder=folder, tools=tools, runtime=runtime,
           entry=entry, data=data, plain=plain)
    (folder / LAUNCH_FILE).write_text(json.dumps(launch, indent=2) + "\n")
    return launch["argv"]


def archive(runtime: Path, folder: Path) -> None:
    """Retain regular runtime outputs and their original identities before cleanup."""
    provider.require(runtime.is_dir() and not runtime.is_symlink(), "SDK runtime was replaced")
    paths = list(runtime.rglob("*"))
    provider.require(len(paths) <= MAX_RUNTIME_FILES and all(not path.is_symlink() for path in paths),
                     "SDK runtime has links or too many outputs")
    records = {}
    total = 0
    for path in sorted(paths):
        if path.is_dir():
            continue
        info = path.lstat()
        provider.require(stat.S_ISREG(info.st_mode), "SDK runtime contains a special file")
        total += info.st_size
        provider.require(total <= MAX_RUNTIME_BYTES, "SDK runtime metadata exceeds its capture budget")
        records[path.relative_to(runtime).as_posix()] = identity(path)
    shutil.copytree(runtime, folder / "sdk-runtime")
    (folder / "runtime-archive.json").write_text(json.dumps({"original": str(runtime), "files": records}, indent=2) + "\n")


@contextmanager
def runtime(entry: dict, folder: Path, *, source_roots: tuple[Path, ...] = ()) -> Iterator[Path | None]:
    """The SDK socket needs a short path; all runtime files remain caller-owned."""
    if not provider.prepared(entry):
        yield None
        return
    provider.require(os.name == "posix", "prepared runtime requires qualified POSIX control sockets")
    with tempfile.TemporaryDirectory(prefix="oej-", dir=capture.temporary_parent(*source_roots)) as temporary:
        path = Path(temporary).resolve() / "r"
        provider.require(len(os.fsencode(path / CONTROL_SOCKET)) <= 100,
                         "runtime socket path exceeds 100 bytes; select a shorter TMPDIR before planning")
        try:
            yield path
        finally:
            if path.exists() or path.is_symlink():
                archive(path, folder)


def origins(runtime: Path, folder: Path, entry: dict) -> None:
    """Required application/driver classes must load from the retained class output."""
    path = runtime / CLASS_LOG
    provider.require(path.is_file() and path.stat().st_size <= MAX_RUNTIME_BYTES, "missing or oversized JVM origin log")
    application = capture.strict_json((folder / APPLICATION_FILE).read_bytes())
    loaded = {}
    for line in path.read_text().splitlines():
        match = re.search(r"\] ([^ ]+) source: (.+)$", line)
        if match and match[1] in application["bindings"]:
            source = unquote(match[2])
            provider.require(source == "file:" + str(folder / "scratch/classes") + "/", "application class loaded from another origin")
            provider.require(match[1] not in loaded, "duplicate application classloader identity")
            loaded[match[1]] = match[2]
    owner = entry["otelc_function"].split("(", 1)[0].rsplit(".", 1)[0]
    provider.require({owner, application["main_class"]} <= set(loaded), "selected application/driver origin is missing")
    (folder / "verified-origins.json").write_text(json.dumps(loaded, indent=2) + "\n")
