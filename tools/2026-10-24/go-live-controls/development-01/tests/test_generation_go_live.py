"""Go schedules retain every owned checkpoint, reply and bounded quiet window."""

import json
import os
from pathlib import Path
import sys
import time
from types import SimpleNamespace
import unittest
from unittest.mock import patch

REPO = Path(__file__).resolve().parents[1]
sys.path[:0] = [str(REPO / "adapters/generation"), str(REPO / "examples")]
import go_control
import go_execution
import go_launch
import go_live
import generation
from test_generation_go_control import live, status
from test_generation_go_execution import completion, preparation, starts
from test_generation_go_prepared import private

STATES = [{"collection": True, "emission": True}, {"collection": False, "emission": True},
          {"collection": True, "emission": False}, {"collection": False, "emission": False}]


class GoLiveTests(unittest.TestCase):
    def test_public_execution_keeps_the_owned_monitor_and_rejects_missing_live_controller(self):
        session, _ = self.session()
        entry = {"language": "go", "go_backend": "source-v1", "sequence_configuration": session.sequence}
        environment = {"OTHER": "preserved"}
        with patch.object(session, "environment", wraps=session.environment) as publish:
            options = generation.execution_options(entry, {}, "instrumented_on", session.folder, None,
                                                   session.bodies, environment, go_session=session)
        self.assertEqual(options, {"record_process": True, "interaction": session})
        self.assertEqual(environment["OTHER"], "preserved")
        self.assertEqual(environment, {"OTHER": "preserved", **session.environment()})
        publish.assert_called_once_with()
        for controller in (None, object()):
            with self.assertRaisesRegex(ValueError, "native Go"):
                generation.execution_options(entry, {}, "baseline", session.folder, None, [], {}, go_session=controller)

    def session(self, *, plain=False, sequence=None):
        fixture, prepared = preparation(self, plain=plain)
        steps = [{"id": "step-" + str(index), "action": "call", "arguments": [1], "metrics": state.copy()}
                 for index, state in enumerate(STATES)] if sequence is None else sequence
        session = go_live.Session(prepared, wait_ms=5000, sequence=steps, bodies=[])
        pid, app = os.getpid() + 100, os.getpid() + 200
        process = SimpleNamespace(pid=pid, args=list(prepared.response["command"]), returncode=None)
        process.poll = lambda: process.returncode
        owner = go_execution.Owner(pid, os.getpid(), app, tuple(process.args))
        supervisor, _ = starts(prepared, owner)
        self.fixture, self.prepared, self.owner, self.supervisor = fixture, prepared, owner, supervisor
        self.kernel = [{"pid": pid, "parent_pid": os.getpid(), "process_group": pid},
                       {"pid": app, "parent_pid": pid, "process_group": pid}]
        self.current = {"collection": True, "emission": True, "completed": 0}
        return session, process

    def marker(self, session, phase):
        message = {"schema_version": 1, "kind": "oteleq.go.ready" if phase == "start" else "oteleq.go.checkpoint",
                   "token": session.binding.token, "pid": self.owner.application_pid, "parent_pid": self.owner.pid}
        if phase != "start":
            message["phase"] = phase
        root = session.binding.root
        private(root / (phase + ".tmp"), message)
        os.link(root / (phase + ".tmp"), root / (phase + ".ready"))

    def bind(self, session, process):
        self.marker(session, "start")
        with patch.object(go_launch, "kernel", side_effect=self.kernel):
            session.poll(process, time.monotonic() + 30)
        self.assertEqual(session.record["pid"], self.owner.application_pid)
        self.assertEqual(session.record["supervisor_pid"], self.owner.pid)

    def request(self, path, command, pid, deadline, **options):
        self.assertEqual(path, self.prepared.intent.runtime / "control.json")
        self.assertEqual(pid, self.owner.application_pid)
        self.assertEqual(options["selection_sha256"], self.prepared.intent.build.receipt["selection"]["sha256"])
        if command.startswith(("collection ", "emission ")):
            key, flag = command.split()
            self.current[key] = flag == "on"
        flags = {key: self.current[key] for key in ("collection", "emission")}
        value = live(**flags) if command == "health" else status(**flags)
        value["pid"] = pid
        if command == "health":
            value.update(options)
            value["controls"]["pid"] = pid
            for key in ("function_started", "function_ended"):
                value["probe_accounting"][key] = str(self.current["completed"])
            value["trace_exports"]["exported_spans"] = str(self.current["completed"])
        return value

    def run_session(self, *, plain=False):
        session, process = self.session(plain=plain)
        self.bind(session, process)
        with patch.object(go_control, "request", side_effect=self.request) as request:
            for index in range(len(STATES)):
                self.marker(session, "before-" + str(index))
                session.poll(process, time.monotonic() + 30)
                self.current["completed"] += 2 if index == 0 else 1
                self.marker(session, "after-" + str(index))
                session.poll(process, time.monotonic() + 30)
                session.holding["until"] = 0
                session.holding["started_ns"] -= 1_000_000_000
                session.poll(process, time.monotonic() + 30)
            self.marker(session, "finish")
            session.poll(process, time.monotonic() + 30)
            if plain:
                request.assert_not_called()
        final = completion(self.prepared, self.owner, self.supervisor)
        if not plain:
            value = final["sdk_health"]
            for key in go_control.health.PROBES:
                value["probe_accounting"][key] = "0"
            for key in ("function_started", "function_ended"):
                value["probe_accounting"][key] = str(self.current["completed"])
            value["trace_exports"]["exported_spans"] = str(self.current["completed"])
            private(self.prepared.intent.runtime / "health.json", value)
            private(self.prepared.intent.runtime / "go-execution.json", final)
        process.returncode = 0
        session.finish(process)
        session.verify_final()
        return session, process

    def test_plain_calls_complete_all_markers_without_fabricating_sdk_replies(self):
        session, _ = self.run_session(plain=True)
        self.assertEqual(session.statuses, 0)
        self.assertIsNone(session.record["sdk_pid"])
        self.assertEqual(session.position, 9)
        for step in session.record["steps"]:
            self.assertEqual(step["before"]["history"], [])
            self.assertIsNone(step["before"]["health"])
            self.assertIsNone(step["after"]["settled"])

    def test_owned_live_schedule_starts_before_factory_and_restores_both_flags(self):
        session, _ = self.run_session()
        first = session.record["steps"][0]
        self.assertEqual(session.completed(first["before"]["health"]), 0)
        self.assertEqual(session.completed(first["after"]["health"]), 2)
        self.assertEqual(session.completed(session.record["restored"]["health"]), 5)
        self.assertEqual(session.record["sdk_pid"], session.record["pid"])
        self.assertTrue(session.record["restored"]["health"]["controls"]["collection"])
        self.assertTrue(session.record["restored"]["health"]["controls"]["emission"])
        self.assertLess(session.statuses, go_control.MAX_STATUSES)
        self.assertEqual(len(list(session.binding.root.iterdir())), 40)
        self.assertEqual(json.loads((session.folder / go_live.RECORD).read_text()), session.record)

    def test_missing_phases_changed_schedule_or_exhausted_reply_budget_refuse(self):
        session, process = self.session()
        session.poll(process, time.monotonic() + 30)
        with self.assertRaisesRegex(ValueError, "before completing"):
            session.finish(process)
        self.bind(session, process)
        session.statuses = go_control.MAX_STATUSES
        with patch.object(go_control, "request") as request, self.assertRaises(ValueError):
            session.query("status", time.monotonic() + 1)
        request.assert_not_called()
        session.sequence[0]["metrics"]["collection"] = False
        with self.assertRaisesRegex(ValueError, "schedule changed"):
            session.poll(process, time.monotonic() + 1)

    def test_checkpoint_refuses_wrong_process_or_phase_and_early_or_unsafe_release(self):
        session, process = self.session()
        self.bind(session, process)
        self.marker(session, "before-0")
        path = session.binding.root / "before-0.tmp"
        original = json.loads(path.read_text())
        for key, changed in (("pid", self.owner.application_pid + 1), ("parent_pid", 1),
                             ("phase", "after-0"), ("schema_version", True), ("token", "f" * 32)):
            private(path, {**original, key: changed})
            with self.subTest(key=key), self.assertRaises(ValueError):
                session.poll(process, time.monotonic() + 1)
        private(path, original)
        path.chmod(0o644)
        with self.assertRaisesRegex(ValueError, "unsafe Go live"):
            session.poll(process, time.monotonic() + 1)
        path.chmod(0o600)
        (session.binding.root / "before-0.resume").write_bytes(b"early")
        with self.assertRaisesRegex(ValueError, "released early"):
            session.poll(process, time.monotonic() + 1)

    def test_disabled_window_rejects_wire_metrics_and_paused_call_count_changes(self):
        for change in ("metrics", "calls"):
            session, process = self.session()
            self.bind(session, process)
            with patch.object(go_control, "request", side_effect=self.request):
                for index in (0, 1):
                    self.marker(session, "before-" + str(index)); session.poll(process, time.monotonic() + 30)
                    self.current["completed"] += 2 if index == 0 else 1
                    self.marker(session, "after-" + str(index)); session.poll(process, time.monotonic() + 30)
                    session.holding["until"] = 0
                    if index == 1:
                        if change == "metrics": session.bodies.append(("/v1/metrics", b"unexpected"))
                        else: self.current["completed"] += 1
                        with self.assertRaises(ValueError):
                            session.poll(process, time.monotonic() + 30)
                    else:
                        session.poll(process, time.monotonic() + 30)

    def test_final_checkpoint_and_record_file_facts_cannot_be_repaired(self):
        session, _ = self.run_session()
        path = session.binding.root / "before-0.tmp"
        path.write_bytes(path.read_bytes() + b" ")
        with self.assertRaisesRegex(ValueError, "checkpoint changed"):
            session.verify_final()
        session, _ = self.run_session()
        path = session.folder / go_live.RECORD
        path.write_bytes(path.read_bytes() + b" ")
        with self.assertRaisesRegex(ValueError, "record changed"):
            session.verify_final()
        session, _ = self.run_session()
        session.record["pid"] += 1
        with self.assertRaisesRegex(ValueError, "evidence changed"):
            session.verify_final()

    def test_invalid_schedules_and_missing_positive_call_refuse(self):
        for sequence in ([], [{"id": "step-0", "action": "release", "metrics": STATES[0]}],
                         [{"id": "step-0", "action": "call", "metrics": {"collection": 1, "emission": True}}],
                         [{"id": "step-0", "action": "call", "metrics": STATES[3]}]):
            with self.subTest(sequence=sequence), self.assertRaises(ValueError):
                self.session(sequence=sequence)
