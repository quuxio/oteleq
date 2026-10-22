"""External generated test workflow; Rust CLI/comparator with compiler-specific workers."""
import argparse
from collections.abc import Collection
import importlib.util
import json
import os
from pathlib import Path
import shutil
import signal
import subprocess
import sys
import tempfile
import time
import tomllib
import uuid

import discovery
import go_project
import go_receivers
import cpp_receivers
import filesystem_effects
import http_effects
import harness
import java_receivers
import java_build
import java_launch
import java_live
import java_control_receipt
import java_provider
import java_profiles
import java_project
import java_archive_context
import java_telemetry
import node_receivers
import node_project
import owned_workspace
import native_profile
import otelc_capture as capture
import otelc_collection
import policy as project_policy
import python_project
import shrinking
import sequences
import typed_capture
import typescript_provider

VERSION = 1
MAX_FILE = 8 * 1024 * 1024
MAX_TREE = 256 * 1024 * 1024
MAX_OUTPUT = 4 * 1024 * 1024
OWNED_MARKER = owned_workspace.MARKER
PLAN_FILE = 'plan.json'
GENERATED_MANIFEST = 'generated-manifest.json'
TYPED_BUNDLE = 'typed-bundle.json'
BUILD_IDENTITIES = 'build-identities.json'
README_FILE = 'README.txt'
COMMANDS = ("plan", "generate", "run", "replay", "clean", "export-tests", "shrink")


def write(path, data):
    path.write_text(json.dumps(data, sort_keys=True, indent=2) + "\n")


def read(path):
    if path.stat().st_size > MAX_TREE:
        raise ValueError("document exceeds size limit")
    return capture.strict_json(path.read_text())


def snapshot_file_size(path: Path) -> int:
    """Reject non-regular snapshot entries before measuring or hashing their bytes."""
    if not path.is_file():
        raise ValueError("source contains a non-regular file")
    return path.stat().st_size


def manifest(root: Path, *, excluded: Collection[str] = (), excluded_files: Collection[str] = (),
             excluded_roots: Collection[str] = (),
             max_file_bytes: int | None = None) -> dict[str, str]:
    """Fingerprint all private contents; only original source walks exclude build trees."""
    result, total = {}, 0
    file_limit = MAX_FILE if max_file_bytes is None else max_file_bytes
    for directory, names, files in capture.walk_tree(root):
        base = Path(directory)
        names[:] = sorted(n for n in names if n not in excluded
                          and (base / n).relative_to(root).as_posix() not in excluded_roots)
        files = [name for name in files if (base / name).relative_to(root).as_posix() not in excluded_files]
        for name in names + files:
            if (base / name).is_symlink():
                raise ValueError("source symlink requires an explicit build recipe: " + str(base / name))
        for name in sorted(files):
            path = base / name
            size = snapshot_file_size(path)
            total += size
            if size > file_limit or total > MAX_TREE or len(result) >= 10000:
                raise ValueError("source snapshot limit exceeded")
            result[path.relative_to(root).as_posix()] = capture.file_digest(path)
    return result


def identity(document):
    return capture.digest(json.dumps(document, sort_keys=True).encode())


def worker_input(folder, input_data):
    if input_data is None:
        return Path(os.devnull)
    if len(input_data) > MAX_FILE * 2:
        raise ValueError("worker input exceeds limit")
    path = folder / "worker-input.json"
    path.write_bytes(input_data)
    return path


def live_process_group(group: int) -> bool:
    """Check a denied cleanup conservatively without exposing process arguments."""
    result = subprocess.run(["/bin/ps", "-axo", "pid=,pgid=,stat="], capture_output=True,
                            check=False, timeout=5)
    if result.returncode or len(result.stdout) > MAX_FILE:
        raise ValueError("process-group cleanup could not be verified")
    for row in result.stdout.decode("ascii").splitlines():
        process_id, process_group, status = row.split()
        if not process_id.isdecimal() or not process_group.isdecimal():
            raise ValueError("process-group cleanup returned an invalid identity")
        if int(process_group) == group and not status.startswith(("Z", "X")):
            return True
    return False


def kill_group(group: int) -> None:
    """A denied signal is benign only after verifying no live group members."""
    try:
        os.killpg(group, signal.SIGKILL)
    except ProcessLookupError:
        pass
    except PermissionError:
        # A denied signal does not establish that cleanup completed. Accept
        # only verified absence; live descendants remain an error.
        if live_process_group(group):
            raise


def finish_process(process: subprocess.Popen) -> None:
    """Clean up the owned group and reap without hiding a denied live group."""
    try:
        kill_group(process.pid)
    except (OSError, ValueError, subprocess.SubprocessError):
        # Waiting for a denied live leader must not become an unbounded hang.
        try:
            process.wait(timeout=1)
        except subprocess.TimeoutExpired:
            pass
        raise
    else:
        process.wait()


def monitor_process(process, out, err, maximum, deadline, interaction):
    """Keep process budgets active while advancing optional private checkpoints."""
    failure = None
    while process.poll() is None:
        if time.monotonic() > deadline:
            failure = "process timeout"
        if out.stat().st_size + err.stat().st_size > maximum:
            failure = "process output limit exceeded"
        if failure:
            break
        if interaction is not None:
            interaction.poll(process, deadline)
        time.sleep(0.01)
    if interaction is not None and failure is None:
        interaction.finish(process)
    return failure


def execute(command, cwd, env=None, folder=None, timeout=60, input_data=None, *, max_output_bytes=None, record_process=False, interaction=None):
    """Trusted local execution with wall time/output limits and process-group cleanup."""
    if folder is None:
        with tempfile.TemporaryDirectory(prefix="oteleq-discover-") as directory:
            return execute(command, cwd, env, Path(directory), timeout, input_data,
                           max_output_bytes=max_output_bytes, record_process=record_process, interaction=interaction)
    maximum = MAX_OUTPUT if max_output_bytes is None else max_output_bytes
    folder.mkdir(parents=True, exist_ok=True)
    out, err = folder / "stdout", folder / "stderr"
    input_path = worker_input(folder, input_data)
    with out.open("wb") as stdout, err.open("wb") as stderr, input_path.open("rb") as stdin:
        process = subprocess.Popen([str(p) for p in command], cwd=cwd, env=env,
                                   stdin=stdin, stdout=stdout, stderr=stderr, start_new_session=True)
        deadline = time.monotonic() + timeout
        failure = None
        try:
            if record_process:
                write(folder / "process.json", {"pid": process.pid, "argv": list(map(str, command))})
            failure = monitor_process(process, out, err, maximum, deadline, interaction)
        finally:
            # Descendants cannot keep running after the leader exits or interrupts the host.
            finish_process(process)
    if failure or out.stat().st_size + err.stat().st_size > maximum:
        raise ValueError(failure or "process output limit exceeded")
    return subprocess.CompletedProcess(command, process.returncode, out.read_bytes(), err.read_bytes())


def source_outside(path, *roots):
    candidate = path.resolve()
    if any(candidate.is_relative_to(root.resolve()) for root in roots):
        raise ValueError("generated outputs must be outside the source and otelc repositories")
    return candidate


def entry_identity(entry):
    language = entry["language"]
    prefix = str(Path(entry["path"]).with_suffix("")).replace("/", ".")
    if language == "c":
        return entry["name"]
    if language == "cpp":
        return entry.get("cpp_function", {}).get("compiler_identity", entry["name"] + "(" + ", ".join(entry["parameters"]) + ")")
    if language == "java":
        package = entry.get("package", "")
        types = ["java.lang.String" if t == "String" else t for t in entry["parameters"]]
        return (package + "." if package else "") + entry["name"] + "(" + ",".join(types) + ")"
    return prefix + "." + entry["name"]


def snapshot_source(source, workspace, contents):
    snapshot = workspace / "snapshot"
    snapshot.mkdir()
    for name, sha in contents.items():
        path = snapshot / name
        path.parent.mkdir(parents=True, exist_ok=True)
        shutil.copyfile(source / name, path)
        if capture.file_digest(path) != sha:
            raise ValueError("source changed while taking snapshot")
    return snapshot


def discovery_tools(root: Path, language: str, adapters: dict) -> tuple[dict, dict]:
    """Resolve the selected compiler/runtime tools and their provider identities."""
    rust_backend = adapters.get("rust", {}).get("backend", "compiler")
    selected = capture.selected_tools(root, language)
    if language == "java":
        selected["javac"] = capture.tool_path(str(selected["java"].parent / "javac"))
        selected["java-modules"] = java_build.module_image(selected["java"])
        if adapters.get("java", {}).get("profile") == java_profiles.ARCHIVES:
            selected["javap"] = capture.tool_path(str(selected["java"].parent / "javap"))
    qualified = (java_provider.artefacts(root, selected, adapters["java"].get("profile", java_profiles.STOCK))
                 if language == "java" and adapters.get("java", {}).get("backend") == "prepared"
                 else capture.artefacts(root, language, selected, rust_backend=rust_backend))
    return selected, qualified


