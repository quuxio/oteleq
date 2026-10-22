"""Declared scalar domains, bounded input sampling and strictly simpler candidates."""
import json
import itertools
import math
import random
import struct
from typing import Any, Iterator

MAX_STRING = 4096
MAX_CASES = 1024


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
        return int(value), 0
    negative_zero = int(type(value) is float and value == 0 and math.copysign(1, value) < 0)
    return abs(value - anchor(domain)), negative_zero


def float_step(value: float, target: float, width: int) -> float:
    """Move one representable value towards the anchor in the actual scalar width."""
    if width == 64:
        return math.nextafter(value, target)
    if value == target:
        return struct.unpack('>f', struct.pack('>f', target))[0]
    if value == 0:
        bits = 1 if target > 0 else 0x80000001
        return struct.unpack('>f', bits.to_bytes(4, 'big'))[0]
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
    elif kind == "integer":
        yield from integer_reductions(value, anchor(domain))
    else:
        yield from float_reductions(value, anchor(domain), width)


def integer_reductions(value, goal) -> Iterator[Any]:
    """Try progressively smaller exact integral deltas towards the domain anchor."""
    yield goal
    distance = value - goal
    step = abs(distance) // 2
    while step >= 1:
        yield value - step * (1 if distance >= 0 else -1)
        step //= 2
    yield value - (1 if value > goal else -1)


def float_reductions(value: float, goal, width: int) -> Iterator[float]:
    """Keep binary deltas bounded and finish with a representable neighbour."""
    yield goal
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


def sample_count(domain: dict, budget: int) -> int:
    """Stop at finite cardinality without expanding an entire Cartesian domain."""
    kind = domain["kind"]
    if kind == "boolean":
        return min(budget, 2)
    if kind == "integer":
        return min(budget, domain["maximum"] - domain["minimum"] + 1)
    if kind == "float":
        if domain["minimum"] == domain["maximum"]:
            return min(budget, 2 if domain["minimum"] == 0 else 1)
        return budget
    size = 0
    for length in range(domain["minimum_length"], domain["maximum_length"] + 1):
        size += len(domain["alphabet"]) ** length
        if size >= budget:
            return budget
    return size


def sample_edges(domain: dict) -> list:
    """Prefer zero or its nearest endpoint, bounds and a central value."""
    kind = domain["kind"]
    if kind == "boolean":
        return [False, True]
    if kind == "string":
        alphabet = domain["alphabet"]
        return [alphabet[0] * domain["minimum_length"], alphabet[0] * domain["maximum_length"],
                alphabet[-1] * domain["minimum_length"], alphabet[-1] * domain["maximum_length"]]
    low, high = domain["minimum"], domain["maximum"]
    middle = (low + high) // 2 if kind == "integer" else low / 2 + high / 2
    return [anchor(domain), low, high, middle, *([0.0, -0.0] if kind == "float" and low <= 0 <= high else [])]


def sample_draws(domain: dict, count: int, rng: random.Random) -> Iterator:
    """Use a local seeded generator with a fixed exploration bound."""
    for _ in range(count * 8):
        kind = domain["kind"]
        if kind == "boolean":
            yield bool(rng.getrandbits(1))
        elif kind == "integer":
            yield rng.randint(domain["minimum"], domain["maximum"])
        elif kind == "float":
            fraction = rng.random()
            value = (1 - fraction) * domain["minimum"] + fraction * domain["maximum"]
            yield max(domain["minimum"], min(domain["maximum"], value))
        else:
            length = rng.randint(domain["minimum_length"], domain["maximum_length"])
            yield "".join(rng.choice(domain["alphabet"]) for _ in range(length))


def sample_fallback(domain: dict, width: int) -> Iterator:
    """Fill small finite pools lazily instead of relying on random collisions."""
    kind = domain["kind"]
    if kind == "boolean":
        yield from (False, True)
    elif kind == "integer":
        yield from range(domain["minimum"], domain["maximum"] + 1)
    elif kind == "string":
        for length in range(domain["minimum_length"], domain["maximum_length"] + 1):
            for characters in itertools.product(domain["alphabet"], repeat=length):
                yield "".join(characters)
    else:
        value, high = domain["minimum"], domain["maximum"]
        while value <= high:
            yield value
            if value == high:
                break
            following = float_step(value, high, width)
            if following <= value:
                break
            value = following


def floating_sample(value: Any, width: int) -> float:
    """Round before de-duplication so narrow target domains remain bounded."""
    try:
        return struct.unpack('>f', struct.pack('>f', value))[0] if width == 32 else float(value)
    except OverflowError as error:
        raise ValueError("declared domain exceeds the floating representation") from error


def sampling_budget(count: int, width: int) -> None:
    """Keep pure sampling entry points within the same bounded profile."""
    if (type(count) is not int or not 1 <= count <= MAX_CASES
            or type(width) is not int or width not in (32, 64)):
        raise ValueError("invalid declared-domain sample budget or floating width")


def samples(domain: dict, count: int, rng: random.Random, *, width: int = 64) -> list:
    """Materialise bounded independent scalar values, retaining exact distinctions."""
    domain = validate(domain)
    sampling_budget(count, width)
    target = sample_count(domain, count)
    values = {}
    candidates = itertools.chain(sample_edges(domain), sample_draws(domain, target, rng),
                                 sample_fallback(domain, width))
    for value in candidates:
        if domain["kind"] == "float":
            value = floating_sample(value, width)
        if contains(value, domain):
            values.setdefault(key([value]), value)
            if len(values) == target:
                break
    if not values:
        raise ValueError("declared domain has no representable generated values")
    return list(values.values())
