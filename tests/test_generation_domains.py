"""Declared independent domains generate frozen cases that the target accepts."""
import argparse
import copy
import itertools
import math
from pathlib import Path
import random
import struct
import sys
import tempfile
import unittest
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[1]
sys.path[:0] = [str(ROOT / "adapters/generation"), str(ROOT / "examples")]
import domains
import discovery
import generation as gen
import harness
import policy
import shrinking

INTEGER = {"kind": "integer", "minimum": 7, "maximum": 9}
FLOAT = {"kind": "float", "minimum": 0.1, "maximum": 0.3}
STRING = {"kind": "string", "minimum_length": 1, "maximum_length": 3, "alphabet": "ab"}


def entry(language: str = "python", parameter: str = "int", declared: dict | None = None) -> dict:
    return {"language": language, "parameters": [parameter],
            "input_domains": [copy.deepcopy(INTEGER if declared is None else declared)],
            "generation_seed": 123}


class GeneratedDomainTests(unittest.TestCase):
    def test_policy_allows_domain_only_fixtures_without_inventing_concrete_cases(self):
        document = {"fixtures": [{"function": "*.selected", "domains": [INTEGER]}]}
        frozen = policy.validate(document)
        self.assertNotIn("cases", frozen["fixtures"][0])
        self.assertEqual(frozen["fixtures"][0]["domains"], [INTEGER])
        self.assertEqual(policy.validate(frozen), frozen)
        self.assertEqual(document, {"fixtures": [{"function": "*.selected", "domains": [INTEGER]}]})
        self.assertIsNone(policy.concrete_cases({"otelc_function": "api.selected", "path": "app.py", "language": "python"}, frozen))

    def test_missing_contract_and_explicit_invalid_cases_remain_errors(self):
        for fixture in ({"function": "f"}, {"function": "f", "domains": None},
                        {"function": "f", "domains": [INTEGER], "cases": None},
                        {"function": "f", "domains": [INTEGER], "cases": []},
                        {"function": "f", "domains": [INTEGER], "cases": [[6]]}):
            with self.subTest(fixture=fixture), self.assertRaises(ValueError):
                policy.validate({"fixtures": [fixture]})

    def test_integer_domain_edges_are_generated_in_all_eight_target_representations(self):
        profiles = (("c", "int"), ("cpp", "int"), ("rust", "i32"), ("python", "int"),
                    ("java", "int"), ("javascript", "dynamic"), ("typescript", "number"), ("go", "int"))
        for language, parameter in profiles:
            with self.subTest(language=language):
                data = entry(language, parameter)
                self.assertEqual(harness.corpus(data, 3), [[7], [9], [8]])
                self.assertTrue(all(domains.contains(case[0], INTEGER) for case in harness.corpus(data, 3)))
                self.assertIs(type(harness.corpus(data, 1)[0][0]), float if language in ("javascript", "typescript") else int)

    def test_existing_concrete_cases_keep_their_exact_count_and_order(self):
        data = {**entry(), "input_cases": [[8], [7]]}
        with patch.object(domains, "samples", side_effect=AssertionError("explicit cases must not be regenerated")):
            self.assertEqual(harness.corpus(data, 3), [[8], [7]])

    def test_finite_domains_return_unique_cases_up_to_the_requested_budget(self):
        self.assertEqual(harness.corpus(entry(), 1024), [[7], [9], [8]])
        boolean = entry(parameter="bool", declared={"kind": "boolean"})
        self.assertEqual(harness.corpus(boolean, 20), [[False], [True]])
        data = {"language": "python", "parameters": ["bool", "bool"],
                "input_domains": [{"kind": "boolean"}, {"kind": "boolean"}]}
        cases = harness.corpus(data, 20)
        self.assertEqual({tuple(case) for case in cases}, set(itertools.product((False, True), repeat=2)))
        self.assertEqual(len(cases), 4)

    def test_signed_domains_keep_zero_then_both_edges(self):
        data = entry(declared={**INTEGER, "minimum": -9})
        self.assertEqual(harness.corpus(data, 3), [[0], [-9], [9]])

    def test_string_domains_generate_declared_lengths_and_alphabet(self):
        data = entry(parameter="str", declared=STRING)
        cases = harness.corpus(data, 12)
        self.assertEqual(len(cases), 12)
        self.assertEqual(len({case[0] for case in cases}), 12)
        self.assertTrue(all(domains.contains(case[0], STRING) for case in cases))
        self.assertEqual(cases[:3], [["a"], ["aaa"], ["b"]])
        singleton = {**STRING, "minimum_length": 2, "maximum_length": 2, "alphabet": "\u03bb"}
        self.assertEqual(harness.corpus(entry(parameter="str", declared=singleton), 8), [["\u03bb\u03bb"]])

    def test_seeded_exploration_is_repeatable_and_does_not_use_global_random_state(self):
        data = entry(declared={**INTEGER, "minimum": -100, "maximum": 100})
        before = copy.deepcopy(data)
        first = harness.corpus(data, 10)
        random.seed(999)
        self.assertEqual(harness.corpus(data, 10), first)
        self.assertNotEqual(harness.corpus({**data, "generation_seed": 124}, 10), first)
        self.assertEqual(data, before)

    def test_float32_boundaries_move_inside_the_original_declared_interval(self):
        data = entry("rust", "f32", FLOAT)
        cases = harness.corpus(data, 6)
        self.assertEqual(len(cases), 6)
        self.assertTrue(all(domains.contains(case[0], FLOAT) for case in cases))
        for case in cases:
            self.assertEqual(case[0], struct.unpack(">f", struct.pack(">f", case[0]))[0])
        self.assertGreater(cases[0][0], 0.1)
        self.assertLess(cases[1][0], 0.3)

    def test_narrow_float_domain_with_no_representable_target_value_is_blocked(self):
        data = entry("go", "float32", {"kind": "float", "minimum": 1.3, "maximum": 1.3})
        with self.assertRaisesRegex(ValueError, "representable"):
            harness.corpus(data, 3)

    def test_large_float_ranges_stay_finite_and_inside_the_domain(self):
        declared = {"kind": "float", "minimum": -1e308, "maximum": 1e308}
        cases = harness.corpus(entry(parameter="float", declared=declared), 20)
        self.assertEqual(len(cases), 20)
        self.assertTrue(all(math.isfinite(case[0]) and domains.contains(case[0], declared) for case in cases))

    def test_many_float32_intervals_retain_only_valid_concrete_values(self):
        rng = random.Random(782)
        for _ in range(100):
            low = rng.uniform(-1e6, 1e6)
            declared = {"kind": "float", "minimum": low, "maximum": low + rng.uniform(1, 100)}
            values = harness.corpus(entry("java", "float", declared), 10)
            self.assertEqual(len(values), 10)
            self.assertTrue(all(domains.contains(case[0], declared) for case in values))
            self.assertTrue(all(case[0] == struct.unpack(">f", struct.pack(">f", case[0]))[0] for case in values))

    def test_signed_zero_is_not_collapsed(self):
        declared = {"kind": "float", "minimum": -0.0, "maximum": 0.0}
        cases = harness.corpus(entry(parameter="float", declared=declared), 8)
        self.assertEqual({struct.pack(">d", case[0]).hex() for case in cases},
                         {"0000000000000000", "8000000000000000"})
        self.assertEqual(len(cases), 2)

    def test_tiny_float32_fallback_keeps_both_zeroes_and_all_representable_points(self):
        high = struct.unpack(">f", bytes.fromhex("00000003"))[0]
        declared = {"kind": "float", "minimum": -0.0, "maximum": high}
        rng = random.Random(123)
        with patch.object(rng, "random", return_value=0.75):
            values = domains.samples(declared, 6, rng, width=32)
        self.assertEqual({struct.pack(">f", value).hex() for value in values},
                         {"00000000", "80000000", "00000001", "00000002", "00000003"})

    def test_float32_steps_cross_zero_and_stop_at_equal_targets(self):
        positive = struct.unpack(">f", bytes.fromhex("00000001"))[0]
        negative = struct.unpack(">f", bytes.fromhex("80000001"))[0]
        self.assertEqual(domains.float_step(-0.0, 1.0, 32), positive)
        self.assertEqual(domains.float_step(0.0, -1.0, 32), negative)
        self.assertEqual(domains.float_step(1.0, 1.0, 32), 1.0)
        self.assertEqual(struct.pack(">f", domains.float_step(-0.0, 0.0, 32)).hex(), "00000000")

    def test_incompatible_domains_and_out_of_range_endpoints_are_visible_errors(self):
        bad = [entry(parameter="str"), entry(declared={"kind": "boolean"}),
               entry("go", "uint8", {**INTEGER, "maximum": 256}),
               entry("typescript", "number", {**INTEGER, "maximum": 2**53}),
               entry("c", "float", {"kind": "float", "minimum": 0.0, "maximum": 1e100})]
        for data in bad:
            with self.subTest(entry=data), self.assertRaises(ValueError):
                harness.corpus(data, 3)

    def test_zero_argument_domain_fixture_is_one_case(self):
        self.assertEqual(harness.corpus({"language": "python", "parameters": [], "input_domains": []}, 3), [[]])
        self.assertEqual(policy.validate({"fixtures": [{"function": "f", "domains": []}]})["fixtures"][0]["domains"], [])
        with self.assertRaisesRegex(ValueError, "argument count"):
            harness.corpus({"language": "python", "parameters": ["int"], "input_domains": []}, 3)

    def test_generated_input_budgets_refuse_instead_of_truncating_a_passing_corpus(self):
        long = {**STRING, "minimum_length": 100, "maximum_length": 100}
        candidate = entry(parameter="str", declared=long)
        with patch.object(harness, "MAX_DOMAIN_INPUT_BYTES", 128):
            with self.assertRaisesRegex(ValueError, "budget"):
                harness.corpus(candidate, 3)

    def test_combined_case_payload_is_bounded_separately_from_parameter_pools(self):
        declared = {**STRING, "minimum_length": 20, "maximum_length": 20}
        data = {"language": "python", "parameters": ["str", "str"], "input_domains": [declared, declared]}
        with patch.object(harness, "MAX_DOMAIN_INPUT_BYTES", 140):
            with self.assertRaisesRegex(ValueError, "cases exceed"):
                harness.corpus(data, 3)

    def test_invalid_sampling_budgets_and_widths_are_not_empty_successes(self):
        rng = random.Random(1)
        for count in (0, -1, True, 1025):
            with self.subTest(count=count), self.assertRaises(ValueError):
                domains.samples(INTEGER, count, rng)
        for width in (16, 32.0):
            with self.subTest(width=width), self.assertRaises(ValueError):
                domains.samples(FLOAT, 3, rng, width=width)

    def test_existing_context_blockers_are_not_cleared_by_domain_generation(self):
        data = {**entry(), "reason": "unsupported original import context"}
        with patch.object(harness, "domain_cases", side_effect=AssertionError("blocked callable must remain blocked")):
            self.assertEqual(gen.qualify_entry(data, Path("unused"), 3), "blocked")
        self.assertEqual(data["reason"], "unsupported original import context")

    def test_receiver_construction_inputs_stay_fixed_without_running_initialisers(self):
        source = ('raise RuntimeError("application initialiser must not run")\n'
                  'class Counter:\n'
                  ' def __init__(self,start:int):self.value=start\n'
                  ' def add(self,value:int)->int:return self.value+value\n')
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            (root / "app.py").write_text(source)
            parsed = discovery.python_inventory(source)
            parsed["entrypoints"] = []
            configuration = policy.validate({"fixtures": [{"function": "app.Counter.add", "domains": [INTEGER],
                "receiver": {"factory": "Counter", "arguments": [10]}}]})
            args = argparse.Namespace(configuration=configuration, cases=3)
            method = next(value for value in parsed["functions"] if value["name"] == "Counter.add")
            data = gen.inventory_entry(method, parsed, "app.py", "python", "a" * 64, root, args)
            self.assertEqual(data["status"], "ready", data["reason"])
            self.assertEqual(data["input_cases"], [[7], [9], [8]])
            self.assertEqual(data["receiver_fixture"]["arguments"], [10])

    def test_planning_materialises_requested_inputs_and_generation_reuses_them(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            (root / "app.py").write_text("def selected(value:int)->int:return value+1\n")
            configuration = policy.validate({"fixtures": [{"function": "*.selected", "domains": [INTEGER]}]})
            args = argparse.Namespace(configuration=configuration, cases=3)
            function = {"name": "selected", "line": 1, "parameters": ["int"], "output": "int", "reason": ""}
            data = gen.inventory_entry(function, {"globals": [], "entrypoints": []},
                                       "app.py", "python", "a" * 64, root, args)
            self.assertEqual(data["status"], "ready", data["reason"])
            self.assertEqual(data["input_cases"], [[7], [9], [8]])
            with patch.object(domains, "samples", side_effect=AssertionError("must consume frozen values")):
                cases = harness.corpus(data, 3)
                retained = gen.generation_case(data, 1, cases[1])
            self.assertEqual(retained["arguments"], [9])
            self.assertEqual(retained["arguments_requested"], [9])
            self.assertEqual(configuration["fixtures"][0]["domains"], [INTEGER])
            self.assertNotIn("cases", configuration["fixtures"][0])

    def test_automatic_domain_cases_keep_the_existing_shrinking_contract(self):
        data = entry()
        data["input_cases"] = harness.domain_cases(data, 3)
        candidates = list(shrinking.candidates(data, [9]))
        self.assertTrue(candidates)
        self.assertTrue(all(domains.contains(case[0], INTEGER) for case in candidates))
        self.assertIn([7], candidates)


if __name__ == "__main__":
    unittest.main()

