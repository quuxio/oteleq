"""Independent process/code-ID OTLP accounting; source origin remains separate."""

from bisect import bisect_left
from collections import Counter
from fractions import Fraction
import math

from google.protobuf.message import DecodeError

import otelc_capture as capture
import python_execution
from python_provider import require

SCOPE = ("io.quux.otelc.functions", "")
CALLS, DURATION, EXCEPTIONS = "otelc.function.calls", "otelc.function.duration", "otelc.function.exceptions"
BOUNDS = [1e-6, 1e-5, 1e-4, .001, .01, .1, 1.]


def attributes(rows) -> dict:
    """Duplicates and missing typed values cannot disappear in a dictionary."""
    values = {}
    for row in rows:
        kind = row.value.WhichOneof("value")
        require(row.key not in values and kind is not None, "duplicate or unset Python OTLP attribute")
        values[row.key] = (kind, getattr(row.value, kind))
    return values


def resource(value, execution: python_execution.Execution, service: str) -> None:
    """Both signals belong to this actual application PID and SDK launch."""
    values = attributes(value.attributes)
    expected = {"service.name": ("string_value", service), "service.instance.id": ("string_value", execution.launch_id),
                "process.pid": ("int_value", execution.application_pid), "otelc.language": ("string_value", "python"),
                "telemetry.sdk.name": ("string_value", "opentelemetry"), "telemetry.sdk.language": ("string_value", "python")}
    version = values.get("telemetry.sdk.version")
    require(all(values.get(key) == item for key, item in expected.items())
            and version is not None and version[0] == "string_value" and 0 < len(version[1]) <= 128
            and value.dropped_attributes_count == 0, "Python OTLP resource identity or completeness differs")


def label(rows, functions: dict[int, str], *, span: bool = False) -> tuple[int, str]:
    """Code IDs join captured VM descriptors, not a source or invocation cookie."""
    values = attributes(rows)
    identity = values.get("otelc.python.code_id")
    name = values.get("code.function.name" if span else "function")
    require(identity is not None and identity[0] == "int_value" and identity[1] in functions
            and name == ("string_value", functions[identity[1]])
            and len(values) == 2, "Python OTLP function/code identity differs")
    return identity[1], name[1]


def trace_group(group, execution: python_execution.Execution, service: str, functions: dict,
                nodes: dict, bindings: dict, calls: Counter, errors: Counter) -> None:
    """Require complete selected local trees, exact labels and complete spans."""
    resource(group.resource, execution, service)
    require(bool(group.scope_spans), "empty Python trace resource")
    for scope in group.scope_spans:
        require((scope.scope.name, scope.scope.version) == SCOPE and bool(scope.spans)
                and not scope.scope.attributes and scope.scope.dropped_attributes_count == 0, "unexpected Python trace scope")
        for span in scope.spans:
            key = capture.span_identity(span)
            code, name = label(span.attributes, functions, span=True)
            require(key not in nodes and span.name == name and span.kind == 1 and span.status.code in (0, 2)
                    and span.dropped_attributes_count == span.dropped_events_count == span.dropped_links_count == 0
                    and not span.links, "invalid, duplicate or dropped Python function span")
            require(len(span.events) == int(span.status.code == 2), "Python function exception event count differs")
            for event in span.events:
                values = attributes(event.attributes)
                kind = values.get("exception.type")
                require(event.name == "exception" and event.dropped_attributes_count == 0
                        and span.start_time_unix_nano <= event.time_unix_nano <= span.end_time_unix_nano
                        and len(values) == 1 and kind is not None and kind[0] == "string_value" and bool(kind[1]),
                        "invalid Python exception event")
            nodes[key] = (span.trace_id, span.parent_span_id) if span.parent_span_id else None
            bindings[key] = code
            calls[code] += 1
            errors[code] += int(span.status.code == 2)


def metric_point(metric, point, functions: dict) -> tuple:
    """Inspect typed values, timestamps and the complete cumulative histogram."""
    code, _ = label(point.attributes, functions)
    require(point.flags == 0 and 0 < point.start_time_unix_nano <= point.time_unix_nano,
            "incomplete Python metric timestamp or flags")
    if metric.name == DURATION:
        require(list(point.explicit_bounds) == BOUNDS and len(point.bucket_counts) == len(BOUNDS) + 1
                and sum(point.bucket_counts) == point.count and math.isfinite(point.sum) and point.sum >= 0,
                "invalid Python duration histogram")
        require(point.HasField("sum") and point.HasField("min") and point.HasField("max") and math.isfinite(point.min)
                and math.isfinite(point.max) and 0 <= point.min <= point.max,
                "unavailable or invalid Python histogram range")
        histogram_range(point)
        count, buckets, total = point.count, tuple(point.bucket_counts), point.sum
    else:
        require(metric.sum.is_monotonic and point.WhichOneof("value") == "as_int" and point.as_int >= 0,
                "Python function counter lacks a monotonic integer value")
        count, buckets, total = point.as_int, (), 0
    limits = (point.min, point.max) if metric.name == DURATION else ()
    return code, (point.start_time_unix_nano, point.time_unix_nano, count, buckets, total, limits)


