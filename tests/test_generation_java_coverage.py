"""Coverage tooling cannot accept altered jars, missing classes or weak scores."""
import hashlib
import io
from pathlib import Path
import sys
import tempfile
import unittest
from unittest.mock import patch
import zipfile

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "ci"))
import java_coverage


def report(covered: int, missed: int, name: str = "OteleqGraph") -> str:
    return f'<report><package><class name="{name}"><counter type="LINE" covered="{covered}" missed="{missed}"/></class></package></report>'


class JavaCoverageTests(unittest.TestCase):
    def test_only_the_observer_class_and_a_nonempty_eighty_percent_score_pass(self):
        with tempfile.TemporaryDirectory() as temporary:
            path = Path(temporary) / "report.xml"
            path.write_text(report(8, 2))
            self.assertEqual(java_coverage.coverage(path), 80)
            for text in (report(7, 3), report(0, 0), report(-1, 2), report(100, 0, "Unrelated"), report(100, 0, "OteleqGraphOther"),
                         report(100, 0).replace('</class>', '<counter type="LINE" covered="1" missed="0"/></class>'),
                         '<report/>', report(100, 0).replace('</package>', '<class name="OteleqGraph"><counter type="LINE" covered="1" missed="0"/></class></package>')):
                path.write_text(text)
                with self.subTest(text=text), self.assertRaises(ValueError):
                    java_coverage.coverage(path)

    def test_compiler_coverage_requires_unique_outer_and_nested_product_classes(self):
        outer = report(8, 2, "OteleqCompile")
        child = '<class name="OteleqCompile$Manager"><counter type="LINE" covered="8" missed="2"/></class>'
        with tempfile.TemporaryDirectory() as temporary:
            path = Path(temporary) / "report.xml"
            path.write_text(outer.replace('</package>', child + '</package>'))
            self.assertEqual(java_coverage.coverage(path, "OteleqCompile", nested=True), 80)
            for text in (report(100, 0, "OteleqCompileOther"), report(100, 0, "OteleqCompile$Manager"),
                         outer.replace('</package>', child * 2 + '</package>'),
                         outer.replace('</package>', child.replace('covered="8"', 'covered="-1"') + '</package>'),
                         outer.replace('</package>', '<class name="OteleqCompile$Manager"/></package>')):
                path.write_text(text)
                with self.subTest(text=text), self.assertRaises(ValueError):
                    java_coverage.coverage(path, "OteleqCompile", nested=True)

    def test_download_and_products_are_pinned_before_any_cache_write(self):
        products = {"jacocoagent.jar": b"agent", "jacococli.jar": b"cli"}
        tools = {name: hashlib.sha256(data).hexdigest() for name, data in products.items()}
        buffer = io.BytesIO()
        with zipfile.ZipFile(buffer, "w") as archive:
            for name, data in products.items():
                archive.writestr("lib/" + name, data)
        data = buffer.getvalue()
        with tempfile.TemporaryDirectory() as temporary:
            cache = Path(temporary) / "tools"
            with patch.object(java_coverage, "TOOLS", tools), patch.object(java_coverage, "ARCHIVE_SHA256", java_coverage.digest(data)):
                with patch.object(java_coverage.urllib.request, "urlopen", return_value=io.BytesIO(data)) as opened:
                    java_coverage.install(cache)
                    self.assertEqual(opened.call_count, 1)
                self.assertTrue(java_coverage.verified(cache))
                with patch.object(java_coverage.urllib.request, "urlopen", side_effect=AssertionError("unexpected network")):
                    java_coverage.install(cache)
                (cache / "jacocoagent.jar").write_bytes(b"changed")
                self.assertFalse(java_coverage.verified(cache))
                with patch.object(java_coverage.urllib.request, "urlopen", return_value=io.BytesIO(b"changed")), self.assertRaisesRegex(ValueError, "release digest"):
                    java_coverage.install(cache)
                (cache / "jacocoagent.jar").unlink()
                with patch.object(java_coverage, "TOOLS", {**tools, "jacococli.jar": "0" * 64}), patch.object(java_coverage.urllib.request, "urlopen", return_value=io.BytesIO(data)), self.assertRaisesRegex(ValueError, "product digest"):
                    java_coverage.install(cache)
                self.assertFalse((cache / "jacocoagent.jar").exists())

    def test_check_requires_pinned_tools_and_instruments_only_observer_probes(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            with self.assertRaisesRegex(ValueError, "make setup"):
                java_coverage.check(root / "missing", root)
            calls = []

            def execute(arguments, **kwargs):
                calls.append((arguments, kwargs))
                if "report" in arguments:
                    Path(arguments[arguments.index("--xml") + 1]).write_text(report(9, 1).replace('</package>',
                        '<class name="OteleqCompile"><counter type="LINE" covered="9" missed="1"/></class></package>'))

            with patch.object(java_coverage, "verified", return_value=True), patch.object(java_coverage, "compiler_probe") as compiler_probe, patch.object(java_coverage.subprocess, "run", side_effect=execute), patch("builtins.print") as printed:
                java_coverage.check(root / "tools", root)
            compiler_probe.assert_called_once()
            self.assertEqual(len(calls), 2)
            environment = calls[0][1]["env"]
            self.assertIn("OTELEQ_JAVA_COVERAGE_AGENT", environment)
            self.assertIn("OTELEQ_JAVA_COVERAGE_EXEC", environment)
            self.assertNotIn("env", calls[1][1])
            self.assertEqual(calls[0][0][-2:], ["test_generation_java_receivers.py", "-v"])
            self.assertIn("90.00%", printed.call_args[0][0])
            self.assertTrue((root / "build/java-observer-coverage.xml").is_file())

    def test_compiler_probe_reports_only_compiler_products_with_a_scoped_agent(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            classes = root / "classes"; classes.mkdir()
            calls = []
            def execute(arguments, **kwargs):
                calls.append((arguments, kwargs))
                if "-d" in arguments:
                    compiled = Path(arguments[arguments.index("-d") + 1])
                    for name in ("OteleqCompile.class", "OteleqCompile$Manager.class", "JavaCompilerProbe.class"):
                        (compiled / name).write_bytes(b"compiled")
            with patch.object(java_coverage.subprocess, "run", side_effect=execute):
                java_coverage.compiler_probe(root / "tools", root, root, classes, root / "jacoco.exec")
            self.assertEqual({path.name for path in classes.iterdir()}, {"OteleqCompile.class", "OteleqCompile$Manager.class"})
            self.assertEqual(len(calls), 2)
            self.assertIn("includes=OteleqCompile*", calls[1][0][1])
            self.assertTrue(all("env" not in options for _, options in calls))

    def test_main_selects_only_setup_or_check(self):
        for action in ("setup", "check"):
            with patch.object(sys, "argv", ["java_coverage.py", action]), patch.object(java_coverage, "install") as install, patch.object(java_coverage, "check") as check:
                java_coverage.main()
                self.assertEqual(install.called, action == "setup")
                self.assertEqual(check.called, action == "check")


if __name__ == "__main__":
    unittest.main()