def discover_file(name, language, root, snapshot, workspace, tools, artefacts, adapter_state=None):
    adapter_state = adapter_state or {}
    adapters = adapter_state.get("configuration", {})
    try:
        if language not in tools:
            tools[language], artefacts[language] = discovery_tools(root, language, adapters)
        def discover_execute(command, cwd, input_data=None, *, max_output_bytes=None):
            environment = capture.environment(snapshot, tools[language], "oteleq-discovery", root)
            environment.update({"GOCACHE": str(workspace / "go-cache/build"), "GOMODCACHE": str(workspace / "go-cache/modules"), "GOTOOLCHAIN": "local",
                                "OTELEQ_EXECUTABLE": os.environ["OTELEQ_EXECUTABLE"]})
            if language == "go" and adapters.get("go", {}).get("module_roots"):
                environment.update(go_project.environment(adapters["go"]))
            if language == "typescript":
                environment["OTELC_TYPESCRIPT_BACKEND"] = adapters.get("typescript", {}).get("backend", "source")
            return execute(command, cwd, environment, input_data=input_data,
                           max_output_bytes=max_output_bytes)
        if language == "go" and adapters.get("go", {}).get("module_roots"):
            return go_project.discover(snapshot / name, snapshot, adapters["go"], tools[language]["go"],
                                       discover_execute, adapter_state.setdefault("go_cache", {}))
        discovered = discovery.discover(snapshot / name, language, root, tools[language], discover_execute)
        if language in ("javascript", "typescript"):
            original = Path(adapter_state["source"]) if "source" in adapter_state else None
            discovered.update(node_project.inventory_context(snapshot / name, snapshot, original, language,
                                                             root, tools[language][language], discover_execute))
        return discovered
    except (ValueError, OSError, KeyError, SyntaxError, RecursionError) as error:
        return {"functions": [{"name": "<parse-or-tool-gap>", "line": 1, "parameters": [],
                               "output": "unknown", "reason": str(error), "inventory_gap": True}], "globals": []}


def qualify_inputs(entry: dict, count: int) -> None:
    """Freeze generated domain requests before checking the common corpus."""
    if "input_domains" in entry and "input_cases" not in entry:
        entry["input_cases"] = harness.domain_cases(entry, count)
    harness.corpus(entry, count)


def qualify_entry(entry, snapshot, count):
    if entry["reason"]:
        return "blocked"
    try:
        node_project.require_callable(entry)
        if entry.get("go_shadowed_recovery", False):
            raise ValueError("shadowed Go panic/recover requires an observation fixture")
        qualify_inputs(entry, count)
        outputs = harness.INTEGERS | harness.FLOATS | harness.BOOLS | harness.VOIDS | harness.STRINGS
        if entry["language"] in ("c", "cpp"):
            outputs = harness.native_scalar_types(entry["language"]) | {"void"}
        java_receiver = entry["language"] == "java" and "receiver_fixture" in entry
        go_receiver = entry["language"] == "go" and "receiver_fixture" in entry
        cpp_receiver = entry["language"] == "cpp" and "receiver_fixture" in entry
        if java_receiver and not java_receivers.supported_type(entry["output"], entry["java_models"], entry["package"], void=True):
            raise ValueError("result type requires an observation fixture")
        if not java_receiver and not go_receiver and not cpp_receiver and entry["language"] not in ("python", "javascript", "typescript") and harness.scalar_type(entry["output"]) not in outputs:
            raise ValueError("result type requires an observation fixture")
        gaps = harness.global_gaps(entry)
        if gaps:
            raise ValueError("unobserved globals require state fixtures: " + ", ".join(gaps))
        if "__oteleq" in (snapshot / entry["path"]).read_text() or (snapshot / "_oteleq_generated").exists():
            raise ValueError("generated observer name collides with application source")
    except ValueError as error:
        entry["reason"] = str(error)
        return "blocked"
    return "ready"


def is_entrypoint(function, language):
    if language == "java":
        return (function["name"].endswith(".main") and function["parameters"] in (["String[]"], ["java.lang.String[]"])
                and function["output"] == "void" and not function["reason"])
    return function.get("entrypoint", function["name"] == "main" and not function["reason"])


def receiver_fixture(entry, discovered, declared):
    """Bind one reviewed factory to its source declaration and concrete arguments."""
    try:
        if entry["language"] == "cpp":
            bound = cpp_receivers.bind(entry, discovered, declared, harness.concrete_arguments)
            fixture = bound["factory"]
            entry.update(cpp_receiver=bound, receiver_class=bound["owner"], receiver_configuration=declared,
                         parameters=bound["method"]["parameters"], output=bound["method"]["output"],
                         receiver_fixture={"factory": fixture["name"], "kind": fixture["kind"], "line": 0,
                                           "source_function": fixture["name"], "arguments": fixture["arguments"],
                                           "arguments_requested": fixture["arguments_requested"], "argument_types": fixture["parameters"]}, reason="")
            return
        if entry["language"] == "go":
            go_receivers.bind(entry, discovered, declared, harness.concrete_arguments)
            return
        if entry["language"] == "java":
            java_receivers.bind(entry, discovered, declared, harness.concrete_arguments)
            return
        owner = entry.get("python_receiver_class") if entry["language"] == "python" else entry.get("node_receiver_class")
        if not owner or entry["language"] not in ("python", "javascript", "typescript"):
            raise ValueError("receiver fixtures currently require an ordinary Python or JavaScript/TypeScript instance method")
        if entry["language"] != "python" and not entry["node_receiver_eligible"]:
            raise ValueError(entry["node_receiver_reason"])
        entry["receiver_class"] = owner
        if entry["language"] != "python":
            entry["node_class_label"] = entry["otelc_function"].rsplit(".", 1)[0]
        factory, kind = receiver_factory(entry, discovered, declared["factory"])
        arguments = harness.concrete_arguments({"language": entry["language"], "parameters": factory["parameters"]}, declared["arguments"])
        entry["receiver_fixture"] = {"factory": factory["name"], "line": factory["line"],
                                     "kind": kind, "source_function": factory["source_function"],
                                     "arguments": arguments, "arguments_requested": declared["arguments"],
                                     "argument_types": factory["parameters"]}
        entry["receiver_configuration"] = declared
        if (entry["language"] != "python" and node_project.commonjs(entry)
                and (any(item["name"] == "require" for item in discovered["functions"])
                     or any(item["name"] == "require" for item in discovered["globals"]))):
            raise ValueError("CommonJS bootstrap requires an unshadowed module require binding")
        if entry["reason"] == "instance method requires a receiver fixture":
            entry["reason"] = ""
    except ValueError as error:
        entry["reason"] = str(error)


def receiver_factory(entry, discovered, name):
    """Use a source constructor directly or one explicitly selected ordinary factory."""
    if entry["language"] != "python":
        return node_receivers.factory(entry, discovered, name)
    constructor = name == entry["python_receiver_class"]
    qualified = name + ".__init__" if constructor else name
    matches = [item for item in discovered["functions"] if item["name"] == qualified]
    if constructor and not matches:
        return {"name": name, "line": 0, "source_function": None, "parameters": []}, "constructor"
    if len(matches) != 1:
        raise ValueError("receiver factory requires one unique same-module source declaration")
    source = matches[0]
    if constructor and "python_constructor_parameters" in source:
        return {"name": name, "line": source["line"], "source_function": qualified,
                "parameters": source["python_constructor_parameters"]}, "constructor"
    if not constructor and not source["reason"]:
        return {"name": name, "line": source["line"], "source_function": qualified,
                "parameters": source["parameters"]}, "function"
    raise ValueError("receiver factory requires an ordinary source constructor or function")


def configure_go_context(entry: dict, discovered: dict, configuration: dict) -> None:
    """Keep compiler package identity and recovery bindings in the frozen entry."""
    entry["go_main_renames"] = discovered.get("main_renames", [])
    entry["go_shadowed_recovery"] = any(function["name"] in ("recover", "panic")
                                      for function in discovered["functions"])
    if "go_context" in discovered:
        entry["go_context"] = discovered["go_context"]
        entry["go_options"] = configuration["adapters"]["go"]
        entry["go_shadowed_recovery"] |= entry["go_context"]["shadowed_recovery"]
        relative = Path(entry["path"]).relative_to(entry["go_context"]["module_root"])
        entry["otelc_runtime_function"] = str(relative.with_suffix("")).replace("/", ".") + "." + entry["name"]


