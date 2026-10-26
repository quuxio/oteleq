"""Alter retained actual SDK receipt; never restart applications or edit raw data."""

import copy
import dataclasses
import hashlib
import json
from pathlib import Path
import sys

SOURCE = Path('/Users/sclarke/github/oteleq-qualification/2026-10-23/java-handle-callers/source-5361e57')
sys.path[:0] = [str(SOURCE / 'adapters/generation'), str(SOURCE / 'examples')]
import java_action_receipt as receipt
import java_health
import java_provider
import java_telemetry
import java_witness
import otelc_capture as capture
from opentelemetry.proto.collector.metrics.v1.metrics_service_pb2 import ExportMetricsServiceRequest
from opentelemetry.proto.collector.trace.v1.trace_service_pb2 import ExportTraceServiceRequest

ROOT = Path(__file__).resolve().parent / sys.argv[1]


def read(path):
    return capture.strict_json(path.read_bytes())


def edit(bodies, trace_id, operation):
    """Alter one actual method span while preserving all other retained bodies."""
    changed = bodies.copy()
    for index, (route, raw) in enumerate(bodies):
        if route != '/v1/traces':
            continue
        message = ExportTraceServiceRequest.FromString(raw)
        for resource in message.resource_spans:
            for group in resource.scope_spans:
                if group.scope.name != receipt.telemetry.METHOD_SCOPE[0]:
                    continue
                for position, span in enumerate(group.spans):
                    if span.trace_id.hex() == trace_id:
                        span_id = span.span_id.hex()
                        if operation == 'remove':del group.spans[position]
                        elif operation == 'cycle':span.parent_span_id = span.span_id
                        elif operation == 'resource_loss':resource.resource.dropped_attributes_count = 1
                        elif operation == 'scope_loss':group.scope.dropped_attributes_count = 1
                        else:raise ValueError('unsupported retained alteration')
                        changed[index] = route, message.SerializeToString()
                        return changed, span_id
    raise ValueError('missing actual selected-method span')


