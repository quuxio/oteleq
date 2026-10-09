"""External generated test workflow; Rust CLI/comparator with compiler-specific workers."""
import argparse
import fnmatch
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
import uuid

import discovery
import harness
import otelc_capture as capture

VERSION = 1
MAX_FILE = 8 * 1024 * 1024
MAX_TREE = 256 * 1024 * 1024
MAX_OUTPUT = 4 * 1024 * 1024
MAX_CHANNEL_BYTES = 256 * 1024
OWNED_MARKER = '.oteleq-owned.json'
PLAN_FILE = 'plan.json'
GENERATED_MANIFEST = 'generated-manifest.json'
BUILD_IDENTITIES = 'build-identities.json'
README_FILE = 'README.txt'
COMMANDS = ("plan", "generate", "run", "replay", "clean", "export-tests")


def write(path, data):
    path.write_text(json.dumps(data, sort_keys=True, indent=2) + "\n")


def read(path):
    if path.stat().st_size > MAX_TREE:
        raise ValueError("document exceeds size limit")
    return capture.strict_json(path.read_text())


def manifest(root):
    result, total = {}, 0
    for directory, names, files in os.walk(root, followlinks=False):
        base = Path(directory)
        names[:] = sorted(n for n in names if n not in discovery.IGNORED)
        for name in names + files:
            if (base / name).is_symlink():
                raise ValueError("source symlink requires an explicit build recipe: " + str(base / name))
        for name in sorted(files):
            path = base / name
            if not path.is_file():
                raise ValueError("source contains a non-regular file")
            size = path.stat().st_size
            total += size
            if size > MAX_FILE or total > MAX_TREE or len(result) >= 10000:
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


def execute(command, cwd, env=None, folder=None, timeout=60, input_data=None):
    """Trusted local execution with wall time/output limits and process-group cleanup."""
    if folder is None:
        with tempfile.TemporaryDirectory(prefix="oteleq-discover-") as directory:
            return execute(command, cwd, env, Path(directory), timeout, input_data)
    folder.mkdir(parents=True, exist_ok=True)
    out, err = folder / "stdout", folder / "stderr"
    input_path = worker_input(folder, input_data)
    with out.open("wb") as stdout, err.open("wb") as stderr, input_path.open("rb") as stdin:
        process = subprocess.Popen([str(p) for p in command], cwd=cwd, env=env,
                                   stdin=stdin, stdout=stdout, stderr=stderr, start_new_session=True)
        deadline = time.monotonic() + timeout
        failure = None
        try:
            while process.poll() is None:
                if time.monotonic() > deadline:
                    failure = "process timeout"
                if out.stat().st_size + err.stat().st_size > MAX_OUTPUT:
                    failure = "process output limit exceeded"
                if failure:
                    break
                time.sleep(0.01)
        finally:
            # Descendants cannot keep running after the leader exits or interrupts the host.
            try:
                os.killpg(process.pid, signal.SIGKILL)
            except ProcessLookupError:
                pass
            process.wait()
    if failure or out.stat().st_size + err.stat().st_size > MAX_OUTPUT:
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
        return entry["name"] + "(" + ", ".join(entry["parameters"]) + ")"
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


def discover_file(name, language, root, snapshot, workspace, tools, artefacts):
    try:
        if language not in tools:
            selected = capture.selected_tools(root, language)
            if language == "java":
                selected["javac"] = capture.tool_path(str(selected["java"].parent / "javac"))
            qualified = capture.artefacts(root, language, selected)
            tools[language], artefacts[language] = selected, qualified
        def discover_execute(command, cwd, input_data=None):
            environment = capture.environment(snapshot, tools[language], "oteleq-discovery", root)
            environment.update({"GOCACHE": str(workspace / "go-cache"), "GOTOOLCHAIN": "local",
                                "OTELEQ_EXECUTABLE": os.environ["OTELEQ_EXECUTABLE"]})
            return execute(command, cwd, environment, input_data=input_data)
        return discovery.discover(snapshot / name, language, root, tools[language], discover_execute)
    except (ValueError, OSError, KeyError, SyntaxError, RecursionError) as error:
        return {"functions": [{"name": "<parse-or-tool-gap>", "line": 1, "parameters": [], "output": "unknown", "reason": str(error)}], "globals": []}


def qualify_entry(entry, snapshot, count):
    if entry["reason"]:
        return "blocked"
    try:
        harness.corpus(entry, count)
        outputs = harness.INTEGERS | harness.FLOATS | harness.BOOLS | harness.VOIDS | harness.STRINGS
        if entry["language"] not in ("python", "javascript", "typescript") and harness.scalar_type(entry["output"]) not in outputs:
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


