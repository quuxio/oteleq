"""Copied diagnostic evidence keeps its original worker identity and bindings."""
import json
from pathlib import Path
import shutil
import tempfile
import unittest
from unittest.mock import patch

import qualify_filesystem

qualifier = qualify_filesystem.qualification


class FilesystemQualificationTests(unittest.TestCase):
    def attempt(self, base: Path) -> Path:
        folder = base / "runs/replay/case/baseline-0"
        project = folder / "project"
        project.mkdir(parents=True)
        for name in ("command.json", "typed-observation.json", "http-capture.json", *qualifier.sidecars):
            (folder / name).write_text("{}")
        (folder / "working-directory.json").write_text(json.dumps(str(project)))
        return folder

    def test_resume_refuses_missing_initial_routes_before_any_commands(self):
        with tempfile.TemporaryDirectory() as temporary:
            base = Path(temporary)
            workspace = base / "cases/retained"
            workspace.mkdir(parents=True)
            provider = base / "provider"
            (workspace / "plan.json").write_text(json.dumps({"otelc_root": str(provider)}))
            cli = base / "cli"
            with patch.object(qualifier, "command") as command, patch.object(qualifier, "framework") as framework:
                with self.assertRaisesRegex(ValueError, "all four completed"):
                    qualifier.retained_workflows(cli, provider, base, True)
                command.assert_not_called()
                framework.assert_not_called()

    def test_direct_and_copied_original_records_resolve_the_actual_worker(self):
        with tempfile.TemporaryDirectory() as temporary:
            base = Path(temporary)
            actual = self.attempt(base)
            copied = base / "shrink-case/original/case/baseline-0"
            shutil.copytree(actual, copied)
            expected = (actual / "project", actual)
            self.assertEqual(qualifier.actual_attempt(actual, "case"), expected)
            self.assertEqual(qualifier.actual_attempt(copied, "case"), expected)

    def test_changed_copies_and_unexpected_worker_rebinding_are_rejected(self):
        with tempfile.TemporaryDirectory() as temporary:
            base = Path(temporary)
            actual = self.attempt(base)
            copied = base / "shrink-case/original/case/baseline-0"
            shutil.copytree(actual, copied)
            (copied / "filesystem-data.json").write_text('{"changed":true}')
            with self.assertRaises(AssertionError):
                qualifier.actual_attempt(copied, "case")
            (actual / "working-directory.json").write_text(json.dumps(str(base / "unexpected/case/baseline-0/project")))
            with self.assertRaises(AssertionError):
                qualifier.actual_attempt(actual, "case")
            outside = base.parent / "outside/case/baseline-0/project"
            (copied / "working-directory.json").write_text(json.dumps(str(outside)))
            with self.assertRaises(AssertionError):
                qualifier.actual_attempt(copied, "case")


if __name__ == "__main__":
    unittest.main()
