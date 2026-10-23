"""Independent exact graph and exhaustive small-permutation matching oracles."""

import copy
from dataclasses import replace
import itertools
from pathlib import Path
import random
import sys
import unittest

REPO = Path(__file__).resolve().parents[1]
sys.path[:0] = [str(REPO / "adapters/generation"), str(REPO / "examples")]
import python_code
from python_code_match import Budget, equivalent
from test_generation_python_code import fixture, record
from test_generation_python_origin import module_graph


def descriptor(value: dict | None = None) -> python_code.Descriptor:
    return python_code.decode(record(fixture() if value is None else value))


def constants(*, unordered: bool, alias: int, bits: tuple[str, str]) -> dict:
    value = fixture()
    value["nodes"][1]["items"] = [7, 12]
    value["nodes"].extend([
        {"id": 9, "type": "float", "data": bits[0]},
        {"id": 10, "type": "float", "data": bits[1]},
        {"id": 11, "type": "frozenset" if unordered else "tuple", "items": [9, 10]},
        {"id": 12, "type": "tuple", "items": [11, alias]},
    ])
    return value


def renumber(value: dict, order: list[int]) -> dict:
    result = copy.deepcopy(value)
    mapping = {old: new for new, old in enumerate(order, 1)}
    nodes = []
    for old in order:
        node = result["nodes"][old - 1]
        node["id"] = mapping[old]
        if "items" in node:
            node["items"] = [mapping[item] for item in node["items"]]
        if "fields" in node:
            node["fields"] = {name: mapping[item] for name, item in node["fields"].items()}
        nodes.append(node)
    result["root"], result["nodes"] = mapping[result["root"]], nodes
    return result


def brute_constants(left: dict, right: dict) -> bool:
    # Enumerate every bijection of four extra nodes. This oracle never uses
    # the product matcher's pending work, pruning or rollback algorithm.
    for permutation in itertools.permutations(range(9, 13)):
        mapping = {identity: identity for identity in range(1, 9)}
        mapping.update(zip(range(9, 13), permutation))
        valid = True
        for identity, target in mapping.items():
            a, b = left["nodes"][identity - 1], right["nodes"][target - 1]
            if a["type"] != b["type"]:
                valid = False
                break
            if "items" in a:
                expected = [mapping[item] for item in a["items"]]
                valid = (set(expected) == set(b["items"]) if a["type"] == "frozenset" else expected == b["items"])
            elif "fields" in a:
                valid = (a["metadata"] == b["metadata"]
                         and {name: mapping[item] for name, item in a["fields"].items()} == b["fields"])
            else:
                valid = {key: value for key, value in a.items() if key != "id"} == {
                    key: value for key, value in b.items() if key != "id"}
            if not valid:
                break
        if valid:
            return True
    return False


