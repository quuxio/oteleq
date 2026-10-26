"""Join Rust prepared records to caller-observed process ownership and final health."""

from dataclasses import dataclass

import native_inputs as inputs
from native_protocol import digest, require, same
import rust_build_recipe
import rust_health
import rust_owned_build
import rust_prepared as prepared

START_FILES = ('rust-supervisor-start.json', 'rust-application-start.json')
RELEASE, FINAL = 'rust-host-release.json', 'rust-execution.json'


@dataclass(frozen=True)
class Owner:
    """Actual Popen/kernel identities observed while the child is held before exec."""

    pid: int
    parent_pid: int
    application_pid: int
    command: tuple[str, ...]


def owner(launch: prepared.Prepared, value: Owner) -> None:
    """Stored SDK process statements cannot supply caller-owned PID expectations."""
    require(type(launch) is prepared.Prepared and type(value) is Owner
            and all(type(pid) is int and 1 < pid <= 0x7fffffff
                    for pid in (value.pid, value.parent_pid, value.application_pid))
            and len({value.pid, value.parent_pid, value.application_pid}) == 3
            and type(value.command) is tuple and same(list(value.command), prepared.supervisor_argv(launch.intent)),
            'invalid independent Rust supervisor/application ownership')


def supervisor(launch: prepared.Prepared, value: Owner) -> dict:
    """The real supervisor has its own session/group and original launch identity."""
    return {'schema_version': 1, 'kind': 'otelc.rust.supervisor', 'pid': value.pid,
            'parent_pid': value.parent_pid, 'process_group': value.pid, 'session': value.pid,
            'launch_id': launch.value(prepared.REQUEST)['launch_id']}


def application(launch: prepared.Prepared, value: Owner) -> dict:
    """The pre-exec record identifies an intended image, not a kernel image observation."""
    return {'schema_version': 1, 'kind': 'otelc.rust.application', 'pid': value.application_pid,
        'parent_pid': value.pid, 'process_group': value.application_pid, 'session': value.application_pid,
        'supervisor_pid': value.pid, 'launch_id': launch.value(prepared.REQUEST)['launch_id'],
        'image': launch.value(prepared.PLAN)['image'], 'phase': 'waiting_exec', 'source_complete': False}


def release(launch: prepared.Prepared, value: Owner) -> dict:
    """An acknowledgement binds the exact observed waiting child and supervisor."""
    return {'schema_version': 1, 'kind': 'otelc.rust.host-release',
            'launch_id': launch.value(prepared.REQUEST)['launch_id'],
            'pid': value.application_pid, 'supervisor_pid': value.pid}


@dataclass(frozen=True)
class Started:
    """Both original start statements remain bound to actual caller observations."""

    launch: prepared.Prepared
    owner: Owner
    records: tuple[inputs.Record, ...]

    def verify(self) -> None:
        """Retain original file facts as well as exact process/session/record fields."""
        owner(self.launch, self.owner)
        self.launch.verify()
        require(type(self.records) is tuple and len(self.records) == 2
                and all(type(record) is inputs.Record for record in self.records),
                'Rust start record denominator changed')
        for record, name, expected in zip(self.records, START_FILES,
                (supervisor(self.launch, self.owner), application(self.launch, self.owner)), strict=True):
            record.verify()
            require(record.file.path == self.launch.intent.runtime / name and same(record.value(), expected),
                    'Rust start differs from actual owner or accepted prepared image')


def bind(launch: prepared.Prepared, value: Owner) -> Started:
    """The host must independently query the real kernel PIDs before calling this."""
    owner(launch, value)
    launch.verify()
    require(not any((launch.intent.runtime / name).exists() or (launch.intent.runtime / name).is_symlink()
                    for name in (RELEASE, FINAL)), 'Rust application was released before ownership binding')
    result = Started(launch, value, tuple(inputs.published(launch.intent.runtime / name) for name in START_FILES))
    result.verify()
    return result


def completed(started: Started, health: inputs.Record | None) -> dict:
    """Reconstruct the diagnostic zero-exit final record without choosing new files."""
    launch, value = started.launch, started.owner
    return {'schema_version': 1, 'kind': 'otelc.rust.execution', 'profile': rust_owned_build.PROFILE,
        'request_sha256': digest(launch.value(prepared.REQUEST)), 'plan_sha256': digest(launch.value(prepared.PLAN)),
        'supervisor': supervisor(launch, value), 'application': application(launch, value),
        'released': True, 'process_exit_code': 0, 'supervisor_exit_code': 0, 'exec_verified': False,
        'sdk_health': health.value() if health is not None else None, 'inputs_rechecked': True,
        'failures': {}, 'source_complete': False}


@dataclass(frozen=True)
class Execution:
    """Actual successful completion remains separate from downstream telemetry receipt."""

    started: Started
    final: inputs.Record
    acknowledgement: inputs.Record
    health: inputs.Record | None

    def verify(self) -> None:
        """Original facts and complete semantic expectations cannot be refreshed."""
        self.started.verify()
        launch, value = self.started.launch, self.started.owner
        for record in (self.final, self.acknowledgement, self.health):
            if record is not None:
                record.verify()
        require(self.final.file.path == launch.intent.runtime / FINAL
                and self.acknowledgement.file.path == launch.intent.runtime / RELEASE
                and same(self.acknowledgement.value(), release(launch, value)), 'Rust host release changed')
        if launch.intent.plain:
            require(self.health is None and not any((launch.intent.runtime / 'app' / name).exists()
                    or (launch.intent.runtime / 'app' / name).is_symlink()
                    for name in ('health.json', 'control.json', 'policy.json', 'plan.json')),
                    'plain Rust application contains SDK evidence')
        else:
            require(type(self.health) is inputs.Record and self.health.file.path == launch.intent.runtime / 'app/health.json',
                    'Rust instrumented execution lacks its fixed SDK checkpoint')
            inputs.directory(launch.intent.runtime / 'app')
            policy = launch.intent.policy()
            rust_health.validate(self.health.value(), pid=value.application_pid, policy=digest(policy),
                selection=digest(rust_build_recipe.selection(policy)), lifetime=launch.intent.source().intent.lifetime)
        require(same(self.final.value(), completed(self.started, self.health)),
                'Rust completion differs from actual owner, diagnostic exit or final SDK checkpoint')


def finish(started: Started, returncode: int) -> Execution:
    """A failed/unavailable supervisor exit cannot become a successful diagnostic."""
    require(type(started) is Started and type(returncode) is int and returncode == 0,
            'Rust diagnostic supervisor did not complete successfully')
    started.verify()
    runtime = started.launch.intent.runtime
    result = Execution(started, inputs.read(runtime / FINAL, private=True),
        inputs.read(runtime / RELEASE, private=True), None if started.launch.intent.plain else
        inputs.read(runtime / 'app/health.json', private=True, maximum=4096))
    result.verify()
    return result
