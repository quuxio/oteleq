"""Decoded C++ sequences retain serial roots and complete recursive descendants."""

import copy
from pathlib import Path
import sys
import unittest
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[1]
sys.path[:0] = [str(ROOT / 'adapters/generation'), str(ROOT / 'examples')]
import generation
import otelc_collection as collection
from test_capture_languages import decoder, span


class CppSequenceWitnessTests(unittest.TestCase):
    target = 'Counter::step(int)'

    def nodes(self):
        result = []
        for index, (start, end) in enumerate(((10, 20), (30, 40))):
            root = span(self.target, identity=bytes([index + 1]) * 8)
            root.trace_id = bytes([index + 1]) * 16
            root.start_time_unix_nano, root.end_time_unix_nano = start, end
            result.append(root)
        child = span(self.target, parent=result[0].span_id, identity=b'c' * 8)
        child.trace_id = result[0].trace_id
        child.start_time_unix_nano, child.end_time_unix_nano = 12, 18
        return [result[1], child, result[0]]

    def test_unordered_receipt_accepts_two_real_serial_roots_with_recursion(self):
        collection.serial_call_trees(self.nodes(), self.target, 2)

    def test_missing_duplicate_and_foreign_trees_cannot_satisfy_the_denominator(self):
        values = self.nodes()
        for nodes, count in ((values, 1), (values[1:], 2), ([*values, copy.deepcopy(values[0])], 2)):
            with self.subTest(count=count), self.assertRaises(ValueError):
                collection.serial_call_trees(nodes, self.target, count)
        values[0].name = 'foreign'
        with self.assertRaisesRegex(ValueError, 'foreign'):
            collection.serial_call_trees(values, self.target, 2)

    def test_empty_or_untyped_call_contracts_cannot_pass(self):
        for calls in (0, -1, 33, True, 2.0):
            with self.subTest(calls=calls), self.assertRaises(ValueError):
                collection.serial_call_trees([], self.target, calls)
        for target in ('', ' ', None):
            with self.subTest(target=target), self.assertRaises(ValueError):
                collection.serial_call_trees(self.nodes(), target, 2)

    def test_overlapping_and_ambiguous_root_intervals_are_refused(self):
        for start, end in ((15, 35), (10, 40), (True, 40), (30, 29), (0, 40)):
            nodes = self.nodes()
            nodes[0].start_time_unix_nano, nodes[0].end_time_unix_nano = start, end
            with self.subTest(start=start, end=end), self.assertRaises(ValueError):
                collection.serial_call_trees(nodes, self.target, 2)

    def test_missing_cross_trace_outliving_and_cyclic_parents_are_refused(self):
        for fault in ('missing', 'trace', 'before', 'after', 'cycle'):
            nodes = self.nodes();child = nodes[1]
            if fault == 'missing':child.parent_span_id = b'x' * 8
            elif fault == 'trace':child.trace_id = b'x' * 16
            elif fault == 'before':child.start_time_unix_nano = 9
            elif fault == 'after':child.end_time_unix_nano = 21
            else:
                child.start_time_unix_nano, child.end_time_unix_nano = 10, 20
                child.parent_span_id = child.span_id
            with self.subTest(fault=fault), self.assertRaises(ValueError):
                collection.serial_call_trees(nodes, self.target, 2)

    def test_generation_checks_serial_trees_before_runtime_witness(self):
        nodes = self.nodes()
        entry = {'language': 'cpp', 'otelc_function': self.target,
            'sequence_configuration': [{'action': 'call'}, {'action': 'call'}]}
        bodies = [(generation.capture.TRACE_PATH, b'component fixture')]
        with patch.object(generation.capture, 'witness', return_value={'verified': True}) as witness:
            actual = generation.sequence_telemetry(bodies, {}, entry, 'expected', decoder(nodes),
                {self.target: 3}, 2, 0)
            self.assertEqual(actual, {'verified': True})
            witness.assert_called_once()
        nodes[0].start_time_unix_nano = 15
        with patch.object(generation.capture, 'witness') as witness, self.assertRaises(ValueError):
            generation.sequence_telemetry(bodies, {}, entry, 'expected', decoder(nodes), {self.target: 3}, 2, 0)
        witness.assert_not_called()
