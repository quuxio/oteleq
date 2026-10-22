"""The live-control oracle must reject changes anywhere in its complete graphs."""

import copy
import sys
from pathlib import Path
import tomllib
import unittest

ROOT = Path(__file__).resolve().parents[1]
sys.path[:0] = [str(ROOT / "adapters/generation"), str(ROOT / "examples")]
import node_controls_oracle as oracle
import policy
import qualify_node_controls as qualification


class NodeControlsOracleTests(unittest.TestCase):
    def test_literal_graphs_include_every_intermediate_state_and_expected_error(self):
        for method in oracle.METHODS:
            for active in (False, True):
                expected = oracle.expected(method, 7, active)
                oracle.check(expected, method, 7, active)
                for changed in ("value", "descriptor", "alias", "field-order", "extra", "outcome"):
                    altered = copy.deepcopy(expected)
                    graph = altered["steps"][1]["after"]
                    if changed == "value":
                        graph["nodes"][1]["fields"][0][1] = oracle.number(999)
                    elif changed == "descriptor":
                        graph["nodes"][2]["fields"][0][1]["value"] = 1
                    elif changed == "alias":
                        graph["nodes"][1]["fields"][1][1] = {"ref": 0}
                    elif changed == "field-order":
                        graph["nodes"][1]["fields"].reverse()
                    elif changed == "extra":
                        graph["unknown"] = True
                    else:
                        altered["steps"][0]["outcome"]["value"]["roots"]["result"] = oracle.number(41)
                    with self.subTest(method=method, active=active, changed=changed), self.assertRaises(ValueError):
                        oracle.check(altered, method, 7, active)
        self.assertEqual(oracle.expected("expected", 7, True)["steps"][2]["outcome"]["kind"], "error")
        with self.assertRaises(ValueError):
            oracle.expected("unknown", 7, False)

    def test_reviewed_policy_selects_only_methods_and_retains_all_four_states(self):
        for language, compiler in (("javascript", "native"), ("typescript", "native"), ("typescript", "api")):
            configuration = policy.validate(tomllib.loads(qualification.policy(language, compiler)))
            self.assertEqual(configuration["functions"]["include"], ["controls.Counter." + method for method in oracle.METHODS])
            self.assertEqual(len(configuration["fixtures"]), 4)
            for fixture in configuration["fixtures"]:
                self.assertEqual([step["metrics"] for step in fixture["sequence"]], list(qualification.STATES))
            source = qualification.source(language)
            self.assertIn("Buffer.from([0,255,10])", source)
            self.assertIn("Buffer.from([1,255,10])", source)
            self.assertIn("throw new TypeError('expected')", source)
            self.assertIn("Counter.delta=0", source)
