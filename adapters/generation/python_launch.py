"""Own generated Python prepared launches and independent source admission."""

from dataclasses import dataclass
import hashlib
import os
from pathlib import Path
import sys
import tomllib

import otelc_capture as capture
import otelc_collection
import python_execution
import python_health
import python_inputs
import python_prepared as prepared
import python_provider as provider
import python_selection as selection
import sequences

LAUNCH_FILE = "python-launch.json"
ORIGIN_FILE = "python-expected-origins.json"
BOOTSTRAP = (
    "import json,sys;from pathlib import Path;sys.path.insert(0,sys.argv[1]);"
    "from otelc.config import Policy;from otelc import prepared_python;"
    "print(json.dumps(prepared_python.prepare(Policy.load(Path(sys.argv[2])),Path(sys.argv[3]),"
    "root=Path(sys.argv[4]),entry=sys.argv[5],plain=sys.argv[6]=='plain',"
    "profile='python-native-origins-v2'),sort_keys=True))"
)
CACHE_BOOTSTRAP = BOOTSTRAP.replace(provider.ORIGIN_PROFILE, provider.CACHE_PROFILE)


@dataclass(frozen=True)
class Run:
    """Retain caller-owned facts across execution, independently of SDK records."""

    intent: prepared.Intent
    launch: dict
    selected: tuple[selection.Selection, ...]
    origin_sha256: str
    parent_pid: int
    caches: tuple[selection.Source, ...] | None = None


def selected_source(project: Path, entry: dict) -> tuple[selection.Selection, ...]:
    """Bind the target and any existing source constructor/factory before launch."""
    source = selection.freeze(project / entry["path"])
    items = [selection.Selection(source, entry["name"], entry["line"])]
    fixture = entry.get("receiver_fixture", {})
    if fixture.get("source_function"):
        items.append(selection.Selection(source, fixture["source_function"], fixture["line"]))
    return tuple(items)


def interpreter(workflow, python: Path, root: Path, environment: dict, folder: Path) -> dict:
    """Observe the selected launcher's native argv0 without site or app hooks."""
    bootstrap = ("import json,sys;print(json.dumps({'version':sys.version,"
                 "'cache_tag':sys.implementation.cache_tag,'argv0':sys.orig_argv[0]}))")
    command = [python, "-I", "-S", "-B", "-c", bootstrap]
    clean = {key: value for key, value in environment.items()
             if not key.startswith(("PYTHON", "OTEL_", "OTELC_", "GH_", "GITHUB_", "SONAR_"))}
    result = workflow.execute(command, root, clean, folder / "python-interpreter", timeout=10, max_output_bytes=4096)
    provider.require(result.returncode == 0, "selected interpreter probe failed")
    value = capture.strict_json(result.stdout)
    provider.require(type(value) is dict and set(value) == {"version", "cache_tag", "argv0"}
                     and value["version"] == sys.version and value["cache_tag"] == sys.implementation.cache_tag
                     and type(value["argv0"]) is str and bool(value["argv0"]) and "\0" not in value["argv0"],
                     "selected interpreter probe differs from the generator host")
    workflow.write(folder / "python-interpreter.json", {"argv": list(map(str, command)), "observed": value})
    return value


def prepare(workflow, root: Path, project: Path, entry: dict, driver: Path,
            tools: dict, environment: dict, folder: Path, config: Path,
            lane: str, catalogue: dict, *, caches: tuple[selection.Source, ...] | None = None) -> Run:
    """Prepare through one fixed API bootstrap and verify its complete response."""
    provider.refuse_unbound(entry)
    provider.require(provider.origin(entry) and tools["python"] == Path(sys.executable).absolute(),
                     "origin execution requires the selected host Python spelling")
    provider.require(lane in ("baseline", "instrumented_on"), "unknown generated Python lane")
    provider.require((caches is not None) == provider.cached(entry), 'Python cache execution lacks its caller-owned context')
    frozen = selected_source(project, entry)
    selected_python = interpreter(workflow, tools["python"], root, environment, folder)
    intent = prepared.Intent(root, project, folder / "python-runtime", driver.relative_to(project),
                             root, tools["python"], selected_python, tomllib.loads(config.read_text()),
                             config, dict(environment), lane == "baseline", profile=entry['python_profile'])
    prepared.optimisation(intent)
    expected = {"python_hexversion": sys.hexversion, "optimisation": prepared.optimisation(intent),
                "plain": intent.plain, "parent_pid": os.getpid(), "selected": [
        {"path_hex": item.source.path.hex(), "sha256": item.source.sha256,
         "device": item.source.device, "inode": item.source.inode,
         "mtime_ns": item.source.mtime_ns, "mode": item.source.mode,
         "qualname": item.qualname, "line": item.line} for item in frozen]}
    if caches is not None:
        expected['caches'] = [{
            'path_hex': item.path.hex(), 'sha256': item.sha256, 'device': item.device,
            'inode': item.inode, 'mtime_ns': item.mtime_ns, 'mode': item.mode} for item in caches]
    workflow.write(folder / ORIGIN_FILE, expected)
    bootstrap = CACHE_BOOTSTRAP if provider.cached(entry) else BOOTSTRAP
    command = [tools["python"], "-I", "-S", "-B", "-c", bootstrap, root, config,
               intent.runtime, project, intent.entry, "plain" if intent.plain else "instrumented"]
    result = workflow.execute(command, root, environment, folder / "python-prepare", timeout=180,
                              max_output_bytes=prepared.MAX_METADATA)
    provider.require(result.returncode == 0, "generated prepare-only failed; inspect python-prepare/stderr")
    launch = capture.strict_json(result.stdout)
    workflow.write(folder / "python-expected-request.json", prepared.expected_request(intent))
    prepared.verify(launch, intent, catalogue)
    provider.require(python_inputs.artefacts(root, tools) == catalogue, "preparation changed frozen provider inputs")
    provider.require(selected_source(project, entry) == frozen, "preparation changed selected source facts")
    if caches is not None:
        provider.require(tuple(selection.freeze(Path(os.fsdecode(item.path))) for item in caches) == caches,
                         'preparation changed frozen Python cache inputs')
    workflow.write(folder / LAUNCH_FILE, launch)
    return Run(intent, launch, frozen, capture.file_digest(folder / ORIGIN_FILE), expected["parent_pid"], caches)


