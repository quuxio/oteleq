"""A matching but wrong Go result or state cannot pass the independent oracle."""
import copy
import hashlib
import json
from pathlib import Path
import sys
import tempfile
import unittest

sys.path.insert(0, str(Path(__file__).resolve().parent))
import qualify_go_receivers as qualifier


class GoReceiverQualificationTests(unittest.TestCase):
    def test_exact_oracle_rejects_matching_wrong_results_arguments_and_state(self):
        graph = {"roots": {"receiver": {"kind": "null"}, "argument:0": {"kind": "integer", "value": "3"},
                           "global:shared": {"kind": "reference", "node_id": "n0"},
                           "global:total": {"kind": "reference", "node_id": "n1"}},
                 "nodes": [{"id": "n0", "fields": {"value": {"kind": "null"}}},
                           {"id": "n1", "fields": {"value": {"kind": "integer", "value": "0"}}}]}
        result = copy.deepcopy(graph)
        result["roots"]["result"] = {"kind": "integer", "value": "3"}
        observed = {"before": graph, "after": graph, "gaps": [], "outcome": {"kind": "return", "graph": result}}
        attempt = {"observation": observed, "execution": {"witness": {"functions": {"counter.api.Counter.Read": 1}}}}
        bundle = {"cases": [{"baseline": [attempt, attempt], "instrumented_on": [attempt, attempt]}]}
        report = {"source_preserved": True, "blocked": [], "cases": [{"case": "case", "function": "counter.api.Counter.Read",
                  "arguments": [3], "exit_code": 0}]}
        with tempfile.TemporaryDirectory() as temporary:
            folder = Path(temporary)
            (folder / "case").mkdir()
            path = folder / "report.json"
            path.write_text(json.dumps(report))
            for lane in ("baseline", "instrumented_on"):
                for index in range(2):
                    target = folder / "case" / (lane + "-" + str(index))
                    target.mkdir()
                    (target / "stdout").write_bytes(b"")
                    (target / "stderr").write_bytes(b"")
                    helper = target / "project/oteleq_generated_observer/observer.go"
                    helper.parent.mkdir(parents=True)
                    helper.write_bytes(b"observer source")
                    (target / "build-identities.json").write_text(json.dumps({"loaded_input_count": 1}))
                    (target / "go-bundle").mkdir()
                    (target / "go-bundle/recipe.json").write_text(json.dumps({"inputs": {str(helper): {"sha256": hashlib.sha256(helper.read_bytes()).hexdigest()}}}))
            typed = folder / "case/typed-bundle.json"
            typed.write_text(json.dumps(bundle))
            self.assertEqual(qualifier.check_report(path, 1), 4)
            for change in ("result", "argument", "total", "shared"):
                altered = copy.deepcopy(bundle)
                for lane in ("baseline", "instrumented_on"):
                    for attempt in altered["cases"][0][lane]:
                        observation = attempt["observation"]
                        if change == "result":
                            observation["outcome"]["graph"]["roots"]["result"]["value"] = "30"
                        elif change == "argument":
                            observation["before"]["roots"]["argument:0"]["value"] = "30"
                        elif change == "total":
                            observation["after"]["nodes"][1]["fields"]["value"]["value"] = "1"
                        else:
                            observation["after"]["nodes"][0]["fields"]["value"] = {"kind": "reference", "node_id": "n1"}
                typed.write_text(json.dumps(altered))
                with self.subTest(change=change), self.assertRaises(AssertionError):
                    qualifier.check_report(path, 1)