def histogram_range(point) -> None:
    """Bound the sum using actual extrema and inclusive-upper bucket semantics.

    Fractions avoid overflow and rounding while constructing feasible bounds.
    The final comparison allows binary64 summation error and subnormal rounding.
    Counts above this error model cannot fit the bounded local trace receipt.
    """
    count, minimum, maximum = point.count, point.min, point.max
    require(0 < count < 2 ** 52, "Python histogram count exceeds the summation bound")
    extrema = (minimum, maximum) if minimum != maximum else (minimum,)
    lower, upper = feasible_range(point.bucket_counts, minimum, maximum, extrema)
    total = Fraction(point.sum)
    require(lower - rounding_bound(count, lower) <= total <= upper + rounding_bound(count, upper),
            "Python histogram sum contradicts its range or populated buckets")


def feasible_range(buckets: tuple, minimum: float, maximum: float, extrema: tuple) -> tuple[Fraction, Fraction]:
    """Bound nonnegative observations and reserve each required actual extreme."""
    lower = upper = Fraction(0)
    remaining = list(buckets)
    # The reported extrema must each be an actual observation, not merely
    # arbitrary limits intersecting one of the populated buckets.
    for value in extrema:
        index = bisect_left(BOUNDS, value)
        remaining[index] -= 1
        require(remaining[index] >= 0, "Python histogram extrema have no observations")
        lower += Fraction(value)
        upper += Fraction(value)
    for index, amount in enumerate(remaining):
        if not amount:
            continue
        low = minimum if index == 0 else max(minimum, math.nextafter(BOUNDS[index - 1], math.inf))
        high = maximum if index == len(BOUNDS) else min(maximum, BOUNDS[index])
        require(low <= high, "Python histogram populated bucket contradicts its extrema")
        lower += Fraction(low) * amount
        upper += Fraction(high) * amount
    return lower, upper


def rounding_bound(count: int, bound: Fraction) -> Fraction:
    """Bound nonnegative binary64 addition error, including subnormal rounding."""
    # For nonnegative binary64 additions, gamma_n bounds relative rounding;
    # n half-minimum-subnormal units additionally bound absolute underflow.
    additions = count - 1  # Adding the first binary64 value to zero is exact.
    gamma = Fraction(additions, 2 ** 53 - additions)
    underflow = Fraction(additions, 2 ** 1075) * (1 + gamma)
    return bound * gamma + underflow if bound else Fraction(0)


def cumulative_histogram(previous: tuple, sample: tuple) -> None:
    """New cumulative sums must fit only the newly added bucket observations."""
    old_minimum, old_maximum = previous[5]
    minimum, maximum = sample[5]
    required = tuple(value for changed, value in ((minimum < old_minimum, minimum), (maximum > old_maximum, maximum)) if changed)
    buckets = tuple(current - old for current, old in zip(sample[3], previous[3], strict=True))
    lower, upper = feasible_range(buckets, minimum, maximum, required)
    _, old_upper = feasible_range(previous[3], old_minimum, old_maximum,
                                 (old_minimum, old_maximum) if old_minimum != old_maximum else (old_minimum,))
    _, current_upper = feasible_range(sample[3], minimum, maximum,
                                     (minimum, maximum) if minimum != maximum else (minimum,))
    error = rounding_bound(previous[2], old_upper) + rounding_bound(sample[2], current_upper)
    added = Fraction(sample[4]) - Fraction(previous[4])
    require(lower - error <= added <= upper + error, "Python cumulative histogram sum contradicts added bucket observations")


def metric_group(group, execution: python_execution.Execution, service: str, functions: dict,
                 observed: dict, exemplars: list) -> int:
    """Account for all received function points; unknown instruments refuse."""
    resource(group.resource, execution, service)
    require(bool(group.scope_metrics), "empty Python metric resource")
    points = 0
    for scope in group.scope_metrics:
        require((scope.scope.name, scope.scope.version) == SCOPE and bool(scope.metrics)
                and not scope.scope.attributes and scope.scope.dropped_attributes_count == 0, "unexpected Python metric scope")
        for metric in scope.metrics:
            histogram = metric.name == DURATION
            require(metric.name in {CALLS, DURATION, EXCEPTIONS} and metric.unit == ("s" if histogram else "")
                    and metric.WhichOneof("data") == ("histogram" if histogram else "sum"), "unexpected Python metric kind or unit")
            data = metric.histogram if histogram else metric.sum
            require(data.aggregation_temporality == 2 and bool(data.data_points), "Python metric is empty or not cumulative")
            for point in data.data_points:
                code, sample = metric_point(metric, point, functions)
                observed.setdefault((metric.name, code), []).append(sample)
                exemplars.extend((value, code, histogram, point.time_unix_nano,
                                  point.min if histogram else 0, point.max if histogram else point.as_int)
                                 for value in point.exemplars)
                points += 1
    return points


