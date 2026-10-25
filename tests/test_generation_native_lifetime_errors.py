"""Literal escaping-target outcomes and adapted raw inputs, not new SDK runs."""

import copy
from pathlib import Path
import sys
import tempfile
import tomllib
import unittest
from unittest.mock import Mock

from opentelemetry.proto.collector.metrics.v1.metrics_service_pb2 import ExportMetricsServiceRequest
from opentelemetry.proto.collector.trace.v1.trace_service_pb2 import ExportTraceServiceRequest

import native_lifetime_audit as audit
import native_lifetime_cases as cases
import native_lifetime_otlp as raw
import native_lifetime_test_capture as inputs
import qualify_native_lifetimes as driver
import test_generation_native_lifetime_promotion as promotion

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'adapters/generation'))
import typed_capture


class NativeLifetimeErrorTests(unittest.TestCase):
    def setUp(self):
        temporary = tempfile.TemporaryDirectory()
        self.addCleanup(temporary.cleanup)
        self.root = Path(temporary.name).resolve()

    def capture(self, name):
        folder = self.root / name
        entry, witness = inputs.capture(folder, 'cpp', 'target-error')
        selected = audit.policy(folder, entry)
        return folder, entry, witness, selected['resource']['service_name']

    def test_escaping_target_has_a_normal_destructor_and_an_explicit_error(self):
        folder = self.root / 'fixture'; folder.mkdir()
        source, config = driver.fixture(folder, 'cpp', False, self.root / 'sdk', mode='target-error')
        body = (source / 'src/app.cpp').read_text()
        self.assertIn('#include <stdexcept>', body)
        self.assertIn('throw std::runtime_error("failure-42");', body)
        self.assertNotIn('catch(', body)
        self.assertLess(body.index('observed_errno=errno;'), body.index('throw std::runtime_error'))
        self.assertIn('~Item(){value=0;}', (source / 'include/item.h').read_text())
        declaration, = tomllib.loads(config.read_text())['fixtures'][0]['lifetimes']
        self.assertIs(declaration['exception_exit'], False)
        self.assertIs(cases.expected('cpp', 'target-error')['function_error'], True)
        with self.assertRaises(ValueError): cases.expected('c', 'target-error')
        with self.assertRaises(ValueError): driver.fixture(self.root / 'invalid', 'c', False,
                                                          self.root / 'sdk', mode='target-error')
        self.assertFalse((self.root / 'invalid').exists())

    def test_literal_error_graph_matches_the_existing_public_observation_codec(self):
        after = {'global:state': {'kind': 'integer', 'type': 'cpp.int', 'value': '12', 'bits': 32, 'signed': True}}
        actual = typed_capture.scalar_error(b'std::runtime_error\tfailure-42', 'cpp', {},
                                           {'roots': copy.deepcopy(after), 'nodes': []})
        expected = {'kind': 'error', 'category': 'exception', 'graph': {
            'roots': {**after, 'error': {'kind': 'reference', 'node_id': 'n0'}},
            'nodes': [{'id': 'n0', 'type': 'cpp.std::runtime_error', 'fields': {
                'message': {'kind': 'bytes', 'type': 'cpp.what', 'hex': '6661696c7572652d3432'}}}]}}
        self.assertEqual(actual, expected)
        self.assertEqual(driver.outcome('cpp', after, 42, mode='target-error'), expected)

    def test_error_function_and_normal_destructor_keep_distinct_raw_flags(self):
        folder, entry, witness, _ = self.capture('spans')
        result = audit.verify(folder, entry, witness, plain=False, mode='target-error')
        self.assertIs(result['lifetimes'][0]['exception_exit'], False)
        with self.assertRaises(ValueError): audit.verify(folder, entry, witness, plain=False)
        message = ExportTraceServiceRequest.FromString((folder / 'otlp-1.protobuf').read_bytes())
        spans = list(message.resource_spans[0].scope_spans[0].spans)
        root, = [span for span in spans if span.name == entry['otelc_runtime_function']]
        lifetime, = [span for span in spans if span.name == 'Item lifetime']
        raw.observation(spans, 'cpp', root.name, mode='target-error')
        root.status.code = 0
        with self.assertRaises(ValueError): raw.observation(spans, 'cpp', root.name, mode='target-error')
        root.status.code = 2
        root.attributes[-1].value.string_value = 'foreign'
        with self.assertRaises(ValueError): raw.observation(spans, 'cpp', root.name, mode='target-error')
        root.attributes[-1].value.string_value = 'exception'
        next(a for a in lifetime.attributes if a.key == 'otelc.destructor.exception_exit').value.bool_value = True
        with self.assertRaises(ValueError): raw.observation(spans, 'cpp', root.name, mode='target-error')

    def test_error_counters_must_be_present_labelled_and_finish_at_one(self):
        for change in ('missing', 'zero', 'label'):
            folder, entry, _, service = self.capture(change)
            raw.receipt(folder, driver.retained.read, 'cpp', service, entry['otelc_runtime_function'],
                        plain=False, mode='target-error')
            for name in ('otlp-0.protobuf', 'otlp-2.protobuf'):
                path = folder / name
                message = ExportMetricsServiceRequest.FromString(path.read_bytes())
                metrics = message.resource_metrics[0].scope_metrics[0].metrics
                error, = [value for value in metrics if value.name == 'otelc.function.errors']
                if change == 'missing': metrics.remove(error)
                elif change == 'zero': error.sum.data_points[0].as_int = 0
                else: error.sum.data_points[0].attributes[-1].value.string_value = 'foreign'
                path.write_bytes(message.SerializeToString())
            with self.subTest(change=change), self.assertRaises(ValueError):
                raw.receipt(folder, driver.retained.read, 'cpp', service, entry['otelc_runtime_function'],
                            plain=False, mode='target-error')

    def report(self, contracts=driver.BASE_CALLS, function='selected'):
        helper = promotion.NativeLifetimePromotionTests()
        helper.root = self.root
        return helper.report(self.root / (function + '-' + str(dict(contracts)[function])), 'cpp',
                             function, contracts, mode='target-error')

    def test_every_repeat_requires_the_literal_error_type_message_and_category(self):
        path = self.report()
        driver.check_report(path, False, Mock(), mode='target-error')
        bundle_path = path.parent / 'selected-0/typed-bundle.json'
        original = driver.retained.read(bundle_path)
        for change in ('class', 'message', 'category'):
            value = copy.deepcopy(original)
            for lane in ('baseline', 'instrumented_on'):
                for attempt in value['cases'][0][lane]:
                    outcome = attempt['observation']['outcome']
                    if change == 'class': outcome['graph']['nodes'][0]['type'] = 'cpp.std::logic_error'
                    elif change == 'message': outcome['graph']['nodes'][0]['fields']['message']['hex'] = '00'
                    else: outcome['category'] = 'panic'
            driver.write(bundle_path, value)
            with self.subTest(change=change), self.assertRaises(ValueError):
                driver.check_report(path, False, Mock(), mode='target-error')

    def test_promoted_errors_refuse_stale_messages_and_equal_normal_returns(self):
        for function, _ in driver.PROMOTED_CALLS:
            path = self.report(driver.PROMOTED_CALLS, function)
            driver.check_report(path, False, Mock(), function=function, contracts=driver.PROMOTED_CALLS, mode='target-error')
            bundle_path = path.parent / (function + '-0/typed-bundle.json')
            original = driver.retained.read(bundle_path)
            for change in ('stale-message', 'normal-return'):
                value = copy.deepcopy(original)
                for lane in ('baseline', 'instrumented_on'):
                    for attempt in value['cases'][0][lane]:
                        outcome = attempt['observation']['outcome']
                        if change == 'stale-message':
                            outcome['graph']['nodes'][0]['fields']['message']['hex'] = b'failure-42'.hex()
                        else:
                            after = attempt['observation']['after']
                            attempt['observation']['outcome'] = {'kind': 'return', 'graph': {
                                'roots': {**after['roots'], 'result': driver.scalar('cpp', 42)}, 'nodes': []}}
                driver.write(bundle_path, value)
                with self.subTest(function=function, change=change), self.assertRaises(ValueError):
                    driver.check_report(path, False, Mock(), function=function,
                                        contracts=driver.PROMOTED_CALLS, mode='target-error')


if __name__ == '__main__':
    unittest.main()
