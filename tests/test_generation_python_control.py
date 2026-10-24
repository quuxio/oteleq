"""Actual checkpoint framing and command-specific Python controls stay closed."""

import copy
import os
from pathlib import Path
import sys
import tempfile
import unittest
from unittest.mock import patch

REPO = Path(__file__).resolve().parents[1]
sys.path[:0] = [str(REPO / "adapters/generation"), str(REPO / "examples")]
import python_checkpoint as checkpoint
import python_control as control
from python_control_fixture import report, status


class PythonControlTests(unittest.TestCase):
    def test_command_specific_replies_keep_missing_fields_and_types_visible(self):
        for command in control.COMMANDS - {"health"}:
            value = status(barrier=command != "flush")
            self.assertEqual(control.status(value, 101, command), value)
            for key in value:
                changed = {name: item for name, item in value.items() if name != key}
                with self.subTest(command=command, key=key), self.assertRaises(ValueError):
                    control.status(changed, 101, command)
        for key, value in (("schema_version", True), ("pid", 102), ("sdk_pid", 101),
                           ("collection", 1), ("active_functions", 1), ("runtime_losses", {"lost": 1}),
                           ("function_completions", False), ("in_flight_exports", -1), ("effective_emission_off", True)):
            with self.subTest(key=key), self.assertRaises(ValueError):
                control.status({**status(), key: value}, 101, "status")

    def test_live_health_reconstructs_the_raw_sdk_and_preserves_unknown_queue_counts(self):
        for collection in (False, True):
            for emission in (False, True):
                value = report(collection=collection, emission=emission)
                self.assertEqual(control.live(value, 101), value)
                self.assertIsNone(value["span_accounting"]["queue_pending"])
        for section, key, changed in ((None, "pid", 103), (None, "source_complete", True),
                (None, "launch_id", "bad"), ("sdk", "export_failed", 1),
                ("sdk", "operation_failures", 1), ("application", "function_completions", 2),
                ("span_accounting", "queue_pending", "0"), ("metric_exports", "units_started", "0"),
                ("sdk", "closed", True), ("application", "lifetime_events_pending", 0)):
            value = copy.deepcopy(report())
            (value if section is None else value[section])[key] = changed
            with self.subTest(section=section, key=key), self.assertRaises(ValueError):
                control.live(value, 101)
        value = report()
        value["sdk"]["traces"]["failed"] = 1
        with self.assertRaises(ValueError):
            control.live(value, 101)

    def test_python_health_uses_the_larger_bounded_frame_and_unsupported_commands_refuse(self):
        with patch.object(control.live_control, "exchange", return_value=report()) as exchange:
            self.assertEqual(control.request(Path("/runtime/control.json"), "health", 101, 99), report())
        self.assertEqual(exchange.call_args.kwargs, {"maximum": 262144})
        with patch.object(control.live_control, "exchange", return_value=status(barrier=False)):
            control.request(Path("/runtime/control.json"), "flush", 101, 99)
        with self.assertRaises(ValueError):
            control.request(Path("/runtime/control.json"), "on", 101, 99)

    def test_worker_publishes_complete_private_markers_and_yields_until_acknowledged(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary).resolve()
            env = {checkpoint.ROOT_ENV: str(root), checkpoint.TOKEN_ENV: "a" * 32}
            message = ("a" * 32 + " before-0\n").encode()
            def host(_):
                self.assertEqual((root / "before-0.ready").read_bytes(), message)
                self.assertEqual((root / "before-0.ready").stat().st_mode & 0o777, 0o600)
                resume = root / "before-0.resume"
                resume.write_bytes(message)
                resume.chmod(0o600)
            with patch.dict(os.environ, env), patch.object(checkpoint.time, "sleep", side_effect=host) as pause:
                checkpoint.checkpoint("before-0")
            self.assertEqual(pause.call_count, 1)
            self.assertEqual({p.name for p in root.iterdir()}, {"before-0.ready", "before-0.resume"})
            with patch.dict(os.environ, env), self.assertRaises(FileExistsError):
                checkpoint.checkpoint("before-0")

    def test_worker_refuses_invalid_bindings_and_nonprivate_or_changed_acknowledgements(self):
        for phase in (None, "before-32", "after--1", "before-00", "../finish"):
            with self.subTest(phase=phase), self.assertRaises(ValueError):
                checkpoint.checkpoint(phase)
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary).resolve()
            env = {checkpoint.ROOT_ENV: str(root), checkpoint.TOKEN_ENV: "a" * 32}
            for token in ("bad", "A" * 32):
                with patch.dict(os.environ, {**env, checkpoint.TOKEN_ENV: token}), self.assertRaises(ValueError):
                    checkpoint.checkpoint("finish")
            root.chmod(0o755)
            with patch.dict(os.environ, env), self.assertRaises(ValueError):
                checkpoint.checkpoint("finish")
            root.chmod(0o700)
            resume = root / "finish.resume"
            for data, mode in ((b"wrong", 0o600), (b"expected", 0o644)):
                resume.write_bytes(data)
                resume.chmod(mode)
                with self.assertRaises(ValueError):
                    checkpoint.read_resume(resume, b"expected")
            resume.unlink()
            self.assertFalse(checkpoint.read_resume(resume, b"expected"))


if __name__ == "__main__":
    unittest.main()
