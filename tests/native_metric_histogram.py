"""Independent binary64 feasibility bounds for the native metric corpus."""

from bisect import bisect_left
from fractions import Fraction
import math

from native_prepared_otlp import require


def interval(buckets: tuple, minimum: float, maximum: float, required: tuple, bounds: list) -> tuple:
    """Reserve observed extrema before bounding each remaining binary64 value."""
    remaining = list(buckets)
    lower = upper = Fraction(0)
    for value in required:
        bucket = bisect_left(bounds, value)
        remaining[bucket] -= 1
        require(remaining[bucket] >= 0, 'native histogram extrema exceed their bucket observations')
        lower += Fraction(value); upper += Fraction(value)
    for index, count in enumerate(remaining):
        if count:
            first = minimum if index == 0 else max(minimum, math.nextafter(bounds[index - 1], math.inf))
            last = maximum if index == len(bounds) else min(maximum, bounds[index])
            require(first <= last, 'native histogram bucket lies outside its observed extrema')
            lower += count * Fraction(first); upper += count * Fraction(last)
    return lower, upper


def error(count: int, total: Fraction) -> Fraction:
    """The first value added to zero is exact; bound only subsequent additions."""
    require(type(count) is int and 0 < count < 2**52, 'native histogram count exceeds the rounding model')
    additions = count - 1
    relative = Fraction(additions, 2**53 - additions)
    subnormal = Fraction(additions, 2**1075) * (1 + relative)
    return total * relative + subnormal if total else Fraction(0)


def extrema(minimum: float, maximum: float) -> tuple:
    return (minimum,) if minimum.as_integer_ratio() == maximum.as_integer_ratio() else (minimum, maximum)


def sample(value: tuple, bounds: list) -> None:
    """Every total needs feasible bucket values, including each actual extreme."""
    count, buckets, total, minimum, maximum = value
    lower, upper = interval(buckets, minimum, maximum, extrema(minimum, maximum), bounds)
    observed = Fraction(total)
    require(lower - error(count, lower) <= observed <= upper + error(count, upper),
            'native histogram sum cannot arise from its buckets and extrema')


def cumulative(previous: tuple, current: tuple, bounds: list) -> None:
    """New bucket observations must explain the change in a cumulative total."""
    old_count, old_buckets, old_sum, old_min, old_max = previous
    count, buckets, total, minimum, maximum = current
    require(count >= old_count and all(new >= old for new, old in zip(buckets, old_buckets, strict=True))
            and total >= old_sum, 'native cumulative histogram observations decreased')
    if count == old_count:
        require(current == previous, 'native histogram changed without added observations')
        return
    if not old_count:
        return
    require(minimum <= old_min and maximum >= old_max, 'native histogram lost an earlier extreme')
    required = tuple(value for changed, value in ((minimum < old_min, minimum), (maximum > old_max, maximum)) if changed)
    added = tuple(new - old for new, old in zip(buckets, old_buckets, strict=True))
    low, high = interval(added, minimum, maximum, required, bounds)
    _, old_upper = interval(old_buckets, old_min, old_max, extrema(old_min, old_max), bounds)
    _, upper = interval(buckets, minimum, maximum, extrema(minimum, maximum), bounds)
    uncertainty = error(old_count, old_upper) + error(count, upper)
    change = Fraction(total) - Fraction(old_sum)
    require(low - uncertainty <= change <= high + uncertainty,
            'native cumulative histogram sum cannot arise from the newly added buckets')
