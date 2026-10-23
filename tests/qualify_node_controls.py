"""Qualify real source Node calls through four same-process metric states."""

import argparse
import hashlib
import json
import os
from pathlib import Path
import sys

import node_controls_oracle as oracle
from qualify_generation import command

STATES = ({"collection": True, "emission": True}, {"collection": False, "emission": True},
          {"collection": True, "emission": False}, {"collection": False, "emission": False})


def source(language: str) -> str:
    annotation = ":number" if language == "typescript" else ""
    fields = "value:number;self:Counter;" if language == "typescript" else ""
    result = "class Counter {static total=0;static delta=0;" + fields
    result += "constructor(start" + annotation + "){this.value=start;this.self=this;}\n"
    for method in oracle.METHODS:
        result += ("async " if method == "later" else "") + method + "(value" + annotation + "){"
        if method == "later":
            result += "await Promise.resolve();"
        result += "this.value+=value;Counter.total+=value;"
        result += "process.stdout.write(Buffer.from([0,255,10]));process.stderr.write(Buffer.from([1,255,10]));"
        if method == "difference":
            result += "if(value===2&&process.execArgv.some(argument=>argument.endsWith('/node-bootstrap.cjs')))Counter.delta=1;if(value===3)Counter.delta=0;"
        if method == "expected":
            result += "if(value===3)throw new TypeError('expected');"
        result += "return 42;}\n"
    return result + "}\n"


def policy(language: str, compiler: str) -> str:
    result = ('schema_version=1\nlanguages=' + json.dumps([language]) + '\n[functions]\ninclude='
              + json.dumps(["controls.Counter." + name for name in oracle.METHODS]) + '\n'
              '[adapters.node]\nbackend="source-v1"\ntypescript_compiler=' + json.dumps(compiler)
              + '\n[limits]\ncase_timeout_ms=60000\n')
    for method in oracle.METHODS:
        result += ('\n[[fixtures]]\nfunction="controls.Counter.' + method
                   + '"\ncases=[[7]]\ndomains=[{kind="integer",minimum=1,maximum=7}]\n'
                   'receiver={factory="Counter",arguments=[10]}\nsequence=[\n')
        for index, flags in enumerate(STATES):
            arguments = '"case"' if index == 0 else json.dumps([index + 1])
            expectation = ('{kind="error",category="exception",type="ecmascript.TypeError.prototype:TypeError"}'
                           if method == "expected" and index == 2 else '{kind="return"}')
            result += ('{action="call",arguments=' + arguments + ',metrics={collection='
                       + str(flags["collection"]).lower() + ',emission=' + str(flags["emission"]).lower()
                       + '},expected_baseline=' + expectation + '},\n')
        result += ']\n'
    return result


def check_attempt(folder: Path, method: str, argument: float, instrumented: bool) -> tuple[str, int]:
    """Check complete literal application graphs, bytes and actual process receipts."""
    oracle.check(json.loads((folder / "observation").read_bytes()), method, argument, instrumented)
    if (folder / "stdout").read_bytes() != bytes.fromhex("00ff0a") * 4 or (folder / "stderr").read_bytes() != bytes.fromhex("01ff0a") * 4:
        raise ValueError("live-control application byte channels differ")
    app = json.loads((folder / "node-source-application.json").read_bytes())
    control = json.loads((folder / "node-controls.json").read_bytes())
    if control["pid"] != app["pid"] or control["supervisor_pid"] != app["supervisor_pid"] or control["plain"] is not (not instrumented):
        raise ValueError("live-control actual process identity differs")
    if len(control["steps"]) != 4 or json.dumps([step["requested"] for step in control["steps"]], sort_keys=True) != json.dumps(STATES, sort_keys=True):
        raise ValueError("live-control four-state schedule differs")
    if instrumented:
        check_sdk(folder, method, control)
    elif control["sdk_pid"] is not None or control["launch_id"] is not None:
        raise ValueError("plain live-control lane fabricated an SDK")
    return str(folder.resolve()), app["pid"]


