"""Own a generated Go ready/release boundary through the shared process runner."""

from dataclasses import dataclass
import json
import os
from pathlib import Path
import re
import stat
import subprocess
import time
import uuid

import go_execution
import go_files as files
import go_prepared as prepared
import go_rendezvous as rendezvous
from go_provider import data_seal, require, same
from otelc_capture import strict_json


def kernel(pid: int, deadline: float) -> dict:
    """Query only the candidate owned PID with a fixed system tool and no shell."""
    require(type(pid) is int and 1 < pid <= 0x7fffffff and time.monotonic() < deadline,
            "invalid Go kernel process query")
    result = subprocess.run(["/bin/ps", "-p", str(pid), "-o", "pid=,ppid=,pgid="],
                            env={"LC_ALL": "C", "PATH": "/usr/bin:/bin"},
                            capture_output=True, timeout=min(2., max(.001, deadline - time.monotonic())))
    values = result.stdout.split()
    require(result.returncode == 0 and len(result.stdout) <= 256 and not result.stderr
            and len(values) == 3 and all(re.fullmatch(rb"[1-9][0-9]{0,9}", value) for value in values)
            and all(1 < int(values[index]) <= 0x7fffffff for index in (0, 2))
            and 1 <= int(values[1]) <= 0x7fffffff, "Go kernel process identity is unavailable")
    record = dict(zip(("pid", "parent_pid", "process_group"), map(int, values)))
    require(record["pid"] == pid, "Go kernel returned another process")
    return record


