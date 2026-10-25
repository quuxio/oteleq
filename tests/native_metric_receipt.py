"""Independently join native fixture checkpoints, frames and complete raw signals."""

import copy
from pathlib import Path
import tomllib

import native_metric_cases as cases
import native_metric_frames as frames
import native_metric_health as health
import native_metric_otlp as otlp
import native_prepared_otlp as wire
import native_prepared_receipt as retained
from native_prepared_otlp import require, same


class Checkpoints:
    """The caller's fixture determines collection, emission, calls and error totals."""

    def __init__(self, bodies: list, entry: dict, start: str, mode: str, amount: int,
                 policy: dict, pid: int, plain: bool):
        cases.validate(entry['language'], mode, start)
        self.bodies, self.entry, self.policy, self.pid, self.plain = bodies, entry, policy, pid, plain
        self.schedule = cases.schedule(start)
        self.flags = self.schedule[0]
        self.name = entry['path'] + '::' + entry['otelc_function']
        self.calls = amount + 1 if mode == 'recursive' else 1
        self.failed = mode == 'error'
        self.total = self.collected = self.errors = self.visible = self.visible_errors = self.cursor = self.statuses = 0
        self.snapshots = []

    def reply(self, value, flags: dict) -> None:
        if self.plain:
            same(value, None)
        else:
            health.status(value, self.pid, flags)

    def running(self, value, flags: dict) -> None:
        if self.plain:
            same(value, None)
        else:
            health.running(value, self.policy, self.entry['language'], self.pid, flags, self.total)
            self.snapshots.append(value)

    def transition(self, value, flags: dict) -> None:
        if self.plain:
            same(value, [])
        else:
            health.transition(value, self.pid, self.flags, flags)
            self.statuses += len(value)

    def prefix(self, end: int) -> None:
        require(type(end) is int and self.cursor <= end <= len(self.bodies), 'native fixture cursor differs')
        if not self.plain:
            otlp.metrics(self.bodies[:end], self.entry['language'], self.policy['resource']['service_name'],
                         self.name, self.visible, self.visible_errors)
        self.cursor = end

    def visible_totals(self, flags: dict) -> None:
        if all(flags.values()):
            self.visible, self.visible_errors = self.collected, self.errors

    def step(self, row: dict, index: int) -> None:
        same(sorted(row), ['after', 'before', 'id', 'requested'])
        flags = self.schedule[index]
        same(row['id'], 'step-' + str(index)); same(row['requested'], flags)
        before, after = row['before'], row['after']
        same(sorted(before), ['cursor', 'flush', 'health', 'history'])
        same(sorted(after), ['cursor', 'flush', 'health', 'held_ns', 'metric_bodies', 'settled', 'settled_flush', 'status'])
        self.transition(before['history'], flags)
        self.reply(before['flush'], flags); self.running(before['health'], flags)
        self.visible_totals(flags); self.prefix(before['cursor'])
        if flags['collection']:
            self.collected += self.calls
            self.errors += int(self.failed and index == 1)
        self.total += self.calls
        for key in ('status', 'flush', 'settled_flush'):
            self.reply(after[key], flags)
        self.running(after['health'], flags); self.running(after['settled'], flags)
        require(type(after['held_ns']) is int and after['held_ns'] >= 0, 'invalid native fixture hold time')
        require(type(after['cursor']) is int and before['cursor'] <= after['cursor'] <= len(self.bodies),
                'invalid native fixture after cursor')
        indices = [i for i in range(before['cursor'], after['cursor']) if self.bodies[i][0] == '/v1/metrics']
        same(after['metric_bodies'], indices)
        self.disabled(before, after, flags, indices)
        self.visible_totals(flags); self.prefix(after['cursor'])
        self.flags = flags
        self.statuses += 7

    def disabled(self, before: dict, after: dict, flags: dict, indices: list[int]) -> None:
        if not all(flags.values()):
            require(not indices and after['held_ns'] >= 1_000_000_000,
                    'native fixture suppressed window emitted metrics or was too short')
            if not self.plain:
                same(before['health']['metric_exports'], after['settled']['metric_exports'])

    def restore(self, row: dict) -> None:
        same(sorted(row), ['cursor', 'flush', 'health', 'history'])
        flags = {'collection': True, 'emission': True}
        self.transition(row['history'], flags)
        self.reply(row['flush'], flags); self.running(row['health'], flags)
        self.visible_totals(flags); self.prefix(row['cursor'])
        self.statuses += 2
        require(self.statuses <= 4096, 'native fixture status budget exceeded')