def configure_entry_context(entry, discovered, configuration, snapshot, excluded):
    """Apply explicit per-language provider settings and source-context bindings."""
    language = entry["language"]
    adapters = configuration["adapters"]
    if language in ("javascript", "typescript"):
        node_project.bind_entry(entry, discovered)
    if language == "typescript":
        entry["typescript_backend"] = adapters["typescript"]["backend"]
    if language == "rust":
        entry["rust_backend"] = adapters["rust"]["backend"]
    if language == "java":
        entry["java_backend"] = adapters.get("java", {}).get("backend", "legacy")
        entry["java_profile"] = adapters.get("java", {}).get("profile", java_profiles.STOCK)
    if language == "go":
        configure_go_context(entry, discovered, configuration)
    if language == "python" and not excluded and adapters["python"]["import_roots"]:
        try:
            entry["python_import"] = python_project.context(snapshot, entry["path"], adapters["python"]["import_roots"])
        except ValueError as error:
            entry["reason"] = str(error)


def inventory_entry(function, discovered, name, language, source_hash, snapshot, args):
    entry = {**function, "path": name, "language": language, "globals": discovered["globals"],
             "parser": discovered.get("parser", "unavailable"), "package": discovered.get("package", ""),
             "package_end": discovered.get("package_end"), "file_functions": discovered["entrypoints"],
             "binding_capture_offset": discovered.get("binding_capture_offset", 0),
             "source_sha256": source_hash, "column": function.get("column", 0)}
    binding = {k: entry[k] for k in ("language", "path", "name", "line", "column", "parameters", "source_sha256")}
    if language == "cpp" and "cpp_function" in entry:
        binding.update(source_offset=entry["source_offset"], symbol=entry["symbol"])
    entry["id"] = identity(binding)[:20]
    entry["otelc_function"] = entry_identity(entry)
    excluded = is_entrypoint(function, language) or bool(function.get("declaration_only"))
    excluded |= not project_policy.selected(entry["otelc_function"], args.configuration["functions"])
    if function.get("inventory_gap"):
        # An unknown callable set cannot prove that the function filter excludes it.
        excluded = False
    entry["generation_seed"] = args.configuration["generation"]["seed"]
    configure_entry_context(entry, discovered, args.configuration, snapshot, excluded)
    fixture = project_policy.matching_fixture(entry, args.configuration) if not excluded else None
    configure_fixture(entry, discovered, fixture)
    entry["status"] = "excluded" if excluded else qualify_entry(entry, snapshot, args.cases)
    return entry


def configure_fixture(entry, discovered, fixture):
    """Keep reviewed input, receiver and expected-outcome declarations together."""
    entry["expected_baseline"] = fixture["expected_baseline"] if fixture else {"kind": "return"}
    if fixture is None:
        return
    if "cases" in fixture:
        entry["input_cases"] = fixture["cases"]
    if "receiver" in fixture:
        receiver_fixture(entry, discovered, fixture["receiver"])
    if "domains" in fixture:
        entry["input_domains"] = fixture["domains"]
    if "preconditions" in fixture:
        entry["input_preconditions"] = fixture["preconditions"]
    if "sequence" in fixture:
        try:
            sequences.configure(entry, fixture["sequence"], harness.concrete_arguments)
        except ValueError as error:
            entry["reason"] = entry["reason"] or str(error)


def inventory_tree(contents, root, snapshot, workspace, args, native_projects=None, java_context=None, *, original_source=None):
    native_projects = native_projects or {}
    tools, artefacts, inventory, covered = native_profile.inventory(
        sys.modules[__name__], native_projects, root, snapshot, workspace, args)
    native_files = {name for _, name in covered}
    adapter_state = {"configuration": args.configuration["adapters"], "go_cache": {}}
    if original_source is not None:
        adapter_state["source"] = str(original_source)
    for name, sha in contents.items():
        language = discovery.LANGUAGES.get(Path(name).suffix)
        if (not language or language not in args.language
                or not project_policy.selected(name, args.configuration["sources"])):
            continue
        if language in ('c', 'cpp') and name in native_files:
            continue
        if language in native_projects:
            discovered = {"functions": [{"name": "<undeclared-native-build>", "line": 1, "parameters": [],
                "output": "unknown", "reason": "selected native file has no declared target compile context",
                "inventory_gap": True}], "globals": []}
        else:
            discovered = discover_file(name, language, root, snapshot, workspace, tools, artefacts,
                                       adapter_state)
        discovered["entrypoints"] = [function for function in discovered["functions"] if is_entrypoint(function, language)]
        for function in discovered["functions"]:
            entry = inventory_entry(function, discovered, name, language, sha, snapshot, args)
            java_project.bind_entry(entry, java_context)
            filesystem_effects.bind(entry, args.configuration)
            typescript_provider.bind(entry, root, workspace, tools.get(language, {}), execute, policy)
            java_provider.bind(entry, root, workspace, tools.get(language, {}), execute)
            inventory.append(entry)
    return tools, artefacts, inventory


def plan_configuration(args):
    """Resolve CLI selection overrides before any private source copy is created."""
    configuration = project_policy.load(getattr(args, "config", None))
    if args.language:
        configuration["languages"] = list(dict.fromkeys(args.language))
    if args.cases is not None:
        configuration["generation"]["cases_per_function"] = args.cases
    configuration["functions"]["exclude"] = list(dict.fromkeys(configuration["functions"]["exclude"] + args.exclude))
    args.configuration, args.language = configuration, configuration["languages"]
    args.cases = configuration["generation"]["cases_per_function"]
    return configuration


def validate_fixture_inventory(configuration: dict, inventory: list, languages: list, workspace: Path) -> None:
    """An unmatched selected fixture retains discovery evidence instead of a plan."""
    for fixture in configuration["fixtures"]:
        if fixture["language"] is not None and fixture["language"] not in languages:
            continue
        if not any(project_policy.fixture_matches(entry, fixture) for entry in inventory):
            write(workspace / "discovery-failure.json", {"schema_version": VERSION,
                  "inventory": inventory, "unmatched_fixture": fixture})
            raise ValueError(f"configured fixture matches no selected callable: {fixture['function']}; partial workspace: {workspace}")


def plan(args):
    if sys.version_info < (3, 12):
        raise ValueError("generation requires Python 3.12+")
    source = args.source.resolve(strict=True)
    root = args.otelc_root.resolve(strict=True)
    if not source.is_dir() or not root.is_dir():
        raise ValueError("source and otelc root must be directories")
    configuration = plan_configuration(args)
    temporary = capture.temporary_parent(source, root)
    parent = source_outside(args.workspace_parent or temporary, source, root)
    java_options = configuration["adapters"]["java"] if "java" in args.language else {}
    java_project.protect_destination(parent, java_project.input_locations(source, java_options))
    excluded_jars = java_project.snapshot_exclusions(source, java_options)
    excluded_owned = source_exclusions(source, configuration)
    excluded_roots = [item["path"] for item in excluded_owned]
    contents = manifest(source, excluded=discovery.IGNORED, excluded_files=excluded_jars,
                        excluded_roots=excluded_roots)
    if not contents and not native_profile.configured(configuration) and "source_roots" not in java_options:
        raise ValueError("empty source tree")
    workspace = Path(tempfile.mkdtemp(prefix="oteleq-run-", dir=parent))
    write(workspace / OWNED_MARKER, {"schema_version": VERSION, "id": uuid.uuid4().hex})
    contents, native_projects = native_profile.prepare_inputs(
        sys.modules[__name__], source, root, workspace, configuration, contents,
        excluded_files=excluded_jars, excluded_roots=excluded_roots)
    java_settings = {}
    if java_archive_context.enabled(java_options):
        selected, _ = discovery_tools(root, "java", configuration["adapters"])
        java_settings = {"java": selected["java"], "execute": execute,
                         "environment": capture.environment(workspace, selected, "oteleq-archive-plan", root)}
    java_context = java_project.prepare(source, workspace, java_options, discovery.IGNORED,
                                        excluded_roots=excluded_roots, **java_settings)
    contents = java_source_manifest(source, java_options, contents, excluded_roots=excluded_roots)
    snapshot = snapshot_source(source, workspace, contents)
    native_profile.directories(snapshot, native_projects)
    java_project.directories(snapshot, java_options)
    tools, artefacts, inventory = inventory_tree(contents, root, snapshot, workspace, args, native_projects, java_context,
                                                original_source=source)
    validate_fixture_inventory(configuration, inventory, args.language, workspace)
    current = native_profile.source_manifest(sys.modules[__name__], source, native_projects,
                                            excluded_files=excluded_jars, excluded_roots=excluded_roots)
    if (source_exclusions(source, configuration) != excluded_owned
            or java_source_manifest(source, java_options, current, excluded_roots=excluded_roots) != contents
            or manifest(snapshot) != contents):
        raise ValueError("source changed during discovery")
    data = {"schema_version": VERSION, "source": str(source), "otelc_root": str(root), "source_manifest": contents,
            "source_sha256": identity(contents), "tools": {lang: {k: str(v) for k, v in selected.items()} for lang, selected in tools.items()},
            "artefacts": artefacts, "inventory": inventory, "cases_per_function": args.cases,
            "configuration": configuration, "configuration_sha256": identity(configuration),
            "excluded_files": [name for name in contents if not project_policy.selected(name, configuration["sources"])],
            "owned_source_exclusions": excluded_owned,
            "excluded_directories": sorted(discovery.IGNORED), "excluded_languages": sorted(set(discovery.LANGUAGES.values()) - set(args.language or discovery.LANGUAGES.values())),
            "generator_sha256": generator_identity(), "cli_sha256": capture.file_digest(Path(os.environ["OTELEQ_EXECUTABLE"]))}
    if native_projects:
        data.update(native_projects=native_projects, native_context_manifest=native_profile.context_manifest(sys.modules[__name__], workspace))
    if java_context is not None:
        data.update(java_context=java_context, java_context_manifest=java_project.context_manifest(workspace))
        data["source_sha256"] = identity({"source": contents, "java_context": data["java_context_manifest"]})
        java_project.verify(workspace, data)
    if (workspace / java_provider.DIRECTORY).exists():
        data["java_provider_manifest"] = manifest(workspace / java_provider.DIRECTORY)
    write(workspace / PLAN_FILE, data)
    marker = read(workspace / OWNED_MARKER)
    marker["plan_sha256"] = identity(data)
    write(workspace / OWNED_MARKER, marker)
    print(workspace, flush=True)
    return 0


