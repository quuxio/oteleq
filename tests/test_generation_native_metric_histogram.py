"""Exact histogram and cumulative-feasibility regressions from the reviewed P2."""

from bisect import bisect_left
from fractions import Fraction
import math
import unittest

from opentelemetry.proto.metrics.v1.metrics_pb2 import HistogramDataPoint

import native_metric_histogram as model
import native_metric_otlp as oracle
from native_prepared_otlp import BOUNDS


def point(values: list[float]) -> HistogramDataPoint:
    result = HistogramDataPoint(count=len(values), sum=0.)
    result.explicit_bounds.extend(BOUNDS)
    buckets = [0] * (len(BOUNDS) + 1)
    for value in values:
        result.sum += value
        buckets[bisect_left(BOUNDS, value)] += 1
    result.bucket_counts.extend(buckets)
    if values:
        result.min = min(values); result.max = max(values)
    return result


class NativeMetricHistogramTests(unittest.TestCase):
    def test_single_measurement_has_no_aggregation_error_budget(self):
        for value in (0., math.nextafter(0., math.inf), 1e-6, math.nextafter(1e-6, math.inf), .01, 2.):
            original = point([value]); oracle.histogram(original)
            for changed_sum in (math.nextafter(value, math.inf), value + 1e-9):
                changed = HistogramDataPoint(); changed.CopyFrom(original); changed.sum = changed_sum
                with self.subTest(value=value, changed_sum=changed_sum), self.assertRaises(ValueError):
                    oracle.histogram(changed)
        self.assertEqual(model.error(1, Fraction(1, 1_000_000)), 0)
        reported = point([1e-6]); reported.sum = 1.0000000005e-6
        with self.assertRaises(ValueError): oracle.histogram(reported)

    def test_legitimate_binary64_sums_keep_extrema_and_bucket_edge_rounding(self):
        values = [1e-6, math.nextafter(1e-6, math.inf), .01, .01, math.nextafter(.01, math.inf), 2.]
        previous = oracle.histogram(point([]))
        for end in range(1, len(values) + 1):
            current = oracle.histogram(point(values[:end]))
            model.cumulative(previous, current, BOUNDS)
            model.cumulative(current, current, BOUNDS)
            previous = current
        tiny = math.nextafter(0., math.inf)
        oracle.histogram(point([tiny] * 12))
        self.assertEqual(model.error(2, Fraction(0)), 0)
        self.assertGreater(model.error(2, Fraction(tiny)), 0)

    def test_two_distinct_extremes_both_require_observations(self):
        original = point([1e-6, 1e-5]); oracle.histogram(original)
        original.sum = 5e-6
        with self.assertRaises(ValueError): oracle.histogram(original)
        for required in ((1e-6, 1e-5),):
            with self.assertRaises(ValueError):
                model.interval((1, 0, 0, 0, 0, 0, 0, 0), 1e-6, 1e-5, required, BOUNDS)
        with self.assertRaises(ValueError):
            model.interval((0, 1, 0, 0, 0, 0, 0, 0), 1e-6, 1e-6, (), BOUNDS)

    def test_individually_feasible_totals_cannot_rewrite_earlier_measurements(self):
        old = oracle.histogram(point([1e-5, 3e-5, *([1.1e-5] * 4)]))
        changed = oracle.histogram(point([1e-5, *([3e-5] * 11)]))
        self.assertEqual((old[0], changed[0]), (6, 12))
        with self.assertRaises(ValueError): model.cumulative(old, changed, BOUNDS)
        valid = oracle.histogram(point([1e-5, 3e-5, *([1.1e-5] * 4), *([2e-5] * 6)]))
        model.cumulative(old, valid, BOUNDS)

    def test_cumulative_counts_buckets_and_extrema_are_immutable_without_new_values(self):
        old = oracle.histogram(point([1e-6, 1e-5]))
        for changed in ((1, old[1], old[2], old[3], old[4]),
                        (2, old[1], old[2] * 2, old[3], old[4]),
                        (3, (0, 3, 0, 0, 0, 0, 0, 0), old[2] * 2, old[3], old[4]),
                        (3, (1, 2, 0, 0, 0, 0, 0, 0), old[2] * 2, 2e-6, old[4])):
            with self.subTest(changed=changed), self.assertRaises(ValueError):
                model.cumulative(old, changed, BOUNDS)
        for count in (0, True, 2**52):
            with self.subTest(count=count), self.assertRaises(ValueError): model.error(count, Fraction(1))


if __name__ == '__main__':
    unittest.main()
