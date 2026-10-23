"""Host-owned live metric rendezvous around unchanged Node receiver calls."""

import json
import os
from pathlib import Path
import time
import uuid

from java_live import marker, metric_bodies, read_owned
import node_control as control
import node_source as provider
from otelc_capture import strict_json

RECORD = "node-controls.json"
INTERVAL_MS = 1000
MAX_RECORD_BYTES = 1024 * 1024


class Session:
    """Keep the supervisor, application and independent SDK identities distinct."""

    def __init__(self, folder: Path, sequence: list[dict], bodies: list, *, language: str, plain: bool):
        self.folder, self.sequence, self.bodies, self.plain = folder, sequence, bodies, plain
        self.root, self.runtime = folder / "node-rendezvous", folder / "node-runtime"
        self.root.mkdir(mode=0o700)
        self.token = uuid.uuid4().hex
        self.phases = [phase + "-" + str(index) for index in range(len(sequence)) for phase in ("before", "after")] + ["finish"]
        self.position, self.statuses = 0, 0
        self.supervisor = self.pid = self.sdk_pid = self.launch_id = None
        self.holding = None
        self.record = {"control_schema_version": 1, "plain": plain, "language": language, "supervisor_pid": None, "pid": None,
                       "sdk_pid": None, "launch_id": None, "interval_ms": INTERVAL_MS, "steps": [], "restored": None}

    def environment(self) -> dict:
        """Only the generated caller reads the private checkpoint bindings."""
        return {"OTELEQ_NODE_CONTROL_ROOT": str(self.root), "OTELEQ_NODE_CONTROL_TOKEN": self.token}

    def save(self) -> None:
        raw = json.dumps(self.record, indent=2) + "\n"
        provider.require(len(raw.encode()) <= MAX_RECORD_BYTES, "live Node record byte budget exceeded")
        temporary = self.folder / (RECORD + ".tmp")
        descriptor = os.open(temporary, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
        with os.fdopen(descriptor, "w") as stream:
            stream.write(raw)
        temporary.replace(self.folder / RECORD)

    def retain(self, rows: list[dict]) -> list[dict]:
        self.statuses += len(rows)
        provider.require(self.statuses <= control.MAX_STATUSES, "live Node status budget exceeded")
        for row in rows:
            value = row["status"]
            if self.sdk_pid is None:
                self.sdk_pid, self.launch_id = value["sdk_pid"], value["launch_id"]
                self.record.update(sdk_pid=self.sdk_pid, launch_id=self.launch_id)
            provider.require(value["sdk_pid"] == self.sdk_pid and value["launch_id"] == self.launch_id
                             and value["language"] == self.record["language"]
                             and os.getpgid(self.sdk_pid) == self.supervisor,
                             "live SDK changed or escaped its owned process group")
        return rows

    def query(self, command: str, deadline: float) -> dict | None:
        if self.plain:
            return None
        value = control.request(self.runtime / control.CONTROL_FILE, command, self.pid, deadline)
        self.retain([{"command": command, "status": value}])
        return value

    def transition(self, requested: dict, deadline: float) -> list[dict]:
        if self.plain:
            return []
        return self.retain(control.switch(self.runtime / control.CONTROL_FILE, self.pid, requested, deadline))

    def acknowledge(self) -> None:
        phase = self.phases[self.position]
        temporary = self.root / (phase + ".acktmp")
        descriptor = os.open(temporary, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
        with os.fdopen(descriptor, "w") as stream:
            stream.write(self.token + " " + phase + "\n")
        temporary.replace(self.root / (phase + ".resume"))
        self.position += 1

    def before(self, index: int, deadline: float) -> None:
        requested = self.sequence[index]["metrics"]
        history = self.transition(requested, deadline)
        previous = self.record["steps"][-1]["after"]["settled"]["function_completions"] if index and history else 0
        provider.require(not history or history[0]["status"]["function_completions"] == previous,
                         "selected calls ran outside the live Node schedule")
        provider.require(index != 0 or not history
                         or all(history[0]["status"][key] is flag for key, flag in requested.items()),
                         "initial Node metric state differs from the frozen first call")
        self.record["steps"].append({"id": self.sequence[index]["id"], "requested": requested.copy(),
                                     "before": {"history": history, "cursor": len(self.bodies)}, "after": None})
        self.save()
        self.acknowledge()

    def after(self, index: int, deadline: float) -> None:
        step = self.record["steps"][index]
        current, flushed = self.query("status", deadline), self.query("flush", deadline)
        if current is not None:
            before = step["before"]["history"][-1]["status"]
            provider.require(current["function_completions"] > before["function_completions"]
                             and flushed["function_completions"] == current["function_completions"]
                             and all(current[key] is flushed[key] is flag for key, flag in step["requested"].items()),
                             "live Node calls or metric state differ")
        self.holding = {"index": index, "started_ns": time.monotonic_ns(), "status": current, "flush": flushed,
                        "until": time.monotonic() + (0 if all(step["requested"].values()) else INTERVAL_MS / 1000)}

    def settle(self, deadline: float) -> None:
        pending = self.holding
        step = self.record["steps"][pending["index"]]
        settled = self.query("flush", deadline)
        if settled is not None:
            provider.require(settled["function_completions"] == pending["status"]["function_completions"]
                             and all(settled[key] is flag for key, flag in step["requested"].items()),
                             "live Node calls or controls changed at a paused boundary")
        end = len(self.bodies)
        received = metric_bodies(self.bodies, step["before"]["cursor"], end)
        provider.require(all(step["requested"].values()) or not received, "disabled Node metrics reached the receiver")
        step["after"] = {"status": pending["status"], "flush": pending["flush"], "settled": settled,
                         "cursor": end, "metric_bodies": received, "held_ns": time.monotonic_ns() - pending["started_ns"]}
        self.holding = None
        self.save()
        self.acknowledge()

    def restore(self, deadline: float) -> None:
        history = self.transition({"collection": True, "emission": True}, deadline)
        flushed = self.query("flush", deadline)
        if flushed is not None:
            provider.require(flushed["function_completions"] == self.record["steps"][-1]["after"]["settled"]["function_completions"]
                             and flushed["collection"] and flushed["emission"], "live Node restoration changed calls")
        self.record["restored"] = {"history": history, "flush": flushed, "cursor": len(self.bodies)}
        self.save()
        self.acknowledge()

    def bind_application(self) -> bool:
        """Wait for complete publication before binding the actual owned PID."""
        application = self.folder / "node-source-application.json"
        staged = application.with_name(application.name + ".staging")
        if ((not application.exists() and not application.is_symlink())
                or staged.exists() or staged.is_symlink()):
            return False
        receipt = strict_json(read_owned(application, 4096))
        self.pid = receipt["pid"]
        provider.require(type(self.pid) is int and self.pid > 1 and self.pid != self.supervisor
                         and receipt == {"pid": self.pid, "supervisor_pid": self.supervisor, "group": self.supervisor}
                         and os.getpgid(self.pid) == self.supervisor, "actual live Node application identity differs")
        self.record["pid"] = self.pid
        return True

    def poll(self, process, deadline: float) -> None:
        """Keep the outer process monitor active while the application yields."""
        if self.supervisor is None:
            self.supervisor = process.pid
            self.record["supervisor_pid"] = process.pid
        provider.require(process.pid == self.supervisor, "live Node supervisor changed")
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
        if self.pid is None and not self.bind_application():
            return
        if self.position == 0 and not self.plain and not (self.runtime / control.CONTROL_FILE).exists():
            return
        if phase == "finish":
            self.restore(deadline)
        elif phase.startswith("before-"):
            self.before(self.position // 2, deadline)
        else:
            self.after(self.position // 2, deadline)

    def finish(self, process) -> None:
        """Missing checkpoints or a process replacement cannot become a pass."""
        provider.require(process.pid == self.supervisor and self.position == len(self.phases)
                         and self.holding is None and self.record["restored"] is not None,
                         "application exited before completing its live Node schedule")
        expected = {phase + suffix for phase in self.phases for suffix in (".ready", ".resume")}
        provider.require({path.name for path in self.root.iterdir()} == expected, "unexpected live Node checkpoint files")
