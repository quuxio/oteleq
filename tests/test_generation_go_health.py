"""Independent Go checkpoints cannot replace PID, selection or decoded receipt."""

import copy
import hashlib
import json
import os
from pathlib import Path
import stat
import sys
import tempfile
import unittest
from unittest.mock import patch

REPO = Path(__file__).resolve().parents[1]
sys.path[:0] = [str(REPO / "adapters/generation"), str(REPO / "examples")]
import go_health as health
import go_provider as provider

PID = 2468
POLICY, SELECTION = "a" * 64, "b" * 64
RECEIVED = {"trace_batches": 2, "spans": 3, "metric_batches": 2, "metric_points": 6}


def report() -> dict:
    """Literal published schema with censored objects and separate API counts."""
    return {"schema_version": 4, "kind": "otelc.runtime-health", "language": "go", "scope": "sdk_pipeline",
        "pid": PID, "policy_sha256": POLICY, "selection_sha256": SELECTION, "phase": "final",
        "sdk_attached": True, "source_complete": False,
        "controls": {"schema_version": 1, "pid": PID, "collection": True,
                     "emission": True, "effective_emission_off": False},
        "lifecycle": {"flush": "succeeded", "shutdown": "succeeded"},
        "metric_flush": {"attempts": "4", "failed_attempts": "0"},
        "probe_accounting": {"function_started": "3", "function_ended": "3", "function_active": "0",
            "function_lost": "0", "observer_started": "1", "observer_ended": "1", "observer_active": "0",
            "observer_lost": "0", "unwind_unknown": "0", "object_admitted": "2", "gc_observed": "0",
            "resource_released": "0", "objects_pending": "2", "resources_unreleased": "2",
            "lifetime_lost": "0", "duplicate_objects": "0", "closed": True},
        "metric_exports": {"observed": True, "attempts": "2", "succeeded": "2", "failed": "0", "closed": True},
        "trace_exports": {"observed": True, "attempts": "2", "succeeded": "2", "failed": "0", "closed": True,
                          "exported_spans": "3", "queue_pending": "0", "queue_dropped": "0"},
        "http_spans": {"observed": True, "closed": True, "started": "0", "ended": "0", "active": "0"},
        "downstream_receipt": "unavailable", "otlp_partial_rejection": "unavailable"}


def validate(value: dict, **options) -> dict:
    return health.validate(value, **({"pid": PID, "policy_sha256": POLICY, "selection_sha256": SELECTION} | options))


def qualify(value: dict, **options) -> dict:
    return health.qualify(value, **({"pid": PID, "policy_sha256": POLICY, "selection_sha256": SELECTION,
        "received": RECEIVED, "function_spans": 3, "observer_completions": 1, "received_http_spans": 0} | options))


