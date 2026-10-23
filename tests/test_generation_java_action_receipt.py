"""Decoded action trees cannot be replaced by names, acknowledgements or counts."""

import copy
import dataclasses
from pathlib import Path
import sys
import unittest
from unittest.mock import patch

from opentelemetry.proto.collector.trace.v1.trace_service_pb2 import ExportTraceServiceRequest

REPO = Path(__file__).resolve().parents[1]
sys.path[:0] = [str(REPO / "adapters/generation"), str(REPO / "examples"), str(REPO / "tests")]
import java_action_receipt as receipt
import java_witness
from test_generation_java_witness import final_report, identity

SERVICE = "independent-action-fixture"
TARGET = receipt.Target("Work", "target")


def expected(**changes):
    values = {"action_id": "9" * 64, "case_id": "e" * 64, "attempt_id": "f" * 64,
              "thread_id": "41", "cookie": "c" * 32, "sequence": "1", "scope_id": "d" * 32,
              "failed": False}
    return receipt.Action(**{**values, **changes})


def fixture(*, recursive=False, failed=False):
    report = final_report()
    scope = report["scopes"][0]
    ids = ["2" * 16, "3" * 16, "4" * 16] + (["5" * 16, "6" * 16] if recursive else [])
    for key in ("started_ids", "ended_ids", "exported_ids"):scope[key] = ids.copy()
    scope["target_entries"] = "2" if recursive else "1"
    message = ExportTraceServiceRequest()
    resource = message.resource_spans.add()
    for key, value in (("service.name", SERVICE), ("otelc.language", "java")):
        attribute = resource.resource.attributes.add();attribute.key = key;attribute.value.string_value = value
    roles = resource.scope_spans.add();roles.scope.name, roles.scope.version = receipt.ROLE_SCOPE
    methods = resource.scope_spans.add();methods.scope.name, methods.scope.version = receipt.telemetry.METHOD_SCOPE
    header = report["producer"]
    common = {"scope_id": "d" * 32, "runtime_id": "b" * 32, "context_cookie": "c" * 32,
              "case_id": "e" * 64, "attempt_id": "f" * 64,
              **{key: header[key] for key in ("build_sha256", "selection_sha256", "policy_sha256", "tooling_sha256")}}

    def add(group, span_id, parent, role, start, end):
        span = group.spans.add()
        span.trace_id = bytes.fromhex("1" * 32);span.span_id = bytes.fromhex(span_id * 16)
        span.parent_span_id = bytes.fromhex(parent * 16) if parent else b""
        span.start_time_unix_nano, span.end_time_unix_nano, span.kind = start, end, 1
        span.status.code = 2 if failed else 0
        attributes = {"otelc.witness." + key: value for key, value in common.items()}
        if role is not None:
            probe = "wrapper" if role == "wrapper" else "target"
            span.name = "otelc.action." + probe
            attributes.update({receipt.ROLE: role, receipt.PROBE: header[probe + "_probe_id"]})
        else:
            span.name = "Work.target"
            attributes.update({"code.namespace": "Work", "code.function": "target"})
        for key, value in attributes.items():
            entry = span.attributes.add();entry.key = key;entry.value.string_value = value
        return span

    add(roles, "2", "", "wrapper", 10, 1000)
    add(roles, "3", "2", "target", 20, 900)
    add(methods, "4", "3", None, 30, 800)
    if recursive:
        add(roles, "5", "4", "recursive_target", 40, 700)
        add(methods, "6", "5", None, 50, 600)
    return report, message


def qualify(report, message, *, actions=None, target=TARGET, bodies=None):
    return receipt.qualify(report, identity(), [expected()] if actions is None else actions, target,
                           [("/v1/traces", message.SerializeToString())] if bodies is None else bodies,
                           service=SERVICE, decoder=ExportTraceServiceRequest.FromString)


def attribute(span, name):
    return next(item.value for item in span.attributes if item.key == name)


