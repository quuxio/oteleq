"""Freeze ordered receiver calls and explicit release/collection boundaries."""
from collections.abc import Callable
import copy
import math
from typing import Any

import preconditions

MAX_STEPS = 32


def fixture(value: dict, expected_outcome: Callable) -> list[dict]:
    """An action schedule always belongs to a declared independently built receiver."""
    if "receiver" not in value:
        raise ValueError("fixture.sequence requires a declared receiver")
    return validate(value["sequence"], expected_outcome)


def validate(value: Any, expected_outcome: Callable) -> list[dict]:
    """Require bounded calls followed by optional release and collection steps."""
    if not isinstance(value, list) or not 1 <= len(value) <= MAX_STEPS:
        raise ValueError("fixture.sequence requires 1 to 32 declared steps")
    result, released, collected, uses_case = [], False, False, False
    for step in value:
        if not isinstance(step, dict):
            raise ValueError("sequence steps require an action object")
        action = step.get("action")
        if action == "call" and not released:
            item = call(step, expected_outcome)
            uses_case |= item["arguments"] == "case"
        elif action == "release" and result and not released and set(step) == {"action"}:
            item, released = {"action": action}, True
        elif action == "collect" and released and not collected and set(step) <= {"action", "gc_rounds", "settle_turns"}:
            item = collection(step)
            collected = True
        else:
            raise ValueError("sequence requires calls, at most one release, then at most one final collection")
        result.append(item)
    if not uses_case:
        raise ValueError("sequence must call the selected method with the case arguments")
    return result


def call(step: dict, expected_outcome: Callable) -> dict:
    """Retain either the generated case inputs or an explicit finite scalar list."""
    if set(step) - {"action", "arguments", "expected_baseline", "metrics"}:
        raise ValueError("unsupported sequence call fields")
    arguments = step.get("arguments", "case")
    if arguments != "case" and (not isinstance(arguments, list) or any(type(value) not in (bool, int, float, str)
                                    or type(value) is float and not math.isfinite(value) for value in arguments)):
        raise ValueError("sequence call arguments require case or finite scalar inputs")
    result = {"action": "call", "arguments": copy.deepcopy(arguments)}
    if "expected_baseline" in step:
        result["expected_baseline"] = expected_outcome(step["expected_baseline"])
    if "metrics" in step:
        settings = step["metrics"]
        if (type(settings) is not dict or set(settings) != {"collection", "emission"}
                or any(type(value) is not bool for value in settings.values())):
            raise ValueError("sequence metrics require collection and emission booleans")
        result["metrics"] = settings.copy()
    return result


def collection(step: dict) -> dict:
    """The retry schedule is a requested capability, never an equality dimension."""
    rounds, turns = step.get("gc_rounds", 64), step.get("settle_turns", 4)
    if type(rounds) is not int or not 1 <= rounds <= 256 or type(turns) is not int or not 1 <= turns <= 16:
        raise ValueError("collection requires gc_rounds 1..256 and settle_turns 1..16")
    return {"action": "collect", "gc_rounds": rounds, "settle_turns": turns}


def configure(entry: dict, value: list[dict], coerce: Callable) -> None:
    """Requested unavailable adapters remain named inventory blockers."""
    if entry["language"] not in ("javascript", "typescript", "java") or "receiver_fixture" not in entry:
        raise ValueError("sequences require a declared Java/JavaScript/TypeScript receiver fixture")
    if entry["language"] == "java" and any(step["action"] != "call" for step in value):
        raise ValueError("Java receiver sequences currently support call actions only")
    if any("metrics" in step for step in value):
        configure_controls(entry, value)
    if (entry["language"] == "typescript" and any(step["action"] == "collect" for step in value)
            and entry.get("typescript_backend") not in ("source", "native")):
        raise ValueError("TypeScript collection requires an explicitly selected emitter")
    for step in value:
        if step["action"] == "call" and step["arguments"] != "case":
            require_arguments(entry, step["arguments"], coerce(entry, step["arguments"]))
    entry["sequence_configuration"] = copy.deepcopy(value)


def configure_controls(entry: dict, value: list[dict]) -> None:
    """Require an actual positive measurement within every controlled schedule."""
    prepared_java = entry["language"] == "java" and entry.get("java_backend") == "prepared"
    source_node = entry["language"] in ("javascript", "typescript") and entry.get("node_backend") == "source-v1"
    if (not (prepared_java or source_node)
            or any(step["action"] != "call" or "metrics" not in step for step in value)):
        raise ValueError("live metrics require prepared Java or source-v1 Node calls with an explicit state for every call")
    positive = {"collection": True, "emission": True}
    if source_node and not any(step["metrics"] == positive for step in value):
        raise ValueError("live Node metrics require a collection-on/emission-on positive control")
    if prepared_java and value[0]["metrics"] != positive:
        raise ValueError("live metrics require an initial collection-on/emission-on positive control")


def concrete(entry: dict, arguments: list, coerce: Callable) -> list[dict]:
    """Freeze all call inputs and expectations into each retained corpus case."""
    result = []
    for index, step in enumerate(entry["sequence_configuration"]):
        item = {**copy.deepcopy(step), "id": "step-" + str(index)}
        if step["action"] == "call":
            generated = step["arguments"] == "case"
            item["arguments"] = copy.deepcopy(arguments) if generated else coerce(entry, step["arguments"])
            require_arguments(entry, arguments if generated else step["arguments"], item["arguments"])
            item["expected_baseline"] = copy.deepcopy(step.get("expected_baseline", entry["expected_baseline"] if generated else {"kind": "return"}))
        result.append(item)
    return result


def require_arguments(entry: dict, requested: list, actual: list) -> None:
    """Apply method preconditions to every fixed or generated call in a schedule."""
    conditions = entry.get("input_preconditions", [])
    preconditions.require(requested, conditions)
    preconditions.require(actual, conditions)


def contracts(case: dict, roots: list[str]) -> list[dict]:
    """Step dimensions are independently requested before workers execute."""
    return [{"id": step["id"], "action": step["action"], "required_roots": roots,
             "expected_baseline": step.get("expected_baseline", {"kind": "return"})}
            for step in case.get("sequence", [])]


def collects(entry: dict) -> bool:
    return any(step["action"] == "collect" for step in entry.get("sequence_configuration", []))


def call_count(entry: dict) -> int:
    """The requested call denominator is fixed before any telemetry is received."""
    return sum(step["action"] == "call" for step in entry["sequence_configuration"]) if "sequence_configuration" in entry else 1


def controls(entry: dict) -> bool:
    """Live controls are an explicit part of each frozen call, never inferred."""
    return any("metrics" in step for step in entry.get("sequence_configuration", []))


def creator(entry: dict) -> str | None:
    """Only a declared source factory is selected as a linked creation call."""
    fixture = entry.get("receiver_fixture", {})
    if not collects(entry) or fixture.get("kind") != "function":
        return None
    return entry["otelc_function"][:-len(entry["name"])] + fixture["source_function"]


def expected_functions(entry: dict, observed: dict) -> dict:
    """A missing collection event cannot redefine the requested witness denominator."""
    result = dict(observed)
    if collects(entry):
        result[entry["node_class_label"] + " lifetime"] = 1
    return result
