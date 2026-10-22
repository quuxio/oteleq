"""Explicit numeric argument relations, evaluated without application callbacks."""
import math
import operator
from typing import Any

MAX_RELATIONS = 32
MAX_ARGUMENTS = 1024
MAX_CANDIDATES = 65536
OPERATORS = {"<": operator.lt, "<=": operator.le, "==": operator.eq,
             "!=": operator.ne, ">=": operator.ge, ">": operator.gt}


def validate(value: Any) -> list[dict]:
    """Validate a bounded conjunction of relations between argument indices."""
    if not isinstance(value, list) or len(value) > MAX_RELATIONS:
        raise ValueError("preconditions must contain at most 32 numeric argument relations")
    result, seen = [], set()
    for item in value:
        if not isinstance(item, dict) or set(item) != {"left", "operator", "right"}:
            raise ValueError("precondition requires left/right argument indices and an operator")
        left, right, relation = item["left"], item["right"], item["operator"]
        if any(type(index) is not int or not 0 <= index < MAX_ARGUMENTS for index in (left, right)):
            raise ValueError("precondition argument index must be an integer from 0 to 1023")
        if type(relation) is not str or relation not in OPERATORS:
            raise ValueError("unsupported numeric precondition operator")
        identity = left, relation, right
        if identity in seen:
            raise ValueError("duplicate numeric precondition")
        seen.add(identity)
        result.append({"left": left, "operator": relation, "right": right})
    return result


def bind(conditions: list[dict], arity: int) -> None:
    """A relation can reference only actual callable arguments."""
    if any(max(item["left"], item["right"]) >= arity for item in conditions):
        raise ValueError("precondition argument index exceeds the callable argument count")


def numeric(value: Any) -> bool:
    """Use exact primitive values; booleans and callbacks are not numeric inputs."""
    return type(value) is int or type(value) is float and math.isfinite(value)


def accepts(arguments: list, conditions: list[dict]) -> bool:
    """Compare finite numbers without narrowing integers to floating point."""
    bind(conditions, len(arguments))
    for item in conditions:
        left, right = arguments[item["left"]], arguments[item["right"]]
        if not numeric(left) or not numeric(right):
            raise ValueError("numeric precondition requires finite numeric arguments")
        if not OPERATORS[item["operator"]](left, right):
            return False
    return True


def require(arguments: list, conditions: list[dict]) -> None:
    """Explicit fixtures must satisfy every declared relation."""
    if not accepts(arguments, conditions):
        raise ValueError("arguments do not satisfy their declared numeric preconditions")
