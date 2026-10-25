"""Join complete native lifetime metric series to independently expected instances."""

from collections import Counter
from fractions import Fraction

import native_telemetry as telemetry
from native_protocol import require

ADMITTED, COMPLETED, INCOMPLETE, DURATION, LIVE = (
    'otelc.lifetime.' + suffix for suffix in ('admitted', 'completed', 'incomplete', 'duration', 'live'))
INSTRUMENTS = {ADMITTED: ('sum', '{object}'), COMPLETED: ('sum', '{object}'),
               INCOMPLETE: ('sum', '{object}'), DURATION: ('histogram', 's'), LIVE: ('gauge', '{object}')}


def expected(observations: tuple, boundary: str) -> dict:
    """Creation, observed release and censored shutdown have different labels."""
    totals = Counter()
    for row in observations:
        end = boundary if row.complete else 'shutdown_censored'
        totals[ADMITTED, row.name, boundary] += 1
        totals[COMPLETED if row.complete else INCOMPLETE, row.name, end] += 1
        totals[DURATION, row.name, end] += 1
        totals[LIVE, row.name, boundary] = 0
    return dict(totals)


def point(metric, value, names: set[str], boundary: str, bounds: list) -> tuple:
    """Require exact labels and wire representations for each lifetime instrument."""
    labels = telemetry.attributes(value.attributes)
    selected = labels.get('type')
    end = labels.get('boundary')
    require(selected in names and labels == {'type': selected, 'boundary': end}
            and end in (boundary, 'shutdown_censored') and value.flags == 0 and not value.exemplars
            and 0 < value.start_time_unix_nano <= value.time_unix_nano,
            'invalid native lifetime metric labels or timestamps')
    require(end == ('shutdown_censored' if metric.name == INCOMPLETE else boundary)
            or metric.name == DURATION, 'lifetime metric uses another release boundary')
    if metric.name == DURATION:
        number, buckets, total, extrema = telemetry.histogram_sample(value, bounds)
    else:
        require(value.WhichOneof('value') == 'as_int' and value.as_int >= 0,
                'invalid lifetime metric scalar representation')
        number, buckets, total, extrema = value.as_int, (), 0, ()
    return (metric.name, selected, end), (value.start_time_unix_nano,
        value.time_unix_nano, number, buckets, total, extrema)


def durations(series: dict, values: dict, bounds: list) -> None:
    """Final histograms retain the durations measured by their lifetime spans."""
    for (name, boundary), samples in values.items():
        sample = series[DURATION, name, boundary][-1]
        buckets = [0] * (len(bounds) + 1)
        for value in samples:
            index = next((index for index, bound in enumerate(bounds) if value <= bound), len(bounds))
            buckets[index] += 1
        require(sample[2] == len(samples) and sample[3] == tuple(buckets)
                and sample[5] == (min(samples), max(samples)),
                'native lifetime histogram differs from observed span durations')
        exact = sum((Fraction.from_float(value) for value in samples), Fraction())
        additions = len(samples) - 1
        # Nonnegative normal binary64 additions have a gamma_n relative error
        # bound, independent of export order. Nanosecond durations cannot enter
        # the subnormal/overflow cases within this profile's finite budgets.
        error = exact * Fraction(additions, (1 << 53) - additions)
        require(abs(Fraction.from_float(sample[4]) - exact) <= error,
                'native lifetime histogram sum differs from observed span durations')


def totals(series: dict, gauges: dict, observations: tuple, boundary: str, bounds: list,
           duration_values: dict) -> dict:
    """Cumulative samples cannot reset; live gauges may rise and fall before zero."""
    result = telemetry.cumulative_totals(series, bounds, histogram=DURATION)
    admitted = Counter(row.name for row in observations)
    for key, samples in gauges.items():
        samples.sort()
        require(len({row[0] for row in samples}) == 1 and
                len({row[1] for row in samples}) == len(samples)
                and all(row[2] <= admitted[key[1]] for row in samples),
                'reset, duplicate or impossible native live gauge')
        result[key] = samples[-1][2]
    require(result == expected(observations, boundary),
            'native lifetime metrics differ from declared completed/censored observations')
    durations(series, duration_values, bounds)
    return result


def validate(values, observations: tuple, boundary: str, bounds: list, enabled: bool,
             duration_values: dict) -> int:
    """Retain every point, including repeated cumulative and gauge observations."""
    series, gauges, points = {}, {}, 0
    names = {row.name for row in observations}
    for metric in values:
        require(metric.name in INSTRUMENTS, 'unbound native lifetime instrument')
        kind, unit = INSTRUMENTS[metric.name]
        data = getattr(metric, kind)
        require(metric.WhichOneof('data') == kind and metric.unit == unit and bool(data.data_points)
                and (kind == 'gauge' or data.aggregation_temporality == 2)
                and (kind != 'sum' or data.is_monotonic),
                'invalid native lifetime metric kind, unit or temporality')
        for value in data.data_points:
            points += 1
            require(points <= telemetry.MAX_POINTS, 'native lifetime metric point budget exceeded')
            key, sample = point(metric, value, names, boundary, bounds)
            (gauges if kind == 'gauge' else series).setdefault(key, []).append(sample)
    if enabled:
        totals(series, gauges, observations, boundary, bounds, duration_values)
    else:
        require(not points, 'native disabled startup emitted lifetime measurements')
    return points
