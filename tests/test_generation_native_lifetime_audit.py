"""Actual captured C bytes and literal C++ signals; no SDK applications run."""

import copy
import hashlib
import json
from pathlib import Path
import shutil
import tempfile
import tomllib
import unittest
from unittest.mock import patch

from opentelemetry.proto.collector.metrics.v1.metrics_service_pb2 import ExportMetricsServiceRequest
from opentelemetry.proto.collector.trace.v1.trace_service_pb2 import ExportTraceServiceRequest

import native_lifetime_audit as audit
import native_lifetime_otlp as raw
import native_lifetime_refusals as refusals
import native_prepared_otlp as common
import native_prepared_receipt as records
from qualify_project_tests import toml

FIXTURES = Path(__file__).with_name('fixtures')


class NativeLifetimeRawAuditTests(unittest.TestCase):
    def setUp(self):
        temporary = tempfile.TemporaryDirectory()
        self.addCleanup(temporary.cleanup)
        self.root = Path(temporary.name).resolve() / 'capture'
        shutil.copytree(FIXTURES / 'native-lifetime-c-capture', self.root)
        report = json.loads((FIXTURES / 'native-lifetime-workflow-c-report.json').read_text())
        self.entry, = [entry for entry in report['inventory'] if entry['status'] == 'ready']
        bundle = json.loads((FIXTURES / 'native-lifetime-workflow-c-typed-bundle.json').read_text())
        self.witness = bundle['cases'][0]['instrumented_on'][0]['execution']['witness']

    def write(self, name, value):
        (self.root / name).write_text(json.dumps(value))

    def check(self):
        return audit.verify(self.root, self.entry, self.witness, plain=False)

    def trace(self):
        return ExportTraceServiceRequest.FromString((self.root / 'otlp-1.protobuf').read_bytes())

    def metrics(self, name='otlp-0.protobuf'):
        return ExportMetricsServiceRequest.FromString((self.root / name).read_bytes())

    def test_complete_actual_capture_hashes_raw_observations_and_health_are_joined(self):
        original = FIXTURES / 'native-lifetime-c-capture'
        index = records.read(original / 'capture.json')
        self.assertEqual(len(index['files']), 12)
        for name, expected in index['files'].items():
            self.assertEqual(hashlib.sha256((original / name).read_bytes()).hexdigest(), expected)
        value = self.check()
        self.assertEqual(value['functions'], {'src/app.c::selected': 1})
        self.assertEqual((value['spans'], len(value['lifetimes']), value['metric_points']), (2, 1, 12))
        self.assertEqual((value['trace_requests'], value['metric_requests']), (1, 2))
        self.assertEqual(value['raw_otlp_sha256'], self.witness['raw_otlp_sha256'])

    def test_literal_cpp_wire_profile_keeps_destructor_flag_and_object_accounting(self):
        """Adapt captured signal values to the declared C++ schema; no C++ execution."""
        function = 'src/app.cpp::selected(int)'
        message = self.trace(); resource = message.resource_spans[0]
        next(a for a in resource.resource.attributes if a.key == 'otelc.language').value.string_value = 'cpp'
        for span in resource.scope_spans[0].spans:
            if span.name == 'Item lifetime':
                next(a for a in span.attributes if a.key == 'boundary').value.string_value = 'destructor_entry'
                span.attributes.add(key='otelc.destructor.exception_exit').value.bool_value = False
            else:
                span.name = function; span.attributes[0].value.string_value = function
        (self.root / 'otlp-1.protobuf').write_bytes(message.SerializeToString())
        for name in ('otlp-0.protobuf', 'otlp-2.protobuf'):
            message = self.metrics(name); resource = message.resource_metrics[0]
            next(a for a in resource.resource.attributes if a.key == 'otelc.language').value.string_value = 'cpp'
            for value in resource.scope_metrics[0].metrics:
                for point in getattr(value, value.WhichOneof('data')).data_points:
                    for attr in point.attributes:
                        attr.value.string_value = function if attr.key == 'function' else 'destructor_entry' if attr.key == 'boundary' else 'Item'
            (self.root / name).write_bytes(message.SerializeToString())
        policy = tomllib.loads((self.root / 'policy.toml').read_text())
        policy['languages'] = ['cpp']; policy['functions']['include'] = ['selected(int)']
        policy['sources']['include'][-2:] = ['src/app.cpp', 'src/keep.cpp']
        (self.root / 'policy.toml').write_text('\n'.join(key + '=' + toml(value) for key, value in policy.items()))
        self.entry.update(language='cpp', path='src/app.cpp', otelc_function='selected(int)', otelc_runtime_function=function)
        request = records.read(self.root / 'native-runtime/native-request.json'); request['policy'] = policy
        self.write('native-runtime/native-request.json', request)
        for name in ('expected-lifetimes-before-build.json', 'expected-lifetimes.json'):
            intent = records.read(self.root / name); intent['roots'] = [function]
            intent['observations'][0]['exception_exit'] = False
            if 'native_profile' in intent: intent['native_profile'] = 'object'
            self.write(name, intent)
        final = records.read(self.root / 'native-runtime/app/health.json'); final['language'] = 'cpp'
        final['object_accounting'] = final.pop('resource_accounting')
        final['object_accounting']['destroying'] = final['object_accounting'].pop('releasing')
        final['policy_sha256'] = records.digest(policy)
        selection = {key: policy[key] for key in ('sources', 'functions')}
        selection['lifetimes'] = {key: policy['lifetimes'][key] for key in ('enabled', 'include', 'exclude')}
        final['selection_sha256'] = records.digest(selection)
        self.write('native-runtime/app/health.json', final)
        digest = hashlib.sha256()
        for row in records.read(self.root / 'http-capture.json')['bodies']:
            body = (self.root / row['file']).read_bytes(); route = row['path']
            digest.update(len(route).to_bytes(8, 'big') + route.encode() + len(body).to_bytes(8, 'big') + body)
        verified = records.read(self.root / 'native-verified-lifetimes.json')
        verified.update(health=final, functions={function: 1}, raw_otlp_sha256=digest.hexdigest())
        verified['lifetimes'][0].update(boundary='destructor_entry', exception_exit=False)
        self.write('native-verified-lifetimes.json', verified)
        self.witness.update(functions={function: 1}, raw_otlp_sha256=digest.hexdigest())
        self.assertEqual(self.check()['lifetimes'][0]['exception_exit'], False)
        self.assertEqual(refusals.run(self.root, self.entry, self.witness, self.root.parent / 'cpp-refusals')['count'], 14)

    def test_actual_c_refusal_corpus_preserves_original_facts_and_discards_only_corrupt_copies(self):
        held = {str(path): records.identity(path) for path in self.root.rglob('*') if path.is_file()}
        destination = self.root.parent / 'c-refusals'
        result = refusals.run(self.root, self.entry, self.witness, destination)
        self.assertEqual((result['count'], result['new_application_launches']), (14, 0))
        self.assertEqual([path.name for path in destination.iterdir()], ['refusals.json'])
        for name, expected in held.items(): self.assertEqual(records.identity(Path(name)), expected)

    def test_new_callable_wire_profile_requires_the_independent_promotion_name(self):
        """Adapt literal labels only; this is not a new C/C++ application capture."""
        function = 'src/app.c::selected_extra'
        message = self.trace()
        for span in message.resource_spans[0].scope_spans[0].spans:
            if span.name != 'Item lifetime':
                span.name = function; span.attributes[0].value.string_value = function
        (self.root / 'otlp-1.protobuf').write_bytes(message.SerializeToString())
        for name in ('otlp-0.protobuf', 'otlp-2.protobuf'):
            message = self.metrics(name)
            for value in message.resource_metrics[0].scope_metrics[0].metrics:
                for point in getattr(value, value.WhichOneof('data')).data_points:
                    for attribute in point.attributes:
                        if attribute.key == 'function': attribute.value.string_value = function
            (self.root / name).write_bytes(message.SerializeToString())
        policy = tomllib.loads((self.root / 'policy.toml').read_text())
        policy['functions']['include'] = ['selected_extra']
        (self.root / 'policy.toml').write_text('\n'.join(key + '=' + toml(value) for key, value in policy.items()))
        self.entry.update(otelc_function='selected_extra', otelc_runtime_function=function)
        request = records.read(self.root / 'native-runtime/native-request.json'); request['policy'] = policy
        self.write('native-runtime/native-request.json', request)
        for name in ('expected-lifetimes-before-build.json', 'expected-lifetimes.json'):
            intent = records.read(self.root / name); intent['roots'] = [function]; self.write(name, intent)
        final = records.read(self.root / 'native-runtime/app/health.json')
        final['policy_sha256'] = records.digest(policy)
        selection = {key: policy[key] for key in ('sources', 'functions')}
        selection['lifetimes'] = {key: policy['lifetimes'][key] for key in ('enabled', 'include', 'exclude')}
        final['selection_sha256'] = records.digest(selection)
        self.write('native-runtime/app/health.json', final)
        digest = hashlib.sha256()
        for row in records.read(self.root / 'http-capture.json')['bodies']:
            body = (self.root / row['file']).read_bytes(); route = row['path']
            digest.update(len(route).to_bytes(8, 'big') + route.encode() + len(body).to_bytes(8, 'big') + body)
        verified = records.read(self.root / 'native-verified-lifetimes.json')
        verified.update(health=final, functions={function: 1}, raw_otlp_sha256=digest.hexdigest())
        self.write('native-verified-lifetimes.json', verified)
        self.witness.update(functions={function: 1}, raw_otlp_sha256=digest.hexdigest())
        for selected in ('selected', 'foreign'):
            with self.subTest(selected=selected), self.assertRaises(ValueError):
                audit.verify(self.root, self.entry, self.witness, plain=False, function=selected)
        self.assertEqual(audit.verify(self.root, self.entry, self.witness, plain=False,
                                     function='selected_extra')['functions'], {function: 1})
        result = refusals.run(self.root, self.entry, self.witness, self.root.parent / 'extra-refusals',
                              function='selected_extra')
        self.assertEqual(result['count'], 14)

    def test_unexpected_acceptance_fails_and_preserves_the_corrupt_copy(self):
        destination = self.root.parent / 'accepted'
        with patch.object(refusals.audit, 'verify', return_value={}), self.assertRaisesRegex(AssertionError, 'accepted altered'):
            refusals.run(self.root, self.entry, self.witness, destination)
        self.assertTrue((destination / 'creation-link/otlp-1.protobuf').is_file())

    def test_lifetime_duration_uses_integer_to_double_before_scaling(self):
        ticks = 9007199254741037
        expected = float(ticks) / 1_000_000_000
        naive = ticks / 1_000_000_000
        self.assertNotEqual(expected, naive)
        message = self.metrics()
        value = next(v for v in message.resource_metrics[0].scope_metrics[0].metrics if v.name == 'otelc.lifetime.duration')
        point = value.histogram.data_points[0]
        del point.bucket_counts[:]; point.bucket_counts.extend([0] * 7 + [1])
        point.sum = point.min = point.max = expected
        self.assertEqual(raw.metric(value, 'free_entry', ticks, {}), 1)
        point.sum = point.min = point.max = naive
        with self.assertRaises(ValueError): raw.metric(value, 'free_entry', ticks, {})

    def test_altered_lifetime_root_link_labels_times_and_dropped_records_refuse(self):
        original = self.trace()
        for change in ('link', 'name', 'complete-type', 'boundary', 'instance', 'parent', 'time', 'drop', 'trace', 'state'):
            message = copy.deepcopy(original)
            lifetime, function = message.resource_spans[0].scope_spans[0].spans
            if change == 'link': lifetime.links[0].span_id = b'x' * 8
            elif change == 'name': lifetime.name = 'foreign lifetime'
            elif change == 'complete-type':
                attr = next(a for a in lifetime.attributes if a.key == 'otelc.lifetime.complete')
                attr.value.int_value = 1
            elif change == 'boundary':
                next(a for a in lifetime.attributes if a.key == 'boundary').value.string_value = 'shutdown_censored'
            elif change == 'instance':
                next(a for a in lifetime.attributes if a.key == 'otelc.lifetime.instance').value.string_value = '2'
            elif change == 'parent': lifetime.parent_span_id = function.span_id
            elif change == 'time': lifetime.end_time_unix_nano = function.end_time_unix_nano + 1
            elif change == 'drop': lifetime.dropped_links_count = 1
            elif change == 'trace': lifetime.trace_id = function.trace_id
            elif change == 'state': lifetime.trace_state = 'foreign=1'
            (self.root / 'otlp-1.protobuf').write_bytes(message.SerializeToString())
            with self.subTest(change=change), self.assertRaises(ValueError): self.check()

    def test_duplicate_missing_or_foreign_function_and_lifetime_spans_refuse(self):
        original = self.trace()
        for change in ('duplicate', 'missing', 'foreign', 'root-attribute'):
            message = copy.deepcopy(original); spans = message.resource_spans[0].scope_spans[0].spans
            if change == 'duplicate': spans.add().CopyFrom(spans[0])
            elif change == 'missing': del spans[0]
            elif change == 'foreign': spans[1].name = 'foreign'
            elif change == 'root-attribute': spans[1].attributes[0].value.bool_value = True
            (self.root / 'otlp-1.protobuf').write_bytes(message.SerializeToString())
            with self.subTest(change=change), self.assertRaises(ValueError): self.check()

    def test_unknown_or_duplicate_resource_scope_attributes_refuse(self):
        original = self.trace()
        for change in ('resource', 'scope', 'duplicate-attribute', 'attribute-type'):
            message = copy.deepcopy(original); resource = message.resource_spans[0]
            if change == 'resource': resource.resource.attributes[0].value.string_value = 'foreign'
            elif change == 'scope': resource.scope_spans[0].scope.name = 'foreign'
            elif change == 'duplicate-attribute': resource.resource.attributes.add().CopyFrom(resource.resource.attributes[0])
            elif change == 'attribute-type': resource.resource.attributes[0].value.int_value = 1
            (self.root / 'otlp-1.protobuf').write_bytes(message.SerializeToString())
            with self.subTest(change=change), self.assertRaises(ValueError): self.check()

    def test_lifetime_metrics_keep_complete_counts_histograms_gauges_and_series(self):
        original = self.metrics()
        for change in ('count', 'duration', 'bucket', 'live', 'label', 'kind', 'duplicate', 'missing', 'incomplete', 'exemplar'):
            message = copy.deepcopy(original); values = message.resource_metrics[0].scope_metrics[0].metrics
            hist = next(v for v in values if v.name == 'otelc.lifetime.duration')
            if change == 'count': hist.histogram.data_points[0].count = 2
            elif change == 'duration':
                p = hist.histogram.data_points[0]; p.sum = p.min = p.max = p.sum / 2
            elif change == 'bucket': hist.histogram.data_points[0].bucket_counts[0] = 1
            elif change == 'live': next(v for v in values if v.name.endswith('.live')).gauge.data_points[0].as_int = 2
            elif change == 'label': hist.histogram.data_points[0].attributes[0].value.string_value = 'foreign'
            elif change == 'kind': hist.ClearField('histogram'); hist.sum.data_points.add(as_int=1)
            elif change == 'duplicate': hist.histogram.data_points.add().CopyFrom(hist.histogram.data_points[0])
            elif change == 'missing':
                for index, value in enumerate(values):
                    if value.name == 'otelc.lifetime.duration': del values[index]; break
                # Both cumulative requests must omit the instrument.
                second = self.metrics('otlp-2.protobuf')
                kept = [v for v in second.resource_metrics[0].scope_metrics[0].metrics if v.name != 'otelc.lifetime.duration']
                del second.resource_metrics[0].scope_metrics[0].metrics[:]
                second.resource_metrics[0].scope_metrics[0].metrics.extend(kept)
                (self.root / 'otlp-2.protobuf').write_bytes(second.SerializeToString())
            elif change == 'incomplete': hist.name = 'otelc.lifetime.incomplete'
            elif change == 'exemplar': hist.histogram.data_points[0].exemplars.add(as_double=1)
            (self.root / 'otlp-0.protobuf').write_bytes(message.SerializeToString())
            with self.subTest(change=change), self.assertRaises(ValueError): self.check()
            (self.root / 'otlp-2.protobuf').write_bytes((FIXTURES / 'native-lifetime-c-capture/otlp-2.protobuf').read_bytes())

    def test_raw_transport_missing_extra_malformed_failed_or_unbounded_payloads_refuse(self):
        original = (self.root / 'otlp-1.protobuf').read_bytes()
        for data in (b'\xff', b''):
            (self.root / 'otlp-1.protobuf').write_bytes(data)
            with self.subTest(data=data), self.assertRaises(ValueError): self.check()
        (self.root / 'otlp-1.protobuf').write_bytes(original)
        (self.root / 'otlp-9.protobuf').write_bytes(original)
        with self.assertRaises(ValueError): self.check()
        (self.root / 'otlp-9.protobuf').unlink()
        response = records.read(self.root / 'http-responses.json'); response['events'][0]['status'] = 503
        self.write('http-responses.json', response)
        with self.assertRaises(ValueError): self.check()
        self.write('http-responses.json', records.read(FIXTURES / 'native-lifetime-c-capture/http-responses.json'))
        with (self.root / 'otlp-1.protobuf').open('wb') as stream: stream.truncate(common.MAX_BYTES + 1)
        with self.assertRaises(ValueError): self.check()

    def test_total_byte_budget_refuses_before_opening_a_later_payload(self):
        first = (self.root / 'otlp-0.protobuf').stat().st_size
        with patch.object(common, 'MAX_BYTES', first + 1), self.assertRaises(ValueError): self.check()

    def test_plain_capture_requires_absent_telemetry_and_sdk_health(self):
        request = records.read(self.root / 'native-runtime/native-request.json'); request['plain'] = True
        self.write('native-runtime/native-request.json', request)
        with self.assertRaises(ValueError): audit.verify(self.root, self.entry, None, plain=True)
        for p in self.root.glob('otlp-*.protobuf'): p.unlink()
        self.write('http-capture.json', {'errors': [], 'bodies': []})
        response = records.read(self.root / 'http-responses.json'); response['events'] = []
        self.write('http-responses.json', response)
        with self.assertRaises(ValueError): audit.verify(self.root, self.entry, None, plain=True)
        (self.root / 'native-runtime/app/health.json').unlink()
        self.assertIsNone(audit.verify(self.root, self.entry, None, plain=True))

    def test_equal_producer_health_cannot_hide_wrong_accounting_exports_or_wire_types(self):
        original = records.read(self.root / 'native-runtime/app/health.json')
        verified = records.read(self.root / 'native-verified-lifetimes.json')
        for section, key, changed in (('resource_accounting', 'completed', '2'), ('resource_accounting', 'closed', 1),
            ('resource_accounting', 'censored', '1'), ('function_accounting', 'registered', '2'),
            ('span_accounting', 'sampled_ended', '1'), ('metric_exports', 'units_succeeded', '11'),
            ('metric_exports', 'batches_pending', '1'), ('controls', 'collection', False),
            ('metric_flush', 'failed_attempts', '1'), ('metric_flush', 'attempts', '0')):
            value = copy.deepcopy(original); value[section][key] = changed
            self.write('native-runtime/app/health.json', value); self.write('native-verified-lifetimes.json', {**verified, 'health': value})
            with self.subTest(section=section, key=key), self.assertRaises(ValueError): self.check()

    def test_verified_summary_witness_and_independent_expectations_cannot_select_outcomes(self):
        original = records.read(self.root / 'native-verified-lifetimes.json')
        for key, changed in (('spans', 1), ('sdk_pid', 1), ('metric_points', 0), ('raw_otlp_sha256', '0' * 64), ('lifetimes', [])):
            self.write('native-verified-lifetimes.json', {**original, key: changed})
            with self.subTest(key=key), self.assertRaises(ValueError): self.check()
        self.write('native-verified-lifetimes.json', original)
        self.witness['spans'] = True
        with self.assertRaises(ValueError): self.check()
        self.witness['spans'] = 1
        intent = records.read(self.root / 'expected-lifetimes-before-build.json'); intent['observations'][0]['complete'] = 1
        self.write('expected-lifetimes-before-build.json', intent)
        with self.assertRaises(ValueError): self.check()

    def test_caller_policy_and_function_are_literal_corpus_inputs(self):
        original = (self.root / 'policy.toml').read_text()
        for change in ('service', 'endpoint', 'flag', 'function'):
            value = tomllib.loads(original)
            if change == 'service': value['resource']['service_name'] = 'foreign'
            elif change == 'endpoint': value['export']['endpoint'] = 'https://foreign.invalid'
            elif change == 'flag': value['metrics']['collection'] = False
            elif change == 'function': value['functions']['include'] = ['foreign']
            (self.root / 'policy.toml').write_text('\n'.join(key + '=' + toml(item) for key, item in value.items()))
            with self.subTest(change=change), self.assertRaises(ValueError): self.check()


if __name__ == '__main__':
    unittest.main()
