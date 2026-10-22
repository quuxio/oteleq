"""Complete literal graphs for the maintained Counter receiver qualification."""

import json

from node_collection_oracle import MISSING, canonical_observation, number

METHODS = {"add", "identity", "later", "silent", "static_only", "fail"}
TRUE = {"type": "boolean", "value": True}


def field(name: str, value: dict) -> list:
    return [name, value, True, True, True]


def array(values: list) -> dict:
    fields = [field(str(index), number(value)) for index, value in enumerate(values)]
    fields.append(["length", number(len(values)), True, False, False])
    return {"type": "array", "fields": fields, "prototype": "Array", "extensible": True}


def descriptor(value: dict) -> dict:
    fields = [field("present", TRUE), field("value", value)]
    fields.extend(field(name, TRUE) for name in ("writable", "enumerable", "configurable"))
    return {"type": "object", "fields": fields, "prototype": "Object", "extensible": True}


def graph(argument: float, value: float, total: float, shared: list,
          *, result=MISSING, error: bool = False) -> dict:
    roots = {"arguments": {"ref": 0}, "receiver": {"ref": 1},
             "static:Counter.total": {"ref": 3}, "static:Counter.instances": {"ref": 4},
             "static:Counter.shared": {"ref": 5}}
    nodes = [array([argument]),
             {"type": "object", "fields": [field("value", number(value)), field("alias", {"ref": 1}),
              field("shared", {"ref": 2})], "prototype": "declared:sample.Counter", "extensible": True},
             array(shared), descriptor(number(total)), descriptor(number(1)), descriptor({"ref": 2})]
    if result is not MISSING:
        roots["result"] = result
    if error:
        roots["error"] = {"ref": 6}
        nodes.append({"type": "TypeError", "fields": [["message", {"type": "string", "value": "expected"}, True, False, True]],
                      "prototype": "TypeError", "extensible": True})
    return {"roots": roots, "nodes": nodes}


def expected(method: str, argument: float, active: bool) -> dict:
    if method not in METHODS:
        raise ValueError("unknown receiver qualification method")
    value = 10 if method == "static_only" else 10 + argument + int(active and method == "silent")
    total = argument + int(active and method == "static_only")
    shared = [] if method in {"silent", "static_only"} else [argument]
    result = {"ref": 1} if method == "identity" else number(value if method in {"add", "later"} else 7)
    outcome = graph(argument, value, total, shared, error=True) if method == "fail" else graph(
        argument, value, total, shared, result=result)
    return {"before": graph(argument, 10, 0, []),
            "outcome": {"kind": "error" if method == "fail" else "return", "value": outcome},
            "after": graph(argument, value, total, shared)}


def check(value: dict, method: str, argument: float, active: bool) -> None:
    """Check every value, descriptor and alias; only local reference IDs may vary."""
    actual = json.dumps(canonical_observation(value), sort_keys=True)
    wanted = json.dumps(canonical_observation(expected(method, argument, active)), sort_keys=True)
    if actual != wanted:
        raise ValueError("complete receiver fixture graphs or outcome differ")
