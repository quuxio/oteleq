"""Artefact stability prevents comparisons spanning a concurrent rebuild."""
import runpy
import subprocess
import sys
from pathlib import Path
import tempfile
import unittest

OBSERVER = runpy.run_path(str(Path(__file__).resolve().parents[1] / "examples/capture_otelc_tasks.py"))


class ArtefactStabilityTests(unittest.TestCase):
    def setUp(self):
        self.directory = tempfile.TemporaryDirectory()
        self.addCleanup(self.directory.cleanup)
        self.root = Path(self.directory.name)
        for relative in ["adapters/python/quux_otelc_python/monitor.py", "adapters/python/requirements.txt",
                         "target/debug/quux-otelc", "python"]:
            path = self.root / relative
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_bytes(b"original bytes")
        self.interpreter = self.root / "python"
        self.identities = OBSERVER["artefact_identities"](self.root, self.interpreter)

    def test_unchanged_tools_qualify_without_importing_the_target(self):
        OBSERVER["require_same_artefacts"](self.root, self.interpreter, self.identities)
        self.assertEqual(len(self.identities), 4)

    def test_rebuilt_launcher_changed_adapter_lock_or_interpreter_cannot_qualify(self):
        for relative in ["target/debug/quux-otelc", "adapters/python/quux_otelc_python/monitor.py",
                         "adapters/python/requirements.txt", "python"]:
            with self.subTest(relative=relative):
                path = self.root / relative
                path.write_bytes(b"changed bytes")
                with self.assertRaisesRegex(ValueError, "changed during capture"):
                    OBSERVER["require_same_artefacts"](self.root, self.interpreter, self.identities)
                path.write_bytes(b"original bytes")

    def test_added_or_missing_adapter_files_cannot_hide_behind_prior_manifest(self):
        extra = self.root / "adapters/python/quux_otelc_python/nested/extra.py"
        extra.parent.mkdir()
        extra.write_bytes(b"new code")
        with self.assertRaises(ValueError):
            OBSERVER["require_same_artefacts"](self.root, self.interpreter, self.identities)
        extra.unlink()
        (extra.parent.parent / "monitor.py").unlink()
        with self.assertRaises(ValueError):
            OBSERVER["require_same_artefacts"](self.root, self.interpreter, self.identities)

    def test_missing_required_executable_is_a_capture_failure(self):
        (self.root / "target/debug/quux-otelc").unlink()
        with self.assertRaises(FileNotFoundError):
            OBSERVER["require_same_artefacts"](self.root, self.interpreter, self.identities)


    def test_actual_capture_aborts_before_recording_success_when_a_run_rebuilds_the_launcher(self):
        app = self.root / "examples/apps/python_tasks_app.py"
        app.parent.mkdir(parents=True)
        launcher = self.root / "target/debug/quux-otelc"
        app.write_text("from pathlib import Path\nPath(" + repr(str(launcher)) + ").write_bytes(b'rebuilt')\nprint('same result')\n")
        (self.root / "examples/python-task-context.toml").write_text("schema_version=2\n")
        report_parent = tempfile.TemporaryDirectory()
        self.addCleanup(report_parent.cleanup)
        reports = Path(report_parent.name) / "reports"
        result = subprocess.run([sys.executable, str(Path(__file__).resolve().parents[1] / "examples/capture_otelc_tasks.py"),
                                 "--otelc-root", str(self.root), "--report-dir", str(reports)],
                                capture_output=True, timeout=10)
        self.assertNotEqual(result.returncode, 0)
        self.assertIn(b"artefacts changed during capture", result.stderr)
        self.assertFalse((reports / "bundle.json").exists())
        self.assertFalse((reports / "baseline-0/attempt.json").exists())
        self.assertFalse((reports / "baseline-1").exists())
