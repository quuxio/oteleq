"""Hold native execution until actual OS ownership and fixed records agree."""

from contextlib import contextmanager
import os
from pathlib import Path
import re
import signal
import subprocess
import time

import native_execution as execution
import native_inputs as inputs
import native_prepared as prepared
from native_protocol import encoded, require, same

HOST_START = 'oteleq-native-start.json'
HOST_FINISH = 'oteleq-native-finish.json'


def kernel(pid: int, deadline: float) -> dict:
    """Query one candidate PID with a fixed command and the original deadline."""
    require(type(pid) is int and 1 < pid <= 0x7fffffff and time.monotonic() < deadline,
            'invalid native kernel query')
    result = subprocess.run(['/bin/ps', '-p', str(pid), '-o', 'pid=,ppid=,pgid='],
        env={'LC_ALL': 'C', 'PATH': '/usr/bin:/bin'}, capture_output=True,
        timeout=min(2., max(.001, deadline - time.monotonic())))
    words = result.stdout.split()
    require(result.returncode == 0 and len(result.stdout) <= 256 and not result.stderr
            and len(words) == 3 and all(re.fullmatch(rb'[1-9][0-9]{0,9}', word) for word in words)
            and all(1 < int(word) <= 0x7fffffff for word in words), 'native OS process identity is unavailable')
    value = dict(zip(('pid', 'parent_pid', 'process_group'), map(int, words)))
    require(value['pid'] == pid and os.getpgid(pid) == value['process_group'],
            'native kernel process identity changed')
    return {**value, 'session': os.getsid(pid)}


def publish(path: Path, value: dict) -> inputs.Record:
    """Publish a complete private file, remove its staging link, then freeze facts."""
    staged = path.with_name(path.name + '.staging')
    descriptor = os.open(staged, os.O_WRONLY | os.O_CREAT | os.O_EXCL | os.O_NOFOLLOW, 0o600)
    info = os.fstat(descriptor)
    try:
        with os.fdopen(descriptor, 'wb', closefd=False) as output:
            output.write((encoded(value) + '\n').encode())
            output.flush()
        os.link(staged, path, follow_symlinks=False)
    finally:
        os.close(descriptor)
        current = staged.lstat()
        require((current.st_dev, current.st_ino) == (info.st_dev, info.st_ino), 'native publication staging file changed')
        staged.unlink()
    return inputs.read(path, private=True)


class Session:
    """Use the shared executor's budgets; keep the child's separate group owned."""

    def __init__(self, launch: prepared.Prepared):
        require(type(launch) is prepared.Prepared, 'native session requires accepted preparation')
        launch.verify()
        require({path.name for path in launch.intent.runtime.iterdir()} ==
                {prepared.REQUEST, prepared.PLAN, prepared.PREPARED}, 'native runtime was already used')
        self.launch = launch
        self.started = self.execution = None
        self.child = None
        self.records: tuple[inputs.Record, ...] = ()

    def poll(self, process, deadline: float) -> None:
        """Keep constructors blocked until the actual parent, group and session agree."""
        require(type(process.pid) is int and same(process.args, prepared.command(self.launch.intent)),
                'native monitor is attached to a different supervisor command')
        if self.started is not None:
            require(process.pid == self.started.owner.pid, 'native supervisor changed after release')
            return
        runtime = self.launch.intent.runtime
        require(not any((runtime / name).exists() or (runtime / name).is_symlink()
                        for name in (execution.RELEASE, execution.FINAL)), 'native runtime released before host binding')
        try:
            first, second = (inputs.published(runtime / name) for name in prepared.START_FILES)
        except FileNotFoundError:
            return
        pid = second.value().get('pid')
        owner = execution.Owner(process.pid, os.getpid(), pid, tuple(process.args))
        require(type(pid) is int and 1 < pid <= 0x7fffffff
                and same(first.value(), execution.supervisor(self.launch, owner))
                and same(second.value(), execution.application(self.launch, owner)),
                'native start records differ from the fixed supervisor and application')
        supervisor = kernel(process.pid, deadline)
        application = kernel(pid, deadline)
        require(same(supervisor, {'pid': process.pid, 'parent_pid': os.getpid(),
                    'process_group': process.pid, 'session': process.pid})
                and same(application, {'pid': pid, 'parent_pid': process.pid,
                    'process_group': pid, 'session': pid})
                and process.poll() is None and time.monotonic() < deadline,
                'native application is not the live owned waiting child')
        self.child = pid
        self.started = execution.bind(self.launch, owner)
        first.verify(); second.verify()
        host = publish(runtime / HOST_START, {'schema_version': 1, 'kind': 'oteleq.native.owned-start',
            'supervisor': supervisor, 'application': application,
            'records': [record.file.gate_identity() for record in self.started.records]})
        self.records = (host,)
        self.started.verify()
        require(process.poll() is None and time.monotonic() < deadline, 'native host release deadline expired')
        acknowledgement = publish(runtime / execution.RELEASE, execution.release(self.launch, owner))
        self.records = (host, acknowledgement)

    def finish(self, process) -> None:
        """Retain success only after exact completion and final SDK health checks."""
        require(self.started is not None and len(self.records) == 2
                and process.pid == self.started.owner.pid
                and same(process.args, prepared.command(self.launch.intent)), 'native completion has no owned start')
        for record in self.records:
            record.verify()
        self.execution = execution.finish(self.started, process.returncode)
        final = publish(self.launch.intent.runtime / HOST_FINISH,
            {'schema_version': 1, 'kind': 'oteleq.native.owned-finish', 'supervisor_pid': process.pid,
             'application_pid': self.child, 'application_exit_code': 0,
             'sdk_pid': None if self.launch.intent.plain else self.child,
             'scope': 'owned completion; direct downstream telemetry qualification remains separate'})
        self.records = (*self.records, final)

    def close(self) -> None:
        """The SDK child has a separate session from the executor's supervisor group."""
        if self.child is not None:
            try:
                os.killpg(self.child, signal.SIGKILL)
            except ProcessLookupError:
                pass
            except PermissionError:
                # Match the shared executor's conservative macOS zombie-group
                # handling; a denied signal alone never proves cleanup.
                from generation import live_process_group
                require(not live_process_group(self.child), 'native child process group cleanup was denied')


@contextmanager
def retained(session: Session):
    """Clean both owned groups, preserving the primary error if cleanup also fails."""
    require(type(session) is Session, 'invalid native execution cleanup context')
    try:
        yield
    except BaseException as error:
        try:
            session.close()
        except Exception as cleanup:
            error.add_note('native child cleanup also failed: ' + str(cleanup))
        raise
    else:
        session.close()