def cumulative(observed: dict) -> dict:
    """Arrival order may vary; resets and contradictory snapshots still fail."""
    result = {}
    for key, samples in observed.items():
        ordered = sorted(samples, key=lambda sample: sample[1])
        previous = ordered[0]
        for sample in ordered[1:]:
            require(sample[0] == previous[0]
                    and (sample == previous if sample[1] == previous[1] else
                         sample[2] >= previous[2] and sample[4] >= previous[4]
                         and all(current >= old for current, old in zip(sample[3], previous[3], strict=True))),
                    "Python cumulative metric reset, conflict or regression")
            require(sample[2:] == previous[2:] if sample[2] == previous[2] else
                    not sample[5] or sample[5][0] <= previous[5][0] and sample[5][1] >= previous[5][1],
                    "Python cumulative histogram range changed without matching observations")
            if sample[5] and sample[2] > previous[2]:
                cumulative_histogram(previous, sample)
            previous = sample
        result[key] = previous[2]
    return result


def check_exemplars(exemplars: list, bindings: dict) -> None:
    """Optional exemplars must reference a received selected span for that code."""
    # The pinned Python SDK timestamps a measurement before lazily creating
    # its aggregation. Its first exemplar can therefore precede point start.
    for value, code, histogram, end, minimum, maximum in exemplars:
        kind = "as_double" if histogram else "as_int"
        number = getattr(value, kind)
        require(value.WhichOneof("value") == kind and math.isfinite(number) and minimum <= number <= maximum
                and not value.filtered_attributes and 0 < value.time_unix_nano <= end
                and len(value.trace_id) == 16 and len(value.span_id) == 8
                and bindings.get((value.trace_id, value.span_id)) == code,
                "invalid, foreign or incomplete Python metric exemplar")


def decode(bodies: list, execution: python_execution.Execution, service: str, functions: dict,
           trace_decoder, metric_decoder) -> dict:
    """Reconcile both signals with all captured selected code identities."""
    require(type(execution) is python_execution.Execution and python_execution.pid(execution.sdk_pid)
            and type(service) is str and bool(service) and type(functions) is dict and bool(functions)
            and all(type(code) is int and code > 0 and type(name) is str and bool(name) for code, name in functions.items())
            and set(functions) == {value.record.identity for value in execution.descriptors},
            "Python telemetry lacks actual execution/code identities")
    nodes, bindings, calls, errors, observed, exemplars = {}, {}, Counter(), Counter(), {}, []
    counts = {"trace_batches": 0, "spans": 0, "metric_batches": 0, "metric_points": 0}
    for route, body in bodies:
        require(route in (capture.TRACE_PATH, "/v1/metrics") and type(body) is bytes and bool(body), "unknown or empty Python OTLP body")
        traces = route == capture.TRACE_PATH
        try:
            message = (trace_decoder if traces else metric_decoder).FromString(body)
        except DecodeError as error:
            raise ValueError("Python prepared provider: invalid OTLP protobuf") from error
        groups = message.resource_spans if traces else message.resource_metrics
        require(bool(groups), "empty Python OTLP export")
        counts["trace_batches" if traces else "metric_batches"] += 1
        for group in groups:
            if traces:
                trace_group(group, execution, service, functions, nodes, bindings, calls, errors)
            else:
                counts["metric_points"] += metric_group(group, execution, service, functions, observed, exemplars)
    roots = capture.trace_roots(nodes)
    check_exemplars(exemplars, bindings)
    totals = cumulative(observed)
    require(set(calls) == set(functions) and roots > 0 and counts["metric_batches"] > 0,
            "Python selected code or positive signal receipt is missing")
    expected = {(name, code): calls[code] for name in (CALLS, DURATION) for code in functions}
    expected.update({(EXCEPTIONS, code): errors[code] for code in functions if errors[code] or (EXCEPTIONS, code) in totals})
    require(totals == expected, "Python decoded metric totals differ from actual traced functions")
    counts["spans"] = sum(calls.values())
    return {"received": counts, "code_calls": dict(calls), "code_errors": dict(errors), "roots": roots,
            "functions": {name: sum(calls[code] for code, label in functions.items() if label == name)
                          for name in set(functions.values())}, "source_origin": "unavailable"}