def check_sdk(folder: Path, method: str, control: dict) -> None:
    """Four actual traced calls yield exactly two collected function measurements."""
    from opentelemetry.proto.collector.metrics.v1.metrics_service_pb2 import ExportMetricsServiceRequest
    from opentelemetry.proto.collector.trace.v1.trace_service_pb2 import ExportTraceServiceRequest
    sdk = json.loads((folder / "node-runtime/node-status.json").read_bytes())
    if (sdk["pid"] != control["pid"] or sdk["sdk_pid"] != control["sdk_pid"] or sdk["launch_id"] != control["launch_id"]
            or sdk["phase"] != "closed" or sdk["function_completions"] != 4 or sdk["span_accounting"]["received"] != 4):
        raise ValueError("live-control final SDK identity or four-call accounting differs")
    bodies = json.loads((folder / "http-capture.json").read_bytes())["bodies"]
    spans, final = [], {}
    for index, row in enumerate(bodies):
        raw = (folder / row["file"]).read_bytes()
        if row["path"] == "/v1/traces":
            message = ExportTraceServiceRequest.FromString(raw)
            spans.extend(span for group in message.resource_spans for scope in group.scope_spans for span in scope.spans)
        elif row["path"] == "/v1/metrics":
            message = ExportMetricsServiceRequest.FromString(raw)
            for group in message.resource_metrics:
                for scope in group.scope_metrics:
                    if scope.scope.name != "io.quux.otelc.functions":
                        continue
                    for metric in scope.metrics:
                        points = metric.histogram.data_points if metric.name.endswith("duration") else metric.sum.data_points
                        for point in points:
                            if metric.name not in final or point.time_unix_nano > final[metric.name][0]:
                                final[metric.name] = (point.time_unix_nano, point.count if metric.name.endswith("duration") else point.as_int)
        else:
            raise ValueError("unrequested live-control telemetry route")
    if len(spans) != 4 or any(span.name != "controls.Counter." + method or span.parent_span_id for span in spans):
        raise ValueError("live-control traces did not retain every independent call")
    expected = {"otelc.function.calls": 2, "otelc.function.duration": 2}
    if method == "expected":
        expected["otelc.function.unwinds"] = 1
    if {key: value[1] for key, value in final.items()} != expected:
        raise ValueError("live-control decoded totals include suppressed calls or lose retained measurements")
    for step in control["steps"]:
        if step["after"]["settled"]["function_completions"] != int(step["id"].split('-')[-1]) + 1:
            raise ValueError("live-control trace/completion state differs")
        if not all(step["requested"].values()):
            before, after = step["before"]["cursor"], step["after"]["cursor"]
            if step["after"]["held_ns"] < 1000000000 or any(row["path"] == "/v1/metrics" for row in bodies[before:after]):
                raise ValueError("disabled live-control window did not stay silent for one interval")


def check_report(path: Path, expected_methods: set[str]) -> set[tuple[str, int]]:
    report = json.loads(path.read_bytes())
    if not report["source_preserved"] or report["blocked"] or len(report["cases"]) != len(expected_methods):
        raise ValueError("live-control report source/inventory scope differs")
    if report["exit_code"] != int("difference" in expected_methods):
        raise ValueError("live-control overall verdict differs")
    methods, identities = set(), set()
    for case in report["cases"]:
        method = case["function"].rsplit('.', 1)[-1]
        if method not in expected_methods or method in methods or case["exit_code"] != int(method == "difference"):
            raise ValueError("live-control case result differs")
        methods.add(method)
        for lane in ("baseline", "instrumented_on"):
            for index in range(2):
                folder = path.parent / case["case"] / (lane + "-" + str(index))
                identities.add(check_attempt(folder, method, case["arguments"][0], lane == "instrumented_on"))
    if methods != expected_methods or len(identities) != len(expected_methods) * 4:
        raise ValueError("live-control method or independent launch count differs")
    return identities


def framework(workspace: Path, folder: Path, name: str) -> set[tuple[str, int]]:
    text = command([sys.executable, "-I", "-B", workspace / "tests/test_equivalence.py"], folder, name, expected=1)
    rows = [json.loads(line) for line in text.splitlines()]
    if len(rows) != len(oracle.METHODS):
        raise ValueError("live-control framework case count differs")
    identities = set()
    methods = set()
    for row in rows:
        path = Path(row["report"])
        case = json.loads(path.read_bytes())["cases"][0]
        method = case["function"].rsplit('.', 1)[-1]
        if method in methods:
            raise ValueError("repeated live-control framework method")
        methods.add(method)
        identities |= check_report(path, {method})
    if methods != set(oracle.METHODS):
        raise ValueError("missing live-control framework method")
    return identities