def source_exclusions(source: Path, configuration: dict) -> list[dict]:
    """Use the same owned-output scope for normal and explicit Java source walks."""
    java = configuration["adapters"]["java"] if "java" in configuration["languages"] else {}
    return owned_workspace.exclusions(sys.modules[__name__], source, java.get("source_roots", []))


def java_source_manifest(source, options, contents, *, excluded_roots=()):
    """Explicit generated Java units still obey the ordinary source snapshot bounds."""
    if "source_roots" not in options:
        return contents
    result = java_project.source_manifest(source, options, contents, discovery.IGNORED,
                                          excluded_roots=excluded_roots)
    if (len(result) > 10000 or any((source / name).stat().st_size > MAX_FILE for name in result)
            or sum((source / name).stat().st_size for name in result) > MAX_TREE):
        raise ValueError("required Java units exceed the source snapshot budget")
    return result


def package_files(package, spec):
    files = {}
    for directory in spec.submodule_search_locations or []:
        base = Path(directory)
        for path in sorted(capture.tree_paths(base)):
            if path.is_file() and path.suffix in (".py", ".so", ".pyd"):
                files[package + ":" + path.relative_to(base).as_posix()] = capture.file_digest(path)
    return files


def decoder_files():
    files = {}
    for package in ("google.protobuf", "opentelemetry.proto"):
        try:
            spec = importlib.util.find_spec(package)
        except ModuleNotFoundError:
            spec = None
        if spec is None:
            files[package] = "unavailable"
            continue
        files.update(package_files(package, spec))
    return files


def generator_identity():
    here = Path(__file__).parent
    names = ("generation.py", "policy.py", "return_expectations.py", "filesystem_effects.py", "http_effects.py", "domains.py", "shrinking.py", "sequences.py", "typescript_provider.py", "python_project.py", "go_project.py", "go_receivers.py", "go_graph.py", "go_observe.go", "node_receivers.py", "java_receivers.py", "java_build.py", "java_control.py", "java_profiles.py", "java_live.py", "java_control_receipt.py", "java_health.py", "java_launch.py", "java_provider.py", "java_telemetry.py", "OteleqCompile.java", "java_graph.py", "OteleqGraph.java", "cpp_models.py", "cpp_receivers.py", "cpp_worker.py", "cpp_graph.py", "cpp_observe.hpp", "native_names.py", "discovery.py", "harness.py", "observe.py", "node_observe.mjs", "node_sequence.mjs", "typed_capture.py", "discover.mjs", "discover.go", "Discover.java")
    files = {name: capture.file_digest(here / name) for name in names}
    files.update({name: capture.file_digest(here / name) for name in (
        'java_project.py', 'java_classpath.py', 'java_archives.py', 'java_archive_context.py',
        'java_helper_binding.py', 'OteleqArchives.java',
        'node_project.py', 'node_context.mjs',
        'native_profile.py', 'native_project.py', 'native_dependencies.py', 'native_frontend.py',
        'native_discover.cpp', 'native_context.py', 'native_workers.py', 'native_workspace.py',
        'owned_workspace.py')})
    files["host-python"] = capture.file_digest(Path(sys.executable))
    files["observer:otelc_capture.py"] = capture.file_digest(Path(capture.__file__))
    files["host-version"] = sys.version
    files.update(decoder_files())
    return identity(files)


def load_workspace(path, generated=False):
    workspace = path.resolve(strict=True)
    if path.is_symlink() or not workspace.is_dir() or read(workspace / OWNED_MARKER)["schema_version"] != VERSION:
        raise ValueError("workspace is not an owned oteleq directory")
    data = read(workspace / PLAN_FILE)
    if read(workspace / OWNED_MARKER).get("plan_sha256") != identity(data):
        raise ValueError("plan identity changed")
    if data["schema_version"] != VERSION or data["generator_sha256"] != generator_identity() or data["cli_sha256"] != capture.file_digest(Path(os.environ["OTELEQ_EXECUTABLE"])):
        raise ValueError("generator or CLI identity changed; create a new plan")
    if (data["configuration_sha256"] != identity(data["configuration"])
            or project_policy.validate(data["configuration"]) != data["configuration"]):
        raise ValueError("configuration identity or schema changed; create a new plan")
    context = data.get("java_context", {})
    excluded_roots = [item["path"] for item in source_exclusions(Path(data["source"]), data["configuration"])]
    contents = native_profile.source_manifest(sys.modules[__name__], Path(data["source"]), data.get('native_projects', {}),
                                              excluded_files=context.get("excluded_source_jars", []),
                                              excluded_roots=excluded_roots)
    java_options = data["configuration"]["adapters"]["java"] if context else {}
    if (java_source_manifest(Path(data["source"]), java_options, contents, excluded_roots=excluded_roots) != data["source_manifest"]
            or manifest(workspace / "snapshot") != data["source_manifest"]):
        raise ValueError("application source or immutable snapshot changed")
    native_profile.verify(sys.modules[__name__], workspace, data)
    java_project.verify(workspace, data, originals="original_source" not in data)
    java_provider.verify_probes(sys.modules[__name__], workspace, data)
    if generated and manifest(workspace / "tests") != read(workspace / GENERATED_MANIFEST):
        raise ValueError("generated suite or corpus changed; create a new plan")
    return workspace, data


def generation_case(entry, index, values):
    """Bind the concrete method and construction inputs into one corpus identity."""
    case = {"id": entry["id"] + "-" + str(index), "function_id": entry["id"],
            "arguments": values, "argument_types": entry["parameters"],
            "expected_baseline": entry["expected_baseline"]}
    if "input_cases" in entry:
        case["arguments_requested"] = entry["input_cases"][index]
    if "receiver_fixture" in entry:
        case["receiver_fixture"] = entry["receiver_fixture"]
    if "sequence_configuration" in entry:
        case["sequence"] = sequences.concrete(entry, values, harness.concrete_arguments)
        case["expected_baseline"] = next(step["expected_baseline"] for step in reversed(case["sequence"]) if step["action"] == "call")
    return case


