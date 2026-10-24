"""Literal process records cannot substitute a different Go application or exit."""

import copy
from dataclasses import replace
import hashlib
import json
from pathlib import Path
import sys
import unittest
from unittest.mock import patch

REPO = Path(__file__).resolve().parents[1]
sys.path[:0] = [str(REPO / "adapters/generation"), str(REPO / "examples")]
import go_execution as execution
import go_prepared as prepared
from test_generation_go_health import report
import test_generation_go_prepared as prepared_fixture
from test_generation_go_prepared import digest, private


def preparation(test: unittest.TestCase, *, plain: bool = False):
    """Reuse the literal preparation setup without running another test method."""
    fixture = prepared_fixture.GoPreparedTests()
    fixture.setUp()
    test.addCleanup(fixture.doCleanups)
    if plain:
        fixture.intent = replace(fixture.intent, plain=True)
        (fixture.intent.runtime / "config.json").unlink()
        fixture.response["request"]["plain"] = True
        fixture.response["plan"]["argv"][0] = str(fixture.intent.build.intent.directory / "plain")
        fixture.response["plan"]["binary"] = fixture.intent.build.receipt["plain"]
        fixture.response["prepared"]["config"] = None
        fixture.publish()
    return fixture, prepared.verify(fixture.response, fixture.intent)


def starts(launch, owner) -> tuple[dict, dict]:
    response = launch.response
    supervisor = {"schema_version": 1, "kind": "otelc.go.supervisor", "profile": "go-source-v1",
        "supervisor_pid": owner.pid, "parent_pid": owner.parent_pid, "process_group": owner.pid,
        "launch_id": response["request"]["launch_id"], "request_sha256": digest(response["request"]),
        "plan_sha256": digest(response["plan"]), "prepared_sha256": digest(response["prepared"])}
    application = {"schema_version": 1, "kind": "otelc.go.application", "profile": "go-source-v1",
        "launch_id": response["request"]["launch_id"], "pid": owner.application_pid,
        "supervisor_pid": owner.pid, "process_group": owner.pid, "plain": launch.intent.plain,
        "argv": response["plan"]["argv"], "binary": response["plan"]["binary"]}
    for name, value in zip(execution.START_FILES, (supervisor, application)):
        private(launch.intent.runtime / name, value)
    return supervisor, application


def completion(launch, owner, supervisor) -> dict:
    health = None
    if not launch.intent.plain:
        health = report()
        health.update(pid=owner.application_pid,
                      policy_sha256=hashlib.sha256(json.dumps(launch.intent.policy, sort_keys=True).encode()).hexdigest(),
                      selection_sha256=launch.intent.build.receipt["selection"]["sha256"])
        health["controls"]["pid"] = owner.application_pid
        private(launch.intent.runtime / "health.json", health)
    result = {"schema_version": 1, "kind": "otelc.go.execution", "profile": "go-source-v1",
        "launch_id": launch.response["request"]["launch_id"], "supervisor": supervisor,
        "application_pid": owner.application_pid, "sdk_pid": None if launch.intent.plain else owner.application_pid,
        "application_exit_code": 0, "interrupted_by": None, "inputs_rechecked": True,
        "sdk_health": health, "failures": {}, "source_complete": False, "downstream_receipt": "unavailable"}
    private(launch.intent.runtime / "go-execution.json", result)
    return result


