"""Fixed Node source launches and independent consumer checks of real receipts."""

import hashlib
import json
import os
from pathlib import Path
import re
import tomllib

import node_source as provider
import node_source_worker as worker
import node_inputs
import node_execution
import otelc_capture as capture
import sequences

ENVIRONMENT_KEYS = ("NODE_OPTIONS", "NODE_PATH", "NODE_PRESERVE_SYMLINKS", "NODE_EXTRA_CA_CERTS",
                    "NODE_ICU_DATA", "NODE_COMPILE_CACHE", "NODE_DISABLE_COMPILE_CACHE",
                    "NODE_COMPILE_CACHE_READONLY", "UV_THREADPOOL_SIZE", "TZ", "LANG", "LC_ALL",
                    "LC_CTYPE", "TMPDIR", "TEMP", "TMP")
REQUEST_FILE = "node-source-request.json"
PROCESS_FILE = "process.json"


def read(path: Path) -> dict:
    """Receipts must be bounded regular files in the owned runtime."""
    provider.require(path.is_file() and not path.is_symlink() and path.stat().st_size <= 32 * 1024 * 1024,
                     "missing, linked or oversized launch receipt: " + path.name)
    return capture.strict_json(path.read_bytes())


def same(actual, expected, reason: str) -> None:
    """Preserve JSON types, including the distinction between false and zero."""
    provider.require(json.dumps(actual, sort_keys=True, allow_nan=False) == json.dumps(expected, sort_keys=True, allow_nan=False), reason)


def file_identity(path: Path) -> dict:
    """Reproduce literal and resolved identity without accepting metadata-selected tools."""
    result = {"path": str(path), "resolved_path": str(path.resolve(strict=True)),
              "sha256": capture.file_digest(path), "size": path.stat().st_size}
    if path.is_symlink():
        result["symlink"] = os.readlink(path)
    return result


def environment_records(environment: dict) -> dict:
    """Record the fixed public allowlist from the consumer's sanitised environment."""
    return {key: ({"state": "present", "value": environment[key],
                   "sha256": hashlib.sha256(environment[key].encode()).hexdigest()}
                  if key in environment else {"state": "absent"}) for key in ENVIRONMENT_KEYS}


def command(root: Path, project: Path, entry: dict, tools: dict,
            folder: Path, lane: str, environment: dict) -> list:
    """Start only the embedded supervisor; request data cannot select Python code."""
    value = {"schema_version": 1, "provider": str(root), "project": str(project),
             "entry": str(project / entry["path"]), "runtime": str(folder / "node-runtime"),
             "policy": str(folder / "policy.toml"),
             "node": str(tools[entry["language"]]), "language": entry["language"],
             "compiler": entry["node_compiler"], "plain": lane == "baseline",
             "gc_fixture": sequences.collects(entry), "timeout_ms": entry["node_timeout_ms"]}
    worker.write(folder / REQUEST_FILE, value)
    worker.write(folder / "node-source-environment.json", environment_records(environment))
    return supervisor_command(tools, folder)


def supervisor_command(tools: dict, folder: Path) -> list:
    """Both launch and verification use the fixed embedded-module entrypoint."""
    here = Path(__file__).parent
    bootstrap = "import runpy,sys;sys.path.insert(0,sys.argv.pop(1));runpy.run_module('node_source_worker',run_name='__main__')"
    return [tools["python-host"], "-I", "-B", "-c", bootstrap, here, folder / REQUEST_FILE]


def expected_original(value: dict, configuration: dict, environment: dict) -> dict:
    """Derive original intent from consumer inputs, independently of SDK metadata."""
    paths = {"root": value["project"], "entry": value["entry"], "runtime": value["runtime"]}
    config = Path(value["policy"])
    return {"schema_version": 1, "profile": "node-source-v1", "policy": configuration,
            "policy_source": {**file_identity(config), "text": config.read_text()},
            "language": value["language"], "backend": value["compiler"], "plain": value["plain"],
            "gc_fixture": value["gc_fixture"], "cwd": value["project"], "node": value["node"], "arguments": [],
            "paths": {name: {"requested": path, "resolved": str(Path(path).resolve(strict=True))} for name, path in paths.items()},
            "environment": environment}


