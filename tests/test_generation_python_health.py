"""Final health cannot replace actual receipt or erase unknown dimensions."""

import copy
import hashlib
import json
from pathlib import Path
import sys
import tempfile
import unittest

REPO = Path(__file__).resolve().parents[1]
sys.path[:0] = [str(REPO / "adapters/generation"), str(REPO / "examples")]
import python_execution
import python_health as health
from test_generation_python_execution import APP, SDK, TOKEN, fixture as execution_fixture, write


def fixture(root: Path) -> tuple:
    """Use the published final schema, not production view-building helpers."""
    intent, launch, owner, catalogue = execution_fixture(root)
    execution = python_execution.read(intent, launch, owner, catalogue)
    digest = hashlib.sha256(json.dumps(intent.policy, sort_keys=True, separators=(",", ":")).encode()).hexdigest()
    application = {"pid": APP, "launch_id": TOKEN, "function_completions": 1, "active_functions": 0,
                   "runtime_losses": {"incomplete": 0}, "handoff": {"attempted": 4, "accepted": 4, "lost": 0, "deadline_ms": 50.0},
                   "span_observation": {"sampled_started": 1, "sampled_ended": 1, "handed_off": 1}}
    sdk = {"schema_version": 1, "kind": "otelc.python.sdk", "pid": APP, "sdk_pid": SDK,
           "launch_id": TOKEN, "policy_sha256": digest, "phase": "closed", "sdk_phase": "closed",
           "collection": True, "emission": True, "effective_emission_off": False, "closed": True,
           "shutdown_complete": True, "shutdown_failed": False, "shutdown_completed": True,
           "export_started": 1, "export_succeeded": 1, "export_failed": 0, "in_flight_exports": 0,
           "flush_started": 0, "flush_failed": 0, "in_flight_flushes": 0,
           "metric_collection": {"started": 1, "succeeded": 1, "failed": 0, "pending": 0, "closed": True,
                                 "shutdown_complete": True, "shutdown_failed": False},
           "traces": {"closed": True, "started": 1, "succeeded": 1, "failed": 0, "pending": 0,
                      "started_items": 1, "exported_items": 1, "failed_items": 0, "pending_items": 0},
           "span_accounting": {"received": 1, "sdk_exported": 1, "queue_pending": 0, "queue_dropped": 0,
                               "queue_evidence": "derived_after_shutdown", "downstream_receipt": "unavailable",
                               "otlp_partial_rejection": "unavailable"},
           "handoff_received": 5, "handoff_incomplete": 0, "producer_checkpoint_available": True,
           "producer": application, "protocol_errors": 0, "operation_failures": 0, "operation_pending": False, "reply_lost": 0}
    report = {"schema_version": 2, "kind": "otelc.runtime-health", "language": "python", "scope": "application_sdk_pair",
              "pid": APP, "sdk_pid": SDK, "launch_id": TOKEN, "policy_sha256": digest, "phase": "final", "sdk_attached": True,
              "lifecycle": {"flush": "unavailable", "shutdown": "succeeded"},
              "metric_flush": {"scope": "exporter", "attempts": "0", "failed_attempts": "0"},
              "span_accounting": {"processors_observed": 1, "batch_processors_observed": 1,
                                  "sampled_started": "1", "sampled_ended": "1", "sampled_active": "0",
                                  "queue_pending": "0", "queue_dropped": "0", "queue_evidence": "derived_after_shutdown"},
              "trace_exports": {"exporters_observed": 1, "unit": "spans", "batches_started": "1", "batches_succeeded": "1",
                                "batches_failed": "0", "batches_pending": "0", "units_started": "1",
                                "units_succeeded": "1", "units_failed": "0"},
              "metric_exports": {"exporters_observed": 1, "unit": "metric_points", "batches_started": "1", "batches_succeeded": "1",
                                 "batches_failed": "0", "batches_pending": "0", "units_started": None,
                                 "units_succeeded": None, "units_failed": None},
              "downstream_receipt": "unavailable", "otlp_partial_rejection": "unavailable", "source_complete": False,
              "application_exit": 0, "sdk_exit": 0, "failures": {}, "application": copy.deepcopy(application), "sdk": copy.deepcopy(sdk)}
    receipt = {"trace_batches": 1, "spans": 1, "metric_batches": 1, "metric_points": 2}
    return intent.runtime, report, sdk, execution, digest, receipt


