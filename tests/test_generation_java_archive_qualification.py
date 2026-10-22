"""Reject equal-but-wrong JDK archive values and incomplete retained observations."""
import copy
import json
from pathlib import Path
import sys
import tempfile
import unittest

sys.path.insert(0, str(Path(__file__).resolve().parent))
import java_archive_oracle as oracle
import java_project_oracle as project


def observed(variant: str, instrumented: bool = False, amount: int = 7) -> dict:
    before = oracle.state(variant, amount, after=False, instrumented=instrumented)
    after = oracle.state(variant, amount, after=True, instrumented=instrumented)
    return {"function_id": oracle.FUNCTION, "fixture": {"status": "ready"}, "gaps": [],
            "before": before, "after": after, "outcome": {"kind": "return", "graph": {
                "nodes": [], "roots": {**after["roots"], "result": project.scalar(oracle.result(variant, amount))}}}}


class JavaArchiveOracleTests(unittest.TestCase):
    def test_each_variant_has_independently_fixed_component_values(self):
        expected = {"ordinary": (5, 5, 13, 41), "inactive": (5, 5, 13, 41), "false": (5, 5, 13, 41),
                    "active": (21, 21, 29, 89), "intermediate": (17, 17, 25, 77), "future": (5, 5, 13, 41),
                    "version-only": (9, 9, 17, 53), "folded": (21, 5, 13, 57),
                    "identical": (5, 5, 29, 57), "collision": (21, 21, 29, 89), "mutation": (21, 21, 29, 7)}
        self.assertEqual(set(expected), set(oracle.VARIANTS))
        for variant, (compiled, method, resource, result) in expected.items():
            self.assertEqual(oracle.result(variant, 7), result)
            for lane in (False, True):
                value = observed(variant, lane)
                roots = value["after"]["roots"]
                for name, number in (("compiled", compiled), ("method", method), ("resource", resource)):
                    self.assertEqual(roots["global:App." + name], project.scalar(number))
                oracle.observation(value, variant, 7, lane)
                for fault in ("result", "initial", "component", "type", "extra", "gaps", "function"):
                    changed = copy.deepcopy(value)
                    if fault == "result": changed["outcome"]["graph"]["roots"]["result"]["value"] = "wrong"
                    elif fault == "initial": changed["before"]["roots"]["global:App.total"]["value"] = "3"
                    elif fault == "component": changed["after"]["roots"]["global:App.compiled"]["value"] = "0"
                    elif fault == "type": changed["after"]["roots"]["global:App.compiled"]["type"] = "java.int"
                    elif fault == "extra": changed["after"]["roots"]["unknown"] = project.scalar(1)
                    elif fault == "gaps": changed["gaps"] = ["missing"]
                    else: changed["function_id"] = "Wrong.selected(int)"
                    with self.subTest(variant=variant, lane=lane, fault=fault), self.assertRaises(AssertionError):
                        oracle.observation(changed, variant, 7, lane)
        oracle.observation(observed("mutation", True, 0), "mutation", 0, True)

    def test_equal_results_cannot_hide_different_compiler_and_runtime_components(self):
        folded = observed("folded")
        identical = observed("identical")
        self.assertEqual(folded["outcome"]["graph"]["roots"]["result"], identical["outcome"]["graph"]["roots"]["result"])
        with self.assertRaises(AssertionError):
            oracle.observation(identical, "folded", 7, False)
        with self.assertRaises(AssertionError):
            oracle.observation(folded, "identical", 7, False)
        self.assertEqual(oracle.member("folded", compiler=True), "META-INF/versions/21/dep/Library.class")
        self.assertEqual(oracle.member("folded", compiler=False), "dep/Library.class")
        self.assertEqual(oracle.member("identical", compiler=False), "META-INF/versions/21/dep/Library.class")
        self.assertEqual(oracle.member("version-only", compiler=True), "META-INF/versions/9/dep/Library.class")

    def test_reports_require_complete_repeats_channels_witness_and_state(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            case = root / "case"
            case.mkdir()
            report = root / "report.json"
            for variant in ("active", "mutation"):
                captured = {"contract": {"function_id": oracle.FUNCTION}}
                for lane in ("baseline", "instrumented_on"):
                    captured[lane] = [{"observation": observed(variant, lane == "instrumented_on"),
                        "execution": {"channels": {"stdout": [], "stderr": []},
                                      "witness": {"functions": {oracle.FUNCTION: 1}, "losses": {"dropped": 0}}}}
                        for _ in range(2)]
                original = json.dumps({"cases": [captured]})
                report.write_text(json.dumps({"source_preserved": True, "blocked": [], "cases": [
                    {"case": "case", "function": oracle.FUNCTION, "arguments": [7], "exit_code": int(variant == "mutation")}]}))
                bundle = case / "typed-bundle.json"
                bundle.write_text(original)
                self.assertEqual(oracle.check_report(report, variant)[0], 4)
                for fault in ("repeat", "function", "loss", "stdout", "state"):
                    changed = json.loads(original)
                    attempts = changed["cases"][0]["instrumented_on"]
                    if fault == "repeat": attempts.pop()
                    elif fault == "function": attempts[0]["execution"]["witness"]["functions"] = {"wrong": 1}
                    elif fault == "loss": attempts[0]["execution"]["witness"]["losses"]["dropped"] = 1
                    elif fault == "stdout": attempts[0]["execution"]["channels"]["stdout"] = [99]
                    else: attempts[0]["observation"]["after"]["roots"].clear()
                    bundle.write_text(json.dumps(changed))
                    with self.subTest(variant=variant, fault=fault), self.assertRaises(AssertionError):
                        oracle.check_report(report, variant)


if __name__ == "__main__":
    unittest.main()