def expected_plan(original: dict, launch: str) -> dict:
    """The exact schema-3 policy has one fixed source-runtime translation."""
    policy = original["policy"]
    return {**policy, "language": original["language"], "backend": original["backend"],
            "plain": original["plain"], "launch_id": launch,
            "annotations": {"read_existing": False, "inject_generated": False},
            "source_matchers": policy["sources"], "function_matchers": policy["functions"],
            "lifetime_matchers": {key: policy["lifetimes"][key] for key in ("include", "exclude")},
            "runtime": {"root": original["paths"]["root"]["resolved"],
                        "directory": original["paths"]["runtime"]["resolved"],
                        "max_functions": 4096, "max_active_calls": 4096}}


def generated_files(root: Path, runtime: Path, value: dict, original: dict, plan: dict) -> list[dict]:
    """Recreate bootstrap and JSON bytes rather than trusting a producer command."""
    prefix = "node-plain" if value["plain"] else "node"
    files = {prefix + "-request.json": json.dumps(original, sort_keys=True) + "\n"}
    if not (value["plain"] and value["language"] == "javascript"):
        loader = "plain-source-loader.ts" if value["plain"] else "source-bootstrap.ts"
        files[prefix + "-plan.json"] = json.dumps(plan, sort_keys=True) + "\n"
        files[prefix + "-bootstrap.cjs"] = ("process.env.OTELC_NODE_PLAN = " + json.dumps(str(runtime / (prefix + "-plan.json")))
                                           + ";\nrequire(" + json.dumps(str(root / "adapters/node/src" / loader)) + ");\n")
    result = []
    for name, text in files.items():
        path = runtime / name
        provider.require(not path.is_symlink() and path.read_bytes() == text.encode(), "generated source launch input differs")
        result.append(file_identity(path))
    return result


def tooling(manifest: dict, root: Path, value: dict) -> None:
    """The installed closure has fixed groups, paths and complete file sets."""
    paths = {"launcher": provider.provider_files(root / "otelc", suffix=".py")}
    if not (value["plain"] and value["language"] == "javascript"):
        paths.update(adapter=provider.provider_files(root / "adapters/node/src"),
                     packages=provider.provider_files(root / "node_modules"),
                     package_metadata=[root / "package.json", root / "package-lock.json"])
        if not value["plain"]:
            version = manifest["runtime"]["version"]
            provider.require(type(version) is str and re.fullmatch(r"\d+\.\d+\.\d+", version) is not None, "invalid selected Node version")
            paths["observer"] = [root / "build/tools" / ("otelc_node_observer-" + version + ".node")]
    expected = {name: [file_identity(path) for path in (sorted(items, key=str) if name in ("launcher", "adapter", "packages") else items)]
                for name, items in paths.items()}
    same(manifest["tooling"], expected, "installed source launcher closure differs")


def process_receipts(folder: Path, value: dict) -> dict:
    """Keep supervisor, application and SDK identities distinct and actually completed."""
    supervisor = read(folder / PROCESS_FILE)
    application = read(folder / "node-source-application.json")
    provider.require(type(supervisor.get("pid")) is int and supervisor["pid"] > 1
                     and type(application.get("pid")) is int and application["pid"] > 1
                     and application["pid"] != supervisor["pid"], "invalid actual process identities")
    same(application, {"pid": application["pid"], "supervisor_pid": supervisor["pid"], "group": supervisor["pid"]},
         "application escaped its owned supervisor group")
    same(read(folder / "node-source-application-exit.json"), {"pid": application["pid"], "returncode": 0}, "actual Node application did not exit successfully")
    completion = read(folder / "node-source-completion.json")
    sdk = completion.get("sdk_pid")
    if not value["plain"]:
        provider.require(type(sdk) is int and sdk > 1 and sdk not in (supervisor["pid"], application["pid"]), "independent SDK PID is missing")
    same(completion, {"application_pid": application["pid"], "application_returncode": 0,
                      "sdk_pid": None if value["plain"] else sdk, "sdk_exited": None if value["plain"] else True,
                      "phase": None if value["plain"] else "closed", "inputs_verified": True}, "source run did not finish and verify its inputs")
    return completion


