"""Returned attempts cannot substitute for real module-body entry evidence."""

import copy
from pathlib import Path
import sys
import unittest

REPO = Path(__file__).resolve().parents[1]
sys.path[:0] = [str(REPO / "adapters/generation"), str(REPO / "examples")]
import node_execution as execution


class NodeExecutionTests(unittest.TestCase):
    def fixture(self, *, plain=False, typed=False):
        value = {"provider": "/provider", "entry": "/project/app.ts" if typed else "/project/app.js", "plain": plain}
        request = {"kind": "module_requested", "load_id": 1, "path": value["entry"],
                   "logical_source": "app.ts" if typed else "app.js", "url": "file://" + value["entry"],
                   "module_type": "typescript" if typed else "javascript"}
        emission = {**{key: request[key] for key in (*execution.ORIGIN, "load_id")},
                    "kind": "loaded" if plain else "instrumented", "source_sha256": "a" * 64,
                    "sha256": "b" * 64, "format": "module", "body_entry": {"schema_version": 1,
                    "goal": "module", "helper": "/provider/adapters/node/src/source-inputs.ts"}}
        entered = {**{key: emission[key] for key in (*execution.ORIGIN, "load_id", "source_sha256")},
                   "kind": "execution_started", "pid": 101, "execution_protocol": 1, "format": "module",
                   "emission_kind": emission["kind"], "emission_sha256": emission["sha256"]}
        return [request, emission, entered], value

    def chain(self, count=3):
        records, value = self.fixture()
        request, emission, entered = records
        result = []
        for load in range(1, count + 1):
            result.append({**request, "load_id": load})
            if load > 1:
                result.append({**{key: request[key] for key in execution.ORIGIN}, "kind": "module_reentered",
                               "load_id": load, "previous_load_id": load - 1})
            result.append({**copy.deepcopy(emission), "load_id": load,
                           "format": "module" if load == count else "node-detected"})
        result.append({**entered, "load_id": count})
        return result, value

    def test_real_entry_and_plain_typescript_keep_the_concrete_format(self):
        for plain, typed in ((False, False), (False, True), (True, True)):
            records, value = self.fixture(plain=plain, typed=typed)
            with self.subTest(plain=plain, typed=typed):
                self.assertEqual(execution.verify(records, value, 101), [{"load_id": 1,
                    **{key: records[0][key] for key in execution.ORIGIN}, "returned_format": "module",
                    "resolved_format": "module", "outcome": "body_entered"}])

    def test_complete_same_url_chain_preserves_unentered_attempts_without_a_resolved_format(self):
        records, value = self.chain()
        actual = execution.verify(records, value, 101)
        for index in (0, 1):
            self.assertEqual(actual[index]["outcome"], "unentered_before_same_url_entry")
            self.assertIsNone(actual[index]["resolved_format"])
            self.assertEqual(actual[index]["reentered_by"], index + 2)
            self.assertEqual(actual[index]["later_entry_load_id"], 3)
        self.assertEqual(actual[-1]["outcome"], "body_entered")

    def test_unselected_javascript_and_native_plain_remain_explicitly_unobserved(self):
        records, value = self.fixture(plain=True)
        records.pop()
        records[1].pop("body_entry")
        self.assertEqual(execution.verify(records, value, 101)[0]["outcome"], "not_observed")
        self.assertEqual(execution.verify([], value, 101), [])

    def test_closed_entry_fields_process_origin_goal_and_returned_bytes_are_required(self):
        records, value = self.fixture()
        changes = (("pid", True), ("pid", 102), ("execution_protocol", True), ("execution_protocol", 2),
                   ("path", "/foreign.js"), ("url", "file:///foreign.js"), ("logical_source", "foreign.js"),
                   ("source_sha256", "c" * 64), ("emission_sha256", "c" * 64), ("emission_kind", "loaded"),
                   ("format", "commonjs"), ("extra", "unknown"), ("load_id", True), ("load_id", 2))
        for key, changed in changes:
            edited = copy.deepcopy(records)
            edited[-1][key] = changed
            with self.subTest(key=key, changed=changed), self.assertRaises(ValueError):
                execution.verify(edited, value, 101)
        for key in execution.ENTRY_FIELDS:
            edited = copy.deepcopy(records)
            edited[-1].pop(key)
            # Removing kind is invalid before dispatch, as enforced by node_inputs.
            with self.subTest(missing=key), self.assertRaises((ValueError, KeyError)):
                execution.verify(edited, value, 101)

    def test_missing_duplicate_and_early_entries_or_emissions_refuse(self):
        records, value = self.fixture()
        variants = [records[:-1], records + [records[-1]], [records[0], records[2], records[1]],
                    [records[0], records[-1]], [records[0], records[1], records[1], records[2]],
                    records + [records[0]], [{**records[0], "load_id": 2}, *records[1:]]]
        for edited in variants:
            with self.subTest(records=edited), self.assertRaises(ValueError):
                execution.verify(edited, value, 101)

    def test_body_observer_is_checked_even_when_a_later_attempt_enters(self):
        records, value = self.chain(2)
        for key, changed in (("schema_version", True), ("schema_version", 2), ("goal", "unknown"),
                             ("helper", "/foreign.ts"), ("extra", "unknown")):
            edited = copy.deepcopy(records)
            edited[1]["body_entry"][key] = changed
            with self.subTest(key=key), self.assertRaises(ValueError):
                execution.verify(edited, value, 101)
        for changed in (None, {"schema_version": 1}, {"schema_version": 1, "goal": "commonjs",
                                                       "helper": "/provider/adapters/node/src/source-inputs.ts"}):
            edited = copy.deepcopy(records)
            edited[-2]["body_entry"] = changed
            with self.subTest(observer=changed), self.assertRaises(ValueError):
                execution.verify(edited, value, 101)

    def test_reentry_requires_complete_adjacent_same_url_emissions_and_a_later_entry(self):
        records, value = self.chain(2)
        for key, changed in (("previous_load_id", True), ("previous_load_id", 2),
                             ("previous_load_id", 0), ("extra", "unknown"), ("path", "/foreign.js")):
            edited = copy.deepcopy(records)
            edited[3][key] = changed
            with self.subTest(key=key), self.assertRaises(ValueError):
                execution.verify(edited, value, 101)
        for edited in (records[:-1], [record for record in records if record["kind"] != "module_reentered"],
                       [records[0], records[2], records[3], *records[4:]],
                       [*records[:3], {"kind": "source"}, *records[3:]],
                       [*records[:4], records[3], *records[4:]]):
            with self.subTest(records=edited), self.assertRaises(ValueError):
                execution.verify(edited, value, 101)
        original, _ = self.fixture()
        with self.assertRaises(ValueError):
            execution.verify([*records[:2], original[-1], *records[2:]], value, 101)


if __name__ == "__main__":
    unittest.main()
