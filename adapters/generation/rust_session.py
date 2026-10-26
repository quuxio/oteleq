"""Observe live Rust process ownership before releasing constructors or user calls."""

from contextlib import contextmanager
import os
import time

import native_inputs as inputs
from native_protocol import require, same
import native_session as shared
import rust_execution as execution
import rust_prepared as prepared

HOST_START, HOST_FINISH = 'oteleq-rust-start.json', 'oteleq-rust-finish.json'


class Session:
    """Use the shared executor's original deadlines and own both private process groups."""

    def __init__(self, launch: prepared.Prepared):
        require(type(launch) is prepared.Prepared, 'Rust monitor requires accepted preparation')
        launch.verify()
        require({path.name for path in launch.intent.runtime.iterdir()} == set(prepared.RECORDS),
                'Rust runtime was used before monitor attachment')
        self.launch = launch
        self.command = tuple(prepared.command(launch))
        self.started: execution.Started | None = None
        self.execution: execution.Execution | None = None
        self.child: int | None = None
        self.records: tuple[inputs.Record, ...] = ()

    def poll(self, process, deadline: float) -> None:
        """Keep the pre-exec gate closed until independent live OS observations agree."""
        require(type(process.pid) is int and same(process.args, list(self.command)),
                'Rust monitor is attached to another supervisor invocation')
        if self.started is not None:
            require(process.pid == self.started.owner.pid, 'Rust supervisor changed after release')
            return
        runtime = self.launch.intent.runtime
        require(not any((runtime / name).exists() or (runtime / name).is_symlink()
                        for name in (execution.RELEASE, execution.FINAL)),
                'Rust runtime was released before independent host binding')
        try:
            first, second = (inputs.published(runtime / name) for name in execution.START_FILES)
        except FileNotFoundError:
            return
        pid = second.value().get('pid')
        require(type(pid) is int and 1 < pid <= 0x7fffffff, 'Rust waiting child PID is unavailable')
        owner = execution.Owner(process.pid, os.getpid(), pid, self.command)
        require(same(first.value(), execution.supervisor(self.launch, owner))
                and same(second.value(), execution.application(self.launch, owner)),
                'Rust start statements differ from the accepted command or waiting image')
        supervisor, application = shared.observed_owner(process, pid, deadline,
            reason='Rust child is not the live independently observed waiting process')
        self.child = pid
        self.started = execution.bind(self.launch, owner)
        first.verify(); second.verify()
        host = shared.publish(runtime / HOST_START, {'schema_version': 1, 'kind': 'oteleq.rust.owned-start',
            'supervisor': supervisor, 'application': application,
            'records': [record.file.gate_identity() for record in self.started.records]})
        self.records = (host,)
        self.started.verify()
        require(process.poll() is None and time.monotonic() < deadline, 'Rust host release deadline expired')
        acknowledgement = shared.publish(runtime / execution.RELEASE, execution.release(self.launch, owner))
        self.records = (host, acknowledgement)

    def finish(self, process) -> None:
        """Bind the real supervisor exit to original acknowledgements and final SDK health."""
        require(self.started is not None and len(self.records) == 2
                and process.pid == self.started.owner.pid and same(process.args, list(self.command)),
                'Rust completion has no independently owned start')
        for record in self.records:
            record.verify()
        self.execution = execution.finish(self.started, process.returncode)
        host = shared.publish(self.launch.intent.runtime / HOST_FINISH,
            {'schema_version': 1, 'kind': 'oteleq.rust.owned-finish', 'supervisor_pid': process.pid,
             'application_pid': self.child, 'application_exit_code': 0,
             'sdk_pid': None if self.launch.intent.plain else self.child,
             'scope': 'owned completion; intended image and SDK drain are separate from downstream receipt'})
        self.records = (*self.records, host)

    def close(self) -> None:
        """The shared executor cleans its supervisor; retain the child's separate group."""
        shared.close_child(self.child)


@contextmanager
def retained(session: Session):
    """Preserve the original error when owned child-group cleanup also fails."""
    require(type(session) is Session, 'invalid Rust cleanup context')
    with shared.cleanup(lambda: session.close()):
        yield
