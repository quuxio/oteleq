"""Bind native start and final SDK records to consumer-owned process identities."""

from dataclasses import dataclass

import native_health
import native_inputs as inputs
import native_prepared as prepared
from native_protocol import PROFILE, digest, require, same

FINAL = 'native-execution.json'
RELEASE = 'native-host-release.json'


@dataclass(frozen=True)
class Owner:
    """Actual Popen/kernel observations captured while the application cannot exec."""

    pid: int
    parent_pid: int
    application_pid: int
    command: tuple[str, ...]


def supervisor(launch: prepared.Prepared, owner: Owner) -> dict:
    """The fixed supervisor owns a session distinct from its waiting child."""
    return {'schema_version': 1, 'kind': 'otelc.native.supervisor', 'pid': owner.pid,
            'parent_pid': owner.parent_pid, 'process_group': owner.pid, 'session': owner.pid,
            'launch_id': launch.value(prepared.REQUEST)['launch_id']}


def application(launch: prepared.Prepared, owner: Owner) -> dict:
    """Child session and image are fixed by the caller's accepted lane."""
    return {'schema_version': 1, 'kind': 'otelc.native.application', 'pid': owner.application_pid,
            'parent_pid': owner.pid, 'process_group': owner.application_pid, 'session': owner.application_pid,
            'supervisor_pid': owner.pid, 'launch_id': launch.value(prepared.REQUEST)['launch_id'],
            'image': launch.value(prepared.PLAN)['image'], 'phase': 'waiting_exec', 'source_complete': False}


def release(launch: prepared.Prepared, owner: Owner) -> dict:
    """Only the host's already-bound application receives an acknowledgement."""
    return {'schema_version': 1, 'kind': 'otelc.native.host-release',
            'launch_id': launch.value(prepared.REQUEST)['launch_id'],
            'pid': owner.application_pid, 'supervisor_pid': owner.pid}


@dataclass(frozen=True)
class Started:
    """Immutable file snapshots retain the exact pre-exec ownership statements."""

    launch: prepared.Prepared
    owner: Owner
    records: tuple[inputs.Record, ...]

    def verify(self) -> None:
        """Recheck both original files and their complete caller-owned expectations."""
        self.launch.verify()
        require(len(self.records) == 2, 'native start record denominator changed')
        for record, name, expected in zip(self.records, prepared.START_FILES,
                (supervisor(self.launch, self.owner), application(self.launch, self.owner)), strict=True):
            record.verify()
            require(record.file.path == self.launch.intent.runtime / name and same(record.value(), expected),
                    'native start differs from actual owner or prepared application')


def bind(launch: prepared.Prepared, owner: Owner) -> Started:
    """Call only after the consumer has independently queried these live OS PIDs."""
    require(type(launch) is prepared.Prepared and type(owner) is Owner
            and all(type(pid) is int and 1 < pid <= 0x7fffffff
                    for pid in (owner.pid, owner.parent_pid, owner.application_pid))
            and len({owner.pid, owner.parent_pid, owner.application_pid}) == 3
            and type(owner.command) is tuple and same(list(owner.command), prepared.command(launch.intent)),
            'invalid caller-owned native process binding')
    launch.verify()
    require(not any((launch.intent.runtime / name).exists() or (launch.intent.runtime / name).is_symlink()
                    for name in (FINAL, RELEASE)), 'native application was released before ownership binding')
    result = Started(launch, owner, tuple(inputs.published(launch.intent.runtime / name) for name in prepared.START_FILES))
    result.verify()
    return result


@dataclass(frozen=True)
class Execution:
    """Owned successful completion; direct downstream telemetry is assessed separately."""

    started: Started
    final: inputs.Record
    acknowledgement: inputs.Record
    health: inputs.Record | None

    def verify(self) -> None:
        """Previously accepted execution evidence cannot be repaired or replaced."""
        self.started.verify()
        for record in (self.final, self.acknowledgement, self.health):
            if record is not None:
                record.verify()


def finish(started: Started, returncode: int) -> Execution:
    """Only a fully observed zero-exit diagnostic can become a successful attempt."""
    require(type(started) is Started and type(returncode) is int and returncode == 0,
            'native diagnostic supervisor did not complete successfully')
    started.verify()
    launch, owner = started.launch, started.owner
    runtime = launch.intent.runtime
    acknowledgement = inputs.read(runtime / RELEASE, private=True)
    require(same(acknowledgement.value(), release(launch, owner)), 'native host acknowledgement changed')
    health = None
    if launch.intent.plain:
        require(not any((runtime / 'app' / name).exists() or (runtime / 'app' / name).is_symlink()
                        for name in ('health.json', 'control.json', 'policy.json', 'plan.json')),
                'plain native application has SDK evidence')
    else:
        inputs.directory(runtime / 'app')
        health = inputs.read(runtime / 'app/health.json', private=True, maximum=4096)
        native_health.validate(health.value(), language=launch.intent.context().language,
            pid=owner.application_pid, policy=digest(launch.intent.policy()),
            selection=digest(launch.intent.selection()), lifetime_kind=launch.intent.lifetime_kind())
    final = inputs.read(runtime / FINAL, private=True)
    expected = {'schema_version': 1, 'kind': 'otelc.native.execution', 'profile': PROFILE,
                'request_sha256': digest(launch.value(prepared.REQUEST)),
                'plan_sha256': digest(launch.value(prepared.PLAN)),
                'supervisor': supervisor(launch, owner), 'application': application(launch, owner),
                'released': True, 'process_exit_code': 0, 'supervisor_exit_code': 0,
                'exec_verified': False, 'sdk_health': health.value() if health else None,
                'inputs_rechecked': True, 'failures': {}, 'source_complete': False}
    require(same(final.value(), expected), 'native completion differs from actual owner, exit or SDK health')
    result = Execution(started, final, acknowledgement, health)
    result.verify()
    return result