def verify(workflow, run: Run, entry: dict, folder: Path, result,
           catalogue: dict) -> tuple[python_execution.Execution, dict[int, str]]:
    """Require actual owner, source execution and all selected SDK code joins."""
    provider.require(capture.file_digest(folder / ORIGIN_FILE) == run.origin_sha256
                     and provider.same(workflow.read(folder / LAUNCH_FILE), run.launch),
                     "caller-owned Python launch or prelaunch source facts changed")
    provider.require(provider.same(workflow.read(folder / "python-expected-request.json"),
                                   prepared.expected_request(run.intent)), "caller-owned Python expected request changed")
    provider.require(selected_source(run.intent.project, entry) == run.selected,
                     "selected source changed during generated execution")
    provider.require((run.caches is not None) == provider.cached(entry), 'Python cache execution context changed')
    if run.caches is not None:
        provider.require(tuple(selection.freeze(Path(os.fsdecode(item.path))) for item in run.caches) == run.caches,
                         'Python cache inputs changed during generated execution')
    process = workflow.read(folder / "process.json")
    command = prepared.expected_command(run.intent)
    provider.require(type(process) is dict and set(process) == {"pid", "argv"}
                     and process["argv"] == command, "missing actual Python supervisor process")
    owner = python_execution.Owner(process["pid"], run.parent_pid, tuple(command), result.returncode, sys.hexversion)
    execution = python_execution.read(run.intent, run.launch, owner, catalogue)
    coverage = selection.verify(execution.journal, run.selected, python_version=sys.hexversion,
                                optimisation=prepared.optimisation(run.intent), plain=run.intent.plain, caches=run.caches)
    labels = {entry["name"]: entry["otelc_function"]}
    creation = provider.creator(entry)
    if creation is not None:
        labels[entry["receiver_fixture"]["source_function"]] = creation
    functions, records = {}, []
    for item in coverage:
        matches = []
        for match in item.matches:
            if match.sdk is not None:
                functions[match.sdk] = labels[item.selection.qualname]
            matches.append({"root": match.root, "execution": match.execution,
                            "member": match.member, "sdk": match.sdk})
            if run.caches is not None:
                matches[-1]['input_binding'] = match.binding
        records.append({"qualname": item.selection.qualname, "line": item.selection.line,
                        "source_sha256": item.selection.source.sha256, "matches": matches})
    workflow.write(folder / "python-verified-origins.json", {
        "source_origin": 'selected-input-bound' if provider.cached(entry) else "selected-source-bound", "expected_sha256": run.origin_sha256,
        "supervisor_pid": owner.pid, "application_pid": execution.application_pid,
        "sdk_pid": execution.sdk_pid, "selected": records})
    return execution, functions


def witness(workflow, run: Run, checked: tuple, folder: Path, entry: dict,
            bodies: list, service: str, trace_decoder) -> dict:
    """Join real decoded function totals and direct SDK health to the selection."""
    from opentelemetry.proto.collector.metrics.v1.metrics_service_pb2 import ExportMetricsServiceRequest
    import python_telemetry

    execution, functions = checked
    received = python_telemetry.decode(bodies, execution, service, functions,
                                       trace_decoder, ExportMetricsServiceRequest)
    # The decoder above checks every resource and the origin-profile scope.
    # The legacy service_spans helper accepts a different SDK scope version.
    spans = [span for route, body in bodies if route == capture.TRACE_PATH
             for group in trace_decoder.FromString(body).resource_spans
             for scope in group.scope_spans for span in scope.spans]
    target, creation = entry["otelc_function"], provider.creator(entry)
    calls = sequences.call_count(entry)
    otelc_collection.sequence_functions(spans, target, calls, creation)
    otelc_collection.serial_call_trees([span for span in spans if span.name == target], target, calls)
    if creation is not None:
        otelc_collection.serial_call_trees([span for span in spans if span.name == creation], creation, 1)
        factory_root = next(span for span in spans if span.name == creation and not span.parent_span_id)
        provider.require(all(factory_root.end_time_unix_nano <= span.start_time_unix_nano
                             for span in spans if span.name == target and not span.parent_span_id),
                         "source factory/constructor did not complete before the selected calls")
    health = python_health.read(run.intent.runtime, execution, python_health.policy_digest(run.intent.policy),
                                received["received"])
    workflow.write(folder / "python-verified-health.json", health)
    workflow.write(folder / "python-verified-telemetry.json", {**received, "source_origin":
        'selected-input-bound' if provider.cached(entry) else "selected-source-bound"})
    raw = hashlib.sha256()
    for _, body in bodies:
        raw.update(body)
    version = provider.profile_version(run.intent.profile)
    return {"decoder": "opentelemetry-proto traces/metrics and Python SDK health2; selected source origins2" if version == 2 else
            'opentelemetry-proto traces/metrics and Python SDK health2; selected source/cache inputs3',
            "raw_otlp_sha256": raw.hexdigest(), "functions": received["functions"],
            "spans": received["received"]["spans"], "losses": health["runtime_losses"], "pending": health["pending"]}
