"""Explicit cache profiles bind public formats and native recipes independently."""

import copy
from dataclasses import replace
import json
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest

ROOT = Path(__file__).resolve().parents[1]
sys.path[:0] = [str(ROOT / 'adapters/generation'), str(ROOT / 'examples')]
import generation
import python_execution as execution
import python_provider as provider
from test_generation_python_execution import fixture, write


class PythonCacheProviderTests(unittest.TestCase):
    def test_cache_negotiation_is_closed_and_separate_from_source_profile(self):
        descriptor = provider.CACHE_PROTOCOLS
        provider.verify_protocols(copy.deepcopy(descriptor), provider.CACHE_PROFILE)
        self.assertEqual(provider.profile_version(provider.CACHE_PROFILE), 3)
        for version in (provider.INPUT_PROFILE, provider.ORIGIN_PROFILE):
            with self.assertRaises(ValueError):
                provider.verify_protocols(descriptor, version)
        for key, value in [('schema_version', True), ('execution', 2), ('code_comparisons', 1),
                           ('source_complete', True), ('origin_scope', provider.ORIGIN_PROTOCOLS['origin_scope'])]:
            with self.subTest(key=key), self.assertRaises(ValueError):
                provider.verify_protocols({**descriptor, key: value}, provider.CACHE_PROFILE)

    def test_protocol_probe_uses_a_separate_fixed_isolated_profile_request(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary).resolve(); workspace = root / 'workspace'; workspace.mkdir()
            calls = []
            def execute(command, *args, **kwargs):
                calls.append(command)
                return subprocess.CompletedProcess(command, 0, json.dumps(provider.CACHE_PROTOCOLS).encode(), b'')
            value = provider.probe_protocols(root, workspace, {'python': Path(sys.executable)}, execute, provider.CACHE_PROFILE)
            self.assertEqual(value, provider.CACHE_PROTOCOLS)
            self.assertIn("profile='python-native-cache-origins-v3'", calls[0][5])
            self.assertEqual(calls[0][1:5], ['-I', '-S', '-B', '-c'])
            provider.probe_protocols(root, workspace, {'python': Path(sys.executable)}, execute, provider.CACHE_PROFILE)
            self.assertEqual(len(calls), 1)
            self.assertTrue((workspace / 'python-provider/protocol-cache-origins-v3/response.json').is_file())

    def test_prepared_and_actual_transport_bind_profile3_in_both_lanes_including_source_fallback(self):
        for plain in (False, True):
            with self.subTest(plain=plain), tempfile.TemporaryDirectory() as temporary:
                intent, launch, owner, catalogue = fixture(Path(temporary), plain=plain, profile=provider.CACHE_PROFILE)
                checked = execution.read(intent, launch, owner, catalogue)
                self.assertEqual(checked.journal.schema_version, 3)
                self.assertEqual(launch['plan']['input_scope'], 'native-application-root-source-and-cache-origins')
                self.assertTrue(checked.journal.capture_complete)
                self.assertEqual([launch[name]['schema_version'] for name in ('request', 'plan', 'prepared')], [3, 3, 3])
                with self.assertRaises(ValueError):
                    execution.read(replace(intent, profile=provider.ORIGIN_PROFILE), launch, owner, catalogue)
                path = intent.runtime / 'python-application-start.json'
                before = generation.read(path)
                changed = copy.deepcopy(before); changed['native_command'][1] = '--origin-loader-root'
                write(path, changed)
                with self.assertRaises(ValueError):
                    execution.read(intent, launch, owner, catalogue)

    def test_cache_metadata_cannot_select_the_source_native_recipe_or_a_downgraded_journal(self):
        with tempfile.TemporaryDirectory() as temporary:
            intent, launch, owner, catalogue = fixture(Path(temporary), profile=provider.CACHE_PROFILE)
            path = intent.runtime / 'python-inputs.journal'
            original = path.read_bytes()
            path.write_bytes(original.replace(b'OTLCPY3\0', b'OTLCPY2\0'))
            with self.assertRaises(ValueError):
                execution.read(intent, launch, owner, catalogue)
