"""Private call checkpoints keep live metric controls outside application code."""
import json
import os
from pathlib import Path
import stat
import time
import uuid

import java_control as control

ROOT_ENV = "OTELEQ_JAVA_CONTROL_ROOT"
TOKEN_ENV = "OTELEQ_JAVA_CONTROL_TOKEN"
RECORD = "java-controls.json"
INTERVAL_MS = 1000
MAX_STATUSES = 512
MAX_RECORD_BYTES = 262144

HELPER = r'''
static void checkpoint(java.lang.String phase) throws java.lang.Exception {
java.nio.file.Path root=java.nio.file.Path.of(java.lang.System.getenv("OTELEQ_JAVA_CONTROL_ROOT"));
java.lang.String message=java.lang.System.getenv("OTELEQ_JAVA_CONTROL_TOKEN")+" "+phase+"\n";
java.nio.file.Path temporary=root.resolve(phase+".tmp"),ready=root.resolve(phase+".ready"),resume=root.resolve(phase+".resume");
java.nio.file.Files.createFile(temporary,java.nio.file.attribute.PosixFilePermissions.asFileAttribute(java.nio.file.attribute.PosixFilePermissions.fromString("rw-------")));
java.nio.file.Files.writeString(temporary,message);
java.nio.file.Files.move(temporary,ready,java.nio.file.StandardCopyOption.ATOMIC_MOVE);
while(!java.nio.file.Files.exists(resume,java.nio.file.LinkOption.NOFOLLOW_LINKS))java.lang.Thread.sleep(1);
if(!java.nio.file.Files.isRegularFile(resume,java.nio.file.LinkOption.NOFOLLOW_LINKS) || !java.nio.file.Files.readString(resume).equals(message))throw new java.lang.AssertionError("invalid host control acknowledgement");
}
'''


def metric_bodies(bodies: list, start: int, end: int) -> list[int]:
    """Keep raw receiver positions; trace exports are independent of metric gates."""
    return [index for index in range(start, end) if bodies[index][0] == "/v1/metrics"]


def read_owned(path: Path, maximum: int) -> bytes:
    """Read only owned bounded regular metadata without waiting on a FIFO."""
    descriptor = os.open(path, os.O_RDONLY | os.O_NOFOLLOW | os.O_NONBLOCK)
    try:
        before = os.fstat(descriptor)
        control.require(stat.S_ISREG(before.st_mode) and before.st_uid == os.getuid()
                        and stat.S_IMODE(before.st_mode) == 0o600 and before.st_size <= maximum,
                        "unsafe checkpoint/control file")
        data = os.read(descriptor, maximum + 1)
        after = os.fstat(descriptor)
        identity = lambda info: (info.st_dev, info.st_ino, info.st_size, info.st_mtime_ns, info.st_ctime_ns, info.st_mode, info.st_uid)
        control.require(len(data) == before.st_size and identity(after) == identity(before), "checkpoint/control file changed")
        return data
    finally:
        os.close(descriptor)


def marker(path: Path, expected: bytes) -> None:
    control.require(read_owned(path, len(expected)) == expected, "checkpoint has the wrong identity")


