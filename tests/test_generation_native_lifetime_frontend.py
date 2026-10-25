"""Literal compiler-query controls; no compiler, helper or SDK is executed."""

from dataclasses import replace
from pathlib import Path
import shlex
import subprocess
import sys
import tempfile
from types import SimpleNamespace
import unittest
from unittest.mock import Mock, patch

ROOT = Path(__file__).resolve().parents[1]
sys.path[:0] = [str(ROOT / 'adapters/generation'), str(ROOT / 'examples')]
import native_lifetime_fixture
import native_lifetime_frontend as frontend
import otelc_capture


class NativeLifetimeFrontendTests(unittest.TestCase):
    def fixture(self, kind='object'):
        temporary = tempfile.TemporaryDirectory()
        self.addCleanup(temporary.cleanup)
        root = Path(temporary.name).resolve()
        intent = native_lifetime_fixture.build(root, kind=kind)
        source = SimpleNamespace(sdk=intent.base.sdk, project=intent.base.project, verify=Mock())
        calls = []

        def execute(argv, directory):
            words = list(map(str, argv))
            calls.append((words, directory))
            if '-M' in words:
                destination = Path(words[words.index('-MF') + 1])
                destination.write_text('otelc-inputs: ' + shlex.join(
                    str(row.path) for row in intent.tool.dependencies) + '\n')
                output = b''
            elif words[-1] == '--libdir':
                output = (str(intent.tool.library_directory) + '\n').encode()
            else:
                self.assertEqual(words[-1], '-print-target-triple')
                output = b'aarch64-unknown-linux-gnu\n'
            return subprocess.CompletedProcess(words, 0, output, b'original diagnostic')

        return root, intent, source, calls, execute

    def test_both_frontends_freeze_fixed_queries_and_complete_original_inputs(self):
        for kind in ('object', 'resource'):
            with self.subTest(kind=kind):
                root, intent, source, calls, execute = self.fixture(kind)
                result = frontend.prepare(source, kind, root / 'frontend', execute)
                result.verify()
                self.assertEqual(len(result.files), 11)
                self.assertEqual(result.tool.dependencies, intent.tool.dependencies)
                self.assertEqual(result.tool.libraries, intent.tool.libraries)
                self.assertEqual(result.tool.host_target, 'aarch64-unknown-linux-gnu')
                expected = [str(source.sdk.toolchain.directory / 'clang++'),
                    *source.sdk.toolchain.cxxflags, '-std=c++17', '-fexceptions', '-O1', '-g',
                    '-M', '-MT', 'otelc-inputs', '-MF', str(root / 'frontend/tool.d'),
                    str(intent.tool.source.path)]
                self.assertEqual(calls[0], (expected, source.sdk.root))
                self.assertEqual(calls[1][0], [str(source.sdk.toolchain.config.path), '--libdir'])
                self.assertEqual(calls[2][0], [str(source.sdk.toolchain.directory / 'clang++'), '-print-target-triple'])
                context = otelc_capture.strict_json((root / 'frontend/context.json').read_bytes())
                self.assertEqual(context['profile'], kind)
                self.assertEqual(context['inputs'], [row.gate_identity() for row in intent.tool.dependencies])
                self.assertGreaterEqual(source.verify.call_count, 2)

    def test_query_failure_preserves_original_command_and_both_channels(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary).resolve()
            execute = Mock(return_value=subprocess.CompletedProcess(['fixed'], 7, b'output', b'error'))
            with self.assertRaisesRegex(ValueError, 'original channels retained'):
                frontend.query(root, 'failed', ['fixed', '--query'], root, execute)
            self.assertEqual((root / 'failed.stdout').read_bytes(), b'output')
            self.assertEqual((root / 'failed.stderr').read_bytes(), b'error')
            record = otelc_capture.strict_json((root / 'failed.command.json').read_bytes())
            self.assertEqual(record, {'argv': ['fixed', '--query'], 'directory': str(root), 'returncode': 7})
            for result in (subprocess.CompletedProcess([], 0, 'text', b''),
                           subprocess.CompletedProcess([], 0, b'too large', b'')):
                with patch.object(frontend, 'MAX_QUERY_BYTES', 2), self.assertRaises(ValueError):
                    frontend.query(root, 'invalid', ['fixed'], root, Mock(return_value=result))

    def test_dependency_discovery_keeps_escaped_names_aliases_and_a_closed_budget(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary).resolve()
            header = root / 'a b$header.h'; header.write_text('literal header')
            alias = root / 'alias.h'; alias.symlink_to(header)
            raw = b'otelc-inputs: a\\ b$$header.h \\\n alias.h a\\ b$$header.h\n'
            paths, aliases = frontend.dependencies(raw, root)
            self.assertEqual(paths, (header,))
            self.assertEqual(aliases, (alias,))
            for raw in (b'other: alias.h', b'otelc-inputs:', b'otelc-inputs: bad\0name',
                        b'otelc-inputs: "unterminated', b'\xff'):
                with self.subTest(raw=raw), self.assertRaises(ValueError):
                    frontend.dependencies(raw, root)
            with self.assertRaises(FileNotFoundError):
                frontend.dependencies(b'otelc-inputs: missing.h', root)
            with patch.object(frontend, 'MAX_DEPENDENCIES', 1), self.assertRaises(ValueError):
                frontend.dependencies(b'otelc-inputs: alias.h alias.h', root)

    def test_fixed_query_outputs_and_early_source_profile_refuse_before_tool_use(self):
        for label, output in (('inputs', b'unexpected'), ('libdir', b'relative'),
                              ('libdir', b'/one\n/two'), ('host', b''), ('host', b'one\ntwo')):
            with self.subTest(label=label, output=output):
                root, _, source, _, execute = self.fixture()
                def altered(argv, directory):
                    result = execute(argv, directory)
                    actual = 'inputs' if '-M' in list(map(str, argv)) else (
                        'libdir' if str(argv[-1]) == '--libdir' else 'host')
                    return replace_result(result, output) if actual == label else result
                with self.assertRaises(ValueError):
                    frontend.prepare(source, 'object', root / 'frontend', altered)
        root, _, source, _, execute = self.fixture()
        source.sdk = replace(source.sdk, source_profile='function-v2')
        with self.assertRaisesRegex(ValueError, 'complete SDK ABI catalogue'):
            frontend.prepare(source, 'object', root / 'frontend', execute)
        self.assertFalse((root / 'frontend').exists())

    def test_changed_or_extra_evidence_and_restored_bytes_cannot_repair_context(self):
        root, _, source, _, execute = self.fixture('resource')
        result = frontend.prepare(source, 'resource', root / 'frontend', execute)
        with self.assertRaises(ValueError):
            replace(result, files=()).verify()
        with self.assertRaises(ValueError):
            replace(result, files=(object(),)).verify()
        extra = result.directory / 'foreign'; extra.write_text('unowned')
        with self.assertRaises(ValueError):
            result.verify()
        extra.unlink()
        path = result.directory / 'host.stdout'
        original = path.read_bytes(); path.write_bytes(b'changed')
        with self.assertRaises(ValueError):
            result.verify()
        path.write_bytes(original)
        with self.assertRaises(ValueError):
            result.verify()


def replace_result(result, stdout):
    return subprocess.CompletedProcess(result.args, result.returncode, stdout, result.stderr)


if __name__ == '__main__':
    unittest.main()
