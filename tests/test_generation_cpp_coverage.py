"""The compiled observer gate counts exact product files and preserves Clang mode."""
from contextlib import redirect_stdout
import io
import json
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "ci"))
import cpp_coverage


class CppCoverageTests(unittest.TestCase):
    def document(self, source, count=10, covered=8):
        return {"data": [{"files": [{"filename": str(source), "summary": {"lines": {"count": count, "covered": covered}}}]}]}

    def test_exact_source_nonempty_unique_and_independent_floor(self):
        source = Path("observer.hpp").resolve()
        self.assertEqual(cpp_coverage.coverage(self.document(source), source), 80)
        for total, covered in ((0, 0), (10, 7), (10, 11), (10, -1), (True, 1)):
            document = self.document(source, total, covered)
            with self.subTest(total=total, covered=covered), self.assertRaises(ValueError):
                cpp_coverage.coverage(document, source)
        for files in ([], [self.document(source)["data"][0]["files"][0]]*2):
            with self.assertRaisesRegex(ValueError, "missing or ambiguous"):
                cpp_coverage.coverage({"data": [{"files": files}]}, source)

    def test_build_uses_cpp_argv_and_matching_real_compiler_coverage_tools(self):
        with tempfile.TemporaryDirectory() as temporary:
            repo = Path(temporary)
            source = repo / "adapters/generation/cpp_observe.hpp"
            source.parent.mkdir(parents=True)
            source.write_text("// observer")
            tools = repo / "bin"
            tools.mkdir()
            actual = tools / "clang-18"
            actual.touch()
            compiler = tools / "clang++"
            compiler.symlink_to(actual)
            for name in ("llvm-profdata", "llvm-cov"):
                (tools / name).touch()
            output = json.dumps(self.document(source)).encode()
            with patch.object(cpp_coverage.shutil, "which", return_value=str(compiler)), \
                 patch.object(cpp_coverage.subprocess, "run", return_value=subprocess.CompletedProcess([], 0, output, b"")) as run, \
                 redirect_stdout(io.StringIO()):
                cpp_coverage.check(repo)
            self.assertEqual(run.call_args_list[0].args[0][0], compiler)
            self.assertEqual(run.call_args_list[2].args[0][0], (tools / "llvm-profdata").resolve())
            self.assertEqual(run.call_args_list[3].args[0][0], (tools / "llvm-cov").resolve())
            self.assertEqual(json.loads((repo / "build/cpp-observer-coverage.json").read_text()), self.document(source))

    def test_missing_compiler_or_matching_tools_is_not_a_skipped_gate(self):
        with patch.object(cpp_coverage.shutil, "which", return_value=None), self.assertRaisesRegex(ValueError, "selected Clang"):
            cpp_coverage.check(Path("."))
        with tempfile.TemporaryDirectory() as temporary:
            compiler = Path(temporary) / "clang++"
            compiler.touch()
            with patch.object(cpp_coverage.shutil, "which", return_value=str(compiler)), self.assertRaisesRegex(ValueError, "llvm-cov"):
                cpp_coverage.check(Path(temporary))