def generate(args):
    workspace, data = load_workspace(args.workspace)
    destination = workspace / "tests"
    destination.mkdir(exist_ok=False)
    cases = []
    for entry in data["inventory"]:
        if entry["status"] == "ready":
            for index, values in enumerate(harness.corpus(entry, data["cases_per_function"])):
                cases.append(generation_case(entry, index, values))
    write(destination / "corpus.json", cases)
    if len(cases) > 1024:
        raise ValueError("generation exceeds 1024 concrete cases; reduce --cases or use explicit exclusions")
    runner = '''# Generated by oteleq. Boilerplate is MIT licensed.
import json, os, subprocess, unittest
from pathlib import Path
WORKSPACE=Path(__file__).resolve().parents[1]
PLAN=json.loads((WORKSPACE/"plan.json").read_text())
CLI=os.environ.get("OTELEQ_CLI",''' + repr(os.environ["OTELEQ_EXECUTABLE"]) + ''')
class GeneratedEquivalence(unittest.TestCase):
    pass
def paired(case):
    def test(self):
        result=subprocess.run([CLI,"replay","--workspace",str(WORKSPACE),"--case",case["id"]],check=False)
        self.assertEqual(result.returncode,0,"paired comparison incomplete or different; inspect retained run report")
    return test
def blocked(entry):
    def test(self):
        self.fail(entry["otelc_function"]+": "+entry["reason"])
    return test
for case in json.loads((WORKSPACE/"tests/corpus.json").read_text()):
    setattr(GeneratedEquivalence,"test_"+case["id"].replace("-","_"),paired(case))
for entry in PLAN["inventory"]:
    if entry["status"]=="blocked":setattr(GeneratedEquivalence,"test_blocked_"+entry["id"],blocked(entry))
if not any(name.startswith("test_") for name in vars(GeneratedEquivalence)):
    def empty(self):self.fail("no selected executable cases")
    GeneratedEquivalence.test_empty=empty
if __name__=="__main__":unittest.main()
'''
    (destination / "test_equivalence.py").write_text(runner)
    shutil.copyfile(Path(__file__).with_name("GENERATED-LICENSE.txt"), destination / "GENERATED-LICENSE.txt")
    for case in cases:
        entry = next(e for e in data["inventory"] if e["id"] == case["function_id"])
        preview = destination / "harnesses" / case["id"]
        if 'native_context' in entry:
            native_profile.preview(sys.modules[__name__], workspace, entry, case, preview, data)
            continue
        for name in entry.get("go_context", {}).get("files", [entry["path"]]):
            target = preview / name
            target.parent.mkdir(parents=True, exist_ok=True)
            shutil.copyfile(workspace / "snapshot" / name, target)
        harness.materialise(preview, entry, case["arguments"])
    write(workspace / GENERATED_MANIFEST, manifest(destination))
    (workspace / README_FILE).write_text("Generated scalar diagnostic suite. Boilerplate: MIT; application snapshot retains its original licence.\nRun: OTELEQ_PYTHON=/path/to/otelc/.venv/bin/python python3 tests/test_equivalence.py\nOr: quux-oteleq run --workspace . --report-dir /new/external/report\nEvery blocked selected callable fails the generated strict suite. No shipping-artefact or universal equivalence claim.\nKeep this whole workspace, or export-tests to a new destination.\n")
    print(json.dumps({"workspace": str(workspace), "cases": len(cases), "ready_functions": sum(e["status"] == "ready" for e in data["inventory"]), "blocked_functions": sum(e["status"] == "blocked" for e in data["inventory"])}))
    return 0


def policy(entry, endpoint, *, service="oteleq-generation"):
    if java_provider.prepared(entry):
        return java_provider.policy(entry, endpoint, service)
    language = entry["language"]
    sources = [entry["path"]] if language == "rust" and entry.get("rust_backend", "compiler") == "llvm" else ["**"]
    functions = [entry.get("otelc_runtime_function", entry["otelc_function"])]
    if sequences.creator(entry) is not None:
        functions.append(sequences.creator(entry))
    text = f'''schema_version = 2
languages = [{json.dumps(language)}]
[sources]
include = {json.dumps(sources)}
[functions]
include = {json.dumps(functions)}
[traces]
enabled = true
root_sample_ratio = 1.0
max_active_traces = 32
max_spans_per_trace = 256
[export]
endpoint = {json.dumps(endpoint)}
interval_ms = 50
'''
    if language == "go":
        text += '[adapters.go]\nbackend = "compile"\n'
    if language == "rust":
        text += '[adapters.rust]\nbackend = ' + json.dumps(entry.get("rust_backend", "compiler")) + '\n'
    if language == "typescript":
        text += '[adapters.typescript]\nbackend = ' + json.dumps(entry["typescript_backend"]) + '\n'
    if sequences.collects(entry):
        text += '[lifetimes]\nenabled = true\nboundary = "collection"\ninclude = ' + json.dumps([entry["node_class_label"]]) + '\n'
    return text


def telemetry(bodies, report, entry, service, decoder):
    # One generated invocation must start one selected trace. Recursive counts are runtime observations.
    names, _, roots, errors = capture.decode(bodies, service, decoder)
    if "sequence_configuration" in entry:
        return sequence_telemetry(bodies, report, entry, service, decoder, names, roots, errors)
    if set(names) != {entry.get("otelc_runtime_function", entry["otelc_function"])} or roots != 1 or not all(n > 0 for n in names.values()):
        raise ValueError("selected function was not witnessed as one complete invocation tree")
    spec = {"functions": names, "trees": 1, "errors": errors}
    return capture.witness(bodies, report, spec, service, decoder, entry["language"])


def sequence_telemetry(bodies, report, entry, service, decoder, names, roots, errors):
    """Validate independent call roots and collection metadata before comparison."""
    target, creator = entry["otelc_function"], sequences.creator(entry)
    calls = sequences.call_count(entry)
    spans = [span for path, body in bodies if path == capture.TRACE_PATH
             for span in capture.service_spans(decoder.FromString(body), service)]
    otelc_collection.sequence_functions(spans, target, calls, creator)
    allowed = {target} | ({creator} if creator is not None else set())
    spec = {"functions": names, "trees": roots, "errors": errors}
    if sequences.collects(entry):
        lifetime = entry["node_class_label"] + " lifetime"
        allowed.add(lifetime)
        spec["collection"] = {"type": entry["node_class_label"], "span": lifetime, "creator": creator, "count": 1}
    if set(names) - allowed:
        raise ValueError("sequence emitted an unexpected function or lifetime identity")
    return capture.witness(bodies, report, spec, service, decoder, entry["language"], allow_incomplete=sequences.collects(entry))


def driver_path(project, entry):
    language = entry["language"]
    if language == "go" and "go_context" in entry:
        return project / go_project.worker_path(entry["go_context"])
    relative = {"python": "_oteleq_generated/driver.py", "c": "_oteleq_driver.c", "cpp": "_oteleq_driver.cpp"}.get(language)
    if language == "java":
        relative = str(Path(entry["path"]).parent / "OteleqDriver.java")
    return project / (relative or entry["path"])


def build_command(root, project, entry, driver, config, tools, env, folder, scratch, lane, *, prepared_runtime=None, java_context=None):
    language = entry["language"]
    prefix = [root / "target/debug/quux-otelc", "--config", config, "--language", language]
    if language in ("c", "cpp"):
        return native_command(prefix, project, language, driver, tools, env, folder, scratch, lane)
    if language == "java":
        return java_command(root, project, entry, driver, config, tools, env, folder, scratch, lane,
                            prepared_runtime=prepared_runtime, context=java_context)
    if language in ("javascript", "typescript") and "node_context" in entry:
        def inspect_node(command, cwd, input_data=None, *, max_output_bytes=None):
            return execute(command, cwd, env, folder / "node-context-probe", input_data=input_data,
                           max_output_bytes=max_output_bytes)
        node_project.verify_attempt(project, entry, root, tools[language], inspect_node, folder)
    # Use the proven build recipes, with bounded execution for every build and launch.
    old_execute = capture.execute
    capture.execute = lambda command, cwd, environment, timeout=180: execute(command, cwd, environment, folder / ("build-" + uuid.uuid4().hex), timeout)
    try:
        if language == "rust":
            command = capture.rust_command(root, project, driver, config, tools, env, folder, scratch, lane,
                                           backend=entry["rust_backend"], expected_function=entry["otelc_function"])
            shutil.copyfile(folder / (lane + "-build-identities.json"), folder / BUILD_IDENTITIES)
            return command
        if language == "go":
            plain, on = capture.go_commands(root, go_build_request(project, entry, driver), config, tools, env, folder)
            shutil.copyfile(folder / "go-build-identities.json", folder / BUILD_IDENTITIES)
        else:
            plain, on = capture.commands(root, project, language, driver, config, tools, env, folder)
    finally:
        capture.execute = old_execute
    return plain if lane == "baseline" else on


def java_command(root, project, entry, driver, config, tools, env, folder, scratch, lane, *, prepared_runtime=None, context=None):
    """Keep the fixed compiler and launch recipe together for both Java providers."""
    classes = scratch / "classes"
    main = (entry["package"] + "." if entry["package"] else "") + "OteleqDriver"
    options = {"context": context} if context is not None else {}
    java_build.build(project, [project / entry["path"], driver], main, tools["java"],
                     classes, folder, env, execute, **options)
    if java_provider.prepared(entry):
        java_provider.require(prepared_runtime is not None, "missing owned runtime context")
        return java_launch.prepare(root, project, folder, tools, prepared_runtime, entry,
                                   tomllib.loads(config.read_text()), lane == "baseline", env, execute, **options)
    paths = os.pathsep.join(map(str, java_project.runtime_classpath(classes, context)))
    flags = ["-Xshare:off"]
    if context is not None:
        flags.append("-Xlog:class+load=info:file=" + str(folder / java_launch.CLASS_LOG))
    prefix = [root / "target/debug/quux-otelc", "--config", config, "--language", "java", "java"]
    return ([tools["java"]] if lane == "baseline" else prefix) + [*flags, "-cp", paths, main]


