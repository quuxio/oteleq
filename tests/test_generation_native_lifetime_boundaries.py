"""Actual completed captures and explicit adapted boundary schemas, not new runs."""

import copy
from pathlib import Path
import sys
import tempfile
import tomllib
import unittest
from unittest.mock import Mock, patch

from opentelemetry.proto.collector.trace.v1.trace_service_pb2 import ExportTraceServiceRequest
from opentelemetry.proto.collector.metrics.v1.metrics_service_pb2 import ExportMetricsServiceRequest

import native_lifetime_audit as audit
import native_lifetime_cases as cases
import native_lifetime_otlp as raw
import native_lifetime_refusals as refusals
import native_lifetime_test_capture as inputs
import native_prepared_receipt as records
import qualify_native_lifetimes as driver

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'adapters/generation'))
import policy

PROFILES = (('c', 'completed'), ('cpp', 'completed'), ('c', 'zero'), ('cpp', 'zero'),
            ('c', 'censored'), ('cpp', 'censored'), ('cpp', 'unwind'))


class NativeLifetimeBoundaryTests(unittest.TestCase):
    def setUp(self):
        temporary = tempfile.TemporaryDirectory()
        self.addCleanup(temporary.cleanup)
        self.root = Path(temporary.name).resolve()

    def prepare(self, language, mode):
        folder = self.root / (language + '-' + mode)
        entry, witness = inputs.capture(folder, language, mode)
        return folder, entry, witness

    def test_actual_cpp_capture_and_complete_original_graphs_are_unchanged(self):
        folder, entry, witness = self.prepare('cpp', 'completed')
        value = audit.verify(folder, entry, witness, plain=False)
        self.assertEqual((value['spans'], value['metric_points']), (2, 12))
        self.assertEqual(value['functions'], {'src/app.cpp::selected(int)': 1})
        self.assertIs(value['lifetimes'][0]['exception_exit'], False)
        report = records.read(folder / 'report.json')
        location = self.root / 'historical/report.json'
        source = {location: report, location.parent / report['cases'][0]['case'] / 'typed-bundle.json':
                  records.read(folder / 'typed-bundle.json')}
        with patch.object(driver.retained, 'read', side_effect=source.__getitem__):
            self.assertEqual(driver.check_report(location, False, Mock()), 4)

    def test_every_declared_boundary_has_its_exact_counts_and_raw_labels(self):
        for language, mode in PROFILES:
            with self.subTest(language=language, mode=mode):
                folder, entry, witness = self.prepare(language, mode)
                observed = audit.verify(folder, entry, witness, plain=False, mode=mode)
                zero = mode == 'zero'
                self.assertEqual(observed['spans'], 1 if zero else 2)
                self.assertEqual(len(observed['lifetimes']), 0 if zero else 1)
                if not zero:
                    row, = observed['lifetimes']
                    self.assertIs(row['complete'], mode != 'censored')
                    self.assertEqual(row['release_path'], None if mode == 'censored' else [0])
                    self.assertEqual(row['boundary'], 'shutdown_censored' if mode == 'censored'
                                     else 'destructor_entry' if language == 'cpp' else 'free_entry')
                    self.assertIs(row['exception_exit'], mode == 'unwind'
                                  if language == 'cpp' and mode != 'censored' else None)
                if mode != 'completed':
                    with self.assertRaises(ValueError): audit.verify(folder, entry, witness, plain=False)

    def test_all_seven_real_or_adapted_wire_profiles_refuse_fourteen_corrupt_copies(self):
        total = 0
        for language, mode in PROFILES:
            folder, entry, witness = self.prepare(language, mode)
            before = {p: records.identity(p) for p in folder.rglob('*') if p.is_file()}
            result = refusals.run(folder, entry, witness, self.root / (language + '-' + mode + '-refusals'), mode=mode)
            self.assertEqual((result['count'], result['new_application_launches']), (14, 0))
            self.assertEqual(result['mode'], mode)
            total += result['count']
            for path, expected in before.items(): self.assertEqual(records.identity(path), expected)
        self.assertEqual(total, 98)

    def test_censoring_and_unwinding_have_direct_span_boundary_controls(self):
        for language, mode in (('c', 'completed'), ('c', 'censored'), ('cpp', 'unwind'), ('cpp', 'zero')):
            folder, entry, _ = self.prepare(language, mode)
            message = ExportTraceServiceRequest.FromString((folder / 'otlp-1.protobuf').read_bytes())
            spans = list(message.resource_spans[0].scope_spans[0].spans)
            raw.observation(spans, language, entry['otelc_runtime_function'], mode=mode)
            function, = [span for span in spans if span.name == entry['otelc_runtime_function']]
            if mode == 'zero':
                spans.append(copy.deepcopy(function)); spans[-1].name = 'Item lifetime'
            else:
                lifetime, = [span for span in spans if span.name == 'Item lifetime']
                if mode == 'censored': lifetime.end_time_unix_nano = function.end_time_unix_nano - 1
                elif mode == 'completed': lifetime.end_time_unix_nano = function.end_time_unix_nano + 1
                else:
                    next(a for a in lifetime.attributes if a.key == 'otelc.destructor.exception_exit').value.bool_value = False
            with self.subTest(mode=mode), self.assertRaises(ValueError):
                raw.observation(spans, language, entry['otelc_runtime_function'], mode=mode)

    def test_censored_metrics_cannot_be_reported_as_completed_or_under_release_labels(self):
        folder, entry, witness = self.prepare('c', 'censored')
        observed = audit.verify(folder, entry, witness, plain=False, mode='censored')
        duration = observed['lifetimes'][0]['duration_ns']
        message = ExportMetricsServiceRequest.FromString((folder / 'otlp-0.protobuf').read_bytes())
        values = message.resource_metrics[0].scope_metrics[0].metrics
        incomplete = next(value for value in values if value.name == 'otelc.lifetime.incomplete')
        raw.metric(incomplete, 'free_entry', duration, {}, mode='censored')
        incomplete.name = 'otelc.lifetime.completed'
        with self.assertRaises(ValueError): raw.metric(incomplete, 'free_entry', duration, {}, mode='censored')
        histogram = next(value for value in values if value.name == 'otelc.lifetime.duration')
        point, = histogram.histogram.data_points
        next(a for a in point.attributes if a.key == 'boundary').value.string_value = 'free_entry'
        with self.assertRaises(ValueError): raw.metric(histogram, 'free_entry', duration, {}, mode='censored')
        with self.assertRaises(ValueError): raw.metric(incomplete, 'free_entry', duration, {}, mode='zero')

    def test_zero_does_not_allow_a_foreign_function_trace_state(self):
        folder, entry, _ = self.prepare('cpp', 'zero')
        message = ExportTraceServiceRequest.FromString((folder / 'otlp-1.protobuf').read_bytes())
        spans = list(message.resource_spans[0].scope_spans[0].spans)
        spans[0].trace_state = 'foreign=value'
        with self.assertRaises(ValueError): raw.observation(spans, 'cpp', entry['otelc_runtime_function'], mode='zero')

    def test_closed_health_cannot_relabel_a_completed_censored_or_zero_instance(self):
        for language, mode in PROFILES:
            folder, entry, witness = self.prepare(language, mode)
            observed = audit.verify(folder, entry, witness, plain=False, mode=mode)
            final = records.read(folder / 'native-runtime/app/health.json')
            selected = audit.policy(folder, entry)
            audit.health(final, selected, language, final['pid'], observed, mode=mode)
            wrong = copy.deepcopy(final)
            key = 'object_accounting' if language == 'cpp' else 'resource_accounting'
            wrong[key]['completed'] = '0' if mode in ('completed', 'unwind') else '1'
            with self.subTest(language=language, mode=mode), self.assertRaises(ValueError):
                audit.health(wrong, selected, language, final['pid'], observed, mode=mode)

    def test_fixture_generation_consumes_explicit_zero_censor_and_unwind_contracts(self):
        for language, mode in PROFILES:
            folder = self.root / (language + '-' + mode); folder.mkdir()
            source, path = driver.fixture(folder, language, False, self.root / 'sdk', mode=mode)
            configuration = policy.validate(tomllib.loads(path.read_text()))
            fixture, = configuration['fixtures']
            self.assertEqual(fixture['cases'], [[0]] if mode == 'zero' else [[5]])
            self.assertEqual(len(fixture['lifetimes']), 0 if mode == 'zero' else 1)
            body = (source / ('src/app.cpp' if language == 'cpp' else 'src/app.c')).read_text()
            if mode == 'zero': self.assertIn('if(amount>0)', body)
            elif mode == 'censored':
                self.assertNotIn('free(item)', body); self.assertNotIn('delete ', body)
                self.assertIs(fixture['lifetimes'][0]['complete'], False)
            elif mode == 'unwind':
                self.assertIn('throw amount;', body); self.assertIn('catch(int)', body)
                self.assertIs(fixture['lifetimes'][0]['exception_exit'], True)
        for language, mode in (('c', 'unwind'), ('cpp', 'foreign'), ('rust', 'completed')):
            with self.assertRaises(ValueError): cases.expected(language, mode)
            with self.assertRaises(ValueError): driver.fixture(self.root / 'invalid', language, False,
                                                                self.root / 'sdk', mode=mode)
        self.assertFalse((self.root / 'invalid').exists())


if __name__ == '__main__':
    unittest.main()
