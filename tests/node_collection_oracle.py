"""Complete literal raw graphs for the declared two-call collection fixture."""

import copy
import json
import struct

MISSING = object()
COLLECTION_GAP = {"phase": "after", "path": "/collection",
                  "reason": "collection was not observed within the declared bound; no leak inference"}


def number(value: float) -> dict:
    return {"type": "float64", "bits": struct.pack(">d", value).hex()}


def graph(argument: float, receiver: float | None, *, held: bool = False,
          result=MISSING) -> dict:
    roots = {"arguments": {"ref": 0}, "receiver": {"ref": 1} if receiver is not None else {"type": "null"}}
    nodes = [{"type": "array", "fields": [["0", number(argument), True, True, True],
              ["length", number(1), True, False, False]], "prototype": "Array", "extensible": True}]
    if held:
        roots["global:held"] = {"ref": 1}
    value = receiver if receiver is not None else 19 if held else None
    if value is not None:
        nodes.append({"type": "object", "fields": [["value", number(value), True, True, True],
                      ["self", {"ref": 1}, True, True, True]],
                      "prototype": "declared:seq.Counter", "extensible": True})
    if result is not MISSING:
        roots["result"] = result
    return {"roots": roots, "nodes": nodes}


def expected(held: bool = False) -> dict:
    steps = []
    values = (("call", 7, 10, 17, number(17)), ("call", 2, 17, 19, number(19)),
              ("release", 2, 19, None, {"type": "undefined"}),
              ("collect", 2, None, None, {"type": "boolean", "value": not held}))
    for index, (action, argument, before, after, result) in enumerate(values):
        steps.append({"id": "step-" + str(index), "action": action,
                      "gaps": [COLLECTION_GAP] if held and action == "collect" else [],
                      "before": graph(argument, before, held=held),
                      "outcome": {"kind": "return", "value": graph(argument, after, held=held, result=result)},
                      "after": graph(argument, after, held=held)})
    return {"before": steps[0]["before"], "outcome": steps[1]["outcome"],
            "after": steps[-1]["after"], "steps": steps}


def canonical_graph(graph: dict) -> dict:
    """Local reference numbers may differ; fields, ordering and aliases must agree."""
    if set(graph) != {"roots", "nodes"}:
        raise ValueError("unknown collection graph fields")
    references, nodes = {}, []

    def walk(value):
        if type(value) is list:
            return [walk(item) for item in value]
        if type(value) is not dict:
            return value
        if set(value) != {"ref"}:
            return {key: walk(item) for key, item in value.items()}
        original = value["ref"]
        if type(original) is not int or not 0 <= original < len(graph["nodes"]):
            raise ValueError("invalid collection graph reference")
        if original not in references:
            references[original] = len(nodes)
            nodes.append(None)
            nodes[references[original]] = walk(graph["nodes"][original])
        return {"ref": references[original]}

    roots = {key: walk(graph["roots"][key]) for key in sorted(graph["roots"])}
    if len(nodes) != len(graph["nodes"]):
        raise ValueError("unreferenced collection graph node")
    return {"roots": roots, "nodes": nodes}


def canonical_observation(value):
    """Normalise only graph references, preserving the complete observation payload."""
    if type(value) is list:
        return [canonical_observation(item) for item in value]
    if type(value) is dict:
        if {"roots", "nodes"} <= set(value):
            return canonical_graph(value)
        return {key: canonical_observation(item) for key, item in value.items()}
    return value


def check(value: dict, *, held: bool = False) -> None:
    """Only the bounded GC turn count varies; all application graphs are literal."""
    actual = copy.deepcopy(value)
    collection = actual["steps"][-1].pop("collection")
    if (set(collection) != {"completed", "rounds"} or collection["completed"] is not (not held)
            or type(collection["rounds"]) is not int or not 1 <= collection["rounds"] <= 64):
        raise ValueError("collection completion or bounded round count differs")
    actual_bytes = json.dumps(canonical_observation(actual), sort_keys=True)
    expected_bytes = json.dumps(canonical_observation(expected(held)), sort_keys=True)
    if actual_bytes != expected_bytes:
        raise ValueError("complete collection fixture graphs or action outcomes differ")
