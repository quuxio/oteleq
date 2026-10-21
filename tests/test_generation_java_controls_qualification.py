"""Independent live-control qualification rejects wrong values and forged states."""
import copy
import json
from pathlib import Path
import sys
import tempfile
from types import SimpleNamespace as NS
import unittest

sys.path.insert(0, str(Path(__file__).resolve().parent))
import qualify_java_controls as qualifier
from qualify_java_receivers import string_node
from test_generation_java_control_receipt import flat_fixture
from test_generation_java_health import report as health_report
from test_generation_java_qualification import integer, reference, state
from test_generation_java_telemetry import metrics, span, traces


def graph(number, total, amount):
    value = state(number, total)
    value["roots"]["argument:0"] = integer(amount)
    return value


def observed(method, active):
    steps, number, total = [], 10, 0
    for index, amount in enumerate((7, 2, 3, 4)):
        before = graph(number, total, amount)
        if method == "transient_value" and index == 3:
            number, total = 26, 16
        else:
            number += amount + int(active and (method == "transient_value" and index == 1 or method == "withheld" and index == 2))
            total += amount
        after = graph(number, total, amount);result = copy.deepcopy(after)
        error = method == "fail" and index == 1
        if error:
            result["roots"]["error"] = reference(2)
            result["nodes"] += [{"id": "n2", "type": "java.lang.IllegalArgumentException", "fields": {"message": reference(3)}},
                                string_node("n3", "00650078007000650063007400650064")]
        else:
            result["roots"]["result"] = reference(0) if method == "identity" else integer(number if method == "secret" else 7)
        outcome = {"kind": "error" if error else "return", "graph": result}
        if error:
            outcome["category"] = "exception"
        steps.append({"id": "step-" + str(index), "action": "call", "gaps": [], "before": before, "after": after, "outcome": outcome})
    return {"before": copy.deepcopy(steps[0]["before"]), "after": copy.deepcopy(steps[-1]["after"]),
            "outcome": copy.deepcopy(steps[-1]["outcome"]), "steps": steps, "gaps": []}


def populate(folder):
    record, _, bodies, _ = flat_fixture()
    for name, value in (("java-controls.json", record), ("process.json", {"pid": 123, "argv": ["java", "Class"]}),
                        ("command.json", ["java", "Class"]), ("typed-observation.json", {"function_id": "Counter.identity(int)"}),
                        ("http-capture.json", {"errors": [], "bodies": [{"path": path, "file": "otlp-" + str(index) + ".protobuf"} for index, (path, _) in enumerate(bodies)]})):
        (folder / name).write_text(json.dumps(value))
    for index in range(len(bodies)):
        (folder / ("otlp-" + str(index) + ".protobuf")).write_bytes(b"on" if index == 0 else b"restored" if index == 2 else b"trace")
    root = folder / "java-rendezvous";root.mkdir()
    phases = [prefix + "-" + str(index) for index in range(4) for prefix in ("before", "after")] + ["finish"]
    for phase in phases:
        for suffix in (".ready", ".resume"):
            (root / (phase + suffix)).write_text("a" * 32 + " " + phase + "\n")
    return record


class JavaControlsQualificationTests(unittest.TestCase):
    def test_all_six_functions_have_complete_independent_four_call_oracles(self):
        for method in qualifier.METHODS:
            for active in (False, True):
                qualifier.observation(observed(method, active), method, 7, active)
        value = observed("transient_value", True)
        value["steps"][1]["after"]["nodes"][0]["fields"]["value"] = integer(19)
        with self.assertRaises(AssertionError):
            qualifier.observation(value, "transient_value", 7, True)

    def test_independent_status_oracle_refuses_unknown_or_coerced_counters(self):
        record, _, _, _ = flat_fixture();original = record["steps"][0]["after"]["settled"]
        qualifier.control_status(original, 123, (True, True), 1)
        for key, value in (("pid", 124), ("completed", True), ("completed", None),
                           ("lifetime_lost", False), ("emission", 1), ("schema_version", True),
                           ("effective_emission_off", True), ("in_flight_exports", -1)):
            changed = {**original, key: value}
            with self.subTest(key=key), self.assertRaises(AssertionError):
                qualifier.control_status(changed, 123, (True, True), 1)

    def test_control_history_checkpoint_tokens_bounds_and_reply_types_cannot_be_forged(self):
        with tempfile.TemporaryDirectory() as temporary:
            folder = Path(temporary);record = populate(folder);path = folder / "java-controls.json"
            qualifier.controls(folder, "identity", plain=False)
            edits = [lambda value: value.update(control_schema_version=True),
                     lambda value: value["steps"][0]["requested"].update(collection=1),
                     lambda value: value["steps"][0]["after"].update(metric_bodies=[False]),
                     lambda value: value["steps"][2]["after"].update(held_ns=0),
                     lambda value: value["restored"].update(cursor=10**15),
                     lambda value: value["steps"][1]["after"]["status"].update(completed=2)]
            for index, edit in enumerate(edits):
                changed = copy.deepcopy(record);edit(changed);path.write_text(json.dumps(changed))
                with self.subTest(index=index), self.assertRaises(AssertionError):
                    qualifier.controls(folder, "identity", plain=False)
            path.write_text(json.dumps(record))
            (folder / "java-rendezvous/before-0.resume").write_text("b" * 32 + " before-0\n")
            with self.assertRaises(AssertionError):
                qualifier.controls(folder, "identity", plain=False)

    def test_raw_receipt_requires_all_four_traces_but_only_two_metric_measurements(self):
        with tempfile.TemporaryDirectory() as temporary:
            folder = Path(temporary);populate(folder);runtime = folder / "sdk-runtime";runtime.mkdir()
            health = health_report();health["span_accounting"].update(sampled_started="4", sampled_ended="4")
            health["trace_exports"].update(units_started="4", units_succeeded="4")
            health["metric_exports"].update(batches_started="2", batches_succeeded="2", units_started="4", units_succeeded="4")
            path = runtime / "health.json";path.write_text(json.dumps(health))
            nodes = [span(bytes([index + 1]) * 8) for index in range(4)]
            for index, node in enumerate(nodes):
                node.trace_id = bytes([index + 1]) * 16;node.name = "Counter.identity"
            trace = traces(nodes)
            decoders = [NS(FromString=lambda _: trace), NS(FromString=lambda raw: metrics(1 if raw == b"on" else 2))]
            launch = {"policy_sha256": "a" * 64, "selection_sha256": "b" * 64}
            qualifier.verify_receipt(folder, launch, 123, *decoders)
            changed = copy.deepcopy(health);changed["span_accounting"]["sampled_ended"] = "2";path.write_text(json.dumps(changed))
            with self.assertRaises(AssertionError):
                qualifier.verify_receipt(folder, launch, 123, *decoders)
            path.write_text(json.dumps(health))
            decoders[1] = NS(FromString=lambda raw: metrics(1))
            with self.assertRaises(AssertionError):
                qualifier.verify_receipt(folder, launch, 123, *decoders)

    def test_supported_outer_error_keeps_its_exact_message_and_receiver_mutation(self):
        value = graph(18, 7, 7);value["roots"]["error"] = reference(2)
        value["nodes"] += [{"id": "n2", "type": "java.lang.RuntimeException", "fields": {"message": reference(3)}},
                           string_node("n3", "006f0075007400650072")]
        qualifier.getter_outcome(value, 18, 7, 7)
        with self.assertRaises(AssertionError):
            qualifier.getter_outcome(value, 17, 7, 7)


if __name__ == "__main__":
    unittest.main()
