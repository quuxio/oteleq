"""Independent sequence fixture oracles reject equal but incorrect captures."""
import copy
import json
from pathlib import Path
import sys
import tempfile
from types import SimpleNamespace as NS
import unittest

sys.path.insert(0, str(Path(__file__).resolve().parent))
import qualify_java_sequences as qualifier
from test_generation_java_qualification import integer, reference, state
from test_generation_java_health import report as health_report
from test_generation_java_telemetry import metrics, span, traces


def graph(value, total, argument):
    result = state(value, total)
    result["roots"]["argument:0"] = integer(argument)
    return result


def observation(method, active=False):
    first = 17 + int(method == "transient" and active)
    steps = []
    for index, (before, after, total, argument) in enumerate(((10, first, 0, 7), (first, 19, 7, 2))):
        before_graph, after_graph = graph(before, total, argument), graph(after, total + argument, argument)
        outcome = copy.deepcopy(after_graph)
        error = method == "fail" and index == 0
        if error:
            outcome["roots"]["error"] = reference(2)
            outcome["nodes"] += [{"id": "n2", "type": "java.lang.IllegalArgumentException", "fields": {"message": reference(3)}},
                                qualifier_string()]
        else:
            outcome["roots"]["result"] = reference(0) if method == "identity" else integer(after if method == "secret" else 7)
        value = {"kind": "error" if error else "return", "graph": outcome}
        if error:
            value["category"] = "exception"
        steps.append({"id": "step-" + str(index), "action": "call", "gaps": [],
                      "before": before_graph, "outcome": value, "after": after_graph})
    return {"before": copy.deepcopy(steps[0]["before"]), "outcome": copy.deepcopy(steps[-1]["outcome"]),
            "after": copy.deepcopy(steps[-1]["after"]), "gaps": [], "steps": steps}


def qualifier_string():
    return {"id": "n3", "type": "java.object:java.lang.String", "fields": {
        "value": {"kind": "string", "type": "java.lang.String", "encoding": "utf16_be", "value": "00650078007000650063007400650064"}}}


class JavaSequenceQualificationTests(unittest.TestCase):
    def test_receipt_oracle_requires_actual_roots_metrics_and_closed_health_counts(self):
        left, right = span(), span(b"b" * 8)
        left.name = right.name = "Counter.identity"
        right.trace_id = b"u" * 16
        trace, metric = traces([left, right]), metrics(2)
        health = health_report()
        health["span_accounting"].update(sampled_started="2", sampled_ended="2")
        health["trace_exports"].update(units_started="2", units_succeeded="2")
        health["metric_exports"].update(batches_started="1", batches_succeeded="1", units_started="2", units_succeeded="2")
        launch = {"policy_sha256": "a" * 64, "selection_sha256": "b" * 64}
        with tempfile.TemporaryDirectory() as temporary:
            folder = Path(temporary);(folder / "sdk-runtime").mkdir()
            path = folder / "sdk-runtime/health.json"
            path.write_text(json.dumps(health))
            (folder / "typed-observation.json").write_text(json.dumps({"function_id": "Counter.identity(int)"}))
            (folder / "http-capture.json").write_text(json.dumps({"errors": [], "bodies": [
                {"path": "/v1/traces", "file": "traces"}, {"path": "/v1/metrics", "file": "metrics"}]}))
            (folder / "traces").write_bytes(b"traces");(folder / "metrics").write_bytes(b"metrics")
            decoders = (NS(FromString=lambda _: trace), NS(FromString=lambda _: metric))
            qualifier.verify_receipt(folder, launch, 123, *decoders)
            for group, key in (("span_accounting", "sampled_ended"), ("trace_exports", "units_succeeded"),
                               ("metric_exports", "units_failed")):
                altered = copy.deepcopy(health);altered[group][key] = "1";path.write_text(json.dumps(altered))
                with self.subTest(group=group), self.assertRaises(AssertionError):
                    qualifier.verify_receipt(folder, launch, 123, *decoders)
            path.write_text(json.dumps(health))
            right.parent_span_id = b"a" * 8
            with self.assertRaises(AssertionError):
                qualifier.verify_receipt(folder, launch, 123, *decoders)
            right.parent_span_id = b""
            metric.resource_metrics[0].scope_metrics[0].metrics[0].sum.data_points[0].as_int = 3
            with self.assertRaises(AssertionError):
                qualifier.verify_receipt(folder, launch, 123, *decoders)

    def test_retained_control_verdicts_and_prelaunch_refusal_cannot_be_omitted(self):
        with tempfile.TemporaryDirectory() as temporary:
            folder = Path(temporary)
            for name, verdict in qualifier.CONTROL_VERDICTS.items():
                (folder / (name + ".stdout")).write_text(json.dumps({"verdict": verdict}))
            (folder / "changed-source.stderr").write_text("application source or immutable snapshot changed")
            self.assertEqual(qualifier.verify_controls(folder), 5)
            (folder / "missing-call.stdout").write_text('{"verdict":"equivalent_observed"}')
            with self.assertRaises(AssertionError):
                qualifier.verify_controls(folder)

    def test_original_shrink_confirmation_is_a_new_launch_despite_its_retained_copy(self):
        launches = {"raw_attempt_folders": 124, "unique_command_identities": 120}
        self.assertEqual(qualifier.audit_counts(120, launches), 120)
        for observations, records in ((116, launches), (124, launches),
                                      (120, {**launches, "raw_attempt_folders": 128})):
            with self.subTest(observations=observations), self.assertRaises(AssertionError):
                qualifier.audit_counts(observations, records)

    def test_every_outcome_has_complete_literal_graphs_in_both_lanes(self):
        for method in qualifier.METHODS:
            for active in (False, True):
                qualifier.check_observation(observation(method, active), method, 7, active)

    def test_equal_outer_results_do_not_hide_intermediate_state_or_argument_edits(self):
        original = observation("identity")
        edits = [lambda item: item["steps"].pop(),
                 lambda item: item["steps"].reverse(),
                 lambda item: item["steps"][0].update(id="step-1"),
                 lambda item: item["steps"][0].update(action="release"),
                 lambda item: item["steps"][0]["gaps"].append("missing"),
                 lambda item: item["steps"][0]["outcome"].update(kind="error"),
                 lambda item: item["steps"][0]["after"]["nodes"][0]["fields"]["value"].update(value="18"),
                 lambda item: item["steps"][1]["before"]["roots"]["argument:0"].update(value="3"),
                 lambda item: item["steps"][1]["after"]["roots"]["static:Counter.total"].update(value="10"),
                 lambda item: item["steps"][0]["outcome"]["graph"]["roots"].update(result=reference(1)),
                 lambda item: item["after"]["nodes"][0]["fields"]["value"].update(value="20")]
        for index, edit in enumerate(edits):
            altered = copy.deepcopy(original);edit(altered)
            with self.subTest(index=index), self.assertRaises(AssertionError):
                qualifier.check_observation(altered, "identity", 7, False)


if __name__ == "__main__":
    unittest.main()
