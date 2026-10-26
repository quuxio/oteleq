"""Qualify prepared Python transport/accounting without source-profile admission.

Use a private source-only SDK copy for each selected interpreter. Preparation
builds that copy before freezing its native products and installed inputs.
"""

import argparse
import copy
from dataclasses import replace
import hashlib
import json
import os
from pathlib import Path
import sys

from opentelemetry.proto.collector.metrics.v1.metrics_service_pb2 import ExportMetricsServiceRequest
from opentelemetry.proto.collector.trace.v1.trace_service_pb2 import ExportTraceServiceRequest

REPO = Path(__file__).resolve().parents[1]
sys.path[:0] = [str(REPO / "adapters/generation"), str(REPO / "examples")]
import generation
import python_execution
import python_health
import python_inputs
import python_prepared
import python_provider
import python_telemetry

PREFIX = '''import sys
count = 0
class Counter:
    total = 0
    def __init__(self): self.value = 0
receiver = Counter()

def workload(value: int) -> int:
    global count
    count += value
    Counter.total += 1
    receiver.value += value
'''
SUFFIX = '''
try:
    result = workload(ARGUMENT)
except ValueError as error:
    result = "ValueError:" + error.args[0]
sys.stdout.buffer.write(b"raw\\x00\\xff|" + str(result).encode() + b"|" + str(count).encode()
                        + b"|" + str(Counter.total).encode() + b"|" + str(receiver.value).encode() + b"\\n")
sys.stderr.buffer.write(b"err\\x00\\xfe\\n")
'''
CASES = {
    "ordinary": ("    return value * 2\n", 5, b"10|5|1|5", 1, 0),
    "recursive": ("    return value + workload(value - 1) if value else 0\n", 3, b"6|6|4|6", 4, 0),
    "exception": ("    raise ValueError('literal')\n", 5, b"ValueError:literal|5|1|5", 1, 1),
}


def source(case: str) -> bytes:
    """A fixed application oracle is independent of cross-lane equality."""
    body, argument, _, _, _ = CASES[case]
    return (PREFIX + body + SUFFIX.replace("ARGUMENT", str(argument))).encode()


def prepare(root: Path, folder: Path, project: Path, environment: dict, interpreter: dict,
            endpoint: str, service: str, plain: bool) -> tuple:
    """Construct fixed commands from caller intent, never from returned argv."""
    entry = {"language": "python", "python_backend": "prepared", "path": "entry.py", "otelc_function": "entry.workload"}
    config = folder / "policy.toml"
    config.write_text(python_provider.policy(entry, endpoint, service))
    policy = python_provider.configuration(entry, endpoint, service)
    runtime = folder / "runtime"
    command = [sys.executable, "-I", "-S", "-B", root / "otelc/cli_bootstrap.py", "--config", config,
               "python", "--root", project, "--entry", "entry.py", "--runtime", runtime, "--prepare-only"]
    if plain:
        command.append("--plain")
    result = generation.execute(command, root, environment, folder / "prepare", timeout=180,
                                max_output_bytes=python_prepared.MAX_METADATA)
    python_provider.require(result.returncode == 0, "actual prepare-only failed: " + str(folder))
    intent = python_prepared.Intent(root, project, runtime, Path("entry.py"), root, Path(sys.executable).absolute(),
                                    interpreter, policy, config, environment, plain)
    return intent, generation.capture.strict_json(result.stdout)


def retain_bodies(folder: Path, bodies: list) -> None:
    """Keep literal collector bodies and hashes for independent reinspection."""
    directory = folder / "raw-otlp"
    directory.mkdir()
    rows = []
    for index, (route, body) in enumerate(bodies):
        name = str(index) + ".bin"
        (directory / name).write_bytes(body)
        rows.append({"path": route, "file": name, "size": len(body), "sha256": hashlib.sha256(body).hexdigest()})
    generation.write(folder / "raw-otlp.json", rows)


def expect_refusal(callback, label: str, refused: list) -> None:
    """A negative control must reach its reader and raise a declared refusal."""
    try:
        callback()
    except ValueError:
        refused.append(label)
    else:
        raise ValueError("altered actual Python evidence passed: " + label)


