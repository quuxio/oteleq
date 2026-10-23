"""Qualify reduced and fresh-source live-control suites on actual applications."""

import hashlib
import json
from pathlib import Path
import shutil
import sys
import tomllib

import node_controls_oracle as oracle
from qualify_generation import command
from qualify_project_tests import command as project_command
import qualify_node_controls as controls


def alter_otlp(attempt: Path, name: str) -> None:
    """Remove actual trace receipt or retained cumulative call measurements."""
    from opentelemetry.proto.collector.trace.v1.trace_service_pb2 import ExportTraceServiceRequest
    from opentelemetry.proto.collector.metrics.v1.metrics_service_pb2 import ExportMetricsServiceRequest
    http = json.loads((attempt / 'http-capture.json').read_bytes())
    for row in http['bodies']:
        path = attempt / row['file']
        if name == 'missing-trace' and row['path'] == '/v1/traces':
            message = ExportTraceServiceRequest.FromString(path.read_bytes())
            message.ClearField('resource_spans')
            path.write_bytes(message.SerializeToString())
            return
        if name == 'retained-metric' and row['path'] == '/v1/metrics':
            message = ExportMetricsServiceRequest.FromString(path.read_bytes())
            suppress_calls(message)
            path.write_bytes(message.SerializeToString())


def suppress_calls(message) -> None:
    """Keep valid metric framing while withholding the second collected call."""
    for resource in message.resource_metrics:
        for scope in resource.scope_metrics:
            for metric in scope.metrics:
                if metric.name == 'otelc.function.calls':
                    for point in metric.sum.data_points:
                        point.as_int = 1


def alter_exports(attempt: Path, name: str) -> None:
    """Keep each reply internally valid while breaking its temporal contract."""
    root = Path(__file__).resolve().parents[1]
    sys.path[:0] = [str(root / 'adapters/generation'), str(root / 'examples')]
    from node_control_receipt import control_statuses
    path = attempt / 'node-controls.json'
    record = json.loads(path.read_bytes())
    if name == 'off-export-admission':
        step = next(step for step in record['steps'] if not step['requested']['emission'])
        rows = [step['after'][key] for key in ('status', 'flush', 'settled')]
        increase = 1
    elif name == 'export-counter-rollback':
        record['restored']['flush'].update(export_started=0, export_succeeded=0, export_failed=0)
        rows, increase = [], 0
    else:
        final = json.loads((attempt / 'node-runtime/node-status.json').read_bytes())
        rows = list(control_statuses(record))
        increase = final['export_started'] + 1
    for current in rows:
        current['export_started'] += increase
        current['export_succeeded'] += increase
    path.write_text(json.dumps(record))


def receipt_controls(profile: Path, workspace: Path, folder: Path) -> int:
    """Actual retained control and OTLP alterations must fail the product verifier."""
    root = Path(__file__).resolve().parents[1]
    sys.path[:0] = [str(root / 'adapters/generation'), str(root / 'examples')]
    import node_telemetry
    from opentelemetry.proto.collector.trace.v1.trace_service_pb2 import ExportTraceServiceRequest

    report = json.loads((profile / 'comparison/report.json').read_bytes())
    case = next(case for case in report['cases'] if case['function'].endswith('.difference'))
    plan = json.loads((workspace / 'plan.json').read_bytes())
    entry = next(entry for entry in plan['inventory'] if entry['otelc_function'] == case['function'])
    original = profile / 'comparison' / case['case'] / 'instrumented_on-0'

    def verify(attempt):
        http = json.loads((attempt / 'http-capture.json').read_bytes())
        if http['errors']:
            raise ValueError('altered control fixture has incomplete capture')
        bodies = [(row['path'], (attempt / row['file']).read_bytes()) for row in http['bodies']]
        policy = tomllib.loads((attempt / 'policy.toml').read_text())
        node_telemetry.witness(attempt, entry, bodies, policy['resource']['service_name'], ExportTraceServiceRequest)

    verify(original)
    edits = {
        'pid': lambda record: record.update(pid=record['pid'] + 1),
        'sdk-pid': lambda record: record.update(sdk_pid=record['sdk_pid'] + 1),
        'launch': lambda record: record.update(launch_id='0' * 32),
        'setter': lambda record: record['steps'][1]['before']['history'][1]['status'].update(emission=False),
        'call-count': lambda record: record['steps'][2]['after']['settled'].update(function_completions=4),
        'held-window': lambda record: record['steps'][1]['after'].update(held_ns=0),
        'metric-window': lambda record: record['steps'][1]['after'].update(metric_bodies=[0]),
        'restoration': lambda record: record['restored'].update(cursor=record['steps'][-1]['after']['cursor']),
    }
    export_errors = {'off-export-admission': 'drained emission-off window',
                     'export-counter-rollback': 'moved backwards',
                     'export-final-bound': 'exceed the final SDK report'}
    for name in (*edits, 'missing-trace', 'retained-metric', *export_errors):
        attempt = folder / ('altered-' + name)
        shutil.copytree(original, attempt)
        if name in edits:
            path = attempt / 'node-controls.json'
            record = json.loads(path.read_bytes());edits[name](record)
            path.write_text(json.dumps(record))
        elif name in export_errors:
            alter_exports(attempt, name)
        else:
            alter_otlp(attempt, name)
        try:
            verify(attempt)
        except ValueError as error:
            if name in export_errors and export_errors[name] not in str(error):
                raise ValueError('export counter control failed for an unrelated reason: ' + name) from error
            (folder / (name + '.refusal.json')).write_text(json.dumps({'refused': True, 'reason': str(error)}) + '\n')
        else:
            raise ValueError('altered actual live-control evidence was accepted: ' + name)
    verify(original)
    return len(edits) + 2 + len(export_errors)


