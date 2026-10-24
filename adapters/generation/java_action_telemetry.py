"""Join generated call outcomes, scoped traces, function metrics and final health."""

import hashlib
import json
from pathlib import Path

import java_action_receipt as receipt
import java_action_run as run
import java_actions
import java_control_receipt
import java_health
import java_launch
import java_telemetry as telemetry
import java_witness as witness
import otelc_capture as capture
import sequences


def method_receipt(bodies: list, target: receipt.Target, trace_decoder, metric_decoder, *, service: str) -> dict:
    """Count only selected method invocations as function measurements.

    Diagnostic wrapper/target role spans contribute to pipeline health, but
    are never function calls. Unscoped selected calls remain visible separately.
    """
    nodes, intervals, unscoped, series = {}, {}, {}, {}
    recorded = {telemetry.CALLS: [], telemetry.DURATION: []}
    points, errors = 0, 0
    for index, (path, raw) in enumerate(bodies):
        witness.require(path in ('/v1/traces', '/v1/metrics'), 'unexpected action receipt route')
        if path == '/v1/metrics':
            current = {telemetry.CALLS: [], telemetry.DURATION: []}
            points += telemetry.metrics(telemetry.decode(metric_decoder, raw), service, target.method, current)
            series[index] = current
            for name in recorded:
                recorded[name].extend(current[name])
            continue
        for resource in telemetry.decode(trace_decoder, raw).resource_spans:
            telemetry.resource(resource.resource, service)
            for group in resource.scope_spans:
                instrumentation = group.scope.name, group.scope.version
                if instrumentation == telemetry.METHOD_SCOPE:
                    _, failed = telemetry.method_scope(group, target.owner, target.method, nodes, intervals)
                    errors += failed
                    for span in group.spans:
                        if receipt.SCOPE not in telemetry.attributes(span.attributes):
                            witness.require(not span.links, 'unscoped selected method contains unsupported links')
                            for event in span.events:
                                witness.require(event.dropped_attributes_count == 0, 'unscoped selected event lost attributes')
                                telemetry.attributes(event.attributes)
                            key = capture.span_identity(span)
                            unscoped[key] = nodes[key]
                else:
                    witness.require(instrumentation == receipt.ROLE_SCOPE
                                    and all(receipt.SCOPE in telemetry.attributes(span.attributes) for span in group.spans),
                                    'unexpected or unscoped diagnostic instrumentation')
    if unscoped:
        capture.trace_roots(unscoped)
        java_control_receipt.trees(unscoped, intervals)
    return {'selected_spans': len(nodes), 'unscoped_selected_spans': len(unscoped),
            'metric_points': points, 'series': series, 'recorded': recorded, 'errors': errors}


def metric_counts(methods: dict, received: dict, controls: dict | None, bodies: list) -> int:
    """Require every cumulative series to reach exactly the independently counted calls."""
    sizes = [action['selected_method_spans'] for action in received['actions']]
    witness.require(sum(sizes) + methods['unscoped_selected_spans'] == methods['selected_spans'],
                    'scoped and global selected-method counts differ')
    expected = methods['selected_spans']
    if controls is not None:
        witness.require(methods['unscoped_selected_spans'] == 0,
                        'live metric schedule contains calls outside the declared actions')
        expected = java_control_receipt.qualify(controls, received['pid'], bodies, sizes, methods['series'])
    for name, points in methods['recorded'].items():
        ordered = [count for _, count in sorted(points)]
        witness.require(ordered and all(0 <= count <= expected for count in ordered)
                        and ordered == sorted(ordered) and ordered[-1] == expected,
                        'missing, reset or mismatched action function metric: ' + name)
    return expected