def controls(intent, launch, owner, catalogue, execution, bodies, service, receipt) -> list:
    """Falsify independent identity, public health and actual protobuf receipt."""
    refused = []
    for name, changed in (("owner-parent", replace(owner, parent_pid=owner.parent_pid + 1)),
                          ("owner-exit", replace(owner, returncode=-9)), ("owner-argv", replace(owner, argv=("other",)))):
        expect_refusal(lambda: python_execution.read(intent, launch, changed, catalogue), name, refused)
    digest = python_health.policy_digest(intent.policy)
    report, _ = python_prepared.read(intent.runtime / "health.json")
    sdk, _ = python_prepared.read(intent.runtime / "sdk/python-sdk-status.json")
    for name, changed in (("invented-flush", {**report, "lifecycle": {"flush": "succeeded", "shutdown": "succeeded"}}),
                          ("invented-metric-units", {**report, "metric_exports": {**report["metric_exports"], "units_succeeded": "2"}}),
                          ("invented-source", {**report, "source_complete": True})):
        expect_refusal(lambda: python_health.qualify(changed, sdk, execution, digest, receipt), name, refused)
    changed_sdk = copy.deepcopy(sdk)
    changed_sdk["producer"]["runtime_losses"]["incomplete"] = None
    expect_refusal(lambda: python_health.qualify(report, changed_sdk, execution, digest, receipt), "unavailable-loss", refused)
    altered = []
    for route, body in bodies:
        if route == "/v1/traces":
            message = ExportTraceServiceRequest.FromString(body)
            for group in message.resource_spans:
                for attribute in group.resource.attributes:
                    if attribute.key == "process.pid":
                        attribute.value.int_value += 1
            body = message.SerializeToString()
        altered.append((route, body))
    expect_refusal(lambda: python_telemetry.decode(altered, execution, service, {1: "entry.workload"},
                                                  ExportTraceServiceRequest, ExportMetricsServiceRequest), "foreign-otlp-pid", refused)
    return refused


def attempt(root: Path, folder: Path, case: str, plain: bool, interpreter: dict, catalogue: dict, tools: dict) -> dict:
    """Fresh files, processes and fixture state isolate every repeat and lane."""
    folder.mkdir(mode=0o700)
    project = folder / "application"
    project.mkdir()
    (project / "entry.py").write_bytes(source(case))
    before = generation.manifest(project)
    service = "oteleq-python-runtime-" + case + "-" + folder.parent.name
    environment = generation.capture.environment(folder, tools, service, root)
    with generation.capture.receiver(response_path=folder / "http-responses.json") as (endpoint, bodies, errors):
        intent, launch = prepare(root, folder, project, environment, interpreter, endpoint, service, plain)
        python_prepared.verify(launch, intent, catalogue)
        python_provider.require(python_inputs.artefacts(root, tools) == catalogue, "Python preparation changed frozen SDK inputs")
        command = python_prepared.expected_command(intent)
        parent = os.getpid()
        generation.write(folder / "owner-input.json", {"parent_pid": parent, "argv": command, "python_hexversion": sys.hexversion})
        result = generation.execute(command, root, environment, folder / "owner", timeout=45, record_process=True)
    retain_bodies(folder, bodies)
    python_provider.require(not errors, "Python collector reported HTTP errors")
    known = generation.read(folder / "owner/process.json")
    owner = python_execution.Owner(known["pid"], parent, tuple(command), result.returncode, sys.hexversion)
    execution = python_execution.read(intent, launch, owner, catalogue)
    expected = b"raw\x00\xff|" + CASES[case][2] + b"\n"
    python_provider.require((result.returncode, result.stdout, result.stderr) == (0, expected, b"err\x00\xfe\n"),
                            "Python application differs from the independent complete channel/state oracle")
    if plain:
        python_provider.require(not bodies, "plain Python application emitted OTLP")
        receipt, checked, refused = None, None, []
    else:
        checked = python_telemetry.decode(bodies, execution, service, {1: "entry.workload"},
                                          ExportTraceServiceRequest, ExportMetricsServiceRequest)
        receipt = checked["received"]
        python_provider.require(checked["code_calls"] == {1: CASES[case][3]} and checked["code_errors"] == {1: CASES[case][4]}
                                and checked["roots"] == 1, "Python actual calls differ from the independent workload oracle")
        python_health.read(intent.runtime, execution, python_health.policy_digest(intent.policy), receipt)
        refused = controls(intent, launch, owner, catalogue, execution, bodies, service, receipt)
    python_provider.require(generation.manifest(project) == before and python_inputs.artefacts(root, tools) == catalogue,
                            "Python source or frozen provider/installed inputs changed during execution")
    value = {"case": case, "plain": plain, "owner_pid": owner.pid, "parent_pid": parent,
             "application_pid": execution.application_pid, "sdk_pid": execution.sdk_pid,
             "launch_id": execution.launch_id, "source_unchanged": True, "inputs_unchanged": True,
             "stdout_hex": result.stdout.hex(), "stderr_hex": result.stderr.hex(), "received": receipt,
             "decoded": checked, "altered_evidence_refused": refused, "source_origin": "unavailable"}
    generation.write(folder / "checked.json", value)
    return value


