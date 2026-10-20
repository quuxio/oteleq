"""Declared scalar domains and deterministic, strictly simpler candidate values."""
import json
import math
import struct
from typing import Any, Iterator

MAX_STRING = 4096


def finite(value: Any) -> bool:
    """Exclude booleans, non-finite values and unrepresentable float conversions."""
    try:
        return type(value) in (int, float) and math.isfinite(value)
    except OverflowError:
        return False


def validate(value: Any) -> dict:
    """A domain asserts independent parameter constraints, never arbitrary preconditions."""
    if not isinstance(value, dict) or type(value.get("kind")) is not str:
        raise ValueError("scalar domain requires an explicit kind")
    kind = value["kind"]
    fields = {"boolean": {"kind"}, "integer": {"kind", "minimum", "maximum"},
              "float": {"kind", "minimum", "maximum"},
              "string": {"kind", "minimum_length", "maximum_length", "alphabet"}}
    if kind not in fields or set(value) != fields[kind]:
        raise ValueError("unsupported scalar domain fields or kind")
    if kind == "integer":
        if (any(type(value[key]) is not int or value[key].bit_length() > 4096 for key in ("minimum", "maximum"))
                or value["minimum"] > value["maximum"]):
            raise ValueError("integer domain needs ordered bounded integer endpoints")
    elif kind == "float":
        if (not all(finite(value[key]) for key in ("minimum", "maximum"))
                or value["minimum"] > value["maximum"]):
            raise ValueError("float domain needs ordered finite endpoints")
    elif kind == "string":
        validate_string(value)
    return value.copy()


def validate_string(value: dict) -> None:
    """Bound lengths and require an ordered alphabet of distinct Unicode scalars."""
    low, high, alphabet = value["minimum_length"], value["maximum_length"], value["alphabet"]
    if (type(low) is not int or type(high) is not int or not 0 <= low <= high <= MAX_STRING
            or type(alphabet) is not str or not 1 <= len(alphabet) <= 256
            or len(set(alphabet)) != len(alphabet) or any(0xD800 <= ord(char) <= 0xDFFF for char in alphabet)):
        raise ValueError("string domain needs bounded lengths and distinct Unicode scalar alphabet")


def contains(value: Any, domain: dict) -> bool:
    """Type and membership are checked both before and after target coercion."""
    kind = domain["kind"]
    if kind == "boolean":
        return type(value) is bool
    if kind == "integer":
        integral = type(value) is int or type(value) is float and math.isfinite(value) and value.is_integer()
        return integral and domain["minimum"] <= value <= domain["maximum"]
    if kind == "float":
        return finite(value) and domain["minimum"] <= value <= domain["maximum"]
    return (type(value) is str and domain["minimum_length"] <= len(value) <= domain["maximum_length"]
            and set(value) <= set(domain["alphabet"]))


def arguments(values: list, declared: list) -> None:
    """Independent domains cannot express relationships between parameters."""
    if len(values) != len(declared) or any(not contains(value, domain) for value, domain in zip(values, declared)):
        raise ValueError("arguments do not satisfy their declared scalar domains")


def key(values: list) -> str:
    """Preserve integer/float and signed-zero distinctions in search bookkeeping."""
    return json.dumps(values, ensure_ascii=True, allow_nan=False, separators=(",", ":"))


def anchor(domain: dict):
    """Use the representable domain endpoint closest to zero when zero is excluded."""
    return max(domain["minimum"], min(0, domain["maximum"]))


def rank(value: Any, domain: dict) -> tuple:
    """This ordering defines local simplicity; it is not a global minimum proof."""
    if domain["kind"] == "string":
        return len(value), tuple(domain["alphabet"].index(char) for char in value)
    if domain["kind"] == "boolean":
        return (int(value),)
    negative_zero = int(type(value) is float and value == 0 and math.copysign(1, value) < 0)
    return abs(value - anchor(domain)), negative_zero


def float_step(value: float, target: float, width: int) -> float:
    """Move one representable value towards the anchor in the actual scalar width."""
    if width == 64:
        return math.nextafter(value, target)
    bits = int.from_bytes(struct.pack('>f', value), 'big')
    bits += -1 if (value > target) == (value > 0) else 1
    return struct.unpack('>f', bits.to_bytes(4, 'big'))[0]


def reductions(value: Any, domain: dict, *, width: int = 64) -> Iterator[Any]:
    """Enumerate a finite deterministic neighbourhood, preserving declared constraints."""
    kind = domain["kind"]
    if kind == "boolean":
        yield False
    elif kind == "string":
        yield from string_reductions(value, domain)
    else:
        goal = anchor(domain)
        yield goal
        if kind == "integer":
            distance = value - goal
            step = abs(distance) // 2
            while step >= 1:
                yield value - step * (1 if distance >= 0 else -1)
                step //= 2
            yield value - (1 if value > goal else -1)
        else:
            goal = float(goal)
            step = (value - goal) / 2
            for _ in range(width):
                yield value - step
                step /= 2
            if value != goal:
                yield float_step(value, goal, width)
            elif value == 0:
                yield 0.0


def string_reductions(value: str, domain: dict) -> Iterator[str]:
    """Try bounded chunk deletion, then a simpler character at each position."""
    yield domain["alphabet"][0] * domain["minimum_length"]
    size = max(1, len(value) // 2)
    while size:
        for start in range(0, len(value), size):
            yield value[:start] + value[start + size:]
        size //= 2
    first = domain["alphabet"][0]
    for index in range(len(value)):
        yield value[:index] + first + value[index + 1:]