def go_build_request(project, entry, driver):
    """Bind a caller-selected module, target and required active package inputs."""
    context = entry.get("go_context")
    module = project / context["module_root"] if context else project
    sources = [project / name for name in context["files"]] if context else [driver]
    if driver.is_file() and driver not in sources:
        sources.append(driver)
    return {"workspace": module, "target": driver, "sources": sources, "project": project}


def native_command(prefix, project, language, driver, tools, env, folder, scratch, lane):
    compiler = "clang++" if language == "cpp" else "clang"
    flags = capture.native_flags(language)
    output = scratch / "application"
    command = [tools[compiler], *flags, driver, "-o", output]
    if lane == "instrumented_on":
        command = prefix + [compiler, *flags, driver, "-o", output]
    result = execute(command, project, env, folder / "build")
    if result.returncode:
        raise ValueError("generated native build failed; inspect build/stderr")
    write(folder / BUILD_IDENTITIES, {"application": capture.file_digest(output)})
    return [output] if lane == "baseline" else prefix + ["run", output]


def validate_private_sources(project, immutable, folder):
    # Generated native binaries are build outputs, not source snapshot members.
    if any(not (project / name).is_file() or capture.file_digest(project / name) != digest for name, digest in immutable.items()):
        raise ValueError("private application/harness source changed")
    for candidate in capture.tree_paths(project):
        if candidate.is_symlink() or (candidate.suffix in discovery.LANGUAGES and candidate.relative_to(project).as_posix() not in immutable):
            raise ValueError("unexpected source or symlink appeared in the private project")
    if not (folder / BUILD_IDENTITIES).exists():
        write(folder / BUILD_IDENTITIES, {name: capture.file_digest(project / name)
              for name in ("plain", "instrumented") if (project / name).is_file()})


def baseline_receipt(entry, folder, bodies):
    """Plain execution must neither emit telemetry nor invent SDK replies."""
    if bodies:
        raise ValueError("baseline unexpectedly exported telemetry")
    if sequences.controls(entry):
        java_control_receipt.read(folder, entry, read(folder / "process.json")["pid"], bodies, plain=True)


def qualify_attempt(data, entry, lane, folder, result, bodies, errors, service, decoder, *, extra_channels=None,
                    capture_complete=True, prepared_runtime=None):
    if errors or result.returncode:
        raise ValueError("application exit or OTLP capture failed; inspect retained stdout/stderr")
    observation = folder / "observation"
    if not observation.is_file() or observation.stat().st_size > MAX_OUTPUT:
        raise ValueError("missing or oversized typed observation")
    extra_channels = extra_channels or {}
    if len(result.stdout) + len(result.stderr) + observation.stat().st_size + sum(map(len, extra_channels.values())) > data["configuration"]["limits"]["max_capture_bytes"]:
        raise ValueError("case observation exceeds comparator channel budget")
    witness = None
    if lane == "baseline":
        baseline_receipt(entry, folder, bodies)
    elif prepared_runtime is not None:
        witness = java_telemetry.witness(prepared_runtime, folder, entry, bodies, service, decoder)
    else:
        runtime = read(folder / "runtime.json")
        if entry["language"] == "rust" and capture.RUST_COMPILER_PROFILE_FILENAME in data.get("artefacts", {}).get("rust", {}):
            capture.rust_future_health(runtime)
        witness = telemetry(bodies, runtime, entry, service, decoder)
    return {"source_sha256_before": data["source_sha256"], "source_sha256_after": data["source_sha256"],
            "termination": {"kind": "exit", "code": 0}, "capture_complete": capture_complete,
            "channels": {"stdout": list(result.stdout), "stderr": list(result.stderr), "state-and-outcome": list(observation.read_bytes()), **extra_channels}, "witness": witness}



def provider_stable(root, language, tools, expected, entry):
    """Re-enumerate the selected provider without changing its frozen API."""
    if java_provider.prepared(entry):
        java_provider.require(java_provider.artefacts(root, tools, entry.get("java_profile", java_profiles.STOCK)) == expected, "SDK or selected tools changed")
    else:
        capture.stable(root, language, tools, expected, rust_backend=entry.get("rust_backend", "compiler"))


def attempt(workspace, data, entry, case, lane, folder, decoder, *, http_fixtures=None):
    http_fixtures = http_fixtures or []
    if [item.settings for item in http_fixtures] != http_effects.selected(data["configuration"]):
        raise ValueError("HTTP effects require the frozen case fixture context before application execution")
    folder.mkdir(parents=True)
    roots = (Path(data["source"]), Path(data["otelc_root"]), workspace)
    with java_launch.runtime(entry, folder, source_roots=roots) as runtime:
        return attempt_with_runtime(workspace, data, entry, case, lane, folder, decoder, http_fixtures, runtime)


def attempt_with_runtime(workspace, data, entry, case, lane, folder, decoder, http_fixtures, runtime):
    """Capture each lane with the same private source, effects and process budgets."""
    root, language = Path(data["otelc_root"]), entry["language"]
    tools = {k: Path(v) for k, v in data["tools"][language].items()}
    provider_stable(root, language, tools, data["artefacts"][language], entry)
    project = folder / "project"
    shutil.copytree(workspace / "snapshot", project)
    if 'native_context' not in entry:
        shutil.copytree(workspace / "tests/harnesses" / case["id"], project, dirs_exist_ok=True)
    driver = driver_path(project, entry)
    service = "oteleq-gen-" + uuid.uuid4().hex
    env = capture.environment(project, tools, service, root)
    scratch = folder / "scratch"
    scratch.mkdir()
    env.update({"TMPDIR": str(scratch), "HOME": str(scratch), "GOCACHE": str(workspace / "go-cache/build"), "GOMODCACHE": str(workspace / "go-cache/modules"), "GOTOOLCHAIN": "local",
                "OTELEQ_OBSERVATION": str(folder / "observation"), "OTELC_REPORT_PATH": str(folder / "runtime.json")})
    if "go_options" in entry:
        env.update(go_project.environment(entry["go_options"]))
    if sequences.collects(entry):
        env["NODE_OPTIONS"] = "--expose-gc"
        write(folder / "collection-controls.json", {"NODE_OPTIONS": "--expose-gc", "sequence": case["sequence"]})
    immutable = manifest(project)
    java_context = java_project.materialise(workspace, data, folder, project) if language == "java" else None
    receiver_options = {"max_requests": java_provider.MAX_TELEMETRY_REQUESTS} if runtime is not None else {}
    with capture.receiver(**receiver_options) as (endpoint, bodies, errors):
        config = folder / "policy.toml"
        config.write_text(policy(entry, endpoint, service=service) if runtime is not None else policy(entry, endpoint))
        if language == "typescript":
            env["OTELC_TYPESCRIPT_BACKEND"] = capture.typescript_backend(root, language, entry, config.read_bytes())
            write(folder / "typescript-controls.json", {"OTELC_TYPESCRIPT_BACKEND": env["OTELC_TYPESCRIPT_BACKEND"],
                                                        "provider": entry.get("typescript_provider")})
        if 'native_context' in entry:
            prefix = [root / 'target/debug/quux-otelc', '--config', config, '--language', language]
            command = native_profile.build(sys.modules[__name__], workspace, data, entry, case,
                                           project, prefix, env, folder, lane)
        else:
            options = attempt_build_options(runtime, java_context)
            command = build_command(root, project, entry, driver, config, tools, env, folder, scratch, lane, **options)
        launch = read(folder / java_launch.LAUNCH_FILE) if runtime is not None else None
        write(folder / "command.json", [str(p) for p in command])
        working_directory = project / entry["go_context"]["module_root"] if "go_context" in entry else project
        write(folder / "working-directory.json", str(working_directory))
        effects, effect_environment = filesystem_effects.prepare(folder, data["configuration"], working_directory=working_directory)
        env.update(effect_environment)
        if effects:
            write(folder / "filesystem-controls.json", {"declarations": filesystem_effects.selected(data["configuration"]), "environment": effect_environment})
        if http_fixtures:
            bindings = http_effects.bindings(http_fixtures)
            env.update(bindings)
            write(folder / "http-controls.json", {"declarations": http_effects.selected(data["configuration"]), "environment": bindings})
        with http_effects.observe(http_fixtures, folder, data["configuration"]["limits"]["max_capture_bytes"]) as requests:
            options = execution_options(entry, case, lane, folder, runtime, bodies, env)
            result = execute(command, working_directory, env, folder, timeout=data["configuration"]["limits"]["case_timeout_ms"] / 1000,
                             **options)
    capture.retain_http(folder, bodies, errors)
    effect_channels, complete = filesystem_effects.finish(effects, folder)
    request_channels, request_complete = http_effects.finish(requests)
    effect_channels.update(request_channels)
    complete &= request_complete
    options = {"java_context": java_context} if java_context is not None else {}
    verify_attempt_inputs(data, entry, project, folder, scratch, tools, immutable, runtime, launch, config, lane=lane, **options)
    return qualify_attempt(data, entry, lane, folder, result, bodies, errors, service, decoder,
                           extra_channels=effect_channels, capture_complete=complete, prepared_runtime=runtime)


