"""Declared numeric relations constrain frozen inputs and reduction candidates."""
import argparse
import copy
from pathlib import Path
import sys
import tempfile
from types import SimpleNamespace
import unittest
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[1]
sys.path[:0] = [str(ROOT / "adapters/generation"), str(ROOT / "examples")]
import discovery
import generation
import harness
import policy
import preconditions
import sequences
import shrinking

LESS = {"left": 0, "operator": "<", "right": 1}
DOMAIN = {"kind": "integer", "minimum": 7, "maximum": 9}


def entry(language: str = "python", parameter: str = "int", conditions: list[dict] | None = None) -> dict:
    return {"language": language, "parameters": [parameter, parameter],
            "input_domains": [DOMAIN.copy(), DOMAIN.copy()],
            "input_preconditions": [LESS.copy()] if conditions is None else conditions,
            "generation_seed": 7}


class NumericPreconditionTests(unittest.TestCase):
    def test_policy_preserves_validated_relations_without_inventing_cases(self):
        document = {"fixtures": [{"function": "*f", "domains": [DOMAIN, DOMAIN], "preconditions": [LESS]}]}
        frozen = policy.validate(document)
        self.assertEqual(frozen["fixtures"][0]["preconditions"], [LESS])
        self.assertNotIn("cases", frozen["fixtures"][0])
        self.assertEqual(policy.validate(frozen), frozen)
        self.assertEqual(document["fixtures"][0]["domains"], [DOMAIN, DOMAIN])

    def test_malformed_relations_are_refused(self):
        invalid = (None, {}, [None], [{}], [{**LESS, "extra": 1}], [{**LESS, "left": True}],
                   [{**LESS, "left": -1}], [{**LESS, "right": 1024}], [{**LESS, "operator": "eval"}],
                   [{**LESS, "operator": []}], [LESS, LESS], [LESS] * 33)
        for value in invalid:
            with self.subTest(value=value), self.assertRaises(ValueError):
                preconditions.validate(value)

    def test_empty_relations_are_an_explicit_noop(self):
        self.assertEqual(preconditions.validate([]), [])
        self.assertTrue(preconditions.accepts([], []))

    def test_each_closed_operator_uses_exact_numeric_values(self):
        values = {"<": ([1, 2], [2, 1]), "<=": ([2, 2], [2, 1]), "==": ([2, 2.0], [2, 3]),
                  "!=": ([2, 3], [2, 2]), ">=": ([2, 2], [1, 2]), ">": ([2, 1], [1, 2])}
        for operator, (accepted, rejected) in values.items():
            condition = [{**LESS, "operator": operator}]
            with self.subTest(operator=operator):
                self.assertTrue(preconditions.accepts(accepted, condition))
                self.assertFalse(preconditions.accepts(rejected, condition))
        self.assertTrue(preconditions.accepts([2**100, 2**100 + 1], [LESS]))

    def test_nonnumeric_and_nonfinite_values_cannot_invoke_application_callbacks(self):
        class Callback:
            def __lt__(self, other):
                raise AssertionError("application comparison callback ran")
        for value in (True, "1", None, float("inf"), float("nan"), Callback()):
            with self.subTest(type=type(value)), self.assertRaisesRegex(ValueError, "finite numeric"):
                preconditions.accepts([value, 2], [LESS])

    def test_relation_indices_are_bound_to_callable_arity(self):
        for arguments in ([], [1]):
            with self.subTest(arguments=arguments), self.assertRaisesRegex(ValueError, "argument count"):
                preconditions.require(arguments, [LESS])
        with self.assertRaisesRegex(ValueError, "argument count"):
            policy.validate({"fixtures": [{"function": "f", "domains": [DOMAIN], "preconditions": [LESS]}]})

    def test_domain_generation_filters_relations_in_all_eight_profiles(self):
        profiles = (("c", "int"), ("cpp", "int"), ("rust", "i32"), ("python", "int"),
                    ("java", "int"), ("javascript", "dynamic"), ("typescript", "number"), ("go", "int"))
        for language, parameter in profiles:
            data = entry(language, parameter)
            original = copy.deepcopy(data)
            with self.subTest(language=language):
                self.assertEqual(harness.corpus(data, 3), [[7, 9], [7, 8], [8, 9]])
                self.assertEqual(data, original)

    def test_explicit_cases_keep_order_and_must_satisfy_relations(self):
        fixture = {"function": "f", "cases": [[8, 9], [7, 8]], "preconditions": [LESS]}
        self.assertEqual(policy.validate({"fixtures": [fixture]})["fixtures"][0]["cases"], fixture["cases"])
        data = {**entry(), "input_cases": fixture["cases"]}
        self.assertEqual(harness.corpus(data, 10), [[8, 9], [7, 8]])
        with self.assertRaisesRegex(ValueError, "preconditions"):
            policy.validate({"fixtures": [{**fixture, "cases": [[9, 7]]}]})

    def test_target_rounding_cannot_turn_an_invalid_relation_into_a_passing_fixture(self):
        data = {"language": "java", "parameters": ["float", "float"],
                "input_cases": [[16777216, 16777217]], "input_preconditions": [LESS]}
        with self.assertRaisesRegex(ValueError, "preconditions"):
            harness.corpus(data, 3)

    def test_preconditions_require_an_explicit_input_strategy(self):
        data = {"language": "python", "parameters": ["int", "int"], "input_preconditions": [LESS]}
        with self.assertRaisesRegex(ValueError, "concrete cases or declared domains"):
            harness.corpus(data, 3)

    def test_finite_unsatisfied_domain_is_a_visible_blocker(self):
        data = entry(conditions=[{**LESS, "right": 0}])
        with self.assertRaisesRegex(ValueError, "no generated inputs"):
            harness.corpus(data, 3)

    def test_search_budget_does_not_turn_partial_generated_inputs_into_success(self):
        with patch.object(preconditions, "MAX_CANDIDATES", 6):
            with self.assertRaisesRegex(ValueError, "candidate budget"):
                harness.corpus(entry(), 3)

    def test_reduction_never_yields_a_relation_breaking_candidate(self):
        data = entry(conditions=[{**LESS, "operator": ">="}])
        data["input_domains"] = [{**DOMAIN, "minimum": 0, "maximum": 32}] * 2
        candidates = list(shrinking.candidates(data, [8, 7]))
        self.assertTrue(candidates)
        self.assertTrue(all(preconditions.accepts(values, data["input_preconditions"]) for values in candidates))
        self.assertNotIn([0, 7], candidates)
        self.assertIn([7, 7], candidates)

    def test_derived_replay_retains_the_relation_in_policy_and_inventory(self):
        selected = {**entry(), "id": "target", "otelc_function": "app.f", "path": "app.py",
                    "expected_baseline": {"kind": "return"}}
        original = {"inventory": [selected], "configuration": {"functions": {}, "fixtures": []},
                    "configuration_sha256": "a" * 64}
        workflow = SimpleNamespace(identity=lambda _: "b" * 64)
        derived = shrinking.derived_data(workflow, original, selected, {"id": "target-0", "arguments": [7, 9]})
        self.assertEqual(derived["configuration"]["fixtures"][0]["preconditions"], [LESS])
        self.assertEqual(derived["inventory"][0]["input_preconditions"], [LESS])
        self.assertEqual(policy.validate(derived["configuration"])["fixtures"][0]["preconditions"], [LESS])

    def test_inventory_freezes_valid_relational_cases_without_running_application_initialisers(self):
        text = 'raise RuntimeError("initializer ran")\ndef f(start:int,end:int)->int:return end-start\n'
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            (root / "app.py").write_text(text)
            discovered = discovery.python_inventory(text)
            discovered["entrypoints"] = []
            configuration = policy.validate({"fixtures": [{"function": "app.f", "domains": [DOMAIN, DOMAIN],
                                                            "preconditions": [LESS]}]})
            args = argparse.Namespace(configuration=configuration, cases=3)
            selected = discovered["functions"][0]
            result = generation.inventory_entry(selected, discovered, "app.py", "python", "a" * 64, root, args)
            self.assertEqual(result["status"], "ready", result["reason"])
            self.assertEqual(result["input_cases"], [[7, 9], [7, 8], [8, 9]])
            self.assertEqual(result["input_preconditions"], [LESS])

    def test_fixed_sequence_calls_must_satisfy_the_method_preconditions(self):
        data = {**entry("java"), "receiver_fixture": {}, "expected_baseline": {"kind": "return"}}
        steps = [{"action": "call", "arguments": [9, 7]}, {"action": "call", "arguments": "case"}]
        with self.assertRaisesRegex(ValueError, "preconditions"):
            sequences.configure(data, steps, harness.concrete_arguments)
        self.assertNotIn("sequence_configuration", data)

    def test_every_materialised_sequence_call_preserves_relations(self):
        data = {**entry("java"), "receiver_fixture": {}, "expected_baseline": {"kind": "return"}}
        steps = [{"action": "call", "arguments": [7, 8]}, {"action": "call", "arguments": "case"}]
        sequences.configure(data, steps, harness.concrete_arguments)
        frozen = sequences.concrete(data, [7, 9], harness.concrete_arguments)
        self.assertEqual([step["arguments"] for step in frozen], [[7, 8], [7, 9]])
        with self.assertRaisesRegex(ValueError, "preconditions"):
            sequences.concrete(data, [9, 7], harness.concrete_arguments)

    def test_fixed_sequence_rounding_cannot_bypass_a_relation(self):
        data = {**entry("java", "float"), "receiver_fixture": {}, "expected_baseline": {"kind": "return"}}
        steps = [{"action": "call", "arguments": [16777216, 16777217]},
                 {"action": "call", "arguments": "case"}]
        with self.assertRaisesRegex(ValueError, "preconditions"):
            sequences.configure(data, steps, harness.concrete_arguments)


if __name__ == "__main__":
    unittest.main()
