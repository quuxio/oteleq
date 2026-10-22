"""Literal collection observations reject equal-but-wrong graphs and SDK counts."""

import copy
from pathlib import Path
import sys
import tomllib
import unittest

sys.path.insert(0, str(Path(__file__).resolve().parent))
import node_collection_oracle as oracle
import qualify_node_source_collection as qualifier


class NodeCollectionOracleTests(unittest.TestCase):
    def observation(self, held=False):
        value = copy.deepcopy(oracle.expected(held))
        value["steps"][-1]["collection"] = {"completed": not held, "rounds": 64 if held else 3}
        return value

    def test_complete_graphs_and_explicitly_retained_object_have_separate_outcomes(self):
        for held in (False, True):
            with self.subTest(held=held):
                oracle.check(self.observation(held), held=held)
        self.assertNotEqual(oracle.expected(), oracle.expected(True))

    def test_return_state_arguments_aliases_order_and_gap_changes_refuse(self):
        for fault in ("result", "state", "argument", "alias", "flags", "numeric-flag", "order", "extra", "gap"):
            value = self.observation()
            if fault == "result":
                value["outcome"]["value"]["roots"]["result"] = oracle.number(99)
            elif fault == "state":
                value["before"]["nodes"][1]["fields"][0][1] = oracle.number(99)
            elif fault == "argument":
                value["steps"][1]["before"]["nodes"][0]["fields"][0][1] = oracle.number(99)
            elif fault == "alias":
                value["before"]["nodes"][1]["fields"][1][1] = {"ref": 0}
            elif fault == "flags":
                value["before"]["nodes"][1]["fields"][0][2] = False
            elif fault == "numeric-flag":
                value["before"]["nodes"][1]["fields"][0][2] = 1
            elif fault == "order":
                value["before"]["nodes"][1]["fields"].reverse()
            elif fault == "extra":
                value["after"]["roots"]["extra"] = oracle.number(1)
            else:
                value["steps"][0]["gaps"] = [oracle.COLLECTION_GAP]
            with self.subTest(fault=fault), self.assertRaises(ValueError):
                oracle.check(value)

    def test_gc_completion_and_round_budget_are_not_fabricated(self):
        for replacement in ({"completed": 1, "rounds": 3}, {"completed": False, "rounds": 3},
                            {"completed": True, "rounds": True}, {"completed": True, "rounds": 0},
                            {"completed": True, "rounds": 65}, {"completed": True, "rounds": 3, "extra": 1}):
            value = self.observation()
            value["steps"][-1]["collection"] = replacement
            with self.subTest(replacement=replacement), self.assertRaises(ValueError):
                oracle.check(value)

    def test_reference_relabelling_keeps_aliases_but_unreachable_or_invalid_nodes_refuse(self):
        value = self.observation(held=True)
        graph = copy.deepcopy(value["before"])
        graph["nodes"].reverse()

        def relabel(item):
            if type(item) is list:
                return [relabel(part) for part in item]
            if type(item) is dict:
                if set(item) == {"ref"}:
                    return {"ref": 1 - item["ref"]}
                return {key: relabel(part) for key, part in item.items()}
            return item

        value["before"] = relabel(graph)
        oracle.check(value, held=True)
        for fault in ("invalid", "unreachable", "unknown"):
            changed = self.observation()
            graph = changed["before"]
            if fault == "invalid":
                graph["roots"]["receiver"] = {"ref": True}
            elif fault == "unreachable":
                graph["nodes"].append(copy.deepcopy(graph["nodes"][0]))
            else:
                graph["extra"] = "unknown"
            with self.subTest(fault=fault), self.assertRaises(ValueError):
                oracle.check(changed)

    def test_equal_invalid_sdk_lifetime_counts_cannot_qualify_the_fixture(self):
        sdk = {"function_completions": 3, "span_accounting": {"received": 4},
               "lifetimes": {"admitted": 1, "gc_completed": 1, "resource_completed": 0, "censored": 0, "current_live": 0}}
        qualifier.check_sdk(sdk)
        for count in (0, 2, True):
            changed = copy.deepcopy(sdk)
            changed["lifetimes"].update(admitted=count, gc_completed=count)
            with self.subTest(count=count), self.assertRaises(ValueError):
                qualifier.check_sdk(changed)

    def test_retained_receiver_requires_actual_censored_counts_without_gc_spans(self):
        sdk = {"function_completions": 3, "span_accounting": {"received": 3},
               "lifetimes": {"admitted": 1, "gc_completed": 0, "resource_completed": 0, "censored": 1, "current_live": 1}}
        qualifier.check_sdk(sdk, held=True)
        for section, key in (("lifetimes", "censored"), ("lifetimes", "current_live"),
                             ("lifetimes", "resource_completed"), ("lifetimes", "gc_completed"),
                             ("span_accounting", "received")):
            changed = copy.deepcopy(sdk)
            changed[section][key] += 1
            with self.subTest(section=section, key=key), self.assertRaises(ValueError):
                qualifier.check_sdk(changed, held=True)

    def test_fixed_policy_and_source_do_not_reuse_the_legacy_provider(self):
        for language in ("javascript", "typescript"):
            for compiler in ("native", "api"):
                config = tomllib.loads(qualifier.policy(language, compiler))
                self.assertEqual(config["adapters"]["node"], {"backend": "source-v1", "typescript_compiler": compiler})
                self.assertEqual(config["fixtures"][0]["cases"], [[7]])
                self.assertEqual([step["action"] for step in config["fixtures"][0]["sequence"]],
                                 ["call", "call", "release", "collect"])
            self.assertIn("held=new Counter(start);return held;", qualifier.fixture(language, held=True))


if __name__ == "__main__":
    unittest.main()