def run(root: Path, report: Path) -> dict:
    """Qualify one selected interpreter against a private, initially mutable SDK."""
    report.mkdir(mode=0o700)
    report = report.resolve(strict=True)
    tools = {"python": Path(sys.executable).absolute()}
    probe = generation.execute([sys.executable, "-I", "-S", "-B", "-c",
        "import json,sys;print(json.dumps({'version':sys.version,'cache_tag':sys.implementation.cache_tag,'argv0':sys.orig_argv[0]}))"],
        root, generation.capture.environment(report, tools, "metadata", root), report / "interpreter", max_output_bytes=4096)
    python_provider.require(probe.returncode == 0, "Python interpreter probe failed")
    interpreter = generation.capture.strict_json(probe.stdout)
    # Only preparation may create native products. All actual lanes use this
    # same subsequently frozen catalogue, including installed package bytes.
    primer = report / "primer"
    primer.mkdir()
    project = primer / "application"
    project.mkdir()
    (project / "entry.py").write_text("raise AssertionError('preparation must not run the app')\n")
    environment = generation.capture.environment(primer, tools, "primer", root)
    prepare(root, primer, project, environment, interpreter, "http://127.0.0.1:4318", "primer", True)
    catalogue = python_inputs.artefacts(root, tools)
    generation.write(report / "input-catalogue.json", catalogue)
    rows = []
    for case in CASES:
        for repeat in range(2):
            pair = report / (case + "-" + str(repeat))
            pair.mkdir()
            for plain in (True, False):
                rows.append(attempt(root, pair / ("baseline" if plain else "instrumented"), case, plain,
                                    interpreter, catalogue, tools))
    python_provider.require(python_inputs.artefacts(root, tools) == catalogue, "final Python SDK catalogue differs")
    result = {"schema_version": 1, "kind": "oteleq.python-prepared-runtime-qualification", "interpreter": interpreter,
              "python_hexversion": sys.hexversion, "attempts": rows, "input_catalogue_sha256": generation.identity(catalogue),
              "actual_application_launches": len(rows), "actual_sdk_launches": sum(not row["plain"] for row in rows),
              "altered_evidence_refusals": sum(len(row["altered_evidence_refused"]) for row in rows),
              "source_profile_status": "blocked", "source_origin": "unavailable",
              "scope": "Prepared execution1/journal1/descriptor2/health2/SDK1 and local OTLP accounting for fixed synchronous workloads. Source binding, per-action attribution, live controls, generated suites and shipping artefacts are not qualified."}
    generation.write(report / "report.json", result)
    return result


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--otelc-root", type=Path, required=True)
    parser.add_argument("--report-dir", type=Path, required=True)
    args = parser.parse_args()
    root = args.otelc_root.resolve(strict=True)
    generation.source_outside(args.report_dir, root, REPO)
    result = run(root, args.report_dir)
    print(json.dumps({"report": str(args.report_dir / "report.json"), "actual_application_launches": result["actual_application_launches"],
                      "source_profile_status": result["source_profile_status"]}))


if __name__ == "__main__":
    main()
