"""Generated action admission joins independent outcomes, scoped receipt and health."""

import copy
import json
from pathlib import Path
import tempfile
from types import SimpleNamespace
import unittest

from opentelemetry.proto.collector.metrics.v1.metrics_service_pb2 import ExportMetricsServiceRequest
from opentelemetry.proto.collector.trace.v1.trace_service_pb2 import ExportTraceServiceRequest

import test_generation_java_action_receipt as decoded
import test_generation_java_control_receipt as controls
import test_generation_java_handle_witness as handles
import test_generation_java_health as health
import java_action_telemetry as action
import java_actions
import java_telemetry as telemetry


def metrics(count: int) -> bytes:
    message = ExportMetricsServiceRequest()
    resource = message.resource_metrics.add()
    for name, value in (('service.name', decoded.SERVICE), ('otelc.language', 'java')):
        row = resource.resource.attributes.add();row.key = name;row.value.string_value = value
    scope = resource.scope_metrics.add();scope.scope.name, scope.scope.version = telemetry.METHOD_SCOPE
    for name, unit, kind in ((telemetry.CALLS, '{call}', 'sum'), (telemetry.DURATION, 's', 'histogram')):
        metric = scope.metrics.add();metric.name, metric.unit = name, unit
        data = getattr(metric, kind);data.aggregation_temporality = 2
        if kind == 'sum':data.is_monotonic = True
        point = data.data_points.add();point.start_time_unix_nano = 10;point.time_unix_nano = 20
        attribute = point.attributes.add();attribute.key = 'function';attribute.value.string_value = 'target'
        if kind == 'sum':point.as_int = count
        else:
            point.count, point.sum = count, count * .001
            point.explicit_bounds.extend(telemetry.BUCKETS)
            point.bucket_counts.extend([count] + [0] * len(telemetry.BUCKETS))
    return message.SerializeToString()


