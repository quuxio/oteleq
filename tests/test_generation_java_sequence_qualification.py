"""Independent sequence fixture oracles reject equal but incorrect captures."""
import copy
from pathlib import Path
import sys
import unittest

sys.path.insert(0, str(Path(__file__).resolve().parent))
import qualify_java_sequences as qualifier
from test_generation_java_qualification import integer, reference, state


def graph(value, total, argument):
    result = state(value, total)
    result["roots"]["argument:0"] = integer(argument)
    return result


def observation(method, active=False):
    first = 17 + int(method == "transient" and active)
    steps = []
    for index, (before, after, total, argument) in enumerate(((10, first, 0, 7), (first, 19, 7, 2))):
        before_graph, after_graph = graph(before, total, argument), graph(after, total + argument, argument)
        outcome = copy.deepcopy(after_graph)
        error = method == "fail" and index == 0
        if error:
            outcome["roots"]["error"] = reference(2)
            outcome["nodes"] += [{"id": "n2", "type": "java.lang.IllegalArgumentException", "fields": {"message": reference(3)}},
                                qualifier_string()]
        else:
            outcome["roots"]["result"] = reference(0) if method == "identity" else integer(after if method == "secret" else 7)
        value = {"kind": "error" if error else "return", "graph": outcome}
        if error:
            value["category"] = "exception"
        steps.append({"id": "step-" + str(index), "action": "call", "gaps": [],
                      "before": before_graph, "outcome": value, "after": after_graph})
    return {"before": copy.deepcopy(steps[0]["before"]), "outcome": copy.deepcopy(steps[-1]["outcome"]),
            "after": copy.deepcopy(steps[-1]["after"]), "gaps": [], "steps": steps}


def qualifier_string():
    return {"id": "n3", "type": "java.object:java.lang.String", "fields": {
        "value": {"kind": "string", "type": "java.lang.String", "encoding": "utf16_be", "value": "00650078007000650063007400650064"}}}


class JavaSequenceQualificationTests(unittest.TestCase):
    def test_every_outcome_has_complete_literal_graphs_in_both_lanes(self):
        for method in qualifier.METHODS:
            for active in (False, True):
                qualifier.check_observation(observation(method, active), method, 7, active)

    def test_equal_outer_results_do_not_hide_intermediate_state_or_argument_edits(self):
        original = observation("identity")
        edits = [lambda item: item["steps"].pop(),
                 lambda item: item["steps"].reverse(),
                 lambda item: item["steps"][0].update(id="step-1"),
                 lambda item: item["steps"][0].update(action="release"),
                 lambda item: item["steps"][0]["gaps"].append("missing"),
                 lambda item: item["steps"][0]["outcome"].update(kind="error"),
                 lambda item: item["steps"][0]["after"]["nodes"][0]["fields"]["value"].update(value="18"),
                 lambda item: item["steps"][1]["before"]["roots"]["argument:0"].update(value="3"),
                 lambda item: item["steps"][1]["after"]["roots"]["static:Counter.total"].update(value="10"),
                 lambda item: item["steps"][0]["outcome"]["graph"]["roots"].update(result=reference(1)),
                 lambda item: item["after"]["nodes"][0]["fields"]["value"].update(value="20")]
        for index, edit in enumerate(edits):
            altered = copy.deepcopy(original);edit(altered)
            with self.subTest(index=index), self.assertRaises(AssertionError):
                qualifier.check_observation(altered, "identity", 7, False)


if __name__ == "__main__":
    unittest.main()
