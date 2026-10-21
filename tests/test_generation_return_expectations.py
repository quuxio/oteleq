"""Declared return values remain independent of both application observations."""
import copy
from pathlib import Path
import sys
import unittest

sys.path[:0] = [str(Path(__file__).resolve().parents[1] / "adapters/generation"),
                str(Path(__file__).resolve().parents[1] / "examples")]
import policy
import return_expectations as expected


class ReturnExpectationTests(unittest.TestCase):
    def test_supported_values_preserve_types_bits_and_code_units(self):
        values = [{"kind": "null"}, {"kind": "undefined"}, {"kind": "unit", "type": "rust.unit"},
                  {"kind": "boolean", "value": False}, {"kind": "boolean", "type": "python.bool", "value": True},
                  {"kind": "integer", "type": "c.int", "value": "-7", "bits": 32, "signed": True},
                  {"kind": "float", "type": "java.double", "bits": "8000000000000000"},
                  {"kind": "float", "type": "python.float64", "bits": "7ff8000000000001"},
                  {"kind": "bytes", "type": "python.bytes", "hex": "00ff"}]
        for encoding, payload in (("utf8", "c3a9"), ("utf16_be", "d800"),
                                  ("codepoints32_be", "0000d800"), ("raw_bytes", "ff00")):
            values.append({"kind": "string", "type": "declared.string", "encoding": encoding, "value": payload})
        for value in values:
            with self.subTest(value=value):
                self.assertEqual(expected.validate(value), value)
                declared = {"kind": "return_value", "value": value}
                self.assertEqual(policy.expected_baseline(declared), declared)
                self.assertIsNot(expected.validate(value), value)

    def test_unbounded_integer_width_is_frozen_explicitly(self):
        value = {"kind": "integer", "type": "python.int", "value": str(2**200), "signed": True}
        result = expected.validate(value)
        self.assertEqual(result, {**value, "bits": None})
        self.assertEqual(expected.validate(result), result)
        self.assertNotIn("bits", value)

    def test_missing_extra_opaque_reference_and_unbound_fields_refuse(self):
        bad = [None, 7, {}, {"kind": []}, {"kind": "unbound"}, {"kind": "reference", "node_id": "n0"},
               {"kind": "opaque", "type": "x", "reason": "unknown"}, {"kind": "null", "value": 0},
               {"kind": "unit"}, {"kind": "unit", "type": ""}, {"kind": "unit", "type": "x" * 1025},
               {"kind": "unit", "type": "\u00e9" * 513}, {"kind": "unit", "type": "\ud800"},
               {"kind": "boolean", "value": 1}, {"kind": "boolean", "value": True, "type": None}]
        for value in bad:
            with self.subTest(value=value), self.assertRaises(ValueError):
                expected.validate(value)
        for value in ({"kind": "return_value"}, {"kind": "return", "value": {"kind": "null"}},
                      {"kind": "return_value", "value": {"kind": "null"}, "type": "extra"}):
            with self.subTest(value=value), self.assertRaises(ValueError):
                policy.expected_baseline(value)

    def test_noncanonical_out_of_range_or_invalid_integers_refuse(self):
        value = {"kind": "integer", "type": "c.int", "value": "7", "bits": 32, "signed": True}
        changes = [{"value": "01"}, {"value": "-0"}, {"value": ""}, {"value": 7},
                   {"value": "1" * 4097}, {"value": str(2**31)}, {"signed": 1},
                   {"signed": False, "value": "-1"}, {"bits": True}, {"bits": 7}, {"bits": "32"}]
        for change in changes:
            with self.subTest(change=change), self.assertRaises(ValueError):
                expected.validate({**value, **change})

    def test_noncanonical_bytes_floats_and_invalid_encodings_refuse(self):
        bad = [{"kind": "bytes", "type": "bytes", "hex": payload}
               for payload in (None, "Ff", "0", "zz", "00 ff", "00" * (expected.MAX_TEXT + 1))]
        bad.extend({"kind": "float", "type": "float", "bits": bits} for bits in (0, "0", "fffff", "FFFF"))
        bad.extend({"kind": "string", "type": "string", "encoding": encoding, "value": payload}
                   for encoding, payload in (([], ""), ("other", ""), ("utf8", "ff"),
                                             ("utf16_be", "ff"), ("codepoints32_be", "00"),
                                             ("codepoints32_be", "00110000")))
        for value in bad:
            with self.subTest(value=value), self.assertRaises(ValueError):
                expected.validate(value)

    def test_sequence_calls_accept_values_and_release_cannot_claim_a_return(self):
        fixture = {"function": "Counter.run", "cases": [[1]],
                   "receiver": {"factory": "Counter", "arguments": []},
                   "sequence": [{"action": "call", "arguments": "case",
                                 "expected_baseline": {"kind": "return_value", "value": {"kind": "null"}}}]}
        parsed = policy.fixture(fixture, 0)
        self.assertEqual(parsed["sequence"][0]["expected_baseline"], fixture["sequence"][0]["expected_baseline"])
        changed = copy.deepcopy(fixture)
        changed["sequence"][0]["action"] = "release"
        with self.assertRaises(ValueError):
            policy.fixture(changed, 0)


if __name__ == "__main__":
    unittest.main()