def execution_options(entry, case, lane, folder, runtime, bodies, env):
    """Add only explicitly requested process recording and live Java checkpoints."""
    options = {"record_process": True} if runtime is not None else {}
    if sequences.controls(entry):
        interaction = java_live.Session(folder, runtime, case["sequence"], bodies, plain=lane == "baseline")
        env.update(interaction.environment())
        options["interaction"] = interaction
    return options


def attempt_build_options(runtime, context):
    """Pass only explicitly present Java runtime and compiler contexts to builders."""
    return {key: value for key, value in (("prepared_runtime", runtime), ("java_context", context)) if value is not None}


def verify_attempt_inputs(data, entry, project, folder, scratch, tools, immutable, runtime, launch, config, *, lane, java_context=None):
    """Recheck private sources, compiler products and the selected launch/provider."""
    root, language = Path(data["otelc_root"]), entry["language"]
    validate_private_sources(project, immutable, folder)
    if language == "java":
        java_build.verify(project, scratch / "classes", folder)
    if runtime is not None:
        java_provider.require(read(folder / java_launch.LAUNCH_FILE) == launch, "retained launch changed during execution")
        options = {"context": java_context} if java_context is not None else {}
        java_launch.verify(launch, root=root, project=project, folder=folder, tools=tools, runtime=runtime,
                           entry=entry, data=tomllib.loads(config.read_text()), plain=lane == "baseline", **options)
        java_launch.origins(runtime, folder, entry, **options)
    if java_context is not None:
        java_project.verify_attempt(folder, java_context)
        if runtime is None:
            java_launch.origins(folder, folder, entry, context=java_context)
    if 'native_context' in entry:
        native_profile.verify_build(sys.modules[__name__], folder)
    provider_stable(root, language, tools, data["artefacts"][language], entry)

def capture_case(workspace, data, entry, case, destination, decoder, contract, *, http_fixtures=None):
    """Keep raw evidence and bounded typed observations for every actual launch."""
    observed = {"baseline": [], "instrumented_on": []}
    typed_observed = {"baseline": [], "instrumented_on": []}
    for lane in observed:
        key = "baseline_repeats" if lane == "baseline" else "instrumented_repeats"
        for repeat in range(data["configuration"]["limits"][key]):
            folder = destination / f"{lane}-{repeat}"
            options = {"http_fixtures": http_fixtures} if http_fixtures else {}
            execution = attempt(workspace, data, entry, case, lane, folder, decoder, **options)
            typed = typed_capture.observation(bytes(execution["channels"]["state-and-outcome"]), entry, contract)
            size = len(json.dumps(typed, ensure_ascii=True).encode())
            size += sum(len(value) for name, value in execution["channels"].items() if name != "state-and-outcome")
            if size > data["configuration"]["limits"]["max_capture_bytes"]:
                raise ValueError("typed observation exceeds comparator channel budget")
            write(folder / "typed-observation.json", typed)
            observed[lane].append(execution)
            typed_execution = {**execution, "channels": {name: value for name, value in execution["channels"].items() if name != "state-and-outcome"}}
            typed_observed[lane].append({"execution": typed_execution, "observation": typed})
    return observed, typed_observed


def compare_case(workspace, data, entry, case, destination, decoder):
    with http_effects.fixtures(data["configuration"]) as fixtures:
        return compare_with_fixtures(workspace, data, entry, case, destination, decoder, fixtures)


def compare_with_fixtures(workspace, data, entry, case, destination, decoder, http_fixtures):
    write(destination / "corpus.json", case)
    roots = typed_capture.required_roots(entry)
    contract = {"observation_schema_version": 1, "case_id": case["id"], "function_id": entry.get("otelc_runtime_function", entry["otelc_function"]),
                "fixture_sha256": identity({"case": case, "source": entry["source_sha256"], "roots": roots}),
                "required_roots": roots, "expected_baseline": case["expected_baseline"]}
    if filesystem_effects.selected(data["configuration"]) or http_fixtures:
        contract["fixture_sha256"] = identity({"fixture": contract["fixture_sha256"], "effects": data["configuration"]["effects"]})
    if http_fixtures:
        contract["fixture_sha256"] = identity({"fixture": contract["fixture_sha256"], "http_environment": http_effects.bindings(http_fixtures)})
    if "sequence" in case:
        contract["steps"] = sequences.contracts(case, roots)
    options = {"http_fixtures": http_fixtures} if http_fixtures else {}
    observed, typed_observed = capture_case(workspace, data, entry, case, destination, decoder, contract, **options)
    selected = sequences.expected_functions(entry, observed["instrumented_on"][0]["witness"]["functions"])
    diagnostic = {"source": data["source_sha256"], "harness": manifest(workspace / "tests/harnesses" / case["id"]),
                  "tools": {name: sha for name, sha in data["artefacts"][entry["language"]].items() if name.startswith("tool:")}}
    scope = {"language": entry["language"], "artefact_class": "diagnostic", "source_sha256": data["source_sha256"],
             "baseline_artefact_sha256": identity(diagnostic), "instrumented_artefact_sha256": identity({**diagnostic, "adapter": data["artefacts"][entry["language"]]}),
             "policy_sha256": identity({"otelc": policy(entry, "receiver"), "generation": data["configuration"]}), "observer": f"oteleq configured scalar generator v1; {sequences.call_count(entry)} target call root(s) required; recursive span counts observed",
             "channels": ["stdout", "stderr", "state-and-outcome", *filesystem_effects.channels(data["configuration"]), *http_effects.channels(data["configuration"])],
             "gaps": ["scalar corpus; business preconditions and branch exhaustiveness not established", "diagnostic access/entrypoint helpers; not shipping artefact evidence", "artefact digests aggregate diagnostic inputs and qualified tools/adapters; emitted runtime compiler/loader outputs are outside those digests", "no undeclared network, imported-module globals or concurrent-schedule qualification", "exception traceback/stack and Java/C++ extra exception fields are unobserved", "compiler sysroots and OS libraries are outside content identity", "trusted local execution; no hostile-code sandbox"]}
    scope["gaps"].append("live metric controls cover selected synchronous Java call trees and bounded export windows; general SDK-instrument, other-language and exporter-fault qualification remains open"
                         if sequences.controls(entry) else "live metric controls and exporter-fault scenarios are unobserved")
    if entry["language"] in ("javascript", "typescript"):
        scope["gaps"].append("state reachable only through CommonJS wrapper/module.exports caches or undeclared imported modules is unobserved")
    scope["gaps"].append("filesystem boundary bytes/kinds/permissions only; timestamps, inode/link identity, transient activity and undeclared paths are unobserved"
                         if filesystem_effects.selected(data["configuration"]) else "filesystem effects are unobserved")
    scope["gaps"].append("HTTP fixture accepted request order/method/target/body, selected raw header lines and scripted response bytes only; other headers, peer/packet timing, other destinations, TLS and broader protocols are unobserved"
                         if http_fixtures else "HTTP fixture effects are unobserved")
    bundle = {"workload_schema_version": 1, "scope": scope, "cases": [{"case_id": case["id"], "corpus_sha256": identity(case),
              "expected_functions": selected, "expected_spans": sum(selected.values()), **observed}]}
    write(destination / "bundle.json", bundle)
    typed_case = {"contract": contract, "corpus_sha256": identity(case), "expected_functions": selected,
                  "expected_spans": sum(selected.values()), **typed_observed}
    typed_scope = {**scope, "channels": ["stdout", "stderr", *filesystem_effects.channels(data["configuration"]), *http_effects.channels(data["configuration"])],
                   "observer": "oteleq typed boundary codecs v1; captured globals/arguments and initial-state checks; name-only decoded invocation witness"}
    if sequences.controls(entry):
        typed_scope["observer"] += "; selected-function live metric collection/emission receipts validated"
    typed_scope["gaps"] = [*scope["gaps"], "graph identities are local to each boundary; cross-boundary replacement, weakref and finalizer effects are unobserved"]
    write(destination / TYPED_BUNDLE, {"typed_schema_version": 1, "scope": typed_scope, "cases": [typed_case]})
    if (destination / TYPED_BUNDLE).stat().st_size > 16 * 1024 * 1024:
        raise ValueError("typed bundle exceeds comparator input limit; lower repeats or capture budget")
    result = execute([os.environ["OTELEQ_EXECUTABLE"], "compare-observations", destination / TYPED_BUNDLE], workspace,
                     folder=destination / "comparator")
    (destination / "comparison.json").write_bytes(result.stdout)
    if not result.stdout:
        raise ValueError("typed comparator produced no result: " + result.stderr.decode(errors="replace")[-2000:])
    return {"case": case["id"], "function": entry["otelc_function"], "exit_code": result.returncode,
            "comparison": capture.strict_json(result.stdout), "arguments": case["arguments"]}


