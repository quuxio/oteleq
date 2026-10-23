"""Private ordinary-JDK action rendezvous, independent of application channels."""

import os
from pathlib import Path
import socket
import stat
import time
import uuid

import java_witness as witness

HELPER = Path(__file__).with_name("OteleqRendezvous.java")
MAX_READY = 512


class Harness:
    """Bind each serial readiness and release to its actual JVM and Java thread.

    The caller owns application execution/deadlines and SDK control. A ready
    record alone does not admit telemetry or release an instrumented action.
    """

    def __init__(self, root: Path, case_id: str, attempt_id: str, actions: list[str]):
        witness.require(witness.hex_id(case_id, 64) and witness.hex_id(attempt_id, 64)
                        and type(actions) is list and 0 < len(actions) <= 65
                        and all(witness.hex_id(action, 64) for action in actions)
                        and len(set(actions)) == len(actions), "invalid private harness plan")
        witness.require(root.is_absolute() and root.parent == root.parent.resolve(strict=True),
                        "harness parent must be canonical")
        self.root, self.case_id, self.attempt_id = root, case_id, attempt_id
        self.actions, self.token = tuple(actions), uuid.uuid4().hex
        self.pid, self.position = None, 0
        self.connection, self.current = None, None
        self.buffer, self.records = bytearray(), []
        self.path = root / "harness.sock"
        witness.require(len(os.fsencode(self.path)) <= 103, "private harness socket path exceeds POSIX limit")
        root.mkdir(mode=0o700)
        self.server = socket.socket(socket.AF_UNIX)
        try:
            self.server.bind(str(self.path))
            self.path.chmod(0o600)
            self.server.listen(1)
            self.server.setblocking(False)
        except BaseException:
            self.server.close()
            raise
        info = self.path.lstat()
        self.socket_identity = info.st_dev, info.st_ino

    def environment(self) -> dict:
        """Only the frozen JDK helper consumes these harness-owned settings."""
        return {"OTELEQ_ACTION_SOCKET": str(self.path), "OTELEQ_ACTION_TOKEN": self.token,
                "OTELEQ_ACTION_CASE": self.case_id, "OTELEQ_ACTION_ATTEMPT": self.attempt_id,
                "OTELEQ_ACTION_IDS": ",".join(self.actions)}

    def _check_endpoint(self) -> None:
        root, info = self.root.lstat(), self.path.lstat()
        witness.require(stat.S_ISDIR(root.st_mode) and root.st_uid == os.getuid()
                        and stat.S_IMODE(root.st_mode) == 0o700
                        and stat.S_ISSOCK(info.st_mode) and info.st_uid == os.getuid()
                        and stat.S_IMODE(info.st_mode) == 0o600
                        and (info.st_dev, info.st_ino) == self.socket_identity,
                        "private harness endpoint changed")

    def poll(self, process, deadline: float) -> dict | None:
        """Read without blocking the executor's output and resource supervision."""
        witness.require(time.monotonic() < deadline, "harness deadline exceeded")
        if self.pid is None:
            witness.require(type(process.pid) is int and process.pid > 0, "missing actual JVM PID")
            self.pid = process.pid
        witness.require(process.pid == self.pid, "harness application process changed")
        self._check_endpoint()
        if self.current is not None:
            return self.current.copy()
        if self.connection is None:
            try:
                self.connection, _ = self.server.accept()
            except BlockingIOError:
                return None
            self.connection.setblocking(False)
        try:
            part = self.connection.recv(MAX_READY + 1 - len(self.buffer))
        except BlockingIOError:
            return None
        witness.require(bool(part) and len(self.buffer) + len(part) <= MAX_READY,
                        "incomplete or oversized harness readiness")
        self.buffer.extend(part)
        if not self.buffer.endswith(b"\n"):
            return None
        witness.require(self.buffer.count(b"\n") == 1 and self.position < len(self.actions),
                        "extra harness frame or action")
        try:
            words = self.buffer.decode("ascii").removesuffix("\n").split(" ")
        except UnicodeError as error:
            raise ValueError("Java action witness: invalid harness encoding") from error
        expected = ["2", "ready", self.token, self.case_id, self.attempt_id, self.actions[self.position]]
        witness.require(len(words) == 8 and words[:6] == expected,
                        "harness readiness identity or action order differs")
        actual_pid = witness.counter(words[6], positive=True)
        witness.counter(words[7], positive=True)
        witness.require(actual_pid == self.pid, "harness readiness is from another JVM")
        self.current = {"case_id": self.case_id, "attempt_id": self.attempt_id,
                        "action_id": self.actions[self.position], "pid": self.pid,
                        "thread_id": words[7], "ready": bytes(self.buffer).decode("ascii")}
        return self.current.copy()

    def release(self, deadline: float) -> dict:
        """Release only the connection which supplied the validated readiness."""
        witness.require(self.current is not None and self.connection is not None,
                        "release has no validated harness readiness")
        self._check_endpoint()
        remaining = min(1., deadline - time.monotonic())
        witness.require(remaining > 0, "harness release deadline exceeded")
        raw = self.current["ready"].replace("2 ready ", "2 release ", 1).encode("ascii")
        self.connection.settimeout(remaining)
        self.connection.sendall(raw)
        record = {**self.current, "release": raw.decode("ascii")}
        self.records.append(record)
        self.connection.close()
        self.connection, self.current = None, None
        self.buffer.clear()
        self.position += 1
        return record.copy()

    def finish(self, process) -> None:
        """A missing or unreleased action cannot become a successful skip."""
        witness.require(process.pid == self.pid and self.position == len(self.actions)
                        and self.current is None and self.connection is None,
                        "JVM exited before completing its harness actions")
        self._check_endpoint()

    def close(self) -> None:
        """Close owned sockets; retained evidence and workspace cleanup stay separate."""
        if self.connection is not None:
            self.connection.close()
            self.connection = None
        self.server.close()
