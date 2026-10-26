"""Literal Rust descriptors bind both original source-build profiles."""

from pathlib import Path
import subprocess
import sys
import unittest
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[1]
sys.path[:0] = [str(ROOT / 'adapters/generation'), str(ROOT / 'examples')]
import generation
import rust_protocol


def literal(version: int) -> dict:
    """Use the reserved SDK contract without asking the reader to produce it."""
    return {'schema_version': 1, 'kind': 'otelc.rust.protocols',
            'profile': 'rust1981-owned-standalone-v1', 'owned_build': 1,
            'source_build': version,
            'source_profile': ('rust1981-standalone-sync-v1' if version == 1
                               else 'rust1981-standalone-drop-v2'),
            'request': 1, 'plan': 1, 'prepared': 1, 'command': 1,
            'execution': 1, 'host_release': 1, 'gate': 1,
            'native_plan': 2 if version == 1 else 3,
            'health': 1 if version == 1 else 5,
            'embedded_sdk': True, 'source_complete': False}


class RustProtocolTests(unittest.TestCase):
    def test_both_literal_descriptors_validate_without_execution(self) -> None:
        with patch.object(subprocess, 'Popen', side_effect=AssertionError('must not execute')):
            for version in (1, 2):
                value = literal(version)
                result = rust_protocol.verify(value, source_build_version=version)
                self.assertEqual(result, value)
                self.assertIsNot(result, value)
                result.clear()
                self.assertEqual(rust_protocol.descriptor(version), value)

    def test_every_missing_extra_or_changed_field_is_refused(self) -> None:
        for version in (1, 2):
            value = literal(version)
            for key, original in value.items():
                if type(original) is int:
                    changes = (True, float(original), 99)
                elif type(original) is bool:
                    changes = (int(original), not original)
                else:
                    changes = ('foreign', None)
                for changed in changes:
                    with self.subTest(version=version, key=key, changed=changed), self.assertRaises(ValueError):
                        rust_protocol.verify(value | {key: changed}, source_build_version=version)
                with self.subTest(missing=key), self.assertRaises(ValueError):
                    rust_protocol.verify({k: v for k, v in value.items() if k != key}, source_build_version=version)
            with self.assertRaises(ValueError):
                rust_protocol.verify(value | {'extra': False}, source_build_version=version)

    def test_caller_version_and_mixed_profiles_are_refused(self) -> None:
        for version in (False, True, 1.0, '1', 0, 3, None):
            with self.subTest(version=version), self.assertRaises(ValueError):
                rust_protocol.descriptor(version)
        with self.assertRaises(ValueError):
            rust_protocol.verify(literal(1), source_build_version=2)
        with self.assertRaises(ValueError):
            rust_protocol.verify(None, source_build_version=1)

    def test_readers_are_embedded_and_bound_to_the_generator_identity(self) -> None:
        embedded = (ROOT / 'src/generation.rs').read_text()
        original_digest = generation.capture.file_digest
        baseline = generation.generator_identity()
        for name in ('rust_tools.py', 'rust_protocol.py', 'rust_inventory.py', 'rust_lifetimes.py',
                     'rust_build_recipe.py', 'rust_source_build.py', 'rust_owned_build.py',
                     'rust_prepared.py', 'rust_health.py', 'rust_execution.py', 'rust_session.py'):
            self.assertIn('include_str!("../adapters/generation/' + name + '")', embedded)

            def changed(path: Path) -> str:
                if path == ROOT / 'adapters/generation' / name:
                    return '0' * 64
                return original_digest(path)

            with patch.object(generation.capture, 'file_digest', side_effect=changed):
                self.assertNotEqual(generation.generator_identity(), baseline)


if __name__ == '__main__':
    unittest.main()
