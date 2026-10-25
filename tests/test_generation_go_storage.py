"""Storage refusal interrupts real owned processes without filling the disk."""

import json
import os
from pathlib import Path
import sys
import tempfile
from types import SimpleNamespace
import unittest
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "adapters/generation"))
import generation
import go_storage


class GoStorageTests(unittest.TestCase):
    def setUp(self):
        temporary = tempfile.TemporaryDirectory()
        self.addCleanup(temporary.cleanup)
        self.folder = Path(temporary.name).resolve()
        self.process = SimpleNamespace(pid=123)

    def test_budget_requires_a_bounded_nonnegative_integer(self):
        for value in (0, 1, 2 ** 63 - 1):
            self.assertEqual(go_storage.minimum(value), value)
        for value in (None, True, False, -1, 1.5, "10", 2 ** 63):
            with self.subTest(value=value), self.assertRaisesRegex(ValueError, "build_min_free_bytes"):
                go_storage.minimum(value)

    def test_disabled_budget_does_not_measure_or_write(self):
        with patch.object(go_storage.shutil, "disk_usage") as usage:
            guard = go_storage.Guard(self.folder, 0)
            guard.poll(self.process, 100)
            guard.finish(self.process)
        usage.assert_not_called()
        self.assertEqual(list(self.folder.iterdir()), [])

    def test_preflight_refuses_before_launch_and_retains_the_actual_measurement(self):
        with patch.object(go_storage.shutil, "disk_usage", return_value=SimpleNamespace(free=9)), \
                self.assertRaisesRegex(ValueError, "storage headroom exhausted"):
            go_storage.Guard(self.folder, 10)
        self.assertEqual(json.loads((self.folder / "storage-refusal.json").read_text()), {
            "schema_version": 1, "kind": "oteleq.go.build-storage-refusal", "phase": "before_start",
            "directory": str(self.folder), "minimum_free_bytes": 10, "observed_free_bytes": 9,
            "process_started": False, "pid": None})

    def test_periodic_checks_are_throttled_and_include_the_floor(self):
        with patch.object(go_storage.shutil, "disk_usage", return_value=SimpleNamespace(free=10)) as usage, \
                patch.object(go_storage.time, "monotonic", side_effect=(1.0, 1.01, 1.1)):
            guard = go_storage.Guard(self.folder, 10)
            for _ in range(3):
                guard.poll(self.process, 100)
            guard.finish(self.process)
        self.assertEqual(usage.call_count, 4)
        self.assertFalse((self.folder / "storage-refusal.json").exists())

    def test_fast_completed_command_still_refuses_low_space(self):
        with patch.object(go_storage.shutil, "disk_usage", side_effect=(SimpleNamespace(free=10), SimpleNamespace(free=9))):
            guard = go_storage.Guard(self.folder, 10)
            with self.assertRaisesRegex(ValueError, "storage headroom exhausted"):
                guard.finish(self.process)
        receipt = json.loads((self.folder / "storage-refusal.json").read_text())
        self.assertEqual((receipt["phase"], receipt["pid"], receipt["process_started"]), ("after_exit", 123, True))

    def test_measurement_errors_refuse_instead_of_assuming_headroom(self):
        with patch.object(go_storage.shutil, "disk_usage", side_effect=OSError("unavailable volume")), \
                self.assertRaisesRegex(OSError, "unavailable volume"):
            go_storage.Guard(self.folder, 10)

    def test_running_refusal_cleans_actual_leader_and_descendant_and_keeps_channels(self):
        ready = self.folder / "ready.json"
        script = ("import json,os,pathlib,subprocess,sys,time\n"
                  "child=subprocess.Popen([sys.executable,'-c','import time; time.sleep(60)'])\n"
                  "ready=pathlib.Path(sys.argv[1]); pending=ready.with_suffix('.pending')\n"
                  "pending.write_text(json.dumps([os.getpid(),child.pid]))\n"
                  "print('compiler channel before refusal',flush=True)\n"
                  "pending.rename(ready)\n"
                  "time.sleep(60)\n")
        def usage(path):
            self.assertEqual(path, self.folder)
            return SimpleNamespace(free=0 if ready.exists() else 10)
        with patch.object(go_storage.shutil, "disk_usage", side_effect=usage):
            guard = go_storage.Guard(self.folder, 1)
            with self.assertRaisesRegex(ValueError, "storage headroom exhausted"):
                generation.execute([sys.executable, "-c", script, ready], self.folder,
                    dict(os.environ), self.folder, timeout=10, record_process=True, interaction=guard)
        leader, child = json.loads(ready.read_text())
        self.assertFalse(generation.live_process_group(leader))
        with self.assertRaises(ProcessLookupError):
            os.kill(leader, 0)
        self.assertNotEqual(leader, child)
        receipt = json.loads((self.folder / "storage-refusal.json").read_text())
        self.assertEqual((receipt["phase"], receipt["pid"], receipt["process_started"]), ("running", leader, True))
        self.assertIn(b"compiler channel before refusal", (self.folder / "stdout").read_bytes())
        self.assertTrue((self.folder / "stderr").is_file())


if __name__ == "__main__":
    unittest.main()
