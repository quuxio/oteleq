"""Independent source-value expectations cannot accept a shared wrong result."""
import copy
import json
from pathlib import Path
import struct
import sys
import unittest

sys.path.insert(0, str(Path(__file__).resolve().parent))
import qualify_project_policy as qualification


def captures(language: str, name: str, arguments: list, result: dict) -> tuple:
    """Supply minimal raw/typed fixture records for the independent oracle."""
    case = {"function": name, "arguments": arguments}
    entry = {"language": language, "name": name, "path": "fixed-source"}
    before = {"roots": {}, "nodes": []}
    if language in ("javascript", "typescript"):
        before = {"roots": {"arguments": {"ref": 0}}, "nodes": [{"fields": [
            ["0", {"type": "float64", "bits": struct.pack(">d", arguments[0]).hex()}]]}]}
    raw = {lane: [{"channels": {"state-and-outcome": list(json.dumps({"before": before}).encode())}}
                  for _ in range(3)] for lane in ("baseline", "instrumented_on")}
    typed = {lane: [{"observation": {"outcome": {"kind": "return", "graph": {
        "roots": {"result": copy.deepcopy(result)}, "nodes": []}}}}
                    for _ in range(3)] for lane in raw}
    return case, entry, raw, typed


class PolicyQualificationTests(unittest.TestCase):
    def test_same_wrong_result_in_both_lanes_fails_the_independent_oracle(self):
        case = {"function": "target.add", "arguments": [7]}
        entry = {"language": "python", "path": "target.py", "name": "add"}
        graph = {"roots": {"result": {"kind": "integer", "type": "python.int",
                                      "value": "9", "bits": None, "signed": True}}, "nodes": []}
        capture = {"before": {"roots": {}, "nodes": []},
                   "outcome": {"kind": "return", "value": graph},
                   "after": {"roots": {}, "nodes": []}}
        raw = {lane: [{"channels": {"state-and-outcome": list(json.dumps(capture).encode())}}
                      for _ in range(3)] for lane in ("baseline", "instrumented_on")}
        typed = {lane: [{"observation": {"outcome": {"kind": "return", "graph": copy.deepcopy(graph)}}}
                        for _ in range(3)] for lane in raw}
        with self.assertRaises(AssertionError):
            qualification.check_case(case, entry, raw, typed)

    def test_known_fixture_oracles_cover_all_languages_and_value_extremes(self):
        for language in ("c", "cpp", "rust", "python", "java", "javascript", "typescript", "go"):
            expected = ({"kind": "float", "bits": "4020000000000000"}
                        if language in ("javascript", "typescript") else {"kind": "integer", "value": "8"})
            with self.subTest(language=language):
                data = captures(language, "add", [7], expected)
                self.assertEqual(qualification.expected_result(*data[:2]), expected)
                qualification.check_case(*data)
        for language, name, value in (("c", "echo", 2**64-1), ("cpp", "echo", -(2**63)),
                                      ("rust", "echo", 2**128-1), ("go", "echo", 2**64-1),
                                      ("java", "unicode.UnicodeCases.wide(long)", -(2**63))):
            data = captures(language, name, [value], {"kind": "integer", "value": str(value)})
            qualification.check_case(*data)
        qualification.check_case(*captures("python", "add", [2**100], {"kind": "integer", "value": str(2**100+1)}))
        qualification.check_case(*captures("java", "unicode.UnicodeCases.unit(int)", [55296],
                                          {"kind": "string", "encoding": "utf16_be", "value": "d800"}))

    def test_unicode_units_and_float32_bits_require_the_complete_value(self):
        unicode = captures("java", "unicode.UnicodeCases.text(java.lang.String)", ["\u00e9\x00\U0001f600"],
                           {"kind": "string", "encoding": "utf16_be", "value": "00e90000d83dde00d800"})
        qualification.check_case(*unicode)
        for language in ("c", "cpp", "rust", "go", "java"):
            for value in (1.3, -0.0):
                expected = {"kind": "float", "bits": struct.pack(">f", value).hex()}
                data = captures(language, "decimal", [value], expected)
                qualification.check_case(*data)
                data[3]["instrumented_on"][2]["observation"]["outcome"]["graph"]["roots"]["result"]["bits"] += "00"
                with self.assertRaises(AssertionError):
                    qualification.check_case(*data)
        unicode[3]["instrumented_on"][1]["observation"]["outcome"]["graph"]["roots"]["result"]["value"] += "0000"
        with self.assertRaises(AssertionError):
            qualification.check_case(*unicode)

    def test_every_repeat_and_lane_must_match_the_literal_oracle(self):
        for lane in ("baseline", "instrumented_on"):
            for repeat in range(3):
                for altered in ("9", "80", "prefix8", True):
                    data = captures("python", "add", [7], {"kind": "integer", "value": "8"})
                    data[3][lane][repeat]["observation"]["outcome"]["graph"]["roots"]["result"]["value"] = altered
                    with self.subTest(lane=lane, repeat=repeat, altered=altered), self.assertRaises(AssertionError):
                        qualification.check_case(*data)

    def test_node_arguments_preserve_negative_values_and_signed_zero(self):
        for language in ("javascript", "typescript"):
            for argument in (-1.0, -0.0, 0.0, 7.0):
                data = captures(language, "add", [argument], {"kind": "float", "bits": struct.pack(">d", argument+1).hex()})
                qualification.check_case(*data)
            data = captures(language, "add", [-0.0], {"kind": "float", "bits": "3ff0000000000000"})
            attempt = data[2]["baseline"][2]
            raw = bytes(attempt["channels"]["state-and-outcome"])
            attempt["channels"]["state-and-outcome"] = list(raw.replace(b"8000000000000000", b"0000000000000000"))
            with self.assertRaises(AssertionError):
                qualification.check_case(*data)

    def test_unknown_fixture_missing_outcome_or_unpaired_observations_refuse(self):
        data = captures("python", "unrecognised", [7], {"kind": "integer", "value": "8"})
        with self.assertRaises(AssertionError):
            qualification.check_case(*data)
        data = captures("python", "add", [7], {"kind": "integer", "value": "8"})
        data[3]["baseline"].pop()
        with self.assertRaises(AssertionError):
            qualification.check_case(*data)
        for change in ("missing", "error"):
            data = captures("python", "add", [7], {"kind": "integer", "value": "8"})
            outcome = data[3]["baseline"][0]["observation"]["outcome"]
            if change == "missing":
                del outcome["graph"]["roots"]["result"]
            else:
                outcome["kind"] = "error"
            with self.assertRaises(AssertionError):
                qualification.check_case(*data)


if __name__ == "__main__":
    unittest.main()
