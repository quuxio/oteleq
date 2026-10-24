"""Frozen live schedules bind real wire fixtures and every private boundary."""

from dataclasses import replace
from pathlib import Path
import sys
import tempfile
import time
from types import SimpleNamespace
import unittest
from unittest.mock import patch

REPO = Path(__file__).resolve().parents[1]
sys.path[:0] = [str(REPO / "adapters/generation"), str(REPO / "examples")]
import python_control
import python_control_receipt as receipt
import python_execution
import python_live
import python_provider
import sequences
from python_control_fixture import report, status
from test_generation_python_execution import fixture

STATES = [{"collection": True, "emission": True}, {"collection": False, "emission": True},
          {"collection": True, "emission": False}, {"collection": False, "emission": False}]


class PythonLiveTests(unittest.TestCase):
    def session(self, root, plain=False):
        intent, launch, owner, catalogue = fixture(root, plain=plain, profile=python_provider.ORIGIN_PROFILE)
        folder = root / "case"; folder.mkdir()
        steps = [{"id": "step-" + str(i), "action": "call", "arguments": [1], "metrics": state.copy()}
                 for i, state in enumerate(STATES)]
        session = python_live.Session(folder, steps, [], plain=plain)
        intent = replace(intent, environment={**intent.environment, **session.environment()})
        session.bind(intent, launch)
        execution = python_execution.read(intent, launch, owner, catalogue)
        return session, execution, SimpleNamespace(pid=owner.pid, args=list(owner.argv))

    def marker(self, session, phase):
        path = session.root / (phase + ".ready")
        path.write_text(session.token + " " + phase + "\n")
        path.chmod(0o600)

    def run_session(self, root, *, plain):
        session, execution, process = self.session(root, plain=plain)
        current = {**STATES[0], "completed": 1}
        def request(path, command, pid, deadline):
            self.assertFalse(plain, "plain worker queried SDK")
            if command.startswith(("collection ", "emission ")):
                key, flag = command.split(); current[key] = flag == "on"
            options = {key: current[key] for key in ("collection", "emission", "completed")}
            value = report(**options) if command == "health" else status(**options, barrier=command != "flush")
            value.update(pid=execution.application_pid, sdk_pid=execution.sdk_pid)
            if command == "health":
                value.update(launch_id=execution.launch_id, policy_sha256=session.record["policy_sha256"])
                value["application"].update(pid=execution.application_pid, sdk_pid=execution.sdk_pid)
                value["sdk"].update(pid=execution.application_pid, sdk_pid=execution.sdk_pid,
                                    launch_id=execution.launch_id, policy_sha256=session.record["policy_sha256"])
            return value
        with patch.object(python_control, "request", side_effect=request), \
                patch.object(python_live.os, "getpgid", return_value=process.pid), \
                patch.object(python_live.os, "getpid", return_value=execution.owner.parent_pid):
            for index in range(len(STATES)):
                self.marker(session, "before-" + str(index)); session.poll(process, time.monotonic() + 30)
                current["completed"] += 1
                self.marker(session, "after-" + str(index)); session.poll(process, time.monotonic() + 30)
                session.holding["until"] = 0
                session.holding["started_ns"] -= 1_000_000_000
                session.poll(process, time.monotonic() + 30)
            self.marker(session, "finish"); session.poll(process, time.monotonic() + 30)
            session.finish(process)
        entry = {"python_profile": session.intent.profile, "sequence_configuration": session.sequence}
        actual = receipt.read(session.folder, entry, execution, session.intent.policy, [], plain=plain)
        self.assertEqual(actual["pid"], execution.application_pid)
        self.assertEqual(actual["supervisor_pid"], process.pid)
        self.assertEqual(session.position, 2 * len(STATES) + 1)
        self.assertEqual(actual["sdk_pid"], execution.sdk_pid)
        return session, execution

    def test_plain_schedule_completes_every_boundary_without_fabricated_sdk_status(self):
        with tempfile.TemporaryDirectory() as temporary:
            session, _ = self.run_session(Path(temporary), plain=True)
            self.assertEqual(session.statuses, 0)

    def test_instrumented_schedule_keeps_creation_prefix_independent_and_restores_flags(self):
        with tempfile.TemporaryDirectory() as temporary:
            session, _ = self.run_session(Path(temporary), plain=False)
            first = session.record["steps"][0]["before"]["health"]["application"]
            self.assertEqual(first["function_completions"], 1)
            self.assertTrue(session.record["restored"]["health"]["sdk"]["collection"])
            self.assertTrue(session.record["restored"]["health"]["sdk"]["emission"])
            record = {"pid": first["pid"], "sdk_pid": first["sdk_pid"],
                      "launch_id": session.launch_id, "policy_sha256": session.record["policy_sha256"]}
            history = session.record["steps"][0]["before"]["history"]
            self.assertEqual(receipt.transition(history, record, 1, STATES[0], initial=True), 3)
            for change in ([], history[1:], [{**history[0], "command": "off"}, *history[1:]]):
                with self.assertRaises(ValueError):
                    receipt.transition(change, record, 1, STATES[0], initial=True)

    def test_missing_checkpoints_wrong_process_unbound_intent_and_response_budget_refuse(self):
        with tempfile.TemporaryDirectory() as temporary:
            session, execution, process = self.session(Path(temporary))
            with self.assertRaises(ValueError):
                session.finish(process)
            with self.assertRaises(ValueError):
                session.bind(session.intent, session.launch)
            with patch.object(python_live.os, "getpgid", return_value=process.pid + 1), \
                    patch.object(python_live.os, "getpid", return_value=execution.owner.parent_pid), \
                    self.assertRaises(ValueError):
                session.bind_application(process)
            session.pid, session.sdk_pid = 101, 102
            session.statuses = python_control.MAX_STATUSES
            with patch.object(python_control, "request", return_value=status()), self.assertRaises(ValueError):
                session.query("status", time.monotonic() + 1)

    def test_collected_call_counts_and_error_totals_have_strict_phase_denominators(self):
        from collections import Counter
        import python_telemetry as telemetry
        calls, errors = Counter({1: 2}), Counter({1: 1})
        good = {(telemetry.CALLS, 1): 2, (telemetry.DURATION, 1): 2, (telemetry.EXCEPTIONS, 1): 1}
        receipt.phase([0], {0: good}, calls, errors, required=True)
        for bad in ({}, {**good, (telemetry.CALLS, 1): 3}, {**good, (telemetry.CALLS, 2): 1}):
            with self.subTest(bad=bad), self.assertRaises(ValueError):
                receipt.phase([0], {0: bad}, calls, errors, required=True)

    def test_only_explicit_origin_profiles_can_freeze_live_python_states(self):
        for profile in (python_provider.ORIGIN_PROFILE, python_provider.CACHE_PROFILE):
            entry = {"language": "python", "python_backend": "prepared", "python_profile": profile,
                     "otelc_function": "entry.Counter.add", "name": "Counter.add", "path": "entry.py",
                     "receiver_fixture": {}, "sequence_configuration": [{"metrics": state} for state in [*STATES, STATES[0]]]}
            steps = [{"action": "call", "metrics": state.copy()} for state in STATES]
            sequences.configure_controls(entry, steps)
            for first in STATES:
                entry["sequence_configuration"][0]["metrics"] = first
                configured = python_provider.configuration(entry, "http://127.0.0.1:4318", "case")
                self.assertEqual({key: configured["metrics"][key] for key in first}, first)
        entry = {"language": "python", "python_backend": "legacy"}
        with self.assertRaises(ValueError):
            sequences.configure_controls(entry, [{"action": "call", "metrics": STATES[0]}])


if __name__ == "__main__":
    unittest.main()
