"""Host-owned metric checkpoints around unchanged synchronous Python calls."""

import json
import os
from pathlib import Path
import sys
import time
import uuid

from java_live import marker, metric_bodies, read_owned
import live_control
import python_checkpoint
import python_control as control
import python_execution
import python_health
import python_prepared
from python_provider import require
from otelc_capture import strict_json

RECORD = "python-controls.json"
INTERVAL_MS = 1000
MAX_RECORD_BYTES = 8 * 1024 * 1024


class Session:
    """Keep the actual supervisor, application and SDK bound to one preparation."""

    def __init__(self, folder: Path, sequence: list[dict], bodies: list, *, plain: bool):
        self.folder, self.sequence, self.bodies, self.plain = folder, sequence, bodies, plain
        self.root = folder / "python-rendezvous"
        self.root.mkdir(mode=0o700)
        self.token = uuid.uuid4().hex
        self.phases = [phase + "-" + str(index) for index in range(len(sequence))
                       for phase in ("before", "after")] + ["finish"]
        self.position = self.statuses = 0
        self.supervisor = self.pid = self.sdk_pid = self.launch_id = None
        self.intent = self.launch = self.holding = None
        self.record = {"control_schema_version": 1, "plain": plain, "profile": None,
                       "supervisor_pid": None, "pid": None, "sdk_pid": None, "launch_id": None,
                       "policy_sha256": None, "interval_ms": INTERVAL_MS, "steps": [], "restored": None}

    def environment(self) -> dict:
        """Freeze observer bindings before preparing the native application."""
        return {python_checkpoint.ROOT_ENV: str(self.root), python_checkpoint.TOKEN_ENV: self.token}

    def bind(self, intent: python_prepared.Intent, launch: dict) -> None:
        """Only the caller's independently verified preparation selects runtime data."""
        require(self.intent is None and intent.plain is self.plain
                and all(intent.environment.get(key) == value for key, value in self.environment().items()),
                "Python live bindings differ from the prepared environment")
        self.intent, self.launch = intent, launch
        self.record.update(profile=intent.profile, policy_sha256=python_health.policy_digest(intent.policy))

    def save(self) -> None:
        """Retain complete bounded protocol replies without the endpoint token."""
        raw = (json.dumps(self.record, indent=2) + "\n").encode()
        require(len(raw) <= MAX_RECORD_BYTES, "live Python record exceeds its byte budget")
        temporary = self.folder / (RECORD + ".tmp")
        descriptor = os.open(temporary, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
        with os.fdopen(descriptor, "wb") as stream:
            stream.write(raw)
        temporary.replace(self.folder / RECORD)

    def query(self, command: str, deadline: float) -> dict | None:
        """Query the actual pair; the plain worker has no SDK endpoint."""
        if self.plain:
            return None
        value = control.request(self.intent.runtime / live_control.CONTROL_FILE, command, self.pid, deadline)
        self.statuses += 1
        require(self.statuses <= control.MAX_STATUSES and value["sdk_pid"] == self.sdk_pid,
                "live Python SDK identity or response budget differs")
        if command == "health":
            require(value["launch_id"] == self.launch_id and value["policy_sha256"] == self.record["policy_sha256"],
                    "live Python launch or policy changed")
        return value

    def transition(self, requested: dict, deadline: float) -> list[dict]:
        """Set each flag independently, preserving the selected completion count."""
        if self.plain:
            return []
        previous = self.query("status", deadline)
        rows = [{"command": "status", "response": previous}]
        for key, other in (("collection", "emission"), ("emission", "collection")):
            command = key + (" on" if requested[key] else " off")
            current = self.query(command, deadline)
            require(current[key] is requested[key] and current[other] is previous[other]
                    and current["function_completions"] == previous["function_completions"],
                    "Python live setter changed independent flags or calls")
            rows.append({"command": command, "response": current})
            previous = current
        while not requested["emission"] and not previous["effective_emission_off"]:
            time.sleep(min(.01, max(0., deadline - time.monotonic())))
            current = self.query("status", deadline)
            require(all(current[key] is value for key, value in requested.items())
                    and current["function_completions"] == previous["function_completions"],
                    "Python live calls changed while draining exports")
            rows.append({"command": "status", "response": current})
            previous = current
        return rows

    def acknowledge(self) -> None:
        phase = self.phases[self.position]
        temporary = self.root / (phase + ".acktmp")
        with os.fdopen(os.open(temporary, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600), "w") as stream:
            stream.write(self.token + " " + phase + "\n")
        temporary.replace(self.root / (phase + ".resume"))
        self.position += 1

    def before(self, index: int, deadline: float) -> None:
        requested = self.sequence[index]["metrics"]
        history = self.transition(requested, deadline)
        if history:
            initial = history[0]["response"]
            require(index != 0 or all(initial[key] is value for key, value in requested.items()),
                    "initial Python metric state differs from the frozen first call")
            if index:
                require(initial["function_completions"] == self.record["steps"][-1]["after"]["settled"]["application"]["function_completions"],
                        "selected Python calls ran outside the live schedule")
        flushed, health = self.query("flush", deadline), self.query("health", deadline)
        self.record["steps"].append({"id": self.sequence[index]["id"], "requested": requested.copy(),
            "before": {"history": history, "flush": flushed, "health": health, "cursor": len(self.bodies)}, "after": None})
        self.save()
        self.acknowledge()

    def after(self, index: int, deadline: float) -> None:
        step = self.record["steps"][index]
        status, flushed, health = (self.query(command, deadline) for command in ("status", "flush", "health"))
        if status is not None:
            previous = step["before"]["health"]["application"]["function_completions"]
            require(status["function_completions"] > previous, "live Python call did not complete")
        self.holding = {"index": index, "status": status, "flush": flushed, "health": health,
                        "started_ns": time.monotonic_ns(),
                        "until": time.monotonic() + (0 if all(step["requested"].values()) else INTERVAL_MS / 1000)}

    def settle(self, deadline: float) -> None:
        pending = self.holding
        step = self.record["steps"][pending["index"]]
        flushed, settled = self.query("flush", deadline), self.query("health", deadline)
        end = len(self.bodies)
        indices = metric_bodies(self.bodies, step["before"]["cursor"], end)
        require(all(step["requested"].values()) or not indices, "disabled Python metrics reached the receiver")
        step["after"] = {key: pending[key] for key in ("status", "flush", "health")}
        step["after"].update(settled_flush=flushed, settled=settled, cursor=end, metric_bodies=indices,
                             held_ns=time.monotonic_ns() - pending["started_ns"])
        self.holding = None
        self.save()
        self.acknowledge()

    def restore(self, deadline: float) -> None:
        rows = self.transition({"collection": True, "emission": True}, deadline)
        flushed, health = self.query("flush", deadline), self.query("health", deadline)
        self.record["restored"] = {"history": rows, "flush": flushed, "health": health, "cursor": len(self.bodies)}
        self.save()
        self.acknowledge()

    def bind_application(self, process) -> bool:
        """Bind startup publications to the kernel-owned supervisor and group."""
        require(self.intent is not None and self.launch is not None, "unbound live Python preparation")
        path = self.intent.runtime / "python-application-start.json"
        if not path.exists() and not path.is_symlink():
            return False
        app = strict_json(read_owned(path, 16384))
        owner = python_execution.Owner(process.pid, os.getpid(), tuple(map(str, process.args)), 0, sys.hexversion)
        expected = python_execution.shared(owner, self.launch)
        python_execution.verify_shared(app, expected, "otelc.python.application",
                                       {"application_pid", "sdk_pid", "sdk_ready", "sdk_launch_id", "native_command"})
        python_execution.native_command(app["native_command"], self.launch)
        self.pid = app["application_pid"]
        require(python_execution.pid(self.pid) and self.pid != process.pid and os.getpgid(self.pid) == process.pid,
                "live Python application escaped its owned process group")
        self.sdk_pid, self.launch_id = python_execution.sdk_identity(self.intent.runtime, app, expected, self.plain)
        require(self.plain or os.getpgid(self.sdk_pid) == process.pid, "live Python SDK escaped its process group")
        self.record.update(pid=self.pid, sdk_pid=self.sdk_pid, launch_id=self.launch_id)
        return True

    def poll(self, process, deadline: float) -> None:
        """Keep the common wall/output monitor active while the worker yields."""
        if self.supervisor is None:
            self.supervisor = process.pid
            self.record["supervisor_pid"] = process.pid
        require(process.pid == self.supervisor, "live Python supervisor changed")
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
        if self.pid is None and not self.bind_application(process):
            return
        if phase == "finish":
            self.restore(deadline)
        elif phase.startswith("before-"):
            self.before(self.position // 2, deadline)
        else:
            self.after(self.position // 2, deadline)

    def finish(self, process) -> None:
        """A missing checkpoint cannot be replaced by a clean process exit."""
        require(process.pid == self.supervisor and self.position == len(self.phases)
                and self.holding is None and self.record["restored"] is not None,
                "application exited before completing its live Python schedule")
        expected = {phase + suffix for phase in self.phases for suffix in (".ready", ".resume")}
        require({path.name for path in self.root.iterdir()} == expected, "unexpected live Python checkpoint files")
