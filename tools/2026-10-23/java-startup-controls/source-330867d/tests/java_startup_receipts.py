"""Actual Java control and OTLP alterations must fail the product verifier."""

from collections.abc import Callable
import json
from pathlib import Path
import shutil
import sys
import tomllib

ROOT = Path(__file__).resolve().parents[1]
sys.path[:0] = [str(ROOT / 'adapters/generation'), str(ROOT / 'examples')]
import java_telemetry
from opentelemetry.proto.collector.trace.v1.trace_service_pb2 import ExportTraceServiceRequest
from opentelemetry.proto.collector.metrics.v1.metrics_service_pb2 import ExportMetricsServiceRequest


def read(path: Path) -> dict:
    return json.loads(path.read_bytes())


def edit(path: Path, change: Callable[[dict], None]) -> None:
    value = read(path)
    change(value)
    path.write_text(json.dumps(value) + '\n')


def receipt_edits(states: tuple[tuple[bool, bool], ...]) -> dict:
    """Alter the actual initial state and a real emission-off boundary."""
    off = next(index for index, state in enumerate(states) if not state[1])

    def flag(record: dict, step: int, acknowledgement: int, key: str) -> None:
        status = record['steps'][step]['before']['history'][acknowledgement]['status']
        status[key] = not status[key]
        status['effective_emission_off'] = not status['emission'] and status['in_flight_exports'] == 0

    return {
        'pid': lambda value: value.update(pid=value['pid'] + 1),
        'initial-collection': lambda value: flag(value, 0, 0, 'collection'),
        'initial-emission': lambda value: flag(value, 0, 0, 'emission'),
        'setter': lambda value: flag(value, 1, 1, 'emission'),
        'call-count': lambda value: value['steps'][2]['after']['settled'].update(completed=999),
        'held-window': lambda value: value['steps'][off]['after'].update(held_ns=0),
        'metric-window': lambda value: value['steps'][off]['after'].update(metric_bodies=[0]),
        'restoration': lambda value: value['restored'].update(cursor=value['steps'][-1]['after']['cursor']),
    }


def alter_otlp(attempt: Path, name: str) -> None:
    for row in read(attempt / 'http-capture.json')['bodies']:
        path = attempt / row['file']
        if name == 'missing-trace' and row['path'] == '/v1/traces':
            message = ExportTraceServiceRequest.FromString(path.read_bytes())
            message.ClearField('resource_spans')
            path.write_bytes(message.SerializeToString())
            return
        if name == 'retained-metric' and row['path'] == '/v1/metrics':
            message = ExportMetricsServiceRequest.FromString(path.read_bytes())
            for resource in message.resource_metrics:
                for scope in resource.scope_metrics:
                    for metric in scope.metrics:
                        if metric.name == 'otelc.function.calls':
                            for point in metric.sum.data_points:
                                point.as_int = 1
            path.write_bytes(message.SerializeToString())


def verify(attempt: Path, entry: dict) -> None:
    capture = read(attempt / 'http-capture.json')
    assert not capture['errors']
    bodies = [(row['path'], (attempt / row['file']).read_bytes()) for row in capture['bodies']]
    policy = tomllib.loads((attempt / 'policy.toml').read_text())
    java_telemetry.witness(attempt / 'sdk-runtime', attempt, entry, bodies,
        policy['resource']['service_name'], ExportTraceServiceRequest)


def qualify(profile: Path, workspace: Path, destination: Path, states: tuple[tuple[bool, bool], ...]) -> dict:
    """Copies are alteration controls, never additional JVM launches."""
    destination.mkdir(mode=0o700)
    report = read(profile / 'comparison/report.json')
    case = next(case for case in report['cases'] if case['function'] == 'Counter.identity(int)')
    original = profile / 'comparison' / case['case'] / 'instrumented_on-0'
    entry = next(entry for entry in read(workspace / 'plan.json')['inventory']
                 if entry.get('otelc_function') == case['function'])
    positive = destination / 'positive'
    shutil.copytree(original, positive)
    verify(positive, entry)
    changes = receipt_edits(states)
    health_edits = {
        'sdk-pid': lambda value: value.update(pid=value['pid'] + 1),
        'sdk-policy': lambda value: value.update(policy_sha256='0' * 64),
        'sdk-loss': lambda value: value['span_accounting'].update(queue_dropped='1'),
        'sdk-drain': lambda value: value['lifecycle'].update(shutdown='failed'),
    }
    reasons = []
    for name in (*changes, 'missing-trace', 'retained-metric', *health_edits):
        attempt = destination / ('altered-' + name)
        shutil.copytree(original, attempt)
        if name in changes:
            edit(attempt / 'java-controls.json', changes[name])
        elif name in health_edits:
            edit(attempt / 'sdk-runtime/health.json', health_edits[name])
        else:
            alter_otlp(attempt, name)
        try:
            verify(attempt, entry)
        except ValueError as error:
            if name.startswith('initial-') and 'initial metric state' not in str(error):
                raise ValueError('Initial-state control failed for an unrelated reason') from error
            if name == 'setter' and 'independent state' not in str(error):
                raise ValueError('Independent-setter control failed for an unrelated reason') from error
            reasons.append({'name': name, 'refused': True, 'reason': str(error)})
        else:
            raise ValueError('Altered Java startup evidence was accepted: ' + name)
    verify(positive, entry)
    result = {'actual_applications': 0, 'copied_attempts': 15, 'evidence_refusals': len(reasons),
        'controls': reasons}
    (destination / 'QUALIFICATION.json').write_text(json.dumps(result, indent=2) + '\n')
    return result
