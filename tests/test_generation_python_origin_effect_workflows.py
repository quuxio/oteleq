"""The prepared workflow oracle must reject matching but incorrect captures."""

import ast
import copy
import json
from pathlib import Path
import sys
import tempfile
import unittest

ROOT = Path(__file__).resolve().parents[1]
sys.path[:0] = [str(ROOT / 'adapters/generation'), str(ROOT / 'examples')]
import generation
import python_origin_effect_workflows as oracle


class OriginEffectOracleTests(unittest.TestCase):
    def test_current_source_stages_declare_the_expected_functions_and_counter_change(self):
        for stage in ('direct', 'export', 'promoted-unchanged', 'promoted-changed-body', 'promoted-added-function'):
            source = oracle.stage_source(stage)
            names = [node.name for node in ast.parse(source).body if isinstance(node, ast.FunctionDef)]
            self.assertEqual(names, ['exercise', 'exercise_added'] if stage == 'promoted-added-function' else ['exercise'])
            self.assertEqual('counter+=value+1' in source, stage in ('promoted-changed-body', 'promoted-added-function'))
        with self.assertRaises(AssertionError):
            oracle.stage_source('unrecognised')

    def test_graph_and_filesystem_oracles_have_complete_literal_values(self):
        self.assertEqual(oracle.graph(3, 4, result=True), {
            'roots': {'arguments': {'ref': 0}, 'global:counter': {'type': 'int', 'value': '4'},
                      'result': {'type': 'int', 'value': '7'}},
            'nodes': [{'type': 'builtins.list', 'items': [{'type': 'int', 'value': '3'}]}]})
        value = oracle.filesystem(3)
        self.assertEqual(value['before']['entries'], [
            {'path_hex': '', 'kind': 'directory', 'mode': 448},
            {'path_hex': '656d707479', 'kind': 'directory', 'mode': 448},
            {'path_hex': '736565642e62696e', 'kind': 'file', 'mode': 384, 'hex': '00ff'}])
        self.assertEqual(value['after']['entries'][2],
                         {'path_hex': '6f75742e62696e', 'kind': 'file', 'mode': 384, 'hex': '00ff03ff'})

    def test_wrong_argument_state_effect_permissions_request_and_witness_refuse(self):
        with tempfile.TemporaryDirectory() as temporary:
            folder = Path(temporary)
            path = folder / 'report.json'
            generation.write(path, {'source_preserved': True, 'blocked': [], 'cases': [
                {'case': 'chosen', 'function': 'app.exercise', 'arguments': [3], 'exit_code': 0}]})
            case = folder / 'chosen'; case.mkdir()
            before = {'roots': {'arguments': {'ref': 0}, 'global:counter': {'type': 'int', 'value': '0'}},
                      'nodes': [{'type': 'builtins.list', 'items': [{'type': 'int', 'value': '3'}]}]}
            after = copy.deepcopy(before); after['roots']['global:counter']['value'] = '3'
            result = copy.deepcopy(after); result['roots']['result'] = {'type': 'int', 'value': '7'}
            raw = {'before': before, 'after': after, 'outcome': {'kind': 'return', 'value': result}}
            http = {'complete': True, 'gaps': [], 'requests': [{'method': 'POST', 'target_hex': '2f6f627365727665',
                'version': 'HTTP/1.1', 'body_hex': '03ff', 'response_index': 0,
                'response_hex': b'HTTP/1.1 201 Fixture\r\nConnection: close\r\nContent-Length: 2\r\n\r\n\x00\xff'.hex(),
                'header_lines_hex': [b'Host: 127.0.0.1:1234'.hex(), b'X-Check: fixture'.hex()]}]}
            bundle = {'baseline': [], 'instrumented_on': []}
            for lane in bundle:
                for index in range(2):
                    attempt = case / (lane + '-' + str(index)); attempt.mkdir()
                    generation.write(attempt / 'observation', raw)
                    generation.write(attempt / 'http-controls.json', {'environment': {'APP_SERVICE_URL': 'http://127.0.0.1:1234'}})
                    generation.write(attempt / 'python-verified-origins.json', {'selected': [{'qualname': 'exercise'}]})
                    execution = {'capture_complete': True, 'termination': {'kind': 'exit', 'code': 0},
                        'channels': {'stdout': [], 'stderr': [],
                                     'filesystem:data': list(json.dumps(oracle.filesystem(3)).encode()),
                                     'http:service': list(json.dumps(http).encode())},
                        'witness': None if lane == 'baseline' else {'functions': {'app.exercise': 1},
                            'spans': 1, 'pending': 0, 'losses': {'incomplete': 0}}}
                    bundle[lane].append({'execution': execution})
            document = {'cases': [bundle]}
            target = case / 'typed-bundle.json'; generation.write(target, document)
            self.assertEqual(len(oracle.check_report(path)[1]), 4)
            changed_raw = copy.deepcopy(raw)
            changed_raw['before']['nodes'][0]['items'][0]['value'] = '4'
            generation.write(case / 'baseline-0/observation', changed_raw)
            with self.assertRaises(AssertionError):
                oracle.check_report(path)
            generation.write(case / 'baseline-0/observation', raw)
            for fault in ('filesystem', 'http', 'witness', 'complete'):
                changed = copy.deepcopy(document)
                execution = changed['cases'][0]['instrumented_on'][0]['execution']
                if fault == 'filesystem':
                    value = oracle.filesystem(3); value['after']['entries'][2]['mode'] = 420
                    execution['channels']['filesystem:data'] = list(json.dumps(value).encode())
                elif fault == 'http':
                    value = copy.deepcopy(http); value['requests'][0]['body_hex'] = '04ff'
                    execution['channels']['http:service'] = list(json.dumps(value).encode())
                elif fault == 'witness':
                    execution['witness']['functions'] = {}
                else:
                    execution['capture_complete'] = False
                generation.write(target, changed)
                with self.subTest(fault=fault), self.assertRaises(AssertionError):
                    oracle.check_report(path)
