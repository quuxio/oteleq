"""Join native live calls to complete raw signals and independent owned health."""

from collections import Counter
import hashlib
import json
from pathlib import Path

import native_control
import native_live
import native_sequence
import native_telemetry as telemetry
from native_protocol import fields, require, same


def checked_status(value: dict, pid: int, flags: dict) -> None:
    """Replies must describe the independently requested state of the same PID."""
    native_control.status(value, pid)
    require(all(value[key] is flag for key, flag in flags.items())
            and (all(flags.values()) or value['effective_emission_off']),
            'native live reply disagrees with the requested effective state')


def transition(rows: list, pid: int, flags: dict, previous: dict) -> None:
    """Require one initial query, only necessary independent setters, then draining."""
    require(type(rows) is list and 1 <= len(rows) <= 128, 'missing native transition replies')
    current = dict(previous)
    expected = ['status'] + [key + (' on' if flags[key] else ' off')
                              for key in ('collection', 'emission') if current[key] is not flags[key]]
    require(len(rows) >= len(expected), 'native metric setter reply is missing')
    for index, row in enumerate(rows):
        fields(row, {'command', 'status'}, 'native transition')
        command = expected[index] if index < len(expected) else 'status'
        require(row['command'] == command, 'native metric command order differs')
        if command != 'status':
            key = command.split()[0]
            current[key] = flags[key]
        value = native_control.status(row['status'], pid)
        require(all(value[key] is flag for key, flag in current.items()),
                'native metric setter changed another flag or call state')
    checked_status(rows[-1]['status'], pid, flags)


def call_trees(spans: dict, steps: list[dict]) -> list[list]:
    """Join root errors to actual typed outcomes; retain each recursive subtree."""
    ordered = sorted((key for key, value in spans.items() if not value.parent_span_id),
                     key=lambda key: spans[key].start_time_unix_nano)
    require(len(ordered) == len(steps), 'native call roots differ from observed frames')
    groups = [[] for _ in ordered]
    positions = {key: index for index, key in enumerate(ordered)}
    for key, span in spans.items():
        root, trail = key, []
        while root not in positions:
            trail.append(root)
            root = (spans[root].trace_id, spans[root].parent_span_id)
        position = positions[root]
        for ancestor in trail:
            positions[ancestor] = position
        groups[position].append(span)
    for key, step in zip(ordered, steps, strict=True):
        require((spans[key].status.code == 2) is (step['outcome']['kind'] == 'error'),
                'native function root error differs from its actual scalar outcome')
    return groups


