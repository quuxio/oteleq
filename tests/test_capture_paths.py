"""Output protection uses directory identities rather than path spelling alone."""

import argparse
import os
from pathlib import Path
import sys
import tempfile
import unittest
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[1]
sys.path[:0] = [str(ROOT / "examples"), str(ROOT / "adapters/generation")]
import otelc_capture as capture
import generation
import go_cache
import java_project


class PathBoundaryTests(unittest.TestCase):
    def setUp(self):
        temporary = tempfile.TemporaryDirectory()
        self.addCleanup(temporary.cleanup)
        self.base = Path(temporary.name).resolve()
        self.source = self.base / "application"
        self.source.mkdir()
        self.sdk = self.base / "sdk"; self.sdk.mkdir()
        self.original = self.source / "original.py"
        self.original.write_text("original source\n")
        self.before = self.original.stat()

    def aliases(self, path):
        link = self.base / (path.name + "-alias")
        link.symlink_to(path, target_is_directory=True)
        result = [link]
        case = path.with_name(path.name.upper())
        # This branch exercises the actual APFS behaviour on this Mac. The
        # symlink identity control above also runs on case-sensitive systems.
        if case.exists() and case.samefile(path):
            result.append(case)
        return result

    def unchanged(self):
        self.assertEqual(self.original.stat(), self.before)
        self.assertEqual(list(self.source.iterdir()), [self.original])

    def test_physical_ancestry_covers_aliases_and_nonexistent_descendants(self):
        self.assertTrue(capture.path_within(self.source, self.source))
        self.assertTrue(capture.path_within(self.source / "new/child", self.source))
        self.assertFalse(capture.path_within(self.base / "sibling", self.source))
        self.assertFalse(capture.path_within(self.source, self.base / "absent"))
        for alias in self.aliases(self.source):
            self.assertTrue(capture.path_within(alias / "new/child", self.source))
        self.unchanged()

    def test_output_and_sdk_cache_paths_refuse_source_aliases_before_writes(self):
        for alias in self.aliases(self.source):
            with self.subTest(alias=alias), self.assertRaisesRegex(ValueError, "outside"):
                generation.source_outside(alias / "new-output", self.source, self.sdk)
            with self.subTest(alias=alias), self.assertRaisesRegex(ValueError, "overlaps"):
                go_cache.location({"directory": str(alias / "cache")}, [self.source])
        self.unchanged()

    def test_cache_ancestor_alias_cannot_hide_protected_source_below_it(self):
        parent = self.base / "parent"; parent.mkdir()
        source = parent / "application"; source.mkdir()
        for alias in self.aliases(parent):
            with self.subTest(alias=alias), self.assertRaisesRegex(ValueError, "overlaps"):
                go_cache.location({"directory": str(alias)}, [source])

    def test_export_refuses_workspace_alias_before_dry_run_or_copy(self):
        for alias in self.aliases(self.source):
            destination = alias / "export"
            with patch.object(generation, "load_workspace", return_value=(self.source, {})):
                for apply in (False, True):
                    with self.subTest(alias=alias, apply=apply), self.assertRaisesRegex(ValueError, "independent"):
                        generation.export_tests(argparse.Namespace(workspace=self.source, destination=destination, apply=apply))
        self.unchanged()

    def test_declared_dependency_alias_remains_protected(self):
        for alias in self.aliases(self.source):
            with self.subTest(alias=alias), self.assertRaisesRegex(ValueError, "outside declared dependencies"):
                java_project.protect_destination(alias / "output", [self.source])
        self.unchanged()

    def test_temporary_source_alias_refuses_before_tempfile_writability_probe(self):
        for alias in self.aliases(self.source):
            for variable in ("TMPDIR", "TEMP", "TMP"):
                with self.subTest(alias=alias, variable=variable), \
                        patch.dict(os.environ, {"TMPDIR": "", "TEMP": "", "TMP": "", variable: str(alias)}), \
                        patch.object(capture.tempfile, "gettempdir") as probe, \
                        self.assertRaisesRegex(ValueError, "outside both repositories"):
                    capture.temporary_parent(self.source, self.sdk)
                probe.assert_not_called()
        self.unchanged()

    def test_resolved_default_temp_alias_and_legacy_go_cache_are_also_refused(self):
        for alias in self.aliases(self.source):
            with patch.dict(os.environ, {"TMPDIR": "", "TEMP": "", "TMP": ""}), \
                    patch.object(capture.tempfile, "gettempdir", return_value=str(alias)), \
                    self.assertRaisesRegex(ValueError, "outside both repositories"):
                capture.temporary_parent(self.source, self.sdk)
            environment = {"GOCACHE": str(alias / "build"), "GOMODCACHE": str(self.base / "modules")}
            with self.assertRaises(ValueError):
                capture.go_caches(self.sdk, self.source, environment, self.base / "evidence")
        self.unchanged()


if __name__ == "__main__":
    unittest.main()
