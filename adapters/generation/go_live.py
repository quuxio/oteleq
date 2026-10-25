"""Own same-process Go metric schedules under the original process monitor."""

import copy
import json
import os
from pathlib import Path
import stat
import time

import go_control as control
import go_files as files
import go_launch
from go_provider import data_seal, policy_digest, require, same
from java_live import metric_bodies
import live_control
from otelc_capture import strict_json

RECORD = "go-controls.json"
INTERVAL_MS = 1000
MAX_RECORD_BYTES = 8 * 1024 * 1024
MAX_TELEMETRY_REQUESTS = 4096


class Session(go_launch.Session):
    """Pause an owned native worker without replacing its deadline or cleanup."""

    def __init__(self, launch, *, wait_ms: int, sequence: list[dict], bodies: list):
        require(type(sequence) is list and 1 <= len(sequence) <= 32
                and all(type(step) is dict and step.get("id") == "step-" + str(index)
                        and step.get("action") == "call" and type(step.get("metrics")) is dict
                        and set(step["metrics"]) == {"collection", "emission"}
                        and all(type(flag) is bool for flag in step["metrics"].values())
                        for index, step in enumerate(sequence)), "invalid Go live call schedule")
        require(any(all(step["metrics"].values()) for step in sequence), "Go live schedule lacks a positive metric call")
        super().__init__(launch, wait_ms=wait_ms)
        self.folder = launch.intent.runtime.parent
        self.sequence, self.bodies = copy.deepcopy(sequence), bodies
        self.phases = [phase + "-" + str(index) for index in range(len(sequence))
                       for phase in ("before", "after")] + ["finish"]
        self.options = {"policy_sha256": policy_digest(launch.intent.policy),
                        "selection_sha256": launch.intent.build.receipt["selection"]["sha256"]}
        require(all(launch.intent.policy["metrics"][key] is flag for key, flag in sequence[0]["metrics"].items()),
                "Go initial metric policy differs from the first declared call")
        self.control_seal = data_seal(self.control_values())
        self.position = self.statuses = 0
        self.last_flushes = 0
        self.holding = None
        self.checkpoints = {}
        self.saved_control = None
        self.final_control = self.final_control_seal = None
        self.record = {"control_schema_version": 1, "plain": launch.intent.plain,
                       "supervisor_pid": None, "pid": None, "sdk_pid": None,
                       "launch_id": launch.response["request"]["launch_id"], **self.options,
                       "interval_ms": INTERVAL_MS, "steps": [], "restored": None}

    def control_values(self) -> dict:
        return {"sequence": self.sequence, "phases": self.phases, "options": self.options,
                "prepared": self.launch.accepted_seal, "binding": self.binding_seal}

    def verify_controls(self) -> None:
        self.verify_binding()
        require(data_seal(self.control_values()) == self.control_seal, "Go live caller schedule changed")

    def save_control(self) -> None:
        """Keep a bounded live record separate from the ownership publications."""
        raw = (json.dumps(self.record, indent=2, allow_nan=False) + "\n").encode()
        require(len(raw) <= MAX_RECORD_BYTES, "Go live record exceeds its byte budget")
        temporary = self.folder / (RECORD + ".tmp")
        descriptor = os.open(temporary, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
        with os.fdopen(descriptor, "wb") as output:
            output.write(raw)
        temporary.replace(self.folder / RECORD)
        self.saved_control = files.file(self.folder / RECORD, MAX_RECORD_BYTES, private=True)[:2]

    def query(self, command: str, deadline: float) -> dict | None:
        if self.launch.intent.plain:
            return None
        require(self.started is not None and self.statuses < control.MAX_STATUSES,
                "Go live query lacks ownership or exceeds its reply budget")
        value = control.request(self.launch.intent.runtime / live_control.CONTROL_FILE, command,
                                self.started.owner.application_pid, deadline, **self.options)
        self.statuses += 1
        return value

    def transition(self, flags: dict, deadline: float) -> list[dict]:
        if self.launch.intent.plain:
            return []
        rows = []
        previous = self.query("status", deadline)
        rows.append({"command": "status", "response": previous})
        for key, other in (("collection", "emission"), ("emission", "collection")):
            command = key + (" on" if flags[key] else " off")
            current = self.query(command, deadline)
            require(current[key] is flags[key] and current[other] is previous[other],
                    "Go live setter changed its independent flag")
            rows.append({"command": command, "response": current})
            previous = current
        return rows

    def checkpoint(self, phase: str) -> bool:
        root = self.binding.root
        if not (root / (phase + ".ready")).exists() and not (root / (phase + ".ready")).is_symlink():
            return False
        require(not any((root / (phase + suffix)).exists() or (root / (phase + suffix)).is_symlink()
                        for suffix in (".resume", ".resume.tmp")), "Go live checkpoint was released early")
        evidence, message = {}, None
        for suffix in (".ready", ".tmp"):
            name = phase + suffix
            identity, facts, raw = files.file(root / name, 1024, keep=True)
            require(stat.S_IMODE(facts[2]) == 0o600 and facts[3] == os.getuid() and facts[8] == 2,
                    "unsafe Go live checkpoint")
            evidence[name] = identity, facts
            if message is None:
                message = raw
        require(evidence[phase + ".ready"][1] == evidence[phase + ".tmp"][1],
                "Go live checkpoint publication has different links")
        expected = {"schema_version": 1, "kind": "oteleq.go.checkpoint", "phase": phase,
                    "token": self.binding.token, "pid": self.started.owner.application_pid,
                    "parent_pid": self.started.owner.pid}
        require(same(strict_json(message), expected), "Go live checkpoint differs from its owned process or phase")
        self.checkpoints[phase] = evidence
        return True

    def acknowledge(self) -> None:
        phase = self.phases[self.position]
        go_launch.private_publish(self.binding.root, phase + ".resume",
                                  (self.binding.token + " " + phase + "\n").encode("ascii"))
        for suffix in (".resume", ".resume.tmp"):
            name = phase + suffix
            self.checkpoints[phase][name] = files.file(self.binding.root / name, 1024)[:2]
        self.position += 1

    def paused_health(self, flags: dict, deadline: float) -> dict | None:
        value = self.query("health", deadline)
        if value is not None:
            flushes = int(value["metric_flush"]["attempts"])
            require(flushes > self.last_flushes, "Go paused flush did not advance the SDK counter")
            self.last_flushes = flushes
            require(all(value["controls"][key] is flag for key, flag in flags.items()),
                    "Go live health differs from its requested metric state")
            trace = value["trace_exports"]
            require(trace["exported_spans"] == value["probe_accounting"]["function_ended"]
                    and trace["queue_pending"] == "0", "Go paused trace flush did not drain selected completions")
            if not all(flags.values()):
                exports = value["metric_exports"]
                require(exports["attempts"] == exports["succeeded"],
                        "Go disabled metric window began before exports drained")
        return value

    @staticmethod
    def completed(value: dict | None) -> int:
        return int(value["probe_accounting"]["function_ended"]) if value is not None else 0

    def before(self, index: int, deadline: float) -> None:
        flags = self.sequence[index]["metrics"]
        history = self.transition(flags, deadline)
        require(index != 0 or not history or all(history[0]["response"][key] is flag for key, flag in flags.items()),
                "Go live startup state differs from the first declared call")
        flushed, health = self.query("flush", deadline), self.paused_health(flags, deadline)
        previous = self.completed(self.record["steps"][-1]["after"]["settled"]) if index else 0
        require(self.completed(health) == previous, "Go selected calls ran outside the declared schedule")
        self.record["steps"].append({"id": self.sequence[index]["id"], "requested": flags.copy(),
            "before": {"history": history, "flush": flushed, "health": health, "cursor": len(self.bodies)}, "after": None})
        self.save_control()
        self.acknowledge()

    def after(self, index: int, deadline: float) -> None:
        step = self.record["steps"][index]
        status, flushed = self.query("status", deadline), self.query("flush", deadline)
        health = self.paused_health(step["requested"], deadline)
        require(health is None or self.completed(health) > self.completed(step["before"]["health"]),
                "Go selected call did not complete at its declared checkpoint")
        self.holding = {"index": index, "status": status, "flush": flushed, "health": health,
                        "started_ns": time.monotonic_ns(),
                        "until": time.monotonic() + (0 if all(step["requested"].values()) else INTERVAL_MS / 1000)}

    def settle(self, deadline: float) -> None:
        pending = self.holding
        step = self.record["steps"][pending["index"]]
        flushed, settled = self.query("flush", deadline), self.paused_health(step["requested"], deadline)
        require(self.completed(settled) == self.completed(pending["health"]),
                "Go selected calls changed while paused after completion")
        end = len(self.bodies)
        indices = metric_bodies(self.bodies, step["before"]["cursor"], end)
        require(all(step["requested"].values()) or not indices, "disabled Go metrics reached the receiver")
        step["after"] = {key: pending[key] for key in ("status", "flush", "health")}
        step["after"].update(settled_flush=flushed, settled=settled, cursor=end, metric_bodies=indices,
                             held_ns=time.monotonic_ns() - pending["started_ns"])
        self.holding = None
        self.save_control()
        self.acknowledge()

    def restore(self, deadline: float) -> None:
        flags = {"collection": True, "emission": True}
        history = self.transition(flags, deadline)
        flushed, health = self.query("flush", deadline), self.paused_health(flags, deadline)
        require(self.completed(health) == self.completed(self.record["steps"][-1]["after"]["settled"]),
                "Go restoration changed selected calls")
        self.record["restored"] = {"history": history, "flush": flushed, "health": health, "cursor": len(self.bodies)}
        self.save_control()
        self.acknowledge()

    def poll(self, process, deadline: float) -> None:
        self.verify_controls()
        super().poll(process, deadline)
        if self.started is None:
            return
        require(data_seal(self.start_values()) == self.start_seal, "Go live accepted ownership changed")
        self.record.update(supervisor_pid=self.started.owner.pid, pid=self.started.owner.application_pid,
                           sdk_pid=None if self.launch.intent.plain else self.started.owner.application_pid)
        if self.holding is not None:
            if time.monotonic() >= self.holding["until"]:
                self.settle(deadline)
            return
        if self.position == len(self.phases):
            return
        phase = self.phases[self.position]
        if not self.checkpoint(phase):
            return
        if phase == "finish":
            self.restore(deadline)
        elif phase.startswith("before-"):
            self.before(self.position // 2, deadline)
        else:
            self.after(self.position // 2, deadline)

    def verify_checkpoints(self) -> None:
        require(set(self.checkpoints) == set(self.phases), "Go live schedule is missing checkpoints")
        names = {"start.ready", "start.tmp", "start.resume", "start.resume.tmp"}
        for phase in self.phases:
            expected = self.checkpoints[phase]
            require(set(expected) == {phase + suffix for suffix in (".ready", ".tmp", ".resume", ".resume.tmp")},
                    "Go live checkpoint evidence is incomplete")
            for name, value in expected.items():
                require(same(files.file(self.binding.root / name, 1024)[:2], value), "Go live checkpoint changed")
            names.update(expected)
        require({path.name for path in self.binding.root.iterdir()} == names, "unexpected Go live checkpoint files")

    def finish(self, process) -> None:
        self.verify_controls()
        require(self.position == len(self.phases) and self.holding is None and self.record["restored"] is not None,
                "Go application exited before completing its live schedule")
        self.verify_checkpoints()
        super().finish(process)
        identity, facts, raw = files.file(self.folder / RECORD, MAX_RECORD_BYTES, keep=True, private=True)
        require(same((identity, facts), self.saved_control) and same(strict_json(raw), self.record),
                "Go live host record changed before completion")
        self.final_control = identity, facts
        self.final_control_seal = data_seal({"record": self.record, "checkpoints": self.checkpoints,
                                            "file": self.final_control, "schedule": self.control_seal})

    def verify_final(self) -> None:
        self.verify_controls()
        require(self.final_control is not None and data_seal({"record": self.record, "checkpoints": self.checkpoints,
                "file": self.final_control, "schedule": self.control_seal}) == self.final_control_seal,
                "Go accepted live control evidence changed")
        require(same(files.file(self.folder / RECORD, MAX_RECORD_BYTES, private=True)[:2], self.final_control),
                "Go live control record changed")
        self.verify_checkpoints()