def inventory_entry(function, discovered, name, language, source_hash, snapshot, args):
    entry = {**function, "path": name, "language": language, "globals": discovered["globals"],
             "parser": discovered.get("parser", "unavailable"), "package": discovered.get("package", ""),
             "package_end": discovered.get("package_end"), "file_functions": discovered["entrypoints"],
             "source_sha256": source_hash, "column": function.get("column", 0)}
    entry["id"] = identity({k: entry[k] for k in ("language", "path", "name", "line", "column", "parameters", "source_sha256")})[:20]
    entry["otelc_function"] = entry_identity(entry)
    excluded = is_entrypoint(function, language) or bool(function.get("declaration_only"))
    excluded |= any(fnmatch.fnmatchcase(entry["otelc_function"], pattern) for pattern in args.exclude)
    entry["status"] = "excluded" if excluded else qualify_entry(entry, snapshot, args.cases)
    return entry


def inventory_tree(contents, root, snapshot, workspace, args):
    tools, artefacts, inventory = {}, {}, []
    for name, sha in contents.items():
        language = discovery.LANGUAGES.get(Path(name).suffix)
        if not language or args.language and language not in args.language:
            continue
        discovered = discover_file(name, language, root, snapshot, workspace, tools, artefacts)
        discovered["entrypoints"] = [function for function in discovered["functions"] if is_entrypoint(function, language)]
        inventory.extend(inventory_entry(function, discovered, name, language, sha, snapshot, args)
                         for function in discovered["functions"])
    return tools, artefacts, inventory


def plan(args):
    if sys.version_info < (3, 12):
        raise ValueError("generation requires Python 3.12+")
    source = args.source.resolve(strict=True)
    root = args.otelc_root.resolve(strict=True)
    if not source.is_dir() or not root.is_dir():
        raise ValueError("source and otelc root must be directories")
    temporary = capture.temporary_parent(source, root)
    parent = source_outside(args.workspace_parent or temporary, source, root)
    contents = manifest(source)
    if not contents:
        raise ValueError("empty source tree")
    workspace = Path(tempfile.mkdtemp(prefix="oteleq-run-", dir=parent))
    write(workspace / OWNED_MARKER, {"schema_version": VERSION, "id": uuid.uuid4().hex})
    snapshot = snapshot_source(source, workspace, contents)
    tools, artefacts, inventory = inventory_tree(contents, root, snapshot, workspace, args)
    if manifest(source) != contents or manifest(snapshot) != contents:
        raise ValueError("source changed during discovery")
    data = {"schema_version": VERSION, "source": str(source), "otelc_root": str(root), "source_manifest": contents,
            "source_sha256": identity(contents), "tools": {lang: {k: str(v) for k, v in selected.items()} for lang, selected in tools.items()},
            "artefacts": artefacts, "inventory": inventory, "cases_per_function": args.cases,
            "excluded_directories": sorted(discovery.IGNORED), "excluded_languages": sorted(set(discovery.LANGUAGES.values()) - set(args.language or discovery.LANGUAGES.values())),
            "generator_sha256": generator_identity(), "cli_sha256": capture.file_digest(Path(os.environ["OTELEQ_EXECUTABLE"]))}
    write(workspace / PLAN_FILE, data)
    marker = read(workspace / OWNED_MARKER)
    marker["plan_sha256"] = identity(data)
    write(workspace / OWNED_MARKER, marker)
    print(workspace, flush=True)
    return 0


def package_files(package, spec):
    files = {}
    for directory in spec.submodule_search_locations or []:
        base = Path(directory)
        for path in sorted(base.rglob("*")):
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
    names = ("generation.py", "discovery.py", "harness.py", "observe.py", "discover.mjs", "discover.go", "Discover.java")
    files = {name: capture.file_digest(here / name) for name in names}
    files["host-python"] = capture.file_digest(Path(sys.executable))
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
    if manifest(Path(data["source"])) != data["source_manifest"] or manifest(workspace / "snapshot") != data["source_manifest"]:
        raise ValueError("application source or immutable snapshot changed")
    if generated and manifest(workspace / "tests") != read(workspace / GENERATED_MANIFEST):
        raise ValueError("generated suite or corpus changed; create a new plan")
    return workspace, data