class Session:
    """Advance one JVM through its fixed calls without blocking output monitoring."""

    def __init__(self, folder: Path, runtime: Path, sequence: list[dict], bodies: list, *, plain: bool):
        self.folder, self.runtime, self.sequence, self.bodies, self.plain = folder, runtime, sequence, bodies, plain
        self.root = folder / "java-rendezvous"
        self.root.mkdir(mode=0o700)
        self.token = uuid.uuid4().hex
        self.phases = [phase + "-" + str(index) for index in range(len(sequence)) for phase in ("before", "after")] + ["finish"]
        self.position, self.pid, self.statuses = 0, None, 0
        self.holding = None
        self.record = {"control_schema_version": 1, "plain": plain, "pid": None,
                       "interval_ms": INTERVAL_MS, "steps": [], "restored": None}

    def environment(self) -> dict:
        """Only generated checkpoints consume these private observer bindings."""
        return {ROOT_ENV: str(self.root), TOKEN_ENV: self.token}

    def save(self) -> None:
        raw = json.dumps(self.record, indent=2) + "\n"
        control.require(len(raw.encode()) <= MAX_RECORD_BYTES, "control metadata exceeds its byte budget")
        temporary = self.folder / (RECORD + ".tmp")
        descriptor = os.open(temporary, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
        with os.fdopen(descriptor, "w") as stream:
            stream.write(raw)
        temporary.replace(self.folder / RECORD)

    def retain(self, value: list[dict]) -> list[dict]:
        self.statuses += len(value)
        control.require(self.statuses <= MAX_STATUSES, "total status record budget exceeded")
        return value

    def query(self, command: str, deadline: float) -> dict | None:
        if self.plain:
            return None
        value = control.request(self.runtime / "control.sock", command, self.pid, deadline)
        self.retain([{"command": command, "status": value}])
        return value

    def transition(self, requested: dict, deadline: float) -> list[dict]:
        if self.plain:
            return []
        result = control.switch(self.runtime / "control.sock", self.pid, **requested, deadline=deadline)
        return self.retain(result)

    def acknowledge(self) -> None:
        phase = self.phases[self.position]
        temporary = self.root / (phase + ".acktmp")
        descriptor = os.open(temporary, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
        with os.fdopen(descriptor, "wb") as stream:
            stream.write((self.token + " " + phase + "\n").encode())
        temporary.replace(self.root / (phase + ".resume"))
        self.position += 1

    def before(self, index: int, deadline: float) -> None:
        requested = self.sequence[index]["metrics"]
        history = self.transition(requested, deadline)
        if history:
            previous = self.record["steps"][-1]["after"]["settled"] if index else {"completed": 0}
            control.require(history[0]["status"]["completed"] == previous["completed"],
                            "selected calls ran outside declared checkpoints")
        self.record["steps"].append({"id": self.sequence[index]["id"], "requested": requested.copy(),
                                     "before": {"history": history, "cursor": len(self.bodies)}, "after": None})
        self.save()
        self.acknowledge()

    def after(self, index: int, deadline: float) -> None:
        step = self.record["steps"][index]
        current, flushed = self.query("status", deadline), self.query("flush", deadline)
        if current is not None:
            before = step["before"]["history"][-1]["status"]
            delta = current["completed"] - before["completed"]
            control.require((delta > 0 if step["requested"]["collection"] else delta == 0)
                            and flushed["completed"] == current["completed"]
                            and all(current[key] == flushed[key] == value for key, value in step["requested"].items()),
                            "collection accounting or control state differs during a call")
        self.holding = {"index": index, "started_ns": time.monotonic_ns(), "status": current, "flush": flushed}
        self.holding["until"] = time.monotonic() + (0 if step["requested"]["emission"] else INTERVAL_MS / 1000)
        self.save()

    def settle(self, deadline: float) -> None:
        pending = self.holding
        step = self.record["steps"][pending["index"]]
        settled = self.query("flush", deadline)
        if settled is not None:
            control.require(settled["completed"] == pending["status"]["completed"]
                            and all(settled[key] == value for key, value in step["requested"].items()),
                            "selected calls or controls changed at a paused checkpoint")
        end = len(self.bodies)
        received = metric_bodies(self.bodies, step["before"]["cursor"], end)
        control.require(step["requested"]["emission"] or not received, "metrics were received after the effective emission-off barrier")
        step["after"] = {"status": pending["status"], "flush": pending["flush"], "settled": settled,
                         "cursor": end, "metric_bodies": received, "held_ns": time.monotonic_ns() - pending["started_ns"]}
        self.holding = None
        self.save()
        self.acknowledge()

    def restore(self, deadline: float) -> None:
        history = self.transition({"collection": True, "emission": True}, deadline)
        flushed = self.query("flush", deadline)
        if flushed is not None:
            control.require(flushed["completed"] == self.record["steps"][-1]["after"]["settled"]["completed"]
                            and flushed["collection"] and flushed["emission"], "final restoration changed selected measurements")
        self.record["restored"] = {"history": history, "flush": flushed, "cursor": len(self.bodies)}
        self.save()
        self.acknowledge()

    def poll(self, process, deadline: float) -> None:
        """The execution loop keeps enforcing the common process/output budgets."""
        if self.pid is None:
            self.pid = process.pid
            self.record["pid"] = self.pid
        control.require(process.pid == self.pid, "application process changed")
        if self.holding is not None:
            if time.monotonic() >= self.holding["until"]:
                self.settle(deadline)
            return
        if self.position == len(self.phases):
            return
        phase = self.phases[self.position]
        path = self.root / (phase + ".ready")
        if not path.exists() and not path.is_symlink():
            return
        marker(path, (self.token + " " + phase + "\n").encode())
        if self.position == 0 and not self.plain:
            socket = self.runtime / "control.sock"
            if not socket.exists() and not socket.is_symlink():
                return  # The SDK's control thread may finish binding after main starts.
        if phase == "finish":
            self.restore(deadline)
        elif phase.startswith("before-"):
            self.before(self.position // 2, deadline)
        else:
            self.after(self.position // 2, deadline)

    def finish(self, process) -> None:
        """A terminated JVM cannot turn missing checkpoints into a passing skip."""
        control.require(process.pid == self.pid and self.position == len(self.phases)
                        and self.holding is None and self.record["restored"] is not None,
                        "application exited before completing its control schedule")
        expected = {phase + suffix for phase in self.phases for suffix in (".ready", ".resume")}
        control.require({path.name for path in self.root.iterdir()} == expected, "unexpected checkpoint files")