def qualify(cli: Path, provider: Path, folder: Path, language: str, compiler: str, suffix: str) -> dict:
    folder.mkdir(mode=0o700)
    application = folder / "application";application.mkdir()
    filename = application / ("controls" + suffix)
    original = source(language);filename.write_text(original)
    config = folder / "equivalence.toml";config.write_text(policy(language, compiler))
    stages = []

    def run(stage, arguments, expected=0):
        row = {"stage": stage, "started": True};stages.append(row)
        (folder / "stages.json").write_text(json.dumps(stages, indent=2) + "\n")
        result = command([cli, *arguments], folder, stage, expected=expected)
        row["completed"] = True
        (folder / "stages.json").write_text(json.dumps(stages, indent=2) + "\n")
        return result

    workspace = Path(run("plan", ["plan", "--source", application, "--otelc-root", provider, "--workspace-parent", folder, "--config", config]))
    run("generate", ["generate", "--workspace", workspace])
    run("run", ["run", "--workspace", workspace, "--report-dir", folder / "comparison"], 1)
    identities = check_report(folder / "comparison/report.json", set(oracle.METHODS))
    identities |= framework(workspace, folder, "framework")
    inventory = {entry["id"]: entry for entry in json.loads((workspace / "plan.json").read_bytes())["inventory"]}
    for case in json.loads((workspace / "tests/corpus.json").read_bytes()):
        method = inventory[case["function_id"]]["otelc_function"].rsplit('.', 1)[-1]
        replay = json.loads(run("replay-" + method, ["replay", "--workspace", workspace, "--case", case["id"]], int(method == "difference")))
        identities |= check_report(Path(replay["report"]), {method})
    exported = folder / "exported"
    run("export-plan", ["export-tests", "--workspace", workspace, "--destination", exported])
    if exported.exists():
        raise ValueError("live-control export dry-run created files")
    run("export-apply", ["export-tests", "--workspace", workspace, "--destination", exported, "--apply"])
    detached = folder / "detached-application";application.rename(detached)
    try:
        identities |= framework(exported, folder, "detached-framework")
    finally:
        detached.rename(application)
    if filename.read_text() != original or len(identities) != 64:
        raise ValueError("live-control source preservation or application count differs")
    return {"language": language, "compiler": compiler, "suffix": suffix, "actual_applications": len(identities),
            "application_identities": sorted(identities), "source_preserved": True, "workspace": str(workspace)}


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--cli", type=Path, required=True)
    parser.add_argument("--otelc-root", type=Path, required=True)
    parser.add_argument("--report-dir", type=Path, required=True)
    args = parser.parse_args()
    cli, provider, root = args.cli.resolve(strict=True), args.otelc_root.resolve(strict=True), args.report_dir.resolve()
    if root.is_relative_to(provider) or root.is_relative_to(Path(__file__).resolve().parents[1]):
        parser.error("qualification outputs must be new and outside consumer/provider sources")
    root.mkdir(mode=0o700)
    os.environ.update(OTELEQ_PYTHON=sys.executable, OTELEQ_CLI=str(cli))
    rows = []
    for language, compiler, suffix in (("javascript", "native", ".cjs"), ("typescript", "native", ".cts"), ("typescript", "api", ".mts")):
        rows.append(qualify(cli, provider, root / (language + "-" + compiler), language, compiler, suffix))
        (root / "progress.json").write_text(json.dumps(rows, indent=2) + "\n")
    result = {"claim": "equivalence over these tests and observations", "profiles": rows,
              "actual_applications": sum(row["actual_applications"] for row in rows),
              "cli_sha256": hashlib.sha256(cli.read_bytes()).hexdigest(),
              "scope": "Declared serial receiver calls, four metric states and actual local telemetry receipt; no shipping or invocation-cookie proof."}
    (root / "QUALIFICATION.json").write_text(json.dumps(result, indent=2) + "\n")
    print(json.dumps(result))


if __name__ == "__main__":
    main()