def generate(args):
    workspace, data = load_workspace(args.workspace)
    destination = workspace / "tests"
    destination.mkdir(exist_ok=False)
    cases = []
    for entry in data["inventory"]:
        if entry["status"] == "ready":
            for index, values in enumerate(harness.corpus(entry, data["cases_per_function"])):
                cases.append({"id": entry["id"] + "-" + str(index), "function_id": entry["id"], "arguments": values})
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
        target = preview / entry["path"]
        target.parent.mkdir(parents=True)
        shutil.copyfile(workspace / "snapshot" / entry["path"], target)
        harness.materialise(preview, entry, case["arguments"])
    write(workspace / GENERATED_MANIFEST, manifest(destination))
    (workspace / README_FILE).write_text("Generated scalar diagnostic suite. Boilerplate: MIT; application snapshot retains its original licence.\nRun: OTELEQ_PYTHON=/path/to/otelc/.venv/bin/python python3 tests/test_equivalence.py\nOr: quux-oteleq run --workspace . --report-dir /new/external/report\nEvery blocked selected callable fails the generated strict suite. No shipping-artefact or universal equivalence claim.\nKeep this whole workspace, or export-tests to a new destination.\n")
    print(json.dumps({"workspace": str(workspace), "cases": len(cases), "ready_functions": sum(e["status"] == "ready" for e in data["inventory"]), "blocked_functions": sum(e["status"] == "blocked" for e in data["inventory"])}))
    return 0


