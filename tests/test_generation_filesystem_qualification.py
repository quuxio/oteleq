"""Copied diagnostic evidence keeps its original worker identity and bindings."""
import json
from pathlib import Path
import shutil
import tempfile
import unittest

import qualify_filesystem as qualifier


class FilesystemQualificationTests(unittest.TestCase):
    def attempt(self, base: Path) -> Path:
        folder = base / "runs/replay/case/baseline-0"
        project = folder / "project"
        project.mkdir(parents=True)
        for name in ("command.json", "filesystem-controls.json", "filesystem-data.json", "typed-observation.json", "http-capture.json"):
            (folder / name).write_text("{}")
        (folder / "working-directory.json").write_text(json.dumps(str(project)))
        return folder

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