def private_publish(root: Path, name: str, data: bytes) -> None:
    """Publish complete bytes without replacement; retain both links for auditing."""
    temporary = root / (name + ".tmp")
    descriptor = os.open(temporary, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
    with os.fdopen(descriptor, "wb") as output:
        output.write(data)
    os.link(temporary, root / name, follow_symlinks=False)


@dataclass(frozen=True)
class Binding:
    root: Path
    root_identity: tuple
    token: str
    wait_ms: int
    prepared_seal: str


def directory_identity(path: Path) -> tuple:
    require(path.is_absolute() and path.resolve(strict=True) == path, "Go rendezvous root must be canonical")
    info = path.lstat()
    require(stat.S_ISDIR(info.st_mode) and info.st_uid == os.getuid()
            and stat.S_IMODE(info.st_mode) == 0o700, "Go rendezvous root must be owned and mode0700")
    return info.st_dev, info.st_ino, info.st_mode, info.st_uid, info.st_gid


class Session:
    """Pause one generated worker until actual kernel/start identities agree."""

    def __init__(self, launch: prepared.Prepared, *, wait_ms: int):
        require(type(launch) is prepared.Prepared and type(wait_ms) is int and 1 <= wait_ms <= 900000,
                "invalid Go ready/release binding")
        launch.verify()
        require(not any((launch.intent.runtime / name).exists() or (launch.intent.runtime / name).is_symlink()
                        for name in prepared.EXECUTION_FILES), "Go runtime was already used before session creation")
        root = launch.intent.runtime / "oteleq-rendezvous"
        root.mkdir(mode=0o700)
        self.launch = launch
        self.binding = Binding(root, directory_identity(root), uuid.uuid4().hex, wait_ms, launch.accepted_seal)
        self.binding_seal = data_seal(self.binding_values())
        self.started = self.execution = None
        self.ready_evidence, self.kernel_observations = {}, {}
        self.start_seal = None

    def binding_values(self) -> dict:
        value = self.binding
        return {"root": str(value.root), "directory": value.root_identity, "token": value.token,
                "wait_ms": value.wait_ms, "prepared": value.prepared_seal}

    def verify_binding(self) -> None:
        require(data_seal(self.binding_values()) == self.binding_seal
                and self.binding.prepared_seal == self.launch.accepted_seal
                and directory_identity(self.binding.root) == self.binding.root_identity,
                "Go ready/release caller binding changed")

    def environment(self) -> dict[str, str]:
        self.verify_binding()
        self.launch.verify()
        return {rendezvous.ROOT_ENV: str(self.binding.root), rendezvous.TOKEN_ENV: self.binding.token,
                rendezvous.WAIT_ENV: str(self.binding.wait_ms)}

    def ready(self) -> dict | None:
        path = self.binding.root / "start.ready"
        if not path.exists() and not path.is_symlink():
            return None
        evidence, raw = {}, None
        for name in ("start.ready", "start.tmp"):
            identity, facts, data = files.file(self.binding.root / name, 1024, keep=True)
            require(stat.S_IMODE(facts[2]) == 0o600 and facts[3] == os.getuid() and facts[8] == 2,
                    "unsafe Go ready checkpoint")
            evidence[name] = identity, facts
            if raw is None:
                raw = data
        require(evidence["start.ready"][1] == evidence["start.tmp"][1], "Go ready publication has different links")
        value = strict_json(raw)
        require(type(value) is dict and set(value) == {"schema_version", "kind", "token", "pid", "parent_pid"}
                and same({key: value[key] for key in ("schema_version", "kind", "token")},
                         {"schema_version": 1, "kind": "oteleq.go.ready", "token": self.binding.token})
                and all(type(value[key]) is int and 1 < value[key] <= 0x7fffffff for key in ("pid", "parent_pid")),
                "Go ready checkpoint differs from caller binding")
        self.ready_evidence = evidence
        return value

    def start_values(self) -> dict:
        return {"start": self.started.seal, "ready": self.ready_evidence, "kernel": self.kernel_observations}

    def save(self, name: str, value: dict) -> None:
        data = (json.dumps(value, indent=2) + "\n").encode()
        require(len(data) <= 65536, "Go ownership record exceeds its byte budget")
        path = self.launch.intent.runtime / name
        descriptor = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
        with os.fdopen(descriptor, "wb") as output:
            output.write(data)

    def poll(self, process, deadline: float) -> None:
        self.verify_binding()
        require(type(process.pid) is int and same(process.args, prepared.command(self.launch.intent)),
                "Go process monitor is attached to another command")
        if self.started is not None:
            require(process.pid == self.started.owner.pid, "Go supervisor changed after release")
            return
        require(not any((self.binding.root / name).exists() or (self.binding.root / name).is_symlink()
                        for name in ("start.resume", "start.resume.tmp")), "Go worker was released before ownership binding")
        ready = self.ready()
        if ready is None or not all((self.launch.intent.runtime / name).exists() for name in go_execution.START_FILES):
            return
        owner = kernel(process.pid, deadline)
        application = kernel(ready["pid"], deadline)
        require(same(owner, {"pid": process.pid, "parent_pid": os.getpid(), "process_group": process.pid})
                and ready["parent_pid"] == process.pid
                and same(application, {"pid": ready["pid"], "parent_pid": process.pid, "process_group": process.pid})
                and process.poll() is None and time.monotonic() < deadline,
                "Go native application is not the live owned supervisor child")
        self.started = go_execution.bind(self.launch, go_execution.Owner(process.pid, os.getpid(), ready["pid"], tuple(process.args)))
        self.kernel_observations = {"supervisor": owner, "application": application}
        self.start_seal = data_seal(self.start_values())
        self.verify_start()
        self.save("oteleq-go-start.json", {"owner": vars(self.started.owner), "kernel": self.kernel_observations,
                                          "ready_files": {name: value[0] for name, value in self.ready_evidence.items()}})
        private_publish(self.binding.root, "start.resume", (self.binding.token + " release\n").encode("ascii"))

    def verify_start(self) -> None:
        require(self.started is not None and data_seal(self.start_values()) == self.start_seal,
                "Go accepted pre-call binding changed")
        self.verify_binding()
        self.started.verify()
        for name, expected in self.ready_evidence.items():
            require(same(files.file(self.binding.root / name, 1024)[:2], expected), "Go ready checkpoint changed")

    def finish(self, process) -> None:
        self.verify_start()
        require(process.pid == self.started.owner.pid and same(process.args, prepared.command(self.launch.intent)),
                "Go completion belongs to another process monitor")
        self.execution = go_execution.finish(self.started, process.returncode)
        self.save("oteleq-go-finish.json", {"owner": vars(self.started.owner), "sdk_pid": self.execution.value["sdk_pid"],
                                           "application_exit_code": 0, "scope": "owned completion; independent OTLP qualification remains separate"})