def policy(entry, endpoint):
    language = entry["language"]
    text = f'''schema_version = 2
languages = [{json.dumps(language)}]
[sources]
include = ["**"]
[functions]
include = [{json.dumps(entry['otelc_function'])}]
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
    return text


def telemetry(bodies, report, entry, service, decoder):
    # One generated invocation must start one selected trace. Recursive counts are runtime observations.
    names, _, roots, errors = capture.decode(bodies, service, decoder)
    if set(names) != {entry["otelc_function"]} or roots != 1 or not all(n > 0 for n in names.values()):
        raise ValueError("selected function was not witnessed as one complete invocation tree")
    spec = {"functions": names, "trees": 1, "errors": errors}
    return capture.witness(bodies, report, spec, service, decoder, entry["language"])


def driver_path(project, entry):
    language = entry["language"]
    relative = {"python": "_oteleq_generated/driver.py", "c": "_oteleq_driver.c", "cpp": "_oteleq_driver.cpp"}.get(language)
    if language == "java":
        relative = str(Path(entry["path"]).parent / "OteleqDriver.java")
    return project / (relative or entry["path"])


def build_command(root, project, entry, driver, config, tools, env, folder, scratch, lane):
    language = entry["language"]
    prefix = [root / "target/debug/quux-otelc", "--config", config, "--language", language]
    if language in ("c", "cpp"):
        return native_command(prefix, project, language, driver, tools, env, folder, scratch, lane)
    if language == "java":
        classes = scratch / "classes"
        classes.mkdir()
        build = execute([tools["javac"], "-d", classes, project / entry["path"], driver], project, env, folder / "build")
        if build.returncode:
            raise ValueError("generated Java build failed; inspect build/stderr")
        main = (entry["package"] + "." if entry["package"] else "") + "OteleqDriver"
        command = [tools["java"], "-Xshare:off", "-cp", classes, main] if lane == "baseline" else prefix + ["java", "-Xshare:off", "-cp", classes, main]
    else:
        # Use the proven build recipes, with bounded execution for every build and launch.
        old_execute = capture.execute
        capture.execute = lambda command, cwd, environment, timeout=180: execute(command, cwd, environment, folder / ("build-" + uuid.uuid4().hex), timeout)
        try:
            plain, on = capture.commands(root, project, language, driver, config, tools, env, folder)
        finally:
            capture.execute = old_execute
        command = plain if lane == "baseline" else on
    return command


def native_command(prefix, project, language, driver, tools, env, folder, scratch, lane):
    compiler = "clang++" if language == "cpp" else "clang"
    flags = ["-O2", "-pthread", "-std=c++17"] if language == "cpp" else ["-O1", "-pthread"]
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
    for candidate in project.rglob("*"):
        if candidate.is_symlink() or (candidate.suffix in discovery.LANGUAGES and candidate.relative_to(project).as_posix() not in immutable):
            raise ValueError("unexpected source or symlink appeared in the private project")
    if not (folder / BUILD_IDENTITIES).exists():
        write(folder / BUILD_IDENTITIES, {name: capture.file_digest(project / name)
              for name in ("plain", "instrumented") if (project / name).is_file()})


def qualify_attempt(data, entry, lane, folder, result, bodies, errors, service, decoder):
    if errors or result.returncode:
        raise ValueError("application exit or OTLP capture failed; inspect retained stdout/stderr")
    observation = folder / "observation"
    if not observation.is_file() or observation.stat().st_size > MAX_OUTPUT:
        raise ValueError("missing or oversized typed observation")
    if len(result.stdout) + len(result.stderr) + observation.stat().st_size > MAX_CHANNEL_BYTES:
        raise ValueError("case observation exceeds comparator channel budget")
    witness = None
    if lane == "baseline":
        if bodies:
            raise ValueError("baseline unexpectedly exported telemetry")
    else:
        witness = telemetry(bodies, read(folder / "runtime.json"), entry, service, decoder)
    return {"source_sha256_before": data["source_sha256"], "source_sha256_after": data["source_sha256"],
            "termination": {"kind": "exit", "code": 0}, "capture_complete": True,
            "channels": {"stdout": list(result.stdout), "stderr": list(result.stderr), "state-and-outcome": list(observation.read_bytes())}, "witness": witness}



def attempt(workspace, data, entry, case, lane, folder, decoder):
    root, language = Path(data["otelc_root"]), entry["language"]
    tools = {k: Path(v) for k, v in data["tools"][language].items()}
    capture.stable(root, language, tools, data["artefacts"][language])
    folder.mkdir(parents=True)
    project = folder / "project"
    shutil.copytree(workspace / "snapshot", project)
    shutil.copytree(workspace / "tests/harnesses" / case["id"], project, dirs_exist_ok=True)
    driver = driver_path(project, entry)
    service = "oteleq-gen-" + uuid.uuid4().hex
    env = capture.environment(project, tools, service, root)
    scratch = folder / "scratch"
    scratch.mkdir()
    env.update({"TMPDIR": str(scratch), "HOME": str(scratch), "GOCACHE": str(workspace / "go-cache"), "GOTOOLCHAIN": "local",
                "OTELEQ_OBSERVATION": str(folder / "observation"), "OTELC_REPORT_PATH": str(folder / "runtime.json")})
    immutable = manifest(project)
    with capture.receiver() as (endpoint, bodies, errors):
        config = folder / "policy.toml"
        config.write_text(policy(entry, endpoint))
        command = build_command(root, project, entry, driver, config, tools, env, folder, scratch, lane)
        write(folder / "command.json", [str(p) for p in command])
        result = execute(command, project, env, folder, timeout=60)
    capture.retain_http(folder, bodies, errors)
    validate_private_sources(project, immutable, folder)
    capture.stable(root, language, tools, data["artefacts"][language])
    return qualify_attempt(data, entry, lane, folder, result, bodies, errors, service, decoder)

def compare_case(workspace, data, entry, case, destination, decoder):
    write(destination / "corpus.json", case)
    observed = {"baseline": [], "instrumented_on": []}
    for lane in observed:
        for repeat in range(2):
            observed[lane].append(attempt(workspace, data, entry, case, lane, destination / f"{lane}-{repeat}", decoder))
    selected = observed["instrumented_on"][0]["witness"]["functions"]
    diagnostic = {"source": data["source_sha256"], "harness": manifest(workspace / "tests/harnesses" / case["id"]),
                  "tools": {name: sha for name, sha in data["artefacts"][entry["language"]].items() if name.startswith("tool:")}}
    scope = {"language": entry["language"], "artefact_class": "diagnostic", "source_sha256": data["source_sha256"],
             "baseline_artefact_sha256": identity(diagnostic), "instrumented_artefact_sha256": identity({**diagnostic, "adapter": data["artefacts"][entry["language"]]}),
             "policy_sha256": capture.digest(policy(entry, "receiver").encode()), "observer": "oteleq scalar generator v1; independently one selected root, recursive span counts observed",
             "channels": ["stdout", "stderr", "state-and-outcome"],
             "gaps": ["scalar corpus; business preconditions and branch exhaustiveness not established", "diagnostic access/entrypoint helpers; not shipping artefact evidence", "artefact digests aggregate diagnostic inputs and qualified tools/adapters; emitted runtime compiler/loader outputs are outside those digests", "no filesystem/network, imported-module globals, instrumented-off or concurrent-schedule qualification", "exception traceback/stack and Java/C++ extra exception fields are unobserved", "compiler sysroots and OS libraries are outside content identity", "trusted local execution; no hostile-code sandbox"]}
    bundle = {"workload_schema_version": 1, "scope": scope, "cases": [{"case_id": case["id"], "corpus_sha256": identity(case),
              "expected_functions": selected, "expected_spans": sum(selected.values()), **observed}]}
    write(destination / "bundle.json", bundle)
    result = execute([os.environ["OTELEQ_EXECUTABLE"], "compare-workload", destination / "bundle.json"], workspace,
                     folder=destination / "comparator")
    (destination / "comparison.json").write_bytes(result.stdout)
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
        results.append(result)
        write(destination / "partial-results.json", results)
    blocked = [e for e in data["inventory"] if e["status"] == "blocked"] if args.command == "run" else []
    load_workspace(workspace, generated=True)
    codes = {r["exit_code"] for r in results}
    code = next((c for c in (4, 2, 1, 3) if c in codes), 3 if blocked or not results else 0)
    report = {"schema_version": VERSION, "claim": "equivalence over these tests and observations", "exit_code": code,
              "cases": results, "blocked": blocked, "inventory": data["inventory"], "source_sha256": data["source_sha256"],
              "source_preserved": True, "workspace": str(workspace), "artefact_class": "diagnostic"}
    write(destination / "report.json", report)
    print(json.dumps({"report": str(destination / "report.json"), "exit_code": code, "cases": len(results), "blocked": len(blocked)}), flush=True)
    return code


def export_tests(args):
    workspace, data = load_workspace(args.workspace, generated=True)
    destination = args.destination.resolve()
    if destination.exists() or destination.is_relative_to(workspace) or workspace.is_relative_to(destination):
        raise ValueError("export destination must be new and independent of the workspace")
    if not args.apply:
        print(json.dumps({"destination": str(destination), "copy": ["snapshot", "tests", PLAN_FILE, README_FILE], "mode": "dry-run"}))
        return 0
    destination.mkdir(mode=0o700)
    for name in ("snapshot", "tests"):
        shutil.copytree(workspace / name, destination / name)
    for name in (OWNED_MARKER, GENERATED_MANIFEST, README_FILE):
        shutil.copyfile(workspace / name, destination / name)
    data["original_source"] = data["source"]
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
    if args.workspace.is_symlink() or workspace.parent == workspace or read(workspace / OWNED_MARKER)["schema_version"] != VERSION:
        raise ValueError("refusing to remove an unowned workspace")
    allowed = {OWNED_MARKER, PLAN_FILE, "snapshot", "tests", GENERATED_MANIFEST, README_FILE, "runs", "go-cache"}
    if any(p.name not in allowed for p in workspace.iterdir()):
        raise ValueError("workspace contains unowned files; retain and inspect it")
    if (workspace / PLAN_FILE).exists():
        data = read(workspace / PLAN_FILE)
        if manifest(workspace / "snapshot") != data["source_manifest"]:
            raise ValueError("snapshot was edited; retain and inspect it")
    if (workspace / GENERATED_MANIFEST).exists() and manifest(workspace / "tests") != read(workspace / GENERATED_MANIFEST):
        raise ValueError("generated suite was edited; retain and inspect it")
    shutil.rmtree(workspace)
    return 0


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    commands = parser.add_subparsers(dest="command", required=True)
    planning = commands.add_parser("plan", help="AST inventory and external immutable snapshot")
    planning.add_argument("--source", type=Path, required=True)
    planning.add_argument("--otelc-root", type=Path, required=True)
    planning.add_argument("--workspace-parent", type=Path)
    planning.add_argument("--language", action="append", choices=sorted(set(discovery.LANGUAGES.values())))
    planning.add_argument("--exclude", action="append", default=[])
    planning.add_argument("--cases", type=int, default=3, choices=range(1, 17))
    for command in COMMANDS[1:]:
        sub = commands.add_parser(command)
        sub.add_argument("--workspace", type=Path, required=True)
        if command == "run":
            sub.add_argument("--report-dir", type=Path, required=True)
        elif command == "replay":
            sub.add_argument("--case", required=True)
        elif command == "export-tests":
            sub.add_argument("--destination", type=Path, required=True)
            sub.add_argument("--apply", action="store_true")
    args = parser.parse_args(argv)
    try:
        return {"plan": plan, "generate": generate, "run": run, "replay": run, "clean": clean, "export-tests": export_tests}[args.command](args)
    except (ValueError, OSError, KeyError, ImportError) as error:
        print("oteleq: " + str(error), file=sys.stderr)
        return 4


if __name__ == "__main__":
    raise SystemExit(main())
