"""Complete independently expected graphs for the four-state Counter corpus."""

import json

from node_collection_oracle import MISSING, canonical_observation, number
from node_receiver_oracle import array, descriptor, field

METHODS = ("add", "later", "expected", "difference")


def graph(argument: float, value: float, total: float, delta: int, *, result=MISSING, error=False) -> dict:
    roots = {"arguments": {"ref": 0}, "receiver": {"ref": 1},
             "static:Counter.total": {"ref": 2}, "static:Counter.delta": {"ref": 3}}
    nodes = [array([argument]),
             {"type": "object", "fields": [field("value", number(value)), field("self", {"ref": 1})],
              "prototype": "declared:controls.Counter", "extensible": True},
             descriptor(number(total)), descriptor(number(delta))]
    if result is not MISSING:
        roots["result"] = result
    if error:
        roots["error"] = {"ref": 4}
        nodes.append({"type": "TypeError", "fields": [["message", {"type": "string", "value": "expected"}, True, False, True]],
                      "prototype": "TypeError", "extensible": True})
    return {"roots": roots, "nodes": nodes}


def expected(method: str, argument: float, instrumented: bool) -> dict:
    if method not in METHODS:
        raise ValueError("unknown live-control fixture method")
    steps, value, total, delta = [], 10, 0, 0
    for index, amount in enumerate((argument, 2, 3, 4)):
        before = graph(amount, value, total, delta)
        value += amount
        total += amount
        if method == "difference" and amount == 2 and instrumented:
            delta = 1
        if method == "difference" and amount == 3:
            delta = 0
        error = method == "expected" and amount == 3
        outcome = graph(amount, value, total, delta, error=True) if error else graph(
            amount, value, total, delta, result=number(42))
        steps.append({"id": "step-" + str(index), "action": "call", "gaps": [], "before": before,
                      "outcome": {"kind": "error" if error else "return", "value": outcome},
                      "after": graph(amount, value, total, delta)})
    return {"before": steps[0]["before"], "outcome": steps[-1]["outcome"], "after": steps[-1]["after"], "steps": steps}


def check(value: dict, method: str, argument: float, instrumented: bool) -> None:
    """Only local reference numbering varies; no descriptor or field is ignored."""
    actual = json.dumps(canonical_observation(value), sort_keys=True)
    wanted = json.dumps(canonical_observation(expected(method, argument, instrumented)), sort_keys=True)
    if actual != wanted:
        raise ValueError("complete live-control fixture graph or outcome differs")
