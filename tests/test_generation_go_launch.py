"""Owned Go calls cannot run until private readiness and actual kernel PIDs agree."""

import copy
from dataclasses import replace
import json
import os
from pathlib import Path
import subprocess
import sys
import time
from types import SimpleNamespace
import unittest
from unittest.mock import patch

REPO = Path(__file__).resolve().parents[1]
sys.path[:0] = [str(REPO / "adapters/generation"), str(REPO / "examples")]
import go_execution as execution
import go_launch as launch
from test_generation_go_execution import completion, preparation, starts
from test_generation_go_prepared import private


class GoOwnedLaunchTests(unittest.TestCase):
    def setUp(self):
        self.fixture, self.prepared = preparation(self)
        self.session = launch.Session(self.prepared, wait_ms=5000)
        self.pid, self.app = os.getpid() + 100, os.getpid() + 200
        self.process = SimpleNamespace(pid=self.pid, args=list(self.prepared.response["command"]), returncode=None)
        self.process.poll = lambda: self.process.returncode
        self.owner = execution.Owner(self.pid, os.getpid(), self.app, tuple(self.process.args))
        self.supervisor, _ = starts(self.prepared, self.owner)
        self.kernel = [{"pid": self.pid, "parent_pid": os.getpid(), "process_group": self.pid},
                       {"pid": self.app, "parent_pid": self.pid, "process_group": self.pid}]
        self.message = {"schema_version": 1, "kind": "oteleq.go.ready", "token": self.session.binding.token,
                        "pid": self.app, "parent_pid": self.pid}

    def ready(self, value=None):
        root = self.session.binding.root
        private(root / "start.tmp", self.message if value is None else value)
        os.link(root / "start.tmp", root / "start.ready")

    def poll(self, values=None):
        with patch.object(launch, "kernel", side_effect=self.kernel if values is None else values):
            self.session.poll(self.process, time.monotonic() + 10)

    def test_worker_is_released_only_after_actual_parent_group_and_prepared_records_match(self):
        self.session.environment()
        self.session.poll(self.process, time.monotonic() + 10)
        self.assertIsNone(self.session.started)
        self.ready()
        self.poll()
        root = self.session.binding.root
        expected = (self.session.binding.token + " release\n").encode()
        self.assertEqual((root / "start.resume").read_bytes(), expected)
        self.assertEqual((root / "start.resume").stat().st_nlink, 2)
        self.assertEqual((root / "start.ready").stat().st_nlink, 2)
        self.poll([])
        completion(self.prepared, self.owner, self.supervisor)
        self.process.returncode = 0
        self.session.finish(self.process)
        self.assertEqual(self.session.execution.value["application_pid"], self.app)
        self.assertEqual(self.session.execution.value["sdk_pid"], self.app)
        self.session.execution.verify()

    def test_normal_early_exit_without_ready_cannot_supply_a_late_pid(self):
        completion(self.prepared, self.owner, self.supervisor)
        self.process.returncode = 0
        with self.assertRaisesRegex(ValueError, "pre-call binding"):
            self.session.finish(self.process)

    def test_simulated_host_pid_one_preserves_owned_child_ready_and_completion(self):
        self.owner = replace(self.owner, parent_pid=1)
        self.supervisor, _ = starts(self.prepared, self.owner)
        self.kernel[0]["parent_pid"] = 1
        self.ready()
        with patch.object(launch.os, "getpid", return_value=1):
            self.poll()
        self.assertEqual(self.session.started.owner.parent_pid, 1)
        self.assertEqual(self.session.kernel_observations["application"]["parent_pid"], self.pid)
        completion(self.prepared, self.owner, self.supervisor)
        self.process.returncode = 0
        self.session.finish(self.process)
        self.assertEqual(self.session.execution.value["supervisor"]["parent_pid"], 1)

    def test_release_that_exists_before_binding_refuses(self):
        launch.private_publish(self.session.binding.root, "start.resume", b"not a host-owned release")
        with self.assertRaisesRegex(ValueError, "released before"):
            self.poll([])

    def test_ready_cannot_choose_another_parent_group_or_stopped_application(self):
        self.ready()
        for field in ("pid", "parent_pid", "process_group"):
            values = copy.deepcopy(self.kernel)
            values[1][field] += 1
            with self.subTest(field=field), self.assertRaisesRegex(ValueError, "live owned"):
                self.poll(values)
        self.process.returncode = 0
        with self.assertRaisesRegex(ValueError, "live owned"):
            self.poll()
        self.assertFalse((self.session.binding.root / "start.resume").exists())

    def test_changed_process_monitor_or_binding_never_releases_work(self):
        self.process.args = ["/never-executed"]
        with self.assertRaisesRegex(ValueError, "another command"):
            self.poll([])
        self.process.args = list(self.prepared.response["command"])
        self.session.binding = replace(self.session.binding, token="f" * 32)
        with self.assertRaisesRegex(ValueError, "caller binding changed"):
            self.session.environment()

    def test_ready_rejects_nonprivate_links_wrong_tokens_coerced_ids_and_unknown_fields(self):
        self.ready()
        path = self.session.binding.root / "start.tmp"
        for value in ({**self.message, "token": "f" * 32}, {**self.message, "pid": float(self.app)},
                      {**self.message, "schema_version": True}, {**self.message, "unknown": 1}, []):
            private(path, value)
            with self.subTest(value=value), self.assertRaises(ValueError):
                self.session.ready()
        private(path, self.message)
        path.chmod(0o644)
        with self.assertRaisesRegex(ValueError, "unsafe Go ready"):
            self.session.ready()
        path.chmod(0o600)
        path.unlink()
        with self.assertRaisesRegex(ValueError, "unsafe Go ready"):
            self.session.ready()

    def test_changed_ready_or_start_data_after_release_refuses_completion(self):
        self.ready(); self.poll()
        self.session.kernel_observations["application"]["pid"] += 1
        with self.assertRaisesRegex(ValueError, "pre-call binding changed"):
            self.session.finish(self.process)

    def test_changed_ready_file_after_release_refuses_completion(self):
        self.ready(); self.poll()
        path = self.session.binding.root / "start.tmp"
        path.write_bytes(path.read_bytes() + b" ")
        with self.assertRaisesRegex(ValueError, "ready checkpoint changed"):
            self.session.finish(self.process)

    def test_same_ready_root_cannot_be_reused_or_substituted(self):
        with self.assertRaises(ValueError):
            launch.Session(self.prepared, wait_ms=True)
        with self.assertRaisesRegex(ValueError, "already used"):
            launch.Session(self.prepared, wait_ms=5000)
        path = self.session.binding.root
        path.chmod(0o755)
        with self.assertRaises(ValueError):
            self.session.environment()

    def test_kernel_query_uses_fixed_argv_and_refuses_inexact_or_foreign_output(self):
        good = subprocess.CompletedProcess([], 0, b"101 202 101\n", b"")
        deadline = time.monotonic() + 60
        with patch.object(launch.subprocess, "run", return_value=good) as run:
            self.assertEqual(launch.kernel(101, time.monotonic() + 5),
                             {"pid": 101, "parent_pid": 202, "process_group": 101})
            self.assertEqual(run.call_args.args[0], ["/bin/ps", "-p", "101", "-o", "pid=,ppid=,pgid="])
        for value in (b"101 202\n", b"101.0 202 101", b"303 202 101", b"101 0 101", b"101 202 1", b"x" * 300):
            invalid = replace_result(good, value)
            with patch.object(launch.subprocess, "run", return_value=invalid), self.assertRaises(ValueError):
                launch.kernel(101, deadline)
        with self.assertRaises(ValueError):
            launch.kernel(True, deadline)
        with self.assertRaises(ValueError):
            launch.kernel(101, 0.)

    def test_kernel_accepts_exact_parent_pid_one_and_refuses_invalid_boundaries(self):
        good = subprocess.CompletedProcess([], 0, b"101 1 101\n", b"")
        deadline = time.monotonic() + 60
        with patch.object(launch.subprocess, "run", return_value=good):
            self.assertEqual(launch.kernel(101, time.monotonic() + 5),
                             {"pid": 101, "parent_pid": 1, "process_group": 101})
        for value in (b"1 202 101", b"101 -1 101", b"101 1.0 101", b"101 true 101",
                      b"101 01 101", b"101 2147483648 101", b"101 1 1", b"101 1 2147483648"):
            invalid = replace_result(good, value)
            with self.subTest(value=value), patch.object(launch.subprocess, "run", return_value=invalid), \
                    self.assertRaises(ValueError):
                launch.kernel(101, deadline)


def replace_result(result, stdout):
    return subprocess.CompletedProcess(result.args, result.returncode, stdout, result.stderr)


if __name__ == "__main__":
    unittest.main()