def decoder():
    from opentelemetry.proto.collector.trace.v1.trace_service_pb2 import ExportTraceServiceRequest
    return ExportTraceServiceRequest


def run(args):
    workspace, data = load_workspace(args.workspace, generated=True)
    root = Path(data["otelc_root"])
    capture.temporary_parent(Path(data["source"]), root)
    message_decoder = decoder()
    if args.command == "replay":
        parent = workspace / "runs"
        parent.mkdir(exist_ok=True)
        destination = Path(tempfile.mkdtemp(prefix="replay-", dir=parent))
    else:
        destination = source_outside(args.report_dir, Path(data["source"]), root, workspace)
        java_project.protect_destination(destination, java_project.original_locations(data))
        destination.mkdir(mode=0o700, exist_ok=False)
    results = []
    cases = read(workspace / "tests/corpus.json")
    if args.command == "replay":
        cases = [case for case in cases if case["id"] == args.case]
        if not cases:
            raise ValueError("unknown case ID")
    for case in cases:
        entry = next(e for e in data["inventory"] if e["id"] == case["function_id"])
        case_path = destination / case["id"]
        case_path.mkdir()
        try:
            result = compare_case(workspace, data, entry, case, case_path, message_decoder)
        except (ValueError, OSError, KeyError) as error:
            result = {"case": case["id"], "function": entry["otelc_function"], "arguments": case["arguments"], "exit_code": 4, "error": str(error)}
        result["argument_types"] = case["argument_types"]
        result.update({key: value for key, value in case.items()
                       if key in ("arguments_requested", "receiver_fixture", "sequence")})
        results.append(result)
        write(destination / "partial-results.json", results)
    blocked = [e for e in data["inventory"] if e["status"] == "blocked"] if args.command == "run" else []
    load_workspace(workspace, generated=True)
    codes = {r["exit_code"] for r in results}
    if blocked or not results:
        codes.add(3)
    code = next((c for c in (4, 2, 3, 1) if c in codes), 0)
    report = {"schema_version": VERSION, "claim": "equivalence over these tests and observations", "exit_code": code,
              "cases": results, "blocked": blocked, "inventory": data["inventory"], "source_sha256": data["source_sha256"],
              "source_preserved": True, "workspace": str(workspace), "artefact_class": "diagnostic"}
    report["configuration"] = data["configuration"]
    report["configuration_sha256"] = data["configuration_sha256"]
    report["owned_source_exclusions"] = source_exclusions(Path(data["source"]), data["configuration"])
    write(destination / "report.json", report)
    print(json.dumps({"report": str(destination / "report.json"), "exit_code": code, "cases": len(results), "blocked": len(blocked)}), flush=True)
    return code


def export_tests(args):
    workspace, data = load_workspace(args.workspace, generated=True)
    destination = args.destination.resolve()
    java_project.protect_destination(destination, java_project.original_locations(data))
    if destination.exists() or destination.is_relative_to(workspace) or workspace.is_relative_to(destination):
        raise ValueError("export destination must be new and independent of the workspace")
    if not args.apply:
        files = ["snapshot", "tests", PLAN_FILE, README_FILE]
        if data.get('native_projects'):
            files.append(native_profile.DIRECTORY)
        if data.get('java_context'):
            files.append(java_project.DIRECTORY)
        if 'java_provider_manifest' in data:
            files.append(java_provider.DIRECTORY)
        print(json.dumps({"destination": str(destination), "copy": files, "mode": "dry-run"}))
        return 0
    destination.mkdir(mode=0o700)
    for name in ("snapshot", "tests"):
        shutil.copytree(workspace / name, destination / name)
    if data.get('native_projects'):
        shutil.copytree(workspace / native_profile.DIRECTORY, destination / native_profile.DIRECTORY)
    if data.get('java_context'):
        shutil.copytree(workspace / java_project.DIRECTORY, destination / java_project.DIRECTORY)
    if 'java_provider_manifest' in data:
        shutil.copytree(workspace / java_provider.DIRECTORY, destination / java_provider.DIRECTORY)
    for name in (OWNED_MARKER, GENERATED_MANIFEST, README_FILE):
        shutil.copyfile(workspace / name, destination / name)
    data["original_source"] = data["source"]
    data["original_owned_source_exclusions"] = data.get("owned_source_exclusions", [])
    data["owned_source_exclusions"] = []
    data["source"] = str(destination / "snapshot")
    write(destination / PLAN_FILE, data)
    marker = read(destination / OWNED_MARKER)
    marker["plan_sha256"] = identity(data)
    write(destination / OWNED_MARKER, marker)
    print(destination)
    return 0


def clean(args):
    # Cleanup does not require the original application/toolchain still to exist.
    workspace = args.workspace.resolve(strict=True)
    if args.workspace.is_symlink() or workspace.parent == workspace:
        raise ValueError("refusing to remove an unowned workspace")
    owned_workspace.verify(sys.modules[__name__], workspace)
    shutil.rmtree(workspace)
    return 0


def case_budget(value):
    """Keep CLI budget errors bounded instead of printing 1,024 choices."""
    try:
        return project_policy.integer(int(value), 1, project_policy.MAX_CASES, "--cases")
    except ValueError as error:
        raise argparse.ArgumentTypeError("--cases must be an integer from 1 to 1024") from error


def trial_budget(value):
    """Keep shrink budget errors specific to the public flag."""
    try:
        return project_policy.integer(int(value), 1, project_policy.MAX_CASES, "--trials")
    except ValueError as error:
        raise argparse.ArgumentTypeError("--trials must be an integer from 1 to 1024") from error


def shrink(args):
    """Use the same sealed worker and comparator for every reduction trial."""
    return shrinking.run(args, sys.modules[__name__])


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__, allow_abbrev=False)
    commands = parser.add_subparsers(dest="command", required=True)
    planning = commands.add_parser("plan", help="AST inventory and external immutable snapshot", allow_abbrev=False)
    planning.add_argument("--source", type=Path, required=True)
    planning.add_argument("--otelc-root", type=Path, required=True)
    planning.add_argument("--config", type=Path, help="validated TOML selection, concrete fixtures and execution budgets")
    planning.add_argument("--workspace-parent", type=Path)
    planning.add_argument("--language", action="append", choices=sorted(set(discovery.LANGUAGES.values())))
    planning.add_argument("--exclude", action="append", default=[])
    planning.add_argument("--cases", type=case_budget, metavar="N", help="per-function budget, 1..1024; policy default or 3")
    for command in COMMANDS[1:]:
        sub = commands.add_parser(command, allow_abbrev=False)
        sub.add_argument("--workspace", type=Path, required=True)
        if command == "run":
            sub.add_argument("--report-dir", type=Path, required=True)
        elif command == "replay":
            sub.add_argument("--case", required=True)
        elif command == "export-tests":
            sub.add_argument("--destination", type=Path, required=True)
            sub.add_argument("--apply", action="store_true")
        elif command == "shrink":
            sub.add_argument("--case", required=True)
            sub.add_argument("--report-dir", type=Path, required=True)
            sub.add_argument("--trials", type=trial_budget, default=64, metavar="N",
                             help="candidate budget 1..1024; original and final confirmations are additional")
    args = parser.parse_args(argv)
    try:
        return {"plan": plan, "generate": generate, "run": run, "replay": run, "clean": clean,
                "export-tests": export_tests, "shrink": shrink}[args.command](args)
    except (ValueError, OSError, KeyError, ImportError) as error:
        print("oteleq: " + str(error), file=sys.stderr)
        return 4


if __name__ == "__main__":
    raise SystemExit(main())