class JavaActionReceiptTests(unittest.TestCase):
    def test_exact_return_recursion_exception_and_recovered_flush_history(self):
        for recursive in (False, True):
            for failed in (False, True):
                with self.subTest(recursive=recursive, failed=failed):
                    report, message = fixture(recursive=recursive, failed=failed)
                    report["scopes"][0]["flush_failures"] = "1"
                    value = qualify(report, message, actions=[expected(failed=failed)])
                    self.assertEqual(value["pid"], 123)
                    self.assertEqual(value["scoped_spans"], 5 if recursive else 3)
                    self.assertEqual(value["unscoped_spans"], 0)
                    self.assertEqual(value["actions"][0]["target_entries"], 2 if recursive else 1)
                    self.assertEqual(value["actions"][0]["flush_failures"], "1")

    def test_independent_action_and_target_contracts_reject_unavailable_or_coerced_values(self):
        for key, value in (("thread_id", "0"), ("sequence", "01"), ("failed", 0),
                           ("action_id", "bad"), ("case_id", None), ("attempt_id", True),
                           ("cookie", "bad"), ("scope_id", "bad")):
            with self.subTest(key=key), self.assertRaises(ValueError):expected(**{key: value})
        for owner, method in (("", "target"), ("Work", ""), (True, "target"), ("Work", "bad\n")):
            with self.assertRaises(ValueError):receipt.Target(owner, method)
        report, message = fixture()
        for actions in ([], None, [None], [expected()] * 2):
            with self.subTest(actions=actions), self.assertRaises(ValueError):
                receipt.qualify(report, identity(), actions, TARGET, [], service=SERVICE, decoder=None)
        with self.assertRaises(ValueError):qualify(report, message, target=None)

    def test_final_runtime_action_and_actual_thread_must_match_pre_release_expectations(self):
        for key, replacement in (("thread_id", "42"), ("cookie", "a" * 32), ("sequence", "2"),
                                 ("scope_id", "a" * 32), ("case_id", "a" * 64), ("attempt_id", "a" * 64)):
            report, message = fixture();report["scopes"][0][key] = replacement
            with self.subTest(key=key), self.assertRaises(ValueError):qualify(report, message)
        for key, replacement in (("queue_evidence", "unavailable"), ("pid", 124)):
            report, message = fixture();report[key] = replacement
            with self.assertRaises(ValueError):qualify(report, message)
        for key, replacement in (("producer_complete", False), ("queue_dropped", None)):
            report, message = fixture();report["scopes"][0][key] = replacement
            if key == "producer_complete":report["scopes"][0]["phase"] = "incomplete"
            with self.assertRaises(ValueError):qualify(report, message)
        report, message = fixture();report["producer"]["error"] = "class_changed"
        with self.assertRaises(ValueError):qualify(report, message)
        report, _ = fixture();report["pid"] = 124
        with self.assertRaises(ValueError):java_witness.final_report(report, pid=124, identity=identity())

    def test_parent_and_method_spans_can_arrive_in_separate_reversed_batches(self):
        report, message = fixture(recursive=True)
        first, second = copy.deepcopy(message), copy.deepcopy(message)
        del first.resource_spans[0].scope_spans[0].spans[:]
        del second.resource_spans[0].scope_spans[1].spans[:]
        value = qualify(report, message, bodies=[("/v1/traces", first.SerializeToString()),
                                                ("/v1/traces", second.SerializeToString())])
        self.assertEqual((value["trace_batches"], value["scoped_spans"]), (2, 5))

    def test_synchronous_recursive_siblings_cannot_overlap_in_either_arrival_order(self):
        for start, accepted in ((350, True), (400, True), (200, False)):
            for reverse in (False, True):
                report, message = fixture(recursive=True)
                roles, methods = message.resource_spans[0].scope_spans
                roles.spans[2].end_time_unix_nano = 350
                methods.spans[1].end_time_unix_nano = 300
                other_role = copy.deepcopy(roles.spans[2])
                other_method = copy.deepcopy(methods.spans[1])
                other_role.span_id = bytes.fromhex("7" * 16)
                other_method.span_id = bytes.fromhex("8" * 16)
                other_method.parent_span_id = other_role.span_id
                other_role.start_time_unix_nano, other_role.end_time_unix_nano = start, 700
                other_method.start_time_unix_nano, other_method.end_time_unix_nano = start + 50, 650
                roles.spans.append(other_role);methods.spans.append(other_method)
                for key in ("started_ids", "ended_ids", "exported_ids"):
                    report["scopes"][0][key].extend(["7" * 16, "8" * 16])
                report["scopes"][0]["target_entries"] = "3"
                if reverse:
                    roles.spans.reverse();methods.spans.reverse()
                with self.subTest(start=start, reverse=reverse):
                    if accepted:
                        self.assertEqual(qualify(report, message)["scoped_spans"], 7)
                    else:
                        with self.assertRaisesRegex(ValueError, "synchronous siblings overlap"):
                            qualify(report, message)

    def test_two_actual_scopes_have_distinct_actions_contexts_and_fresh_traces(self):
        report, message = fixture()
        second = copy.deepcopy(report["scopes"][0])
        second.update(cookie="a" * 32, sequence="2", scope_id="b" * 32, trace_id="7" * 32)
        report["scopes"].append(second)
        second_resource = copy.deepcopy(message.resource_spans[0])
        for group in second_resource.scope_spans:
            for span in group.spans:
                span.trace_id = bytes.fromhex("7" * 32)
                span.start_time_unix_nano += 1000
                span.end_time_unix_nano += 1000
                attribute(span, receipt.SCOPE).string_value = "b" * 32
                attribute(span, receipt.PREFIX + "context_cookie").string_value = "a" * 32
        message.resource_spans.append(second_resource)
        other = expected(action_id="a" * 64, cookie="a" * 32, sequence="2", scope_id="b" * 32)
        self.assertEqual(qualify(report, message, actions=[expected(), other])["scoped_spans"], 6)
        touching = copy.deepcopy(message)
        for group in touching.resource_spans[1].scope_spans:
            for span in group.spans:
                span.start_time_unix_nano -= 10
                span.end_time_unix_nano -= 10
        self.assertEqual(qualify(report, touching, actions=[expected(), other])["scoped_spans"], 6)
        for changed_resource, shift in ((1, -11), (0, 2000)):
            altered = copy.deepcopy(message)
            for group in altered.resource_spans[changed_resource].scope_spans:
                for span in group.spans:
                    span.start_time_unix_nano += shift
                    span.end_time_unix_nano += shift
            with self.subTest(resource=changed_resource), self.assertRaisesRegex(ValueError, "serial action intervals"):
                qualify(report, altered, actions=[expected(), other])
        for key in ("action_id", "scope_id", "cookie", "sequence"):
            changed = dataclasses.replace(other, **{key: getattr(expected(), key)})
            with self.subTest(key=key), self.assertRaises(ValueError):qualify(report, message, actions=[expected(), changed])
        report["scopes"][1]["trace_id"] = report["scopes"][0]["trace_id"]
        with self.assertRaisesRegex(ValueError, "share a trace"):
            qualify(report, message, actions=[expected(), other])

    def test_background_and_metric_channels_remain_retained_outside_action_counts(self):
        report, message = fixture()
        background = copy.deepcopy(message.resource_spans[0].scope_spans[1].spans[0])
        background.trace_id = b"\x99" * 16;background.span_id = b"\x88" * 8;background.parent_span_id = b""
        del background.attributes[:]
        message.resource_spans[0].scope_spans[1].spans.append(background)
        body = message.SerializeToString()
        value = qualify(report, message, bodies=[("/v1/metrics", b""), ("/v1/traces", body)])
        self.assertEqual((value["spans"], value["scoped_spans"], value["unscoped_spans"]), (4, 3, 1))
        self.assertEqual((value["trace_batches"], value["metric_batches"]), (1, 1))
        reversed_value = qualify(report, message, bodies=[("/v1/traces", body), ("/v1/metrics", b"")])
        self.assertNotEqual(value["raw_receipt_sha256"], reversed_value["raw_receipt_sha256"])

    def test_missing_duplicate_and_relabelled_spans_cannot_satisfy_receiver_confirmation(self):
        report, message = fixture()
        for group in (0, 1):
            changed = copy.deepcopy(message);del changed.resource_spans[0].scope_spans[group].spans[0]
            with self.subTest(group=group), self.assertRaises(ValueError):qualify(report, changed)
        changed = copy.deepcopy(message)
        changed.resource_spans[0].scope_spans[0].spans.append(changed.resource_spans[0].scope_spans[0].spans[0])
        with self.assertRaisesRegex(ValueError, "duplicate"):qualify(report, changed)
        changed = copy.deepcopy(message);span = changed.resource_spans[0].scope_spans[1].spans[0]
        for index, item in enumerate(span.attributes):
            if item.key == receipt.SCOPE:del span.attributes[index];break
        with self.assertRaisesRegex(ValueError, "unattributed"):qualify(report, changed)
        changed = copy.deepcopy(message);attribute(changed.resource_spans[0].scope_spans[0].spans[0], receipt.SCOPE).string_value = "a" * 32
        with self.assertRaisesRegex(ValueError, "unknown action"):qualify(report, changed)
        changed = copy.deepcopy(message);attribute(changed.resource_spans[0].scope_spans[0].spans[0], receipt.SCOPE).int_value = 7
        with self.assertRaises(ValueError):qualify(report, changed)

    def test_every_scoped_identity_and_compiler_probe_requires_exact_typed_data(self):
        for key in ("scope_id", "runtime_id", "context_cookie", "case_id", "attempt_id",
                    "build_sha256", "selection_sha256", "policy_sha256", "tooling_sha256", "probe_id"):
            for kind in ("wrong", "typed"):
                report, message = fixture()
                value = attribute(message.resource_spans[0].scope_spans[0].spans[0], receipt.PREFIX + key)
                if kind == "wrong":value.string_value = "bad"
                else:value.int_value = 1
                with self.subTest(key=key, kind=kind), self.assertRaises(ValueError):qualify(report, message)
        for replacement in ("unknown", "recursive_target"):
            report, message = fixture()
            attribute(message.resource_spans[0].scope_spans[0].spans[0], receipt.ROLE).string_value = replacement
            with self.assertRaises(ValueError):qualify(report, message)

    def test_method_labels_scope_versions_and_extra_probe_attributes_refuse(self):
        edits = [(0, "name", "other"), (1, "name", "other"), (0, "version", "2"), (1, "version", "other")]
        for group, key, value in edits:
            report, message = fixture();setattr(message.resource_spans[0].scope_spans[group].scope, key, value)
            with self.subTest(group=group, key=key), self.assertRaises(ValueError):qualify(report, message)
        for key in ("code.namespace", "code.function"):
            report, message = fixture();attribute(message.resource_spans[0].scope_spans[1].spans[0], key).string_value = "other"
            with self.assertRaises(ValueError):qualify(report, message)
        report, message = fixture()
        extra = message.resource_spans[0].scope_spans[1].spans[0].attributes.add()
        extra.key = receipt.PROBE;extra.value.string_value = "8" * 64
        with self.assertRaises(ValueError):qualify(report, message)

    def test_malformed_spans_drop_counts_links_events_and_outcome_status_refuse(self):
        edits = (("kind", 2), ("trace_id", b"\x00" * 16), ("span_id", b"\x00" * 8),
                 ("parent_span_id", b"x"), ("name", ""), ("name", "other"),
                 ("start_time_unix_nano", 0), ("dropped_attributes_count", 1),
                 ("dropped_events_count", 1), ("dropped_links_count", 1))
        for key, value in edits:
            report, message = fixture();setattr(message.resource_spans[0].scope_spans[0].spans[0], key, value)
            with self.subTest(key=key), self.assertRaises(ValueError):qualify(report, message)
        for code in (1, 2):
            report, message = fixture();message.resource_spans[0].scope_spans[0].spans[0].status.code = code
            with self.assertRaises(ValueError):qualify(report, message)
        report, message = fixture();message.resource_spans[0].scope_spans[0].spans[0].links.add()
        with self.assertRaises(ValueError):qualify(report, message)
        report, message = fixture();event = message.resource_spans[0].scope_spans[0].spans[0].events.add()
        event.name = "exception";event.dropped_attributes_count = 1
        with self.assertRaises(ValueError):qualify(report, message)
        event.dropped_attributes_count = 0
        self.assertEqual(qualify(report, message)["scoped_spans"], 3)

    def test_disconnected_cyclic_wrong_parent_and_wrong_intervals_refuse(self):
        edits = ((0, 1, "parent_span_id", b"\x77" * 8), (0, 1, "parent_span_id", b""),
                 (1, 0, "parent_span_id", b"\x22" * 8), (1, 0, "parent_span_id", b"\x44" * 8),
                 (0, 1, "end_time_unix_nano", 1001), (1, 0, "start_time_unix_nano", 19))
        for group, index, key, value in edits:
            report, message = fixture();setattr(message.resource_spans[0].scope_spans[group].spans[index], key, value)
            with self.subTest(group=group, key=key, value=value), self.assertRaises(ValueError):qualify(report, message)
        report, message = fixture(recursive=True)
        message.resource_spans[0].scope_spans[1].spans[1].parent_span_id = b"\x44" * 8
        with self.assertRaises(ValueError):qualify(report, message)
        report, message = fixture();message.resource_spans[0].scope_spans[1].spans[0].status.code = 2
        with self.assertRaises(ValueError):qualify(report, message)

    def test_producer_counts_and_forged_joint_omission_cannot_replace_actual_method_receipt(self):
        report, message = fixture();report["scopes"][0]["target_entries"] = "2"
        with self.assertRaises(ValueError):qualify(report, message)
        report, message = fixture();del message.resource_spans[0].scope_spans[1].spans[:]
        for key in ("started_ids", "ended_ids", "exported_ids"):report["scopes"][0][key].remove("4" * 16)
        with self.assertRaises(ValueError):qualify(report, message)

    def test_resource_duplicate_attributes_and_invalid_protobuf_refuse(self):
        for key, value in (("service.name", "other"), ("otelc.language", "go")):
            report, message = fixture();resource = message.resource_spans[0].resource
            next(item for item in resource.attributes if item.key == key).value.string_value = value
            with self.assertRaises(ValueError):qualify(report, message)
        report, message = fixture()
        span = message.resource_spans[0].scope_spans[0].spans[0];span.attributes.append(span.attributes[0])
        with self.assertRaises(ValueError):qualify(report, message)
        report, message = fixture()
        with self.assertRaises(ValueError):qualify(report, message, bodies=[("/v1/traces", b"\xff")])

    def test_raw_record_and_decode_budgets_refuse_without_partial_success(self):
        report, message = fixture();body = message.SerializeToString()
        for bodies in ([], None, [None], [("/v1/traces",)], [("/logs", body)], [("/v1/traces", "text")]):
            with self.subTest(bodies=bodies), self.assertRaises(ValueError):
                receipt.qualify(report, identity(), [expected()], TARGET, bodies, service=SERVICE,
                                decoder=ExportTraceServiceRequest.FromString)
        for name, value in (("MAX_BYTES", 1), ("MAX_SPANS", 2), ("MAX_BODIES", 0)):
            with patch.object(receipt, name, value), self.assertRaises(ValueError):qualify(report, message)
        with self.assertRaises(ValueError):
            receipt.qualify(report, identity(), [expected()], TARGET, [("/v1/traces", body)], service="",
                            decoder=ExportTraceServiceRequest.FromString)


if __name__ == "__main__":
    unittest.main()