results = []
for repeat in (1, 2):
    lane = ROOT / ('instrumented-' + str(repeat))
    runtime = lane / 'sdk-runtime'
    metadata = read(runtime / 'witness.json')
    expected = {key: metadata[key] for key in ('build_sha256', 'selection_sha256', 'policy_sha256', 'tooling_sha256')}
    expected.update({role + '_probe_id': value['probe_id'] for role, value in metadata['bindings'].items()})
    expected['route_binding_sha256'] = metadata['route']['sha256']
    pid = read(lane / 'process/process.json')['pid']
    controls = read(lane / 'controls.json')
    identity = java_witness.Identity.bind(next(row['reply'] for row in controls if row['operation'] == 'status'), expected, pid=pid, profile=java_witness.HANDLE_PROFILE)
    arms = [row['reply']['scope'] for row in controls if row['operation'] == 'arm' and row['reply']['error'] is None]
    ready = read(lane / 'harness.json')[:4]
    observations = [capture.strict_json(row) for row in (lane / 'observations.jsonl').read_bytes().splitlines()]
    actions = [receipt.Action(row['action_id'], row['case_id'], row['attempt_id'], row['thread_id'],
        arm['cookie'], arm['sequence'], arm['scope_id'], observation['outcome']['kind'] == 'error')
        for row, arm, observation in zip(ready, arms, observations)]
    assert len(actions) == 4
    final = read(runtime / 'witness-health.json')
    index = read(lane / 'otlp/index.json')
    bodies = [(row['route'], (lane / 'otlp' / row['file']).read_bytes()) for row in index]
    assert all(hashlib.sha256(body).hexdigest() == row['sha256'] for row, (_, body) in zip(index, bodies))
    service = read(lane / 'policy.json')['resource']['service_name']

    def qualify(report, raw, expected_actions):
        value = receipt.qualify(report, identity, expected_actions, receipt.Target('ActionFixture', 'target'),
            raw, service=service, decoder=ExportTraceServiceRequest.FromString)
        recorded = {java_telemetry.CALLS: [], java_telemetry.DURATION: []}
        points = sum(java_telemetry.metrics(ExportMetricsServiceRequest.FromString(body), service, 'target', recorded)
                     for route, body in raw if route == '/v1/metrics')
        java_health.qualify(java_health.read(runtime), pid=pid, policy_sha256=expected['policy_sha256'],
            selection_sha256=expected['selection_sha256'], trace_batches=value['trace_batches'], spans=value['spans'],
            metric_batches=value['metric_batches'], metric_points=points)
        for samples in recorded.values():
            values = [count for _, count in sorted(samples)]
            java_provider.require(bool(values) and values[-1] == 7 and values == sorted(values)
                and all(0 <= count <= 7 for count in values), 'retained function metrics differ')
        return value

    assert qualify(final, bodies, actions) == read(lane / 'verified-action-receipt.json')
    qualify(final, list(reversed(bodies)), actions)
    results.extend([{'repeat': repeat, 'case': name, 'accepted': True} for name in ('original', 'reversed_body_arrival')])
    for kind in ('remove', 'cycle', 'resource_loss', 'scope_loss', 'joint_omission',
                 'wrong_thread', 'wrong_outcome', 'wrong_count', 'missing_metrics',
                 'wrong_route', 'unverified_route', 'missing_route', 'mistyped_route', 'v2_fallback'):
        report, raw, expected_actions = copy.deepcopy(final), bodies, actions.copy()
        if kind in ('remove', 'cycle', 'resource_loss', 'scope_loss', 'joint_omission'):
            raw, span_id = edit(bodies, report['scopes'][0]['trace_id'], 'remove' if kind == 'joint_omission' else kind)
            if kind == 'joint_omission':
                for key in ('started_ids', 'ended_ids', 'exported_ids'):report['scopes'][0][key].remove(span_id)
        elif kind == 'wrong_thread':expected_actions[0] = dataclasses.replace(actions[0], thread_id=str(int(actions[0].thread_id) + 1))
        elif kind == 'wrong_outcome':expected_actions[0] = dataclasses.replace(actions[0], failed=not actions[0].failed)
        elif kind == 'wrong_count':report['scopes'][0]['target_entries'] = str(int(report['scopes'][0]['target_entries']) + 1)
        elif kind == 'missing_metrics':raw = [row for row in bodies if row[0] != '/v1/metrics']
        elif kind == 'wrong_route':report['producer']['route_binding_sha256'] = '0' * 64
        elif kind == 'unverified_route':report['scopes'][0]['route_verified'] = False
        elif kind == 'missing_route':del report['producer']['route_binding_sha256']
        elif kind == 'mistyped_route':report['scopes'][0]['route_verified'] = 1
        elif kind == 'v2_fallback':report['producer']['profile'] = java_witness.PROFILE
        try:
            qualify(report, raw, expected_actions)
        except ValueError as error:
            results.append({'repeat': repeat, 'case': kind, 'accepted': False, 'refusal': str(error)})
        else:
            raise AssertionError('altered actual receipt passed: ' + kind)
    assert all(hashlib.sha256((lane / 'otlp' / row['file']).read_bytes()).hexdigest() == row['sha256'] for row in index)

record = {'consumer_head': 'c57870ee44af7cac47ad8229b5d0ed57a4f84150',
    'proof_sha256': hashlib.sha256((ROOT / 'proof.json').read_bytes()).hexdigest(),
    'application_started': False, 'raw_files_preserved': True, 'cases': results}
(ROOT / 'alteration-controls.json').write_text(json.dumps(record, indent=2) + '\n')
print(json.dumps({'accepted': sum(row['accepted'] for row in results),
    'refused': sum(not row['accepted'] for row in results),
    'sha256': hashlib.sha256((ROOT / 'alteration-controls.json').read_bytes()).hexdigest()}))
