"""Receiver qualification rejects matching lanes with incorrect graph contents."""

import copy
from pathlib import Path
import sys
import unittest

sys.path.insert(0, str(Path(__file__).resolve().parent))
import node_receiver_oracle as oracle


class NodeReceiverOracleTests(unittest.TestCase):
    def test_every_fixed_method_lane_and_reduced_argument_has_a_complete_oracle(self):
        for method in oracle.METHODS:
            for active in (False, True):
                for argument in (0, 7):
                    with self.subTest(method=method, active=active, argument=argument):
                        oracle.check(oracle.expected(method, argument, active), method, argument, active)
        with self.assertRaisesRegex(ValueError, "unknown"):
            oracle.expected("unknown", 7, False)

    def test_same_return_controls_require_their_independent_instance_or_static_difference(self):
        for method in ("silent", "static_only"):
            plain = oracle.expected(method, 7, False)
            active = oracle.expected(method, 7, True)
            self.assertEqual(plain["outcome"]["value"]["roots"]["result"],
                             active["outcome"]["value"]["roots"]["result"])
            with self.subTest(method=method), self.assertRaises(ValueError):
                oracle.check(plain, method, 7, True)

    def test_unchecked_fields_descriptors_aliases_and_exception_payloads_cannot_pass(self):
        value = oracle.expected("fail", 7, False)
        for fault in ("argument", "shared", "instances", "descriptor", "alias", "message", "prototype", "extra"):
            changed = copy.deepcopy(value)
            graph = changed["outcome"]["value"]
            if fault == "argument":
                graph["nodes"][0]["fields"][0][1] = oracle.number(99)
            elif fault == "shared":
                graph["nodes"][2]["fields"][0][1] = oracle.number(99)
            elif fault == "instances":
                graph["nodes"][4]["fields"][1][1] = oracle.number(99)
            elif fault == "descriptor":
                graph["nodes"][3]["fields"][2][1]["value"] = 1
            elif fault == "alias":
                graph["nodes"][1]["fields"][2][1] = {"ref": 0}
            elif fault == "message":
                graph["nodes"][6]["fields"][0][1]["value"] = "wrong"
            elif fault == "prototype":
                graph["nodes"][1]["prototype"] = "Object"
            else:
                changed["extra"] = "unexpected"
            with self.subTest(fault=fault), self.assertRaises(ValueError):
                oracle.check(changed, "fail", 7, False)


if __name__ == "__main__":
    unittest.main()
