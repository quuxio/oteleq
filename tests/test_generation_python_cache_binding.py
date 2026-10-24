"""Expected callable identity follows the explicit ordinary cache-loader profile."""
import hashlib
import os
from pathlib import Path
import py_compile
import sys
import tempfile
from types import FunctionType
import unittest
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[1]
sys.path[:0] = [str(ROOT / 'adapters/generation'), str(ROOT / 'examples')]
import harness
import observe

OLD = '__oteleq_freeze_marker=1/0\ndef selected(value:int)->int:return value+1\n'
NEW = OLD.replace('value+1', 'value+2')
TIME = 1_700_000_000_123456789


def manifest(root: Path) -> dict:
    return {str(p.relative_to(root)): (hashlib.sha256(p.read_bytes()).hexdigest(), p.stat().st_mtime_ns,
                                     p.stat().st_mode, p.stat().st_ino)
            for p in root.rglob('*') if p.is_file()}


class PythonCacheBindingTests(unittest.TestCase):
    def test_unchecked_cache_can_keep_an_older_body_without_claiming_current_source_compilation(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary).resolve(); source = root / 'target.py'; source.write_text(OLD)
            os.utime(source, ns=(TIME, TIME))
            py_compile.compile(str(source), doraise=True, invalidation_mode=py_compile.PycInvalidationMode.UNCHECKED_HASH)
            source.write_text(NEW); os.utime(source, ns=(TIME, TIME))
            before = manifest(root)
            with patch.object(sys, 'dont_write_bytecode', True):
                cached = observe.function_code(source, 'selected', 2, cached=True)
            current = observe.function_code(source, 'selected', 2)
            self.assertEqual(FunctionType(cached, {})(7), 8)
            self.assertEqual(FunctionType(current, {})(7), 9)
            self.assertNotEqual(cached, current)
            self.assertEqual(manifest(root), before)
            with patch.object(sys, 'dont_write_bytecode', True), self.assertRaisesRegex(ValueError, 'unique source'):
                observe.function_code(source, 'missing', 2, cached=True)

    def test_missing_and_invalidated_caches_follow_source_without_creating_or_replacing_files(self):
        for mode in (None, py_compile.PycInvalidationMode.TIMESTAMP, py_compile.PycInvalidationMode.CHECKED_HASH):
            with self.subTest(mode=mode), tempfile.TemporaryDirectory() as temporary:
                root = Path(temporary).resolve(); source = root / 'target.py'; source.write_text(OLD)
                os.utime(source, ns=(TIME, TIME))
                if mode is not None:
                    py_compile.compile(str(source), doraise=True, invalidation_mode=mode)
                source.write_text(NEW); os.utime(source, ns=(TIME + 2_000_000_000, TIME + 2_000_000_000))
                before = manifest(root)
                with patch.object(sys, 'dont_write_bytecode', True):
                    expected = observe.function_code(source, 'selected', 2, cached=True)
                self.assertEqual(FunctionType(expected, {})(7), 9)
                self.assertEqual(manifest(root), before)

    def test_cache_aware_binding_refuses_to_enable_loader_writes(self):
        with tempfile.TemporaryDirectory() as temporary:
            source = Path(temporary).resolve() / 'target.py'; source.write_text(OLD)
            with patch.object(sys, 'dont_write_bytecode', False), \
                    patch.object(observe, 'SourceFileLoader') as loader, self.assertRaisesRegex(ValueError, 'disabled bytecode writes'):
                observe.function_code(source, 'selected', 2, cached=True)
            loader.assert_not_called()

    def test_only_explicit_cache_profile_changes_target_and_source_factory_binding(self):
        entry = {'language': 'python', 'path': 'target.py', 'name': 'Counter.add', 'line': 8,
                 'globals': [], 'receiver_fixture': {'source_function': 'make_counter', 'line': 20},
                 'python_receiver_class': 'Counter'}
        for profile in (None, 'python-native-origins-v2', 'python-native-cache-origins-v3'):
            configured = {**entry, 'python_backend': 'prepared', 'python_profile': profile}
            text = harness.python_driver(configured, [7])
            calls = [line for line in text.splitlines() if line.startswith(('expected_code =', 'expected_factory ='))]
            self.assertEqual(len(calls), 2)
            self.assertEqual(sum('cached=True' in call for call in calls),
                             2 if profile == 'python-native-cache-origins-v3' else 0)