class GoExecutionTests(unittest.TestCase):
    def setUp(self):
        self.fixture, self.launch = preparation(self)
        self.owner = execution.Owner(101, 202, 303, tuple(self.fixture.response["command"]))
        self.supervisor, self.application = starts(self.launch, self.owner)

    def test_pre_call_owner_and_same_native_sdk_completion_are_independent(self):
        with patch("subprocess.run", side_effect=AssertionError("reader executed a command")), \
                patch("subprocess.Popen", side_effect=AssertionError("reader launched target")):
            started = execution.bind(self.launch, self.owner)
            value = completion(self.launch, self.owner, self.supervisor)
            checked = execution.finish(started, 0)
            checked.verify()
        self.assertEqual(checked.value, value)
        self.assertEqual(checked.value["sdk_pid"], self.owner.application_pid)
        self.assertEqual(checked.health["probe_accounting"]["objects_pending"], "2")

    def test_missing_pre_call_binding_cannot_be_replaced_by_completed_records(self):
        completion(self.launch, self.owner, self.supervisor)
        with self.assertRaisesRegex(ValueError, "completed before binding"):
            execution.bind(self.launch, self.owner)

    def test_host_pid_one_binds_and_completes_both_lanes(self):
        for plain in (False, True):
            with self.subTest(plain=plain):
                _, launch = preparation(self, plain=plain)
                owner = replace(self.owner, parent_pid=1, command=tuple(launch.response["command"]))
                supervisor, _ = starts(launch, owner)
                started = execution.bind(launch, owner)
                completion(launch, owner, supervisor)
                checked = execution.finish(started, 0)
                checked.verify()
                self.assertEqual(checked.value["supervisor"]["parent_pid"], 1)

    def test_invalid_caller_pid_command_and_supervisor_exit_refuse(self):
        for owner in (replace(self.owner, pid=True), replace(self.owner, application_pid=303.0),
                      replace(self.owner, pid=1), replace(self.owner, application_pid=1),
                      *(replace(self.owner, parent_pid=value) for value in (True, 1.0, 0, -1, 0x80000000)),
                      replace(self.owner, parent_pid=101), replace(self.owner, application_pid=101),
                      replace(self.owner, command=(Path("/never-executed"),)),
                      replace(self.owner, command=("/never-executed",))):
            with self.subTest(owner=owner), self.assertRaises(ValueError):
                execution.bind(self.launch, owner)
        started = execution.bind(self.launch, self.owner)
        for code in (None, False, 0.0, 1, -15):
            with self.subTest(code=code), self.assertRaises(ValueError):
                execution.finish(started, code)

    def test_rehashed_start_records_cannot_choose_other_identities_or_binary(self):
        for name, original, key, value in (
                (execution.START_FILES[0], self.supervisor, "schema_version", True),
                (execution.START_FILES[0], self.supervisor, "parent_pid", 909),
                (execution.START_FILES[0], self.supervisor, "request_sha256", "a" * 64),
                (execution.START_FILES[1], self.application, "pid", 303.0),
                (execution.START_FILES[1], self.application, "process_group", 909),
                (execution.START_FILES[1], self.application, "argv", ["/never-executed"]),
                (execution.START_FILES[1], self.application, "binary", {}),
                (execution.START_FILES[1], self.application, "unknown", True)):
            private(self.launch.intent.runtime / name, {**original, key: value})
            with self.subTest(name=name, key=key), self.assertRaises(ValueError):
                execution.bind(self.launch, self.owner)
            private(self.launch.intent.runtime / name, original)

    def test_changed_start_file_or_accepted_data_cannot_reuse_binding(self):
        started = execution.bind(self.launch, self.owner)
        started.evidence["unknown"] = ({}, ())
        with self.assertRaisesRegex(ValueError, "start metadata changed"):
            started.verify()
        started = execution.bind(self.launch, self.owner)
        private(self.launch.intent.runtime / execution.START_FILES[0], {**self.supervisor, "parent_pid": 909})
        with self.assertRaises(ValueError):
            started.verify()

    def test_completion_pid_lane_exit_failure_and_closed_fields_must_all_match(self):
        started = execution.bind(self.launch, self.owner)
        original = completion(self.launch, self.owner, self.supervisor)
        for key, value in (("schema_version", True), ("profile", "other"), ("launch_id", "f" * 32),
                           ("application_pid", 909), ("sdk_pid", 303.0), ("application_exit_code", False),
                           ("application_exit_code", 1), ("interrupted_by", 15), ("inputs_rechecked", 1),
                           ("failures", {"execution": "failed"}), ("sdk_health", None),
                           ("source_complete", 0), ("downstream_receipt", "confirmed"), ("unknown", 1)):
            private(self.launch.intent.runtime / "go-execution.json", {**original, key: value})
            with self.subTest(key=key, value=value), self.assertRaises(ValueError):
                execution.finish(started, 0)

    def test_final_health_must_be_direct_exact_and_completed(self):
        started = execution.bind(self.launch, self.owner)
        original = completion(self.launch, self.owner, self.supervisor)
        for key, value in (("phase", "running"), ("pid", 909), ("policy_sha256", "a" * 64),
                           ("selection_sha256", "a" * 64), ("lifecycle", {"flush": "failed", "shutdown": "succeeded"})):
            changed = {**original["sdk_health"], key: value}
            private(self.launch.intent.runtime / "health.json", changed)
            private(self.launch.intent.runtime / "go-execution.json", {**original, "sdk_health": changed})
            with self.subTest(key=key), self.assertRaises(ValueError):
                execution.finish(started, 0)
        private(self.launch.intent.runtime / "health.json", original["sdk_health"])
        private(self.launch.intent.runtime / "go-execution.json", original)
        execution.finish(started, 0).verify()

    def test_accepted_completion_dictionaries_and_original_files_remain_bound(self):
        started = execution.bind(self.launch, self.owner)
        completion(self.launch, self.owner, self.supervisor)
        checked = execution.finish(started, 0)
        for target, key, value in ((checked.value, "sdk_pid", 909), (checked.health, "pid", 909),
                                   (checked.evidence, "unknown", ({}, ()))):
            before = copy.deepcopy(target)
            target[key] = value
            with self.assertRaisesRegex(ValueError, "completion metadata changed"):
                checked.verify()
            target.clear(); target.update(before)
        path = self.launch.intent.runtime / "go-execution.json"
        path.write_bytes(path.read_bytes() + b" ")
        with self.assertRaises(ValueError):
            checked.verify()

    def test_plain_execution_cannot_invent_sdk_identity_or_health(self):
        _, launch = preparation(self, plain=True)
        owner = replace(self.owner, command=tuple(launch.response["command"]))
        supervisor, _ = starts(launch, owner)
        started = execution.bind(launch, owner)
        completion(launch, owner, supervisor)
        self.assertIsNone(execution.finish(started, 0).health)
        private(launch.intent.runtime / "control.json", {})
        with self.assertRaisesRegex(ValueError, "plain Go execution"):
            execution.finish(started, 0)


if __name__ == "__main__":
    unittest.main()