def current_suite(bundle: Path, application: Path, folder: Path, name: str, *, result: float) -> set[tuple[str, int]]:
    """Check the fresh snapshot and complete observations after a real body change."""
    output = project_command([sys.executable, "-I", "-B", bundle / "test_equivalence.py"],
        folder, name, 1, {"OTELEQ_SOURCE": str(application), "OTELEQ_WORKSPACE_PARENT": str(folder)})
    rows = [json.loads(line) for line in output.splitlines()]
    if len(rows) != len(oracle.METHODS) + 1 or rows[0].get("project_source") != str(application):
        raise ValueError("promoted live-control suite lost its current source or cases")
    workspace = Path(rows[0]["workspace"])
    plan = json.loads((workspace / "plan.json").read_bytes())
    for name, digest in plan["source_manifest"].items():
        if hashlib.sha256((application / name).read_bytes()).hexdigest() != digest:
            raise ValueError("promoted live-control snapshot differs from current source")
    identities, methods = set(), set()
    for row in rows[1:]:
        path = Path(row["report"])
        case = json.loads(path.read_bytes())["cases"][0]
        method = case["function"].rsplit('.', 1)[-1]
        if method in methods:
            raise ValueError("promoted live-control suite repeated a method")
        methods.add(method)
        identities |= controls.check_report(path, {method}, result=result)
    if methods != set(oracle.METHODS) or len(identities) != 16:
        raise ValueError("promoted live-control suite did not execute every method independently")
    return identities


def retained_routes(cli: Path, profile: Path, workspace: Path, filename: Path) -> dict:
    """Preserve all four states through reduction, replay and current-source promotion."""
    folder = profile / "retained-routes"
    folder.mkdir(mode=0o700)
    refusals = receipt_controls(profile, workspace, folder)
    report = json.loads((profile / "comparison/report.json").read_bytes())
    target = next(case for case in report["cases"] if case["function"].endswith('.difference'))
    reduced = folder / "shrink"
    command([cli, "shrink", "--workspace", workspace, "--case", target["case"],
             "--report-dir", reduced, "--trials", "1"], folder, "shrink", expected=1)
    shrink = json.loads((reduced / "shrink.json").read_bytes())
    if (shrink["original_arguments"] != [7] or shrink["reduced_arguments"] != [1]
            or shrink["status"] != "candidate_rule_minimal" or len(shrink["trials"]) != 1):
        raise ValueError("live-control reduction lost its independent domain or stable difference")
    identities = set()
    for path in [reduced / "original/report.json", reduced / "confirmation/report.json",
                 *[Path(trial["report"]) for trial in shrink["trials"]]]:
        identities |= controls.check_report(path, {"difference"})
    replay = Path(shrink["workspace"])
    identities |= controls.framework(replay, folder, "reduced-framework", {"difference"})
    output = json.loads(command([cli, "replay", "--workspace", replay, "--case", target["case"]],
                                folder, "reduced-replay", expected=1))
    identities |= controls.check_report(Path(output["report"]), {"difference"})
    if len(identities) != 20:
        raise ValueError("live-control reduction/replay launch count differs")
    bundle = folder / "project-tests"
    application = filename.parent
    arguments = [cli, "promote", "--workspace", workspace, "--source", application, "--destination", bundle]
    dry = json.loads(command(arguments, folder, "promote-plan"))
    if dry["mode"] != "dry-run" or len(dry["files"]) != 6 or bundle.exists():
        raise ValueError("live-control promotion dry-run changed files")
    command([*arguments, "--apply"], folder, "promote-apply")
    identities |= current_suite(bundle, application, folder, "promoted-original", result=42)
    original = filename.read_text()
    if original.count('return 42;') != 4:
        raise ValueError("live-control body-change fixture differs")
    try:
        filename.write_text(original.replace('return 42;', 'return 43;'))
        identities |= current_suite(bundle, application, folder, "promoted-changed", result=43)
    finally:
        filename.write_text(original)
    if len(identities) != 52:
        raise ValueError("live-control retained routes reused an application")
    record = {"actual_applications": len(identities), "application_identities": sorted(identities),
              "reduced_arguments": shrink["reduced_arguments"], "changed_return": 43,
              "source_preserved": filename.read_text() == original, "evidence_refusals": refusals}
    (folder / "QUALIFICATION.json").write_text(json.dumps(record, indent=2) + '\n')
    return record