def qualify(runtime: Path, folder: Path, entry: dict, case: dict, session: run.Session,
            bodies: list, *, service: str, trace_decoder) -> dict | None:
    """Qualify actual SDK evidence against host state frozen before each release."""
    from opentelemetry.proto.collector.metrics.v1.metrics_service_pb2 import ExportMetricsServiceRequest
    record_sha256 = session.audit()
    action = session.action
    witness.require(action.case_id == java_actions.case_id(case)
                    and action.actions == tuple(java_actions.action_ids(case))
                    and action.profile == entry[java_actions.FIELD]
                    and action.terminal is not None and action.pending is None,
                    'retained action plan is incomplete or differs from the frozen case')
    process = capture.strict_json((folder / 'process.json').read_bytes())
    launch = capture.strict_json((folder / java_launch.LAUNCH_FILE).read_bytes())
    witness.require(type(process) is dict and set(process) == {'pid', 'argv'}
                    and type(process['pid']) is int and process['pid'] == action.harness.pid
                    and process['argv'] == launch['argv'], 'actual action JVM launch identity differs')
    if action.plain:
        witness.require(not bodies and not action.controls and action.identity is None
                        and not action.armed and not action.completed,
                        'baseline contains SDK action evidence')
        return None
    witness.require(isinstance(action.identity, witness.Identity), 'missing pre-release SDK action identity')
    failed = run.outcomes((folder / 'observation').read_bytes(), entry, case)
    final = witness.read_final(runtime, pid=process['pid'], identity=action.identity)
    target = receipt.Target(*entry['otelc_function'].split('(', 1)[0].rsplit('.', 1))
    received = receipt.qualify(final, action.identity, action.receipt_actions(failed), target, bodies,
                               service=service, decoder=trace_decoder.FromString)
    methods = method_receipt(bodies, target, trace_decoder.FromString, ExportMetricsServiceRequest.FromString,
                             service=service)
    controls = java_control_receipt.read(folder, entry, process['pid'], bodies, plain=False) if sequences.controls(entry) else None
    collected = metric_counts(methods, received, controls, bodies)
    health = java_health.read(runtime)
    verified = java_health.qualify(health, pid=process['pid'], policy_sha256=launch['policy_sha256'],
        selection_sha256=launch['selection_sha256'], trace_batches=received['trace_batches'], spans=received['spans'],
        metric_batches=received['metric_batches'], metric_points=methods['metric_points'])
    summary = {**received, 'record_sha256': record_sha256,
               'selected_method_spans': methods['selected_spans'],
               'unscoped_selected_method_spans': methods['unscoped_selected_spans'],
               'collected_method_calls': collected, 'metric_points': methods['metric_points']}
    (folder / 'verified-actions.json').write_text(json.dumps(summary, indent=2) + '\n')
    (folder / 'verified-health.json').write_text(json.dumps(verified, indent=2) + '\n')
    if controls is not None:
        (folder / 'verified-controls.json').write_text(json.dumps({'control_record_sha256': controls['record_sha256'],
            'pid': process['pid'], 'selected_spans': methods['selected_spans'],
            'collected_spans': collected, 'source': 'java-controls.json'}, indent=2) + '\n')
    functions = {entry['otelc_function']: methods['selected_spans'],
                 'otelc.action.wrapper': len(received['actions']),
                 'otelc.action.target': sum(row['target_entries'] for row in received['actions'])}
    witness.require(sum(functions.values()) == received['spans'], 'pipeline receipt has unaccounted spans')
    raw = hashlib.sha256()
    for _, body in bodies:
        raw.update(body)
    return {'decoder': received['decoder'] + '; independently checked function metrics and SDK health1',
            'raw_otlp_sha256': raw.hexdigest(), 'functions': functions, 'spans': received['spans'],
            'losses': {'sdk.queue_dropped': int(health['span_accounting']['queue_dropped']),
                       'sdk.trace_export_failed': int(health['trace_exports']['units_failed']),
                       'sdk.metric_export_failed': int(health['metric_exports']['units_failed'])},
            'pending': int(health['span_accounting']['queue_pending']) + int(health['span_accounting']['sampled_active'])
                       + int(health['trace_exports']['batches_pending']) + int(health['metric_exports']['batches_pending'])}