class PythonCodeMatchTests(unittest.TestCase):
    def test_snapshot_ids_order_and_envelope_offsets_do_not_define_code_values(self) -> None:
        value = fixture()
        left = descriptor(value)
        right = descriptor(renumber(value, list(reversed(range(1, 9)))))
        right = replace(right, record=replace(right.record, offset=2, identity=17, sequence=2))
        budget = Budget()
        self.assertTrue(equivalent(left, left.root, right, budget))
        self.assertGreater(budget.steps, 0)
        root = descriptor(module_graph())
        self.assertTrue(equivalent(root, 9, left, Budget()))

    def test_values_bits_metadata_order_and_aliases_all_matter(self) -> None:
        original = descriptor()
        variants = []
        for index, field, value in ((3, "value", "other"), (5, "data", "970064005301")):
            changed = fixture(); changed["nodes"][index][field] = value; variants.append(changed)
        changed = fixture(); changed["nodes"][0]["metadata"]["co_firstlineno"] = 2; variants.append(changed)
        changed = fixture()
        changed["nodes"].append({"id": 9, "type": "unicode", "value": "workload"})
        changed["nodes"][0]["fields"]["co_qualname"] = 9; variants.append(changed)
        for changed in variants:
            with self.subTest(changed=changed):
                self.assertFalse(equivalent(original, original.root, descriptor(changed), Budget()))
        left = constants(unordered=False, alias=9, bits=("0000000000000000", "8000000000000000"))
        right = copy.deepcopy(left); right["nodes"][10]["items"].reverse()
        self.assertFalse(equivalent(descriptor(left), 1, descriptor(right), Budget()))

    def test_unordered_choices_backtrack_when_a_later_alias_requires_it(self) -> None:
        left = constants(unordered=True, alias=9, bits=("7ff8000000000001",) * 2)
        right = copy.deepcopy(left); right["nodes"][11]["items"][-1] = 10
        self.assertTrue(equivalent(descriptor(left), 1, descriptor(right), Budget()))
        right["nodes"][10]["items"].reverse()
        self.assertTrue(equivalent(descriptor(left), 1, descriptor(right), Budget()))
        right["nodes"][8]["data"] = "7ff8000000000002"
        self.assertFalse(equivalent(descriptor(left), 1, descriptor(right), Budget()))

    def test_existing_aliases_into_a_frozenset_are_checked_in_both_directions(self) -> None:
        left = constants(unordered=True, alias=9, bits=("7ff8000000000001",) * 2)
        left["nodes"][11]["items"] = [9, 11]
        right = copy.deepcopy(left)
        right["nodes"][10]["items"] = [10]
        self.assertFalse(equivalent(descriptor(left), 1, descriptor(right), Budget()))
        # An earlier ordered constraint fixes one equal leaf, then the set
        # must place the other distinct object without reusing that target.
        right = copy.deepcopy(left); right["nodes"][11]["items"][0] = 10
        self.assertTrue(equivalent(descriptor(left), 1, descriptor(right), Budget()))

    def test_exhaustive_small_bijection_oracle_agrees_for_seeded_graph_pairs(self) -> None:
        rng = random.Random(501)
        bits = ("0000000000000000", "8000000000000000", "7ff8000000000001")
        matched = refused = 0
        for _ in range(500):
            left = constants(unordered=bool(rng.randrange(2)), alias=rng.choice((9, 10)),
                             bits=(rng.choice(bits), rng.choice(bits)))
            right = copy.deepcopy(left)
            right["nodes"][11]["items"][-1] = rng.choice((9, 10))
            if rng.randrange(2):
                right["nodes"][10]["items"].reverse()
            if rng.randrange(3) == 0:
                right["nodes"][rng.choice((8, 9))]["data"] = rng.choice(bits)
            expected = brute_constants(left, right)
            matched += expected
            refused += not expected
            order = list(range(1, 13)); rng.shuffle(order)
            actual = equivalent(descriptor(left), 1, descriptor(renumber(right, order)), Budget())
            self.assertEqual(actual, expected)
        self.assertGreater(matched, 100)
        self.assertGreater(refused, 100)

    def test_budget_exhaustion_never_becomes_a_match_and_profiles_are_explicit(self) -> None:
        left = descriptor()
        with self.assertRaisesRegex(ValueError, "budget exceeded"):
            equivalent(left, 1, left, Budget(1))
        for limit in (0, True, 1_000_001):
            with self.assertRaises(ValueError):
                Budget(limit)
        self.assertFalse(equivalent(left, 1, replace(left, filesystem=("utf-8", "strict")), Budget()))
        changed = replace(left, record=replace(left.record, python_version=0x030e00f0))
        self.assertFalse(equivalent(left, 1, changed, Budget()))
        for candidate, member in ((None, 1), (left, True), (left, 0), (left, 9), (left, 3)):
            with self.assertRaises(ValueError):
                equivalent(candidate, member, left, Budget())


if __name__ == "__main__":
    unittest.main()