class JavaActionTelemetryTests(unittest.TestCase):
    def setUp(self):
        temporary = tempfile.TemporaryDirectory(prefix='oeq-at-', dir='/tmp')
        self.addCleanup(temporary.cleanup)
        self.folder = Path(temporary.name).resolve()
        self.runtime = self.folder / 'r';self.runtime.mkdir(mode=0o700)
        self.entry = {'language': 'java', 'package': '', 'parameters': ['int'], 'output': 'int', 'globals': [],
                      'otelc_function': 'Work.target(int)', java_actions.FIELD: handles.PROFILE}
        self.case = {'id': 'generated-case', 'arguments': [7]}
        self.prepare()

    def prepare(self, *, recursive=False, failed=False):
        self.final, self.trace = decoded.fixture(recursive=recursive, failed=failed)
        self.final.update(schema_version=3, producer=handles.reply(None, False))
        self.final['scopes'][0]['route_verified'] = True
        self.identity = handles.identity()
        self.case_id = java_actions.case_id(self.case)
        self.ids = java_actions.action_ids(self.case)
        self.final['scopes'][0]['case_id'] = self.case_id
        for resource in self.trace.resource_spans:
            for group in resource.scope_spans:
                for span in group.spans:
                    decoded.attribute(span, 'otelc.witness.case_id').string_value = self.case_id
        self.controller = SimpleNamespace(case_id=self.case_id, attempt_id='f' * 64, actions=tuple(self.ids),
            profile=handles.PROFILE, terminal={'pid': 123}, pending=None, plain=False,
            identity=self.identity, harness=SimpleNamespace(pid=123), controls=[], armed=[], completed=[])
        # This fake supplies the already-tested host/session boundary only. The
        # independent final report, raw protobufs, outcome parser and health are real.
        self.controller.receipt_actions = lambda failed: [decoded.expected(action_id=self.ids[0],
            case_id=self.case_id, failed=failed[0])]
        self.session = SimpleNamespace(action=self.controller, audit=lambda: 'a' * 64)
        self.launch = {'argv': ['fixed-java'], 'policy_sha256': dict(self.identity.hashes)['policy_sha256'],
                       'selection_sha256': dict(self.identity.hashes)['selection_sha256']}
        self.process = {'pid': 123, 'argv': ['fixed-java']}
        observation = (b'before\nerror:java.lang.IllegalStateException:string:utf16:006e006f\nafter\n' if failed
                       else b'before\nreturn:java.lang.Integer:OA==\nafter\n')
        (self.folder / 'observation').write_bytes(observation)
        self.count, self.spans = (2, 5) if recursive else (1, 3)
        self.write_inputs()

    def write_inputs(self):
        for name, value in (('prepared-launch.json', self.launch), ('process.json', self.process)):
            (self.folder / name).write_text(json.dumps(value))
        path = self.runtime / 'witness-health.json';path.write_text(json.dumps(self.final));path.chmod(0o600)
        value = health.report()
        value.update(policy_sha256=self.launch['policy_sha256'], selection_sha256=self.launch['selection_sha256'])
        value['span_accounting'].update(sampled_started=str(self.spans), sampled_ended=str(self.spans))
        for name, units in (('trace_exports', self.spans), ('metric_exports', 2)):
            value[name].update(batches_started='1', batches_succeeded='1', units_started=str(units), units_succeeded=str(units))
        path = self.runtime / 'health.json';path.write_text(json.dumps(value));path.chmod(0o600)

    def bodies(self):
        return [('/v1/traces', self.trace.SerializeToString()), ('/v1/metrics', metrics(self.count))]

    def qualify(self, *, bodies=None):
        return action.qualify(self.runtime, self.folder, self.entry, self.case, self.session,
                              self.bodies() if bodies is None else bodies, service=decoded.SERVICE,
                              trace_decoder=ExportTraceServiceRequest)

    def test_scoped_calls_keep_diagnostic_roles_out_of_function_metrics(self):
        for recursive in (False, True):
            for failed in (False, True):
                with self.subTest(recursive=recursive, failed=failed):
                    self.prepare(recursive=recursive, failed=failed)
                    received = self.qualify()
                    self.assertEqual(received['spans'], self.spans)
                    self.assertEqual(received['functions'], {'Work.target(int)': self.count,
                        'otelc.action.wrapper': 1, 'otelc.action.target': self.count})
                    self.assertEqual(received['pending'], 0)
                    self.assertTrue(all(value == 0 for value in received['losses'].values()))
                    summary = json.loads((self.folder / 'verified-actions.json').read_bytes())
                    self.assertEqual(summary['selected_method_spans'], self.count)
                    self.assertEqual(summary['collected_method_calls'], self.count)
                    self.assertEqual(summary['metric_points'], 2)
                    self.assertEqual(summary['record_sha256'], 'a' * 64)

    def unscoped(self):
        group = self.trace.resource_spans[0].scope_spans[1]
        span = group.spans.add();span.CopyFrom(group.spans[0])
        span.trace_id, span.span_id, span.parent_span_id = b'u' * 16, b'u' * 8, b''
        span.start_time_unix_nano, span.end_time_unix_nano = 1, 5
        kept = [copy.deepcopy(row) for row in span.attributes if not row.key.startswith('otelc.witness.')]
        del span.attributes[:];span.attributes.extend(kept)
        self.count += 1;self.spans += 1;self.write_inputs()
        return span

    def test_unscoped_selected_calls_are_counted_separately_and_in_global_health(self):
        self.unscoped();received = self.qualify()
        self.assertEqual(received['functions']['Work.target(int)'], 2)
        summary = json.loads((self.folder / 'verified-actions.json').read_bytes())
        self.assertEqual(summary['unscoped_selected_method_spans'], 1)
        self.assertEqual(summary['unscoped_spans'], 1)

    def test_unknown_unscoped_method_parent_role_or_event_cannot_supply_measurements(self):
        for fault in ('method', 'parent', 'links', 'event', 'role'):
            with self.subTest(fault=fault):
                self.prepare();span = self.unscoped()
                if fault == 'method':decoded.attribute(span, 'code.function').string_value = 'other'
                elif fault == 'parent':span.parent_span_id = b'x' * 8
                elif fault == 'links':span.links.add()
                elif fault == 'event':span.events.add().dropped_attributes_count = 1
                else:
                    resource = self.trace.resource_spans[0]
                    resource.scope_spans[0].spans.add().CopyFrom(span)
                with self.assertRaises(ValueError):self.qualify()

    def test_missing_wrong_or_reset_function_measurements_refuse(self):
        for count in (0, 2):
            self.count = count
            with self.subTest(count=count), self.assertRaisesRegex(ValueError, 'function metric'):
                self.qualify()
        self.count = 1
        with self.assertRaises(ValueError):self.qualify(bodies=self.bodies()[:1])
        with self.assertRaises(ValueError):self.qualify(bodies=[('/v1/metrics', b'bad protobuf')])
        with self.assertRaises(ValueError):
            action.method_receipt([('/unexpected', b'')], decoded.TARGET, None, None, service=decoded.SERVICE)

    def test_live_metric_counts_use_scoped_method_sizes_and_retained_off_measurements(self):
        record, _, bodies, series = controls.fixture()
        methods = {'selected_spans': 10, 'unscoped_selected_spans': 0, 'series': series,
                   'recorded': {name: [(20, 1), (40, 4)] for name in (telemetry.CALLS, telemetry.DURATION)}}
        received = {'pid': 123, 'actions': [{'selected_method_spans': size} for size in (1, 2, 3, 4)]}
        self.assertEqual(action.metric_counts(methods, received, record, bodies), 4)
        changed = {**methods, 'selected_spans': 11, 'unscoped_selected_spans': 1}
        with self.assertRaisesRegex(ValueError, 'outside the declared actions'):
            action.metric_counts(changed, received, record, bodies)
        with self.assertRaisesRegex(ValueError, 'counts differ'):
            action.metric_counts({**methods, 'selected_spans': 12}, received, None, bodies)
        changed = copy.deepcopy(methods);changed['recorded'][telemetry.CALLS] = [(10, 4), (20, 1), (40, 4)]
        with self.assertRaisesRegex(ValueError, 'function metric'):
            action.metric_counts(changed, received, record, bodies)

    def test_case_process_pending_or_host_identity_mismatches_refuse(self):
        for fault in ('case', 'actions', 'profile', 'pending', 'terminal', 'identity', 'pid', 'argv'):
            with self.subTest(fault=fault):
                self.prepare()
                if fault == 'case':self.case['arguments'] = [8]
                elif fault == 'actions':self.controller.actions = ('a' * 64, 'b' * 64)
                elif fault == 'profile':self.controller.profile = 'future'
                elif fault == 'pending':self.controller.pending = {}
                elif fault == 'terminal':self.controller.terminal = None
                elif fault == 'identity':self.controller.identity = None
                elif fault == 'pid':self.process['pid'] = True
                else:self.process['argv'] = ['another-java']
                self.write_inputs()
                with self.assertRaises(ValueError):self.qualify()

    def test_baseline_has_the_same_host_plan_and_never_fabricates_sdk_evidence(self):
        self.controller.plain = True;self.controller.identity = None
        self.assertIsNone(self.qualify(bodies=[]))
        for name, value in (('controls', [{'fake': True}]), ('identity', self.identity),
                            ('armed', [{}]), ('completed', [{}])):
            with self.subTest(name=name):
                setattr(self.controller, name, value)
                with self.assertRaisesRegex(ValueError, 'baseline contains'):
                    self.qualify(bodies=[])
                setattr(self.controller, name, None if name == 'identity' else [])
        with self.assertRaises(ValueError):self.qualify()


if __name__ == '__main__':
    unittest.main()