def controls(value: dict, bodies: list, entry: dict, start: str, mode: str, amount: int,
             policy: dict, pid: int, supervisor: int, *, plain: bool) -> Checkpoints:
    """Strict transcript fields cannot choose their own schedule or expected totals."""
    require(type(value) is dict and type(value.get('steps')) is list and len(value['steps']) == 4,
            'native fixture transcript lacks four calls')
    require(not plain or not bodies, 'plain native fixture emitted telemetry')
    same(value, {'schema_version': 1, 'kind': 'oteleq.native.live-controls', 'plain': plain,
        'pid': pid, 'supervisor_pid': supervisor, 'policy_sha256': retained.digest(policy),
        'selection_sha256': retained.digest({key: policy[key] for key in ('sources', 'functions')}),
        'interval_ms': 1000, 'steps': value['steps'], 'restored': value['restored']})
    result = Checkpoints(bodies, entry, start, mode, amount, policy, pid, plain)
    for index, row in enumerate(value['steps']):
        result.step(row, index)
    result.restore(value['restored'])
    return result


def publications(folder: Path, record: dict) -> None:
    """Each immutable host snapshot is the exact prefix preceding its acknowledgement."""
    same(sorted(path.name for path in folder.glob('native-live-*.json')),
         ['native-live-' + str(index) + '.json' for index in range(9)])
    for index in range(9):
        path = folder / ('native-live-' + str(index) + '.json')
        retained.identity(path, private=True)
        expected = copy.deepcopy(record)
        if index < 8:
            expected['restored'] = None
            expected['steps'] = expected['steps'][:index // 2 + 1]
            if index % 2 == 0:
                expected['steps'][-1]['after'] = None
        same(retained.read(path), expected)


def receipt(folder: Path, read, language: str, service: str, name: str, *, plain: bool,
            entry: dict, mode: str, start: str, amount: int, version: int = 42) -> tuple:
    """Combine original evidence and known workload arithmetic without product readers."""
    same(language, entry['language']); same(name, entry['path'] + '::' + entry['otelc_function'])
    policy = tomllib.loads((folder / 'policy.toml').read_text())
    retained.policy(policy, entry, metric_flags=cases.schedule(start)[0])
    same(service, policy['resource']['service_name'])
    bodies = wire.payloads(folder, read)
    application = read(folder / 'native-runtime/native-application-start.json')
    record_path = folder / 'native-controls.json'; retained.identity(record_path, private=True)
    record = read(record_path)
    expected = cases.expected(language, mode, amount, instrumented=not plain, version=version)
    frames.evidence(folder, entry, expected); publications(folder, record)
    checked = controls(record, bodies, entry, start, mode, amount, policy,
                       application['pid'], application['supervisor_pid'], plain=plain)
    if plain:
        require(not bodies and not (folder / 'native-verified-controls.json').exists(),
                'plain native fixture emitted SDK receipt')
        return None, 0, 0, 0
    total = otlp.traces(bodies, language, service, name, checked.calls, failed=checked.failed)
    points = otlp.metrics(bodies, language, service, name, checked.collected, checked.errors)
    final = read(folder / 'native-runtime/app/health.json')
    traces = sum(route == '/v1/traces' for route, _ in bodies)
    metrics = len(bodies) - traces
    retained.health(final, policy, language, application['pid'], points, traces, metrics, functions=total)
    health.progress([*checked.snapshots, final])
    expected = otlp.witness(bodies, name, total)
    same(read(folder / 'native-verified-controls.json'), {**expected,
        'collected_functions': {name: checked.collected}, 'collected_errors': {name: checked.errors} if checked.errors else {},
        'metric_points': points, 'health': final})
    return expected, points, traces, metrics
