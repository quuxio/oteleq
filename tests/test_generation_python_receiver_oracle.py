"""Existing receiver compatibility checks cover complete raw and typed state."""

import argparse
import copy
import json
import os
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest

ROOT = Path(__file__).resolve().parents[1]
sys.path[:0] = [str(ROOT / 'adapters/generation'), str(ROOT / 'examples')]
import discovery
import generation
import harness
import policy
import typed_capture
import python_receiver_oracle as oracle
import qualify_receivers


class PythonReceiverOracleTests(unittest.TestCase):
    def test_each_original_plain_worker_matches_every_declared_value_and_alias(self):
        for method in oracle.METHODS:
            with self.subTest(method=method), tempfile.TemporaryDirectory() as temporary:
                folder = Path(temporary)
                package = folder / 'src/pkg'
                package.mkdir(parents=True)
                (package / '__init__.py').write_text('')
                (package / 'state.py').write_text(qualify_receivers.SOURCE)
                parsed = discovery.python_inventory(qualify_receivers.SOURCE)
                parsed['entrypoints'] = []
                identity = 'src.pkg.state.Counter.' + method
                fixture = {'function': identity, 'cases': [[7]],
                           'receiver': {'factory': 'make_counter' if method == 'silent' else 'Counter',
                                        'arguments': [10]}}
                if method == 'fail':
                    fixture['expected_baseline'] = {'kind': 'error', 'category': 'exception',
                                                    'type': 'python.builtins.ValueError'}
                configuration = policy.validate({'languages': ['python'],
                    'adapters': {'python': {'import_roots': ['src']}},
                    'functions': {'include': [identity]}, 'fixtures': [fixture]})
                selected = next(row for row in parsed['functions'] if row['name'] == 'Counter.' + method)
                entry = generation.inventory_entry(selected, parsed, 'src/pkg/state.py', 'python', 'a' * 64,
                    folder, argparse.Namespace(configuration=configuration, cases=1))
                self.assertEqual(entry['status'], 'ready', entry['reason'])
                driver = harness.materialise(folder, entry, [7])
                output = folder / 'observation'
                result = subprocess.run([sys.executable, '-B', driver], cwd=folder,
                    env={**os.environ, 'OTELEQ_OBSERVATION': str(output)},
                    capture_output=True, timeout=30, check=False)
                self.assertEqual((result.returncode, result.stdout, result.stderr), (0, b'', b''))
                raw = json.loads(output.read_text())
                observed = typed_capture.observation(output.read_bytes(), entry,
                    {'case_id': 'case', 'function_id': identity, 'fixture_sha256': 'b' * 64})
                oracle.check_observation(observed, raw, method, 7, False)

    def test_missing_or_wrong_legacy_state_cannot_be_a_passing_compatibility_case(self):
        raw = oracle.raw_observation('identity', 7, False)
        from python_sequence_fixture import boundaries
        observed = {'gaps': [], **boundaries(raw)}
        oracle.check_observation(observed, raw, 'identity', 7, False)
        for target in ('global', 'alias', 'field'):
            changed = copy.deepcopy(raw)
            if target == 'global':
                changed['after']['roots']['static:Counter.total']['value'] = '999'
            else:
                receiver = changed['after']['nodes'][changed['after']['roots']['receiver']['ref']]
                receiver['fields'][1 if target == 'alias' else 0][1] = {'type': 'int', 'value': '999'}
            with self.subTest(target=target), self.assertRaises(AssertionError):
                oracle.check_observation(observed, changed, 'identity', 7, False)
        altered = copy.deepcopy(observed)
        altered['after']['roots']['static:Counter.total']['value'] = '999'
        with self.assertRaises(AssertionError):
            oracle.check_observation(altered, raw, 'identity', 7, False)

    def test_old_silent_and_static_only_differences_remain_independently_expected(self):
        for method in ('silent', 'static_only'):
            before = oracle.raw_observation(method, 7, False)
            after = oracle.raw_observation(method, 7, True)
            self.assertNotEqual(before['after'], after['after'])
            self.assertEqual(before['outcome']['value']['roots']['result'],
                             after['outcome']['value']['roots']['result'])


if __name__ == '__main__':
    unittest.main()