class GoProviderHealthTests(unittest.TestCase):
    def test_policy_prepared_and_selection_digest_encodings_remain_distinct(self):
        value = {"snow": "\u2603", "number": 1.0, "flag": True}
        policy = b'{"flag": true, "number": 1.0, "snow": "\\u2603"}'
        selection = b'{"flag":true,"number":1.0,"snow":"\\u2603"}'
        self.assertEqual(provider.policy_digest(value), hashlib.sha256(policy).hexdigest())
        self.assertEqual(provider.metadata_digest(value), hashlib.sha256(policy + b"\n").hexdigest())
        self.assertEqual(provider.selection_digest(value), hashlib.sha256(selection).hexdigest())
        self.assertEqual(len({provider.policy_digest(value), provider.metadata_digest(value),
                              provider.selection_digest(value)}), 3)
        self.assertNotEqual(provider.data_seal({"value": True}), provider.data_seal({"value": 1}))
        self.assertNotEqual(provider.data_seal({"value": 1}), provider.data_seal({"value": 1.0}))
        with self.assertRaises(ValueError):
            provider.metadata_digest({"invalid": float("nan")})

    def test_protocol_descriptor_is_closed_and_never_coerces_numbers_or_flags(self):
        descriptor = {"schema_version": 1, "kind": "otelc.go.protocols", "profile": "go-source-v1",
            "build": 4, "config": 2, "request": 1, "plan": 1, "prepared": 1, "command": 1,
            "execution": 1, "health": 4, "embedded_sdk": True, "source_complete": False}
        self.assertEqual(provider.verify_protocols(descriptor), descriptor)
        for key, values in {"schema_version": [True, 1.0], "build": [2, 3, 4.0], "config": [1, 2.0], "request": [True, 2],
                "profile": ["legacy", None], "health": [3, 4.0], "embedded_sdk": [1, False],
                "source_complete": [0, True]}.items():
            for value in values:
                with self.subTest(key=key, value=value), self.assertRaises(ValueError):
                    provider.verify_protocols({**descriptor, key: value})
        for value in (None, [], {**descriptor, "new": 1}, {key: value for key, value in descriptor.items() if key != "plan"}):
            with self.assertRaises(ValueError):
                provider.verify_protocols(value)

    def test_final_counts_bind_actual_pid_selection_and_both_raw_signals(self):
        value = report(); original = copy.deepcopy(value)
        result = qualify(value)
        self.assertEqual(result["pid"], result["sdk_pid"])
        self.assertEqual(result["received"], RECEIVED)
        self.assertEqual(result["probe_accounting"]["objects_pending"], 2)
        self.assertEqual(result["probe_accounting"]["resources_unreleased"], 2)
        self.assertIsNone(result["metric_exported_points"])
        self.assertEqual(result["trace_exports"]["exported_spans"], 3)
        self.assertEqual(value, original)

    def test_raw_live_snapshots_do_not_invent_quiescent_counter_relations(self):
        value = report(); value["phase"] = "running"
        value["probe_accounting"].update(function_started="1", function_ended="2", function_active=str(health.MAX_COUNTER))
        self.assertIs(validate(value), value)
        with self.assertRaises(ValueError):
            qualify(value)

    def test_unobserved_traces_keep_unavailable_data_and_refuse_received_spans(self):
        value = report(); value["trace_exports"] = {"observed": False}
        value["http_spans"] = {"observed": False}
        self.assertIs(validate(value), value)
        with self.assertRaises(ValueError):
            qualify(value)
        value["probe_accounting"].update(function_started="0", function_ended="0")
        result = qualify(value, received={**RECEIVED, "trace_batches": 0, "spans": 0}, function_spans=0)
        self.assertIsNone(result["trace_exports"])
        self.assertIsNone(result["http_spans"])
        for item in ({"observed": False, "queue_pending": "0"}, {"observed": 0}, None):
            value["trace_exports"] = item
            with self.assertRaises(ValueError):
                validate(value)

    def test_http_operation_counts_are_separate_and_require_actual_complete_receipt(self):
        value = report()
        value["http_spans"].update(started="2", ended="2")
        value["trace_exports"]["exported_spans"] = "5"
        result = qualify(value, received={**RECEIVED, "spans": 5}, received_http_spans=2)
        self.assertEqual(result["http_spans"], {"closed": True, "started": 2, "ended": 2, "active": 0})
        self.assertEqual(result["probe_accounting"]["resource_released"], 0)
        self.assertEqual(result["probe_accounting"]["gc_observed"], 0)
        for changes in ({"started": "3"}, {"active": "1"}, {"closed": False}, {"ended": "1"}):
            changed = copy.deepcopy(value); changed["http_spans"].update(changes)
            self.assertIs(validate(changed), changed)
            with self.subTest(changes=changes), self.assertRaisesRegex(ValueError, "HTTP span completions"):
                qualify(changed, received={**RECEIVED, "spans": 5}, received_http_spans=2)
        leaked = report(); leaked["http_spans"].update(started="1", ended="0", active="1")
        with self.assertRaisesRegex(ValueError, "HTTP span completions"):
            qualify(leaked)
        with self.assertRaisesRegex(ValueError, "HTTP receipt exceeds"):
            qualify(value, received_http_spans=4)

    def test_legacy_health_and_invented_or_malformed_http_dimensions_refuse(self):
        value = report(); value["schema_version"] = 3
        with self.assertRaises(ValueError):
            validate(value)
        del value["http_spans"]
        with self.assertRaises(ValueError):
            validate(value)
        for http in ({"observed": False}, {"observed": 1}, {"observed": True},
                     {**report()["http_spans"], "active": 0}, {"observed": False, "active": "0"}):
            value = {**report(), "http_spans": http}
            with self.subTest(http=http), self.assertRaises(ValueError):
                validate(value)
        value = report(); value["trace_exports"] = value["http_spans"] = {"observed": False}
        with self.assertRaisesRegex(ValueError, "without a recording observer"):
            qualify(value, received_http_spans=1)

    def test_runtime_directory_alias_during_read_is_refused(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary).resolve()
            runtime = root / "runtime"; runtime.mkdir(mode=0o700)
            path = runtime / "health.json"; path.write_text(json.dumps(report())); path.chmod(0o600)
            original = health.os.fstat
            replaced = False
            def changed(descriptor):
                nonlocal replaced
                info = original(descriptor)
                if not replaced and stat.S_ISDIR(info.st_mode):
                    replaced = True
                    moved = root / "moved"
                    runtime.rename(moved)
                    runtime.symlink_to(moved, target_is_directory=True)
                return info
            with patch.object(health.os, "fstat", side_effect=changed), self.assertRaisesRegex(ValueError, "runtime changed"):
                health.read(runtime)

    def test_identity_control_and_scope_substitution_refuse(self):
        for key, invalid in (("schema_version", True), ("schema_version", 2), ("language", "java"),
                ("scope", "all_code"), ("kind", None), ("pid", True), ("pid", PID + 1),
                ("sdk_attached", 1), ("source_complete", 0), ("phase", []),
                ("policy_sha256", "c" * 64), ("selection_sha256", "c" * 64),
                ("downstream_receipt", "succeeded"), ("otlp_partial_rejection", "zero")):
            value = {**report(), key: invalid}
            with self.subTest(key=key), self.assertRaises(ValueError):
                validate(value)
        for options in ({"pid": True}, {"pid": 1}, {"policy_sha256": "A" * 64}, {"selection_sha256": None}):
            value = report()
            with self.assertRaises(ValueError):
                validate(value, **options)
        for key, invalid in (("schema_version", True), ("pid", PID + 1), ("collection", 1),
                             ("emission", None), ("effective_emission_off", True)):
            value = report(); value["controls"][key] = invalid
            with self.subTest(key=key), self.assertRaises(ValueError):
                validate(value)

    def test_missing_unknown_and_noncanonical_counters_refuse(self):
        original = report()
        for section in (None, "controls", "lifecycle", "metric_flush", "probe_accounting", "metric_exports", "trace_exports"):
            for key in (original if section is None else original[section]):
                value = report(); del (value if section is None else value[section])[key]
                with self.subTest(section=section, missing=key), self.assertRaises(ValueError):
                    validate(value)
            value = report(); (value if section is None else value[section])["unknown"] = "0"
            with self.assertRaises(ValueError):
                validate(value)
        for section, key in (("probe_accounting", "function_started"), ("metric_flush", "attempts"),
                             ("trace_exports", "exported_spans")):
            for invalid in (None, True, 0, -1, "00", "-1", "+1", "1.0", "1e2", "١", "1١", str(1 << 64)):
                value = report(); value[section][key] = invalid
                with self.subTest(section=section, invalid=invalid), self.assertRaises(ValueError):
                    validate(value)
        for section, key, invalid in (("probe_accounting", "closed", 1), ("metric_exports", "observed", 1),
                                      ("trace_exports", "closed", None), ("lifecycle", "flush", [])):
            value = report(); value[section][key] = invalid
            with self.assertRaises(ValueError):
                validate(value)

    def test_failed_drain_losses_counters_and_receipt_mismatches_refuse(self):
        mutations = [("probe_accounting", name, "1") for name in
            ("function_active", "function_lost", "observer_active", "observer_lost", "unwind_unknown", "lifetime_lost")]
        mutations += [("probe_accounting", "function_ended", "4"), ("probe_accounting", "observer_ended", "2"),
            ("probe_accounting", "closed", False), ("metric_flush", "attempts", "0"),
            ("metric_flush", "failed_attempts", "1"), ("lifecycle", "shutdown", "timed_out"),
            ("metric_exports", "closed", False), ("metric_exports", "failed", "1"),
            ("metric_exports", "attempts", "3"), ("trace_exports", "queue_pending", "1"),
            ("trace_exports", "queue_dropped", "1"), ("trace_exports", "exported_spans", "4")]
        for section, key, invalid in mutations:
            value = report(); value[section][key] = invalid
            with self.subTest(section=section, key=key), self.assertRaises(ValueError):
                qualify(value)
        for options in ({"function_spans": True}, {"observer_completions": -1},
                {"received": {**RECEIVED, "trace_batches": True}}, {"received": {**RECEIVED, "spans": 4}},
                {"received": {**RECEIVED, "metric_batches": 3}}, {"received": {}}):
            value = report()
            with self.assertRaises(ValueError):
                qualify(value, **options)

    def test_private_file_reader_rejects_links_permissions_fifo_and_oversize(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary).resolve(); path = root / "health.json"
            path.write_text(json.dumps(report())); path.chmod(0o600)
            self.assertEqual(health.read(root), report())
            root.chmod(0o755)
            with self.assertRaises(ValueError):
                health.read(root)
            root.chmod(0o700); path.chmod(0o644)
            with self.assertRaises(ValueError):
                health.read(root)
            path.chmod(0o600)
            with patch.object(health, "MAX_REPORT_BYTES", 2), self.assertRaises(ValueError):
                health.read(root)
            alias = root / "alias"; os.link(path, alias)
            with self.assertRaises(ValueError):
                health.read(root)
            alias.unlink(); path.unlink(); path.symlink_to(root / "absent")
            with self.assertRaises(OSError):
                health.read(root)
            path.unlink(); os.mkfifo(path, 0o600)
            with self.assertRaises(ValueError):
                health.read(root)
            path.unlink(); path.write_text('{"schema_version":3,"schema_version":2}'); path.chmod(0o600)
            with self.assertRaises(ValueError):
                health.read(root)
            parent_alias = root / "linked"; parent_alias.symlink_to(root, target_is_directory=True)
            with self.assertRaises(ValueError):
                health.read(parent_alias)

    def test_private_file_replacement_during_read_refuses(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary).resolve(); path = root / "health.json"
            path.write_text(json.dumps(report())); path.chmod(0o600)
            fstat, calls = health.os.fstat, []
            def changed(descriptor):
                value = fstat(descriptor)
                if stat.S_ISREG(value.st_mode):
                    calls.append(descriptor)
                    if len(calls) == 2:
                        path.write_text("{}")
                        value = fstat(descriptor)
                return value
            with patch.object(health.os, "fstat", side_effect=changed), self.assertRaises(ValueError):
                health.read(root)


if __name__ == "__main__":
    unittest.main()