class PythonHealthTests(unittest.TestCase):
    def test_final_report_matches_separate_sdk_and_receipt_without_inventing_unknown_units(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            runtime, report, sdk, execution, digest, receipt = fixture(Path(temporary))
            value = health.qualify(report, sdk, execution, digest, receipt)
            self.assertEqual(value, {"pid": APP, "sdk_pid": SDK, "launch_id": TOKEN, "received": receipt,
                                    "runtime_losses": {"incomplete": 0}, "pending": 0, "aggregate_flush": "unavailable",
                                    "sdk_metric_points": None, "source_origin": "unavailable"})
            write(runtime / "health.json", report)
            write(runtime / "sdk/python-sdk-status.json", sdk)
            self.assertEqual(health.read(runtime, execution, digest, receipt), value)
            # Successful empty collection cycles need not produce an export batch.
            sdk["metric_collection"].update(started=2, succeeded=2)
            report["sdk"] = copy.deepcopy(sdk)
            health.qualify(report, sdk, execution, digest, receipt)

    def test_policy_digest_uses_sdk_compact_bytes_without_prepared_terminal_newline(self) -> None:
        policy = {"z": False, "a": {"value": "literal"}}
        self.assertEqual(health.policy_digest(policy), hashlib.sha256(b'{"a":{"value":"literal"},"z":false}').hexdigest())
        with self.assertRaises(ValueError):
            health.policy_digest({"value": float("nan")})

    def test_missing_unknown_or_noninteger_receipt_dimensions_cannot_establish_health(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            _, report, sdk, execution, digest, receipt = fixture(Path(temporary))
            invalid = [None, [], {}, {**receipt, "extra": 0}]
            for key in receipt:
                invalid.append({name: value for name, value in receipt.items() if name != key})
                invalid.extend({**receipt, key: value} for value in (0, None, True, -1, "1", 1.0, 2 ** 64))
            for candidate in invalid:
                with self.subTest(receipt=candidate), self.assertRaises(ValueError):
                    health.qualify(report, sdk, execution, digest, candidate)
            for candidate in (None, "", "A" * 64, "a" * 63):
                with self.subTest(digest=candidate), self.assertRaises(ValueError):
                    health.qualify(report, sdk, execution, candidate, receipt)
            with self.assertRaises(ValueError):
                health.qualify(report, sdk, None, digest, receipt)

    def test_sdk_schema_identity_and_every_final_control_flag_are_checked(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            _, report, sdk, execution, digest, receipt = fixture(Path(temporary))
            invalid = [None, [], {}, {**sdk, "extra": 1}]
            for key in sdk:
                invalid.append({name: value for name, value in sdk.items() if name != key})
            for key, value in (("schema_version", True), ("kind", "other"), ("pid", APP + 1), ("sdk_pid", SDK + 1),
                               ("launch_id", "c" * 32), ("policy_sha256", "d" * 64), ("phase", "failed"), ("sdk_phase", "closing")):
                invalid.append({**sdk, key: value})
            for key in ("collection", "emission", "closed", "shutdown_complete", "shutdown_completed", "producer_checkpoint_available",
                        "effective_emission_off", "shutdown_failed", "operation_pending"):
                invalid.extend({**sdk, key: value} for value in (None, int(sdk[key]), not sdk[key]))
            for candidate in invalid:
                with self.subTest(sdk=candidate), self.assertRaises(ValueError):
                    health.qualify(report, candidate, execution, digest, receipt)

    def test_failure_pending_and_unknown_top_level_sdk_counters_never_become_zero(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            _, report, sdk, execution, digest, receipt = fixture(Path(temporary))
            names = ("export_started", "export_succeeded", "export_failed", "in_flight_exports", "in_flight_flushes",
                     "flush_started", "flush_failed", "handoff_received", "handoff_incomplete", "protocol_errors", "operation_failures", "reply_lost")
            for name in names:
                variants = [None, True, -1, 1.0, "0", 2 ** 64]
                if name != "flush_started":
                    variants.append(sdk[name] + 1)
                for value in variants:
                    changed = {**sdk, name: value}
                    with self.subTest(name=name, value=value), self.assertRaises(ValueError):
                        health.qualify(report, changed, execution, digest, receipt)
            self.assertEqual(health.count(2 ** 64 - 1, "maximum"), 2 ** 64 - 1)

    def test_application_identity_active_calls_losses_handoff_and_span_totals_are_checked(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            _, report, sdk, execution, digest, receipt = fixture(Path(temporary))
            original = sdk["producer"]
            invalid = [None, {}, {**original, "lifetimes": {}}]
            for key, value in (("pid", APP + 1), ("launch_id", "c" * 32), ("function_completions", 0),
                               ("active_functions", 1), ("runtime_losses", {}), ("runtime_losses", {"incomplete": None}),
                               ("runtime_losses", {"incomplete": 0, "capture": 1}),
                               ("runtime_losses", {"incomplete": 0, "": 0}),
                               ("runtime_losses", {"incomplete": 0, **dict.fromkeys(map(str, range(33)), 0)})):
                invalid.append({**original, key: value})
            for key, value in (("attempted", 5), ("accepted", 3), ("lost", 1), ("deadline_ms", True),
                               ("deadline_ms", None), ("deadline_ms", float("inf")), ("deadline_ms", float("nan")),
                               ("deadline_ms", 10 ** 1000), ("deadline_ms", 49)):
                invalid.append({**original, "handoff": {**original["handoff"], key: value}})
            for key in original["span_observation"]:
                invalid.append({**original, "span_observation": {**original["span_observation"], key: 0}})
            for candidate in invalid:
                with self.subTest(producer=str(candidate)[:160]), self.assertRaises(ValueError):
                    health.qualify(report, {**sdk, "producer": candidate}, execution, digest, receipt)

    def test_trace_collection_and_queue_dimensions_require_complete_final_accounting(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            _, report, sdk, execution, digest, receipt = fixture(Path(temporary))
            for section in ("traces", "metric_collection", "span_accounting"):
                original = sdk[section]
                invalid = [None, {}, {**original, "extra": 0}]
                for key, value in original.items():
                    changed = (not value if type(value) is bool else value + 1 if type(value) is int else "other")
                    invalid.append({**original, key: changed})
                    if type(value) is int:
                        invalid.append({**original, key: None})
                for candidate in invalid:
                    with self.subTest(section=section, candidate=candidate), self.assertRaises(ValueError):
                        health.qualify(report, {**sdk, section: candidate}, execution, digest, receipt)

    def test_public_view_cannot_rewrite_raw_sdk_unknowns_outcomes_or_loss_counters(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            _, report, sdk, execution, digest, receipt = fixture(Path(temporary))
            invalid = [None, {}, {**report, "extra": 0}]
            for key, value in (("source_complete", True), ("sdk_attached", 1), ("application_exit", True), ("sdk_exit", 7),
                               ("downstream_receipt", "succeeded"), ("otlp_partial_rejection", "0"),
                               ("lifecycle", {"flush": "succeeded", "shutdown": "succeeded"}), ("sdk", {}), ("application", {})):
                invalid.append({**report, key: value})
            for section, key, value in (("metric_exports", "units_succeeded", "2"), ("trace_exports", "units_succeeded", "01"),
                                        ("span_accounting", "queue_pending", 0), ("metric_flush", "attempts", None)):
                invalid.append({**report, section: {**report[section], key: value}})
            for candidate in invalid:
                with self.subTest(report=candidate), self.assertRaises(ValueError):
                    health.qualify(candidate, sdk, execution, digest, receipt)

    def test_direct_sdk_report_file_has_independent_private_file_guards(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            runtime, report, sdk, execution, digest, receipt = fixture(Path(temporary))
            write(runtime / "health.json", report)
            path = runtime / "sdk/python-sdk-status.json"
            write(path, sdk)
            path.chmod(0o644)
            with self.assertRaises(ValueError):
                health.read(runtime, execution, digest, receipt)