def launch_manifest(manifest: dict, value: dict, original: dict, root: Path, entry: dict) -> None:
    """Bind the declared source protocol to consumer intent and the actual supervisor."""
    fields = {"schema_version", "request", "preloads", "launch_id", "language", "backend", "plain", "root", "argv", "cwd",
              "launcher_pid", "node", "runtime", "entry", "plan_sha256", "resolved_plan", "tooling_environment", "ambient_sha256",
              "tooling", "generated", "entry_context"}
    provider.require(type(manifest) is dict and set(manifest) == fields and type(manifest["schema_version"]) is int
                     and manifest["schema_version"] == provider.PROTOCOLS["source"] and type(manifest["launch_id"]) is str
                     and re.fullmatch("[a-f0-9]{32}", manifest["launch_id"]) is not None, "unsupported source launch receipt")
    same(manifest["request"], original, "public source request differs from consumer intent")
    plan = expected_plan(original, manifest["launch_id"])
    same(manifest["resolved_plan"], plan, "source plan differs from common policy")
    provider.require(manifest["plan_sha256"] == capture.digest(json.dumps(plan, sort_keys=True).encode()), "source plan digest differs")
    for key, expected in {"language": value["language"], "backend": value["compiler"], "plain": value["plain"],
                          "root": value["project"], "cwd": value["project"], "argv": worker.expected_argv(value),
                          "entry": file_identity(Path(value["entry"])), "node": file_identity(Path(value["node"]))}.items():
        same(manifest[key], expected, "source launch " + key + " differs")
    same(manifest["generated"], generated_files(root, Path(value["runtime"]), value, original, plan), "source generated file set differs")
    provider.require(manifest["runtime"].get("version") == entry["node_context"]["node_version"].removeprefix("v"),
                     "Node version differs from actual source inspection")
    same(manifest["ambient_sha256"], {}, "unexpected ambient Node loader controls")
    expected_environment = {key: ({"state": "absent"} if key.startswith("NODE_") else record)
                            for key, record in original["environment"].items()}
    same(manifest["tooling_environment"], expected_environment, "tooling environment differs from sanitised consumer intent")
    preloads = manifest["preloads"]
    provider.require(type(preloads) is dict and type(preloads.get("schema_version")) is int and preloads["schema_version"] == 1,
                     "unsupported source preload receipt")
    for key, expected in {"argv": None, "entries": [], "gaps": [], "requests": [], "resolution_flags": [],
                          "coverage": "resolved_entries_and_nearest_package_context", "cwd": value["project"]}.items():
        same(preloads.get(key), expected, "unrequested Node preloads or resolution controls")
    tooling(manifest, root, value)


