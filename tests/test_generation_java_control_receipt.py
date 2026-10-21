"""Direct control oracles distinguish recording suppression from transport silence."""
import copy
import json
from pathlib import Path
import sys
import tempfile
import unittest

REPO = Path(__file__).resolve().parents[1]
sys.path[:0] = [str(REPO / "adapters/generation"), str(REPO / "examples"), str(REPO / "tests")]
import java_control_receipt as receipt
from test_generation_java_control import reply

STATES = [dict(collection=True, emission=True), dict(collection=False, emission=True),
          dict(collection=True, emission=False), dict(collection=False, emission=False)]
CALLS, DURATION = "otelc.function.calls", "otelc.function.duration"


def status(state, completed):
    return reply(**state, completed=completed, effective_emission_off=not state["emission"])


def history(previous, requested, completed):
    middle = {**previous, "collection": requested["collection"]}
    return [{"command": "status", "status": status(previous, completed)},
            {"command": "collection " + ("on" if requested["collection"] else "off"), "status": status(middle, completed)},
            {"command": "emission " + ("on" if requested["emission"] else "off"), "status": status(requested, completed)}]


def fixture():
    bodies = [("/v1/metrics", b"on"), ("/v1/traces", b"trace"), ("/v1/metrics", b"restored")]
    series = {0: {CALLS: [(20, 1)], DURATION: [(20, 1)]},
              2: {CALLS: [(40, 4)], DURATION: [(40, 4)]}}
    steps = []
    completed, previous = 0, STATES[0]
    for index, (state, size, start, end) in enumerate(zip(STATES, (1, 2, 3, 4), (0, 1, 1, 2), (1, 1, 2, 2))):
        before = {"history": history(previous, state, completed), "cursor": start}
        completed += size if state["collection"] else 0
        after = {key: status(state, completed) for key in ("status", "flush", "settled")}
        after.update(cursor=end, metric_bodies=[0] if index == 0 else [], held_ns=1000000000 if not state["emission"] else 0)
        steps.append({"id": "step-" + str(index), "requested": state.copy(), "before": before, "after": after})
        previous = state
    record = {"control_schema_version": 1, "plain": False, "pid": 123, "interval_ms": 1000, "steps": steps,
              "restored": {"history": history(previous, STATES[0], completed), "flush": status(STATES[0], completed), "cursor": 3}}
    entry = {"sequence_configuration": [{"action": "call", "metrics": state.copy()} for state in STATES]}
    return record, entry, bodies, series


def flat_fixture():
    record, entry, bodies, series = fixture()
    for index, step in enumerate(record["steps"]):
        for row in step["before"]["history"]:
            row["status"]["completed"] = (0, 1, 1, 2)[index]
        for key in ("status", "flush", "settled"):
            step["after"][key]["completed"] = (1, 1, 2, 2)[index]
    for row in record["restored"]["history"]:
        row["status"]["completed"] = 2
    record["restored"]["flush"]["completed"] = 2
    series[2] = {name: [(40, 2)] for name in (CALLS, DURATION)}
    return record, entry, bodies, series


class JavaControlReceiptTests(unittest.TestCase):
    def qualify(self, record, entry, bodies, series):
        with tempfile.TemporaryDirectory() as temporary:
            folder = Path(temporary)
            path = folder / "java-controls.json";path.write_text(json.dumps(record));path.chmod(0o600)
            retained = receipt.read(folder, entry, 123, bodies, plain=False)
            self.assertEqual(len(retained["record_sha256"]), 64)
            return receipt.qualify(retained, 123, bodies, [1, 2, 3, 4], series)

    def test_collected_calls_include_retained_emission_off_data_and_exclude_both_collection_off_states(self):
        self.assertEqual(self.qualify(*fixture()), 4)

    def test_wrong_pid_counters_requested_states_or_unknown_data_cannot_qualify(self):
        original, entry, bodies, series = fixture()
        edits = [lambda value: value.update(pid=124), lambda value: value.update(plain=True),
                 lambda value: value.update(control_schema_version=True), lambda value: value.update(extra=0),
                 lambda value: value["steps"].pop(),
                 lambda value: value["steps"][0].update(id="other"),
                 lambda value: value["steps"][0]["requested"].update(collection=1),
                 lambda value: value["steps"][1]["after"]["status"].update(completed=3),
                 lambda value: value["steps"][2]["after"]["settled"].update(completed=1),
                 lambda value: value["steps"][3]["before"]["history"][0]["status"].update(pid=124),
                 lambda value: value["steps"][0]["before"]["history"][1].update(command="off"),
                 lambda value: value["restored"]["flush"].update(completed=10),
                 lambda value: value["restored"].update(cursor=1)]
        for index, edit in enumerate(edits):
            record = copy.deepcopy(original);edit(record)
            with self.subTest(index=index), self.assertRaises(ValueError):
                self.qualify(record, entry, bodies, series)

    def test_missing_positive_controls_unknown_transport_and_too_short_off_windows_refuse(self):
        original, entry, bodies, series = fixture()
        for edit in (lambda value: value["steps"][2]["after"].update(held_ns=999999999),
                     lambda value: value["steps"][0]["after"].update(metric_bodies=[False]),
                     lambda value: value["steps"][0]["before"].update(cursor=-1),
                     lambda value: value["steps"][2]["after"].update(cursor=3, metric_bodies=[2])):
            changed = copy.deepcopy(original);edit(changed)
            with self.assertRaises(ValueError):
                self.qualify(changed, entry, bodies, series)
        for index, name, values in ((0, CALLS, []), (2, DURATION, [(40, 1)]), (0, CALLS, [(20, 3)])):
            changed = copy.deepcopy(series);changed[index][name] = values
            with self.subTest(index=index), self.assertRaises(ValueError):
                self.qualify(original, entry, bodies, changed)

    def test_recursive_tree_sizes_require_serial_complete_intervals(self):
        nodes = {"a": None, "b": "a", "c": None}
        intervals = {"a": (10, 20), "b": (11, 19), "c": (21, 30)}
        self.assertEqual(receipt.trees(nodes, intervals), [2, 1])
        for changes in ({"c": (19, 30)}, {"b": (11, 21)}, {"c": (10, 20)}):
            altered = {**intervals, **changes}
            with self.assertRaises(ValueError):
                receipt.trees(nodes, altered)

    def test_plain_lane_contains_no_fabricated_sdk_state_or_metrics(self):
        record, entry, _, _ = fixture();record.update(plain=True)
        for step in record["steps"]:
            step["before"] = {"history": [], "cursor": 0}
            step["after"].update(status=None, flush=None, settled=None, cursor=0, metric_bodies=[])
        record["restored"] = {"history": [], "flush": None, "cursor": 0}
        with tempfile.TemporaryDirectory() as temporary:
            folder = Path(temporary);path = folder / "java-controls.json"
            path.write_text(json.dumps(record));path.chmod(0o600)
            receipt.read(folder, entry, 123, [], plain=True)
            record["steps"][0]["after"]["status"] = reply()
            path.write_text(json.dumps(record))
            with self.assertRaises(ValueError):
                receipt.read(folder, entry, 123, [], plain=True)


if __name__ == "__main__":
    unittest.main()