def witness(completed, session: native_live.Session, bodies: list, service: str,
            roots: tuple[str, ...], folder: Path):
    """Every prefix, off window, retained measurement and final SDK unit must agree."""
    require(type(session) is native_live.Session and completed.started is session.started,
            'native live receipt has no matching owned session')
    completed.verify(); session.verify()
    require(session.final is not None and session.observation is not None
            and same(session.record, session.final.value()), 'native control transcript changed')
    session.checkpoints.finish()
    policy = completed.started.launch.intent.policy()
    require(service == policy['resource']['service_name'] and type(bodies) is list
            and len(bodies) <= native_live.MAX_TELEMETRY_REQUESTS
            and all(type(row) is tuple and len(row) == 2 and row[0] in ('/v1/traces', '/v1/metrics')
                    and type(row[1]) is bytes and bool(row[1]) for row in bodies)
            and sum(len(raw) for _, raw in bodies) <= telemetry.MAX_BYTES,
            'native live service or telemetry capture budget differs')
    if completed.started.launch.intent.plain:
        require(not bodies and completed.health is None and session.client is None,
                'plain native schedule emitted SDK evidence')
        return None
    require(policy['traces']['enabled'] is True
            and type(policy['traces']['sample_ratio']) in (int, float)
            and policy['traces']['sample_ratio'] == 1., 'native live traces require complete sampling')
    language = completed.started.launch.intent.context().language
    graph, _ = telemetry.function_graph(telemetry.trace_values(bodies, language, service), roots)
    from otelc_capture import strict_json
    observations = native_sequence.decode(session.observation.content, strict_json(session.entry_json))
    groups = call_trees(graph, observations['steps'])
    calls, errors, visible_calls, visible_errors = Counter(), Counter(), Counter(), Counter()
    total, cursor, statuses = 0, 0, 0
    snapshots = []
    flags = {key: policy['metrics'][key] for key in ('collection', 'emission')}
    require(len(session.record['steps']) == len(groups) == len(session.sequence()),
            'native live transcript call denominator differs')

    def health(value, requested, count):
        native_control.running_health(value, pid=session.record['pid'], language=language,
            policy=session.record['policy_sha256'], selection=session.record['selection_sha256'])
        checked_status(value['controls'], session.record['pid'], requested)
        require(value['function_accounting']['started'] == str(count),
                'native checkpoint function count differs from its actual call tree')
        snapshots.append(value)

    def prefix(end):
        nonlocal cursor
        require(type(end) is int and cursor <= end <= len(bodies), 'native receipt cursor differs')
        telemetry.metrics(bodies[:end], language, service, dict(visible_calls), visible_errors,
                          policy['metrics']['histogram_boundaries_seconds'], bool(visible_calls))
        cursor = end

    for index, (step, wanted, group) in enumerate(zip(session.record['steps'], session.sequence(), groups, strict=True)):
        fields(step, {'id', 'requested', 'before', 'after'}, 'native live step')
        require(step['id'] == wanted['id'] and same(step['requested'], wanted['metrics']),
                'native live transcript changed its caller-owned schedule')
        requested, before, after = wanted['metrics'], step['before'], step['after']
        fields(before, {'history', 'flush', 'health', 'cursor'}, 'native live before')
        fields(after, {'status', 'flush', 'health', 'settled_flush', 'settled', 'cursor',
                       'metric_bodies', 'held_ns'}, 'native live after')
        transition(before['history'], session.record['pid'], requested, flags)
        statuses += len(before['history']) + 7
        checked_status(before['flush'], session.record['pid'], requested)
        health(before['health'], requested, total)
        if all(requested.values()):
            visible_calls, visible_errors = calls.copy(), errors.copy()
        prefix(before['cursor'])
        if requested['collection']:
            calls.update(span.name for span in group)
            errors.update(span.name for span in group if span.status.code == 2)
        total += len(group)
        for name in ('status', 'flush', 'settled_flush'):
            checked_status(after[name], session.record['pid'], requested)
        health(after['health'], requested, total)
        health(after['settled'], requested, total)
        require(type(after['held_ns']) is int and after['held_ns'] >= 0,
                'native off-state duration is invalid')
        require(type(after['cursor']) is int and before['cursor'] <= after['cursor'] <= len(bodies),
                'native after cursor differs')
        indices = [i for i in range(before['cursor'], after['cursor']) if bodies[i][0] == '/v1/metrics']
        require(same(after['metric_bodies'], indices), 'native metric window evidence differs')
        if all(requested.values()):
            visible_calls, visible_errors = calls.copy(), errors.copy()
        else:
            require(not indices and after['held_ns'] >= native_live.INTERVAL_MS * 1_000_000
                    and before['health']['metric_exports'] == after['settled']['metric_exports'],
                    'native disabled window emitted metrics, changed exports or was too short')
        prefix(after['cursor'])
        flags = requested
    restored = fields(session.record['restored'], {'history', 'flush', 'health', 'cursor'}, 'native restored state')
    flags_on = {'collection': True, 'emission': True}
    transition(restored['history'], session.record['pid'], flags_on, flags)
    checked_status(restored['flush'], session.record['pid'], flags_on)
    health(restored['health'], flags_on, total)
    visible_calls, visible_errors = calls, errors
    prefix(restored['cursor'])
    statuses += len(restored['history']) + 2
    require(statuses == session.statuses <= native_live.MAX_STATUSES, 'native response denominator differs')
    final = completed.health.value()
    checked_status(final['controls'], session.record['pid'], flags_on)
    for previous, current in zip(snapshots, snapshots[1:] + [final], strict=True):
        for section in ('trace_exports', 'metric_exports'):
            for key in ('batches_started', 'batches_succeeded', 'units_started', 'units_succeeded'):
                require(int(current[section][key]) >= int(previous[section][key]),
                        'native exporter counters moved backwards')
    points = telemetry.metrics(bodies, language, service, dict(calls), errors,
                                policy['metrics']['histogram_boundaries_seconds'], True)
    names = dict(Counter(span.name for span in graph.values()))
    require(final['function_accounting']['registered'] == str(len(names))
            and final['function_accounting']['started'] == str(total)
            and final['trace_exports']['units_succeeded'] == str(total)
            and final['metric_exports']['units_succeeded'] == str(points),
            'native final SDK units differ from complete direct receipt')
    raw = hashlib.sha256()
    for route, body in bodies:
        raw.update(len(route).to_bytes(8, 'big') + route.encode() + len(body).to_bytes(8, 'big') + body)
    result = {'decoder': 'native owned live controls, scalar frames and complete raw OTLP',
        'raw_otlp_sha256': raw.hexdigest(), 'functions': names, 'spans': total,
        'losses': {'function_lost': 0, 'metadata_errors': 0, 'queue_dropped': 0, 'diagnostic_dropped': 0},
        'pending': 0, 'collected_functions': dict(calls), 'collected_errors': dict(errors),
        'metric_points': points, 'health': final}
    session.verify(); completed.verify()
    (folder / 'native-verified-controls.json').write_text(json.dumps(result, indent=2, allow_nan=False) + '\n')
    return {name: result[name] for name in telemetry.WITNESS_FIELDS}
