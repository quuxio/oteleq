"""The live-control oracle must reject changes anywhere in its complete graphs."""

import copy
import json
import os
import shutil
import subprocess
import sys
from pathlib import Path
import tempfile
import tomllib
import unittest
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[1]
sys.path[:0] = [str(ROOT / "adapters/generation"), str(ROOT / "examples")]
import node_controls_oracle as oracle
import node_controls_routes as routes
import policy
import qualify_node_controls as qualification


class NodeControlsOracleTests(unittest.TestCase):
    def test_startup_rotations_keep_policy_states_and_error_collection_independent(self):
        for name, offset in qualification.STARTUP_OFFSETS.items():
            states = qualification.startup_states(name)
            self.assertEqual(states, qualification.STATES[offset:] + qualification.STATES[:offset])
            self.assertEqual(sum(state['collection'] for state in states), 2)
            self.assertEqual(sum(all(state.values()) for state in states), 1)
            for language, compiler in (('javascript', 'native'), ('typescript', 'native'), ('typescript', 'api')):
                configured = policy.validate(tomllib.loads(qualification.policy(language, compiler, states=states)))
                for fixture in configured['fixtures']:
                    self.assertEqual([step['metrics'] for step in fixture['sequence']], list(states))
            for method in oracle.METHODS:
                expected = {'otelc.function.calls': 2, 'otelc.function.duration': 2}
                if method == 'expected' and states[2]['collection']:
                    expected['otelc.function.unwinds'] = 1
                self.assertEqual(qualification.expected_metrics(method, states), expected)
            states[0]['collection'] = not states[0]['collection']
            self.assertEqual(qualification.startup_states(name)[0], qualification.STATES[offset])
        with self.assertRaisesRegex(ValueError, 'startup metric state'):
            qualification.startup_states('unknown')

    def test_rotated_framework_retains_the_expected_state_in_each_report_check(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            report = root / 'report.json'
            report.write_text(json.dumps({'cases': [{'function': 'controls.Counter.difference'}]}))
            states = qualification.startup_states('both-off')
            with patch.object(qualification, 'command', return_value=json.dumps({'report': str(report)})), \
                    patch.object(qualification, 'check_report', return_value={('runtime', 101)}) as check:
                self.assertEqual(qualification.framework(root, root, 'rotated', {'difference'}, states=states),
                                 {('runtime', 101)})
                check.assert_called_once_with(report, {'difference'}, states=states)

    def test_receipt_alterations_change_actual_flags_and_only_disabled_windows(self):
        for name in qualification.STARTUP_OFFSETS:
            states = qualification.startup_states(name)
            record = {'steps': [
                {'requested': state.copy(), 'before': {'history': [
                    {'status': state.copy()}, {'status': {'emission': state['emission'],
                        'effective_emission_off': not state['emission'], 'in_flight_exports': 0}}]},
                 'after': {'held_ns': 1000000000, 'metric_bodies': []}}
                for state in states]}
            edits = routes.receipt_edits(states)
            self.assertEqual(len(edits), 9)
            for edit, key, index in (('held-window', 'held_ns', 0), ('metric-window', 'metric_bodies', [0])):
                changed = copy.deepcopy(record)
                edits[edit](changed)
                altered = [i for i, (old, new) in enumerate(zip(record['steps'], changed['steps'])) if old != new]
                self.assertEqual(len(altered), 1)
                self.assertFalse(all(states[altered[0]].values()))
                self.assertEqual(changed['steps'][altered[0]]['after'][key], index)
            for edit, step, reply, flag in (('initial-state', 0, 0, 'collection'), ('setter', 1, 1, 'emission')):
                changed = copy.deepcopy(record)
                before = changed['steps'][step]['before']['history'][reply]['status'][flag]
                edits[edit](changed)
                self.assertIs(changed['steps'][step]['before']['history'][reply]['status'][flag], not before)
                if edit == 'setter':
                    status = changed['steps'][step]['before']['history'][reply]['status']
                    self.assertIs(status['effective_emission_off'], not status['emission'])

    def test_retained_negative_controls_change_only_the_requested_raw_signal(self):
        from opentelemetry.proto.collector.metrics.v1.metrics_service_pb2 import ExportMetricsServiceRequest
        from opentelemetry.proto.collector.trace.v1.trace_service_pb2 import ExportTraceServiceRequest
        from test_generation_node_telemetry import metrics, traces
        with tempfile.TemporaryDirectory() as temporary:
            folder = Path(temporary)
            trace = traces().SerializeToString()
            metric = metrics()
            calls = metric.resource_metrics[0].scope_metrics[0].metrics[0]
            self.assertEqual(calls.name, 'otelc.function.calls')
            calls.sum.data_points[0].as_int = 2
            (folder / 'trace.protobuf').write_bytes(trace)
            (folder / 'metrics.protobuf').write_bytes(metric.SerializeToString())
            (folder / 'http-capture.json').write_text(json.dumps({'errors': [], 'bodies': [
                {'path': '/v1/traces', 'file': 'trace.protobuf'},
                {'path': '/v1/metrics', 'file': 'metrics.protobuf'}]}))
            routes.alter_otlp(folder, 'retained-metric')
            changed = ExportMetricsServiceRequest.FromString((folder / 'metrics.protobuf').read_bytes())
            self.assertEqual(changed.resource_metrics[0].scope_metrics[0].metrics[0].sum.data_points[0].as_int, 1)
            self.assertEqual((folder / 'trace.protobuf').read_bytes(), trace)
            preserved = (folder / 'metrics.protobuf').read_bytes()
            routes.alter_otlp(folder, 'missing-trace')
            self.assertEqual(len(ExportTraceServiceRequest.FromString((folder / 'trace.protobuf').read_bytes()).resource_spans), 0)
            self.assertEqual((folder / 'metrics.protobuf').read_bytes(), preserved)

    def test_changed_current_source_requires_its_independent_return_oracle(self):
        for method in oracle.METHODS:
            for active in (False, True):
                observed = oracle.expected(method, 7, active, result=43)
                oracle.check(observed, method, 7, active, result=43)
                with self.assertRaises(ValueError):
                    oracle.check(observed, method, 7, active)

    def test_reduced_framework_requires_exact_selected_method_set(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            report = root / 'report.json'
            report.write_text(json.dumps({'cases': [{'function': 'controls.Counter.difference'}]}))
            output = json.dumps({'report': str(report)})
            with patch.object(qualification, 'command', return_value=output), \
                    patch.object(qualification, 'check_report', return_value={('actual-runtime', 101)}):
                self.assertEqual(qualification.framework(root, root, 'reduced', {'difference'}), {('actual-runtime', 101)})
                with self.assertRaises(ValueError):
                    qualification.framework(root, root, 'missing-methods')
                with self.assertRaises(ValueError):
                    qualification.framework(root, root, 'wrong-method', {'add'})

    def test_negative_fixture_uses_actual_launch_arguments_after_sdk_environment_cleanup(self):
        node = os.environ.get("OTELC_NODE") or shutil.which("node")
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            script = root / "controls.cjs"
            script.write_text(qualification.source("javascript")
                              + '\nconst counter=new Counter(10),states=[];for(const value of [7,2,3,4]){counter.difference(value);states.push(Counter.delta);}'
                              + 'require("node:fs").writeFileSync(process.env.OTELEQ_OBSERVATION,JSON.stringify(states));\n')
            output = root / "observed.json"
            for bootstrap, active in ((None, False), ("node-plain-bootstrap.cjs", False), ("node-bootstrap.cjs", True)):
                arguments = []
                if bootstrap:
                    filename = root / bootstrap;filename.write_text('// Controlled argv fixture; no SDK is installed here.\n')
                    arguments = ["--require", str(filename)]
                environment = {**os.environ, "OTELEQ_OBSERVATION": str(output)}
                environment.pop("OTELC_NODE_PLAN", None)
                result = subprocess.run([node, *arguments, script], env=environment, capture_output=True, timeout=10)
                self.assertEqual(result.returncode, 0, result.stderr)
                self.assertEqual(json.loads(output.read_bytes()), [0, int(active), 0, 0])
                self.assertEqual(result.stdout, bytes.fromhex("00ff0a") * 4)
                self.assertEqual(result.stderr, bytes.fromhex("01ff0a") * 4)

    def test_literal_graphs_include_every_intermediate_state_and_expected_error(self):
        for method in oracle.METHODS:
            for active in (False, True):
                expected = oracle.expected(method, 7, active)
                oracle.check(expected, method, 7, active)
                for changed in ("value", "descriptor", "alias", "field-order", "extra", "outcome"):
                    altered = copy.deepcopy(expected)
                    graph = altered["steps"][1]["after"]
                    if changed == "value":
                        graph["nodes"][1]["fields"][0][1] = oracle.number(999)
                    elif changed == "descriptor":
                        graph["nodes"][2]["fields"][0][1]["value"] = 1
                    elif changed == "alias":
                        graph["nodes"][1]["fields"][1][1] = {"ref": 0}
                    elif changed == "field-order":
                        graph["nodes"][1]["fields"].reverse()
                    elif changed == "extra":
                        graph["unknown"] = True
                    else:
                        altered["steps"][0]["outcome"]["value"]["roots"]["result"] = oracle.number(41)
                    with self.subTest(method=method, active=active, changed=changed), self.assertRaises(ValueError):
                        oracle.check(altered, method, 7, active)
        self.assertEqual(oracle.expected("expected", 7, True)["steps"][2]["outcome"]["kind"], "error")
        with self.assertRaises(ValueError):
            oracle.expected("unknown", 7, False)

    def test_reviewed_policy_selects_only_methods_and_retains_all_four_states(self):
        for language, compiler in (("javascript", "native"), ("typescript", "native"), ("typescript", "api")):
            configuration = policy.validate(tomllib.loads(qualification.policy(language, compiler)))
            self.assertEqual(configuration["functions"]["include"], ["controls.Counter." + method for method in oracle.METHODS])
            self.assertEqual(len(configuration["fixtures"]), 4)
            for fixture in configuration["fixtures"]:
                self.assertEqual([step["metrics"] for step in fixture["sequence"]], list(qualification.STATES))
            source = qualification.source(language)
            self.assertIn("Buffer.from([0,255,10])", source)
            self.assertIn("Buffer.from([1,255,10])", source)
            self.assertIn("throw new TypeError('expected')", source)
            self.assertIn("Counter.delta=0", source)