def verify(root: Path, project: Path, entry: dict, tools: dict, folder: Path, lane: str) -> None:
    """Qualify real process/launch/input receipts after the supervisor has terminated."""
    expected = {"schema_version": 1, "provider": str(root), "project": str(project),
                "entry": str(project / entry["path"]), "runtime": str(folder / "node-runtime"),
                "policy": str(folder / "policy.toml"), "node": str(tools[entry["language"]]),
                "language": entry["language"], "compiler": entry["node_compiler"], "plain": lane == "baseline",
                "gc_fixture": sequences.collects(entry), "timeout_ms": entry["node_timeout_ms"]}
    same(read(folder / REQUEST_FILE), expected, "consumer supervisor request changed")
    # Checked receipts cannot select paths for subsequent evidence reads.
    value = expected
    completion = process_receipts(folder, value)
    runtime = Path(value["runtime"])
    prefix = "node-plain" if value["plain"] else "node"
    manifest_path = runtime / (prefix + "-launch.json")
    manifest = read(manifest_path)
    configuration = tomllib.loads(Path(value["policy"]).read_text())
    same(configuration, provider.configuration(entry, configuration["export"]["endpoint"], configuration["resource"]["service_name"]),
         "common source policy no longer matches the selected entry")
    original = expected_original(value, configuration, read(folder / "node-source-environment.json"))
    launch_manifest(manifest, value, original, root, entry)
    process = read(folder / PROCESS_FILE)
    same(process["argv"], list(map(str, supervisor_command(tools, folder))), "actual supervisor command differs")
    provider.require(manifest["launcher_pid"] == process["pid"], "SDK launcher is not the actual supervisor")
    same(read(folder / "node-source-command.json"), worker.expected_argv(value), "actual application command differs")
    inputs = read(runtime / (prefix + "-inputs.json"))
    fields = {"schema_version", "launch_id", "phase", "action_delivery_verified", "loaded_inputs", "launch_manifest",
              "module_execution_protocol", "module_outcomes", "module_execution_observation"}
    if not value["plain"]:
        fields |= {"application_pid", "sdk_pid", "sdk_report"}
    provider.require(type(inputs) is dict and set(inputs) == fields and type(inputs["schema_version"]) is int
                     and inputs["schema_version"] == provider.PROTOCOLS["source"] and inputs["launch_id"] == manifest["launch_id"]
                     and inputs["phase"] == "verified" and inputs["action_delivery_verified"] is False,
                     "source input verification is missing, failed or claims action delivery")
    same(inputs["launch_manifest"], file_identity(manifest_path), "verified inputs belong to another source launch")
    node_inputs.verify(inputs["loaded_inputs"], value, manifest)
    provider.require(type(inputs["module_execution_protocol"]) is int
                     and inputs["module_execution_protocol"] == provider.PROTOCOLS["execution"],
                     "invalid source module execution protocol")
    outcomes = node_execution.verify(inputs["loaded_inputs"], value, completion["application_pid"])
    same(inputs["module_outcomes"], outcomes, "SDK module outcomes differ from independent raw execution evidence")
    observation = "native_plain_unavailable" if value["plain"] and value["language"] == "javascript" else "injected_body_entry"
    same(inputs["module_execution_observation"], observation, "module execution observation scope differs")
    verify_loaded(inputs["loaded_inputs"], value, entry, completion, original)
    if not value["plain"]:
        status_path = runtime / "node-status.json"
        report = read(status_path)
        fifo = runtime / "node-events.fifo"
        provider.require(not fifo.exists() and not fifo.is_symlink(), "inactive source transport was not removed")
        same(read(folder / "node-source-transport.json"), {"path": str(fifo), "kind": "fifo", "mode": 0o600,
             "sdk_pid": completion["sdk_pid"], "removed_after_sdk_exit": True}, "source transport cleanup receipt differs")
        same(inputs["sdk_report"], file_identity(status_path), "SDK status changed after input verification")
        for key in ("application_pid", "sdk_pid"):
            same(inputs[key], completion[key], "SDK input verification belongs to another process")
        same(read(runtime / "node-sdk-ready.json"), {"schema_version": 1, "pid": completion["sdk_pid"], "launch_id": manifest["launch_id"]}, "SDK startup belongs to another launch")
        provider.require(report["launch_id"] == manifest["launch_id"] and report["pid"] == completion["application_pid"]
                         and report["sdk_pid"] == completion["sdk_pid"], "SDK final status belongs to another process or launch")


def verify_loaded(records: list, value: dict, entry: dict, completion: dict, original: dict) -> None:
    """Check original startup/source and selected module formats independently."""
    provider.require(type(records) is list, "missing actual source reads")
    if value["plain"] and value["language"] == "javascript":
        same(records, [], "plain JavaScript unexpectedly claims a loader journal")
        return
    starts = [record for record in records if record.get("kind") == "startup"]
    argv = worker.expected_argv(value)
    expected = {"kind": "startup", "path": value["entry"],
                "startup": {"pid": completion["application_pid"], "node": value["node"], "cwd": value["project"],
                            "argv": [argv[0], argv[-1]], "exec_argv": argv[1:-1], "environment": original["environment"]}}
    same(starts, [expected], "actual Node startup differs from original consumer intent")
    provider.require(records and records[0] == expected, "actual startup must precede source loading")
    source = Path(value["entry"])
    reads = [record for record in records if record.get("kind") == "source" and record.get("path") == str(source)]
    provider.require(reads and all(record.get("sha256") == capture.file_digest(source)
                                  and type(record.get("size")) is int and record["size"] == source.stat().st_size for record in reads),
                     "actual entry source read is missing or changed")
    phases = ["execution_started"]
    if value["language"] == "typescript":
        phases.append("compiled")
    for phase in phases:
        emissions = [record for record in records if record.get("kind") == phase and record.get("path") == str(source)]
        provider.require(emissions and all(record.get("format") == entry["node_context"]["format"] for record in emissions),
                         "actual selected execution/compiler format differs from inspected source context")
    # The reviewed SDK finish() checks compiler semantics; the consumer separately
    # rechecks raw journal continuity, fixed profiles, origins and retained bytes.
    # Neither receipt authenticates an individual function invocation.
