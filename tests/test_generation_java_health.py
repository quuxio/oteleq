"""Consumer health validation never turns missing evidence or receipt into zero."""
import copy
import json
import os
from pathlib import Path
import sys
import tempfile
import unittest

REPO = Path(__file__).resolve().parents[1]
sys.path[:0] = [str(REPO / "adapters/generation"), str(REPO / "examples")]
import java_health


def report() -> dict:
    def exported(unit, batches, units):
        return {"exporters_observed": 1, "unit": unit, "batches_started": str(batches),
                "batches_succeeded": str(batches), "batches_failed": "0", "batches_pending": "0",
                "units_started": str(units), "units_succeeded": str(units), "units_failed": "0"}
    return {"schema_version": 1, "kind": "otelc.runtime-health", "language": "java", "pid": 123,
            "policy_sha256": "a" * 64, "selection_sha256": "b" * 64, "scope": "sdk_pipeline",
            "phase": "final", "sdk_attached": True, "lifecycle": {"flush": "succeeded", "shutdown": "succeeded"},
            "metric_flush": {"attempts": "1", "failed_attempts": "0"},
            "span_accounting": {"processors_observed": 1, "batch_processors_observed": 1,
                                "sampled_started": "1", "sampled_ended": "1", "sampled_active": "0",
                                "queue_pending": "0", "queue_dropped": "0", "queue_evidence": "derived_after_shutdown"},
            "trace_exports": exported("spans", 1, 1), "metric_exports": exported("metric_points", 2, 12),
            "downstream_receipt": "unavailable", "otlp_partial_rejection": "unavailable"}


def qualify(value: dict, **overrides) -> dict:
    arguments = {"pid": 123, "policy_sha256": "a" * 64, "selection_sha256": "b" * 64,
                 "trace_batches": 1, "spans": 1, "metric_batches": 2, "metric_points": 12}
    return java_health.qualify(value, **{**arguments, **overrides})


class JavaHealthTests(unittest.TestCase):
    def test_exact_receipt_and_retained_successful_retry_history(self):
        self.assertEqual(qualify(report())["pid"], 123)
        retried = report()
        retried["metric_flush"] = {"attempts": "3", "failed_attempts": "2"}
        self.assertEqual(qualify(retried)["metric_flush"], {"attempts": 3, "failed_attempts": 2})
        self.assertEqual(java_health.counter("9007199254740993", "large"), 9007199254740993)

    def test_counter_unknown_boolean_non_ascii_and_noncanonical_values_refuse(self):
        for value in (None, True, 0, -1, "-1", "01", "1.0", "1e2", " 1", "1\n", "\u0661", "1\u0661"):
            with self.subTest(value=value), self.assertRaises(ValueError):
                java_health.counter(value, "counter")

    def test_identity_lifecycle_and_shape_failures_refuse(self):
        edits = (("schema_version", True), ("kind", "other"), ("language", "go"), ("pid", True),
                 ("pid", 124), ("phase", "running"), ("sdk_attached", False), ("policy_sha256", "c" * 64),
                 ("selection_sha256", "c" * 64), ("lifecycle", {"flush": "failed", "shutdown": "succeeded"}),
                 ("metric_flush", {"attempts": "0", "failed_attempts": "0"}),
                 ("metric_flush", {"attempts": "2", "failed_attempts": "0"}),
                 ("metric_flush", {}), ("downstream_receipt", "succeeded"), ("otlp_partial_rejection", "0"))
        for key, value in edits:
            changed = report();changed[key] = value
            with self.subTest(key=key, value=value), self.assertRaises(ValueError): qualify(changed)
        for value in ({}, {**report(), "unknown": 0}):
            with self.assertRaises(ValueError): qualify(value)
        for key, value in (("pid", True), ("policy_sha256", "bad"), ("metric_points", 0), ("spans", True)):
            unchanged = report()
            with self.subTest(key=key), self.assertRaises(ValueError): qualify(unchanged, **{key: value})

    def test_unknown_loss_pending_or_export_count_mismatch_refuses(self):
        for group in ("span_accounting", "trace_exports", "metric_exports"):
            for key, value in list(report()[group].items()):
                changed = copy.deepcopy(report())
                changed[group][key] = True if type(value) is int else None if value == "0" else "0"
                with self.subTest(group=group, key=key), self.assertRaises(ValueError): qualify(changed)
        changed = report();changed["trace_exports"]["extra"] = "0"
        with self.assertRaises(ValueError): qualify(changed)

    def test_private_bounded_regular_report_and_duplicate_json_fields(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary).resolve();root.chmod(0o700)
            path = root / "health.json";path.write_text(json.dumps(report()));path.chmod(0o600)
            self.assertEqual(java_health.read(root), report())
            root.chmod(0o755)
            with self.assertRaises(ValueError): java_health.read(root)
            root.chmod(0o700)
            path.chmod(0o644)
            with self.assertRaises(ValueError): java_health.read(root)
            path.chmod(0o600)
            path.write_bytes(b"x" * 4097)
            with self.assertRaises(ValueError): java_health.read(root)
            path.write_text('{"pid":123,"pid":123}')
            with self.assertRaises(ValueError): java_health.read(root)
            path.unlink();path.symlink_to(root / "missing")
            with self.assertRaises(OSError): java_health.read(root)
            path.unlink();os.mkfifo(path, 0o600)
            with self.assertRaises(ValueError): java_health.read(root)

    def test_directory_refusals_do_not_leak_file_descriptors(self):
        descriptors = Path("/proc/self/fd") if Path("/proc/self/fd").is_dir() else Path("/dev/fd")
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary).resolve();root.chmod(0o700)
            (root / "health.json").mkdir(mode=0o700)
            before = len(list(descriptors.iterdir()))
            for _ in range(20):
                with self.assertRaises(ValueError):java_health.read(root)
            self.assertEqual(len(list(descriptors.iterdir())), before)


if __name__ == "__main__":
    unittest.main()
