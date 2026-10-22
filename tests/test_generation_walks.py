"""Uninspectable directories cannot become successful partial input inventories."""
import argparse
import errno
from contextlib import redirect_stdout
import io
import os
from pathlib import Path
import stat
import sys
import tempfile
from types import SimpleNamespace
import unittest
from unittest.mock import patch

REPO = Path(__file__).resolve().parents[1]
sys.path[:0] = [str(REPO / "adapters/generation"), str(REPO / "examples")]
import generation as gen
import java_build
import java_classpath
import java_launch
import java_project
import java_provider
import native_profile
import owned_workspace
import otelc_capture as capture
import capture_otelc_tasks


class InputWalkTests(unittest.TestCase):
    def setUp(self):
        temporary = tempfile.TemporaryDirectory(prefix="oteleq unreadable inputs ")
        self.addCleanup(temporary.cleanup)
        self.base = Path(temporary.name).resolve()

    def deny(self, directory: Path) -> None:
        """Exercise a real permission failure and restore it before test cleanup."""
        mode = stat.S_IMODE(directory.stat().st_mode)
        self.addCleanup(directory.chmod, mode)
        directory.chmod(0)
        try:
            list(directory.iterdir())
        except PermissionError:
            return
        self.skipTest("the current account can enumerate a mode-000 directory")

    def tree(self, suffix: str = ".py", *, root: Path | None = None) -> tuple[Path, Path]:
        root = root or self.base / "application"
        private = root / "private"
        private.mkdir(parents=True)
        (root / ("Visible" + suffix)).write_text("def visible(n:int)->int:return n+1\n")
        (private / ("Hidden" + suffix)).write_text("def hidden(n:int)->int:return n+2\n")
        return root, private

    def plan(self, source: Path) -> Path:
        """Use the real planner, stubbing only the external SDK tool boundary."""
        provider = self.base / "provider"
        provider.mkdir(exist_ok=True)
        cli = self.base / "cli"
        cli.write_text("fixed CLI")
        args = argparse.Namespace(source=source, otelc_root=provider, workspace_parent=self.base,
                                  language=["python"], exclude=[], cases=1)
        with patch.dict(os.environ, {"OTELEQ_EXECUTABLE": str(cli)}), \
             patch.object(capture, "selected_tools", return_value={"python": Path(sys.executable)}), \
             patch.object(capture, "artefacts", return_value={"fixed": "SDK"}), \
             redirect_stdout(io.StringIO()) as output:
            gen.plan(args)
        self.cli = cli
        return Path(output.getvalue().strip())

    def test_source_manifest_refuses_unreadable_directory(self):
        root, private = self.tree()
        self.deny(private)
        with self.assertRaises(PermissionError):
            gen.manifest(root)

    def test_planning_refuses_before_creating_a_partial_workspace(self):
        root, private = self.tree()
        self.deny(private)
        with self.assertRaises(PermissionError):
            self.plan(root)
        self.assertEqual(list(self.base.glob("oteleq-run-*")), [])

    def test_added_unreadable_source_cannot_preserve_an_old_plan(self):
        root = self.base / "application"
        root.mkdir()
        (root / "visible.py").write_text("def visible(n:int)->int:return n+1\n")
        workspace = self.plan(root)
        added, _ = self.tree(root=root / "added")
        self.deny(added)
        with patch.dict(os.environ, {"OTELEQ_EXECUTABLE": str(self.cli)}):
            with self.assertRaises(PermissionError):
                gen.load_workspace(workspace)

    def test_owned_bundle_scan_refuses_unreadable_directory(self):
        root, private = self.tree()
        self.deny(private)
        with self.assertRaises(PermissionError):
            owned_workspace.exclusions(gen, root)

    def test_explicit_java_generated_root_refuses_partial_source_units(self):
        root = self.base / "application"
        generated, private = self.tree(".java", root=root / "build/generated")
        self.deny(private)
        options = {"source_roots": ["build/generated"]}
        ignored = {"build"}
        with self.assertRaises(PermissionError):
            java_project.source_files(root, options, ignored)

    def test_java_dependency_directory_refuses_partial_byte_inventory(self):
        root, private = self.tree(".class")
        self.deny(private)
        with self.assertRaises(PermissionError):
            java_classpath.inspect(root)

    def test_java_private_build_refuses_partial_input_identity(self):
        root, private = self.tree(".java")
        self.deny(private)
        with self.assertRaises(PermissionError):
            java_build.files(root)

    def test_compiled_java_classpath_refuses_partial_output_inventory(self):
        root, private = self.tree(".class")
        self.deny(private)
        with self.assertRaises(PermissionError):
            java_project.classpath_files(root, None)

    def test_java_runtime_archive_refuses_before_copying_partial_output(self):
        root, private = self.tree(".json")
        output = self.base / "retained"
        output.mkdir()
        self.deny(private)
        with patch.object(java_launch.shutil, "copytree", side_effect=AssertionError("must inspect first")):
            with self.assertRaises(PermissionError):
                java_launch.archive(root, output)
        self.assertFalse((output / "sdk-runtime").exists())

    def test_prepared_java_sdk_closure_refuses_unreadable_source(self):
        root = self.base / "sdk"
        package, private = self.tree(root=root / "otelc")
        for name in java_provider.SDK_MODULES:
            (package / name).write_text("# SDK fixture\n")
        (root / "adapters/java/src/main").mkdir(parents=True)
        for name in (java_provider.AGENT, java_provider.EXTENSION, "adapters/java/pom.xml"):
            path = root / name
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_text("fixed fixture")
        self.deny(private)
        with patch.object(capture, "file_digest", return_value=java_provider.AGENT_SHA256):
            with self.assertRaises(PermissionError):
                java_provider.artefacts(root, {})

    def test_legacy_sdk_closure_refuses_unreadable_source(self):
        root = self.base / "sdk"
        _, private = self.tree(root=root / "adapters/python")
        (root / ".venv/lib/python3.12/site-packages").mkdir(parents=True)
        self.deny(private)
        with patch.object(capture, "file_digest", return_value="fixed SDK fixture"):
            with self.assertRaises(PermissionError):
                capture.artefacts(root, "python", {})

    def test_task_sdk_closure_refuses_unreadable_source(self):
        root = self.base / "sdk"
        _, private = self.tree(root=root / "adapters/python/quux_otelc_python")
        self.deny(private)
        interpreter = Path(sys.executable)
        with patch.object(capture_otelc_tasks, "file_digest", return_value="fixed SDK fixture"):
            with self.assertRaises(PermissionError):
                capture_otelc_tasks.artefact_identities(root, interpreter)

    def test_decoder_package_closure_refuses_unreadable_directory(self):
        root, private = self.tree()
        self.deny(private)
        spec = SimpleNamespace(submodule_search_locations=[root])
        with self.assertRaises(PermissionError):
            gen.package_files("decoder", spec)

    def test_private_guard_refuses_unreadable_new_source(self):
        root, private = self.tree()
        immutable = {"Visible.py": capture.file_digest(root / "Visible.py")}
        output = self.base / "attempt"
        output.mkdir()
        self.deny(private)
        with self.assertRaises(PermissionError):
            gen.validate_private_sources(root, immutable, output)
        self.assertFalse((output / gen.BUILD_IDENTITIES).exists())

    def test_intentionally_excluded_directory_remains_outside_the_walk(self):
        root, private = self.tree(root=self.base / "application/build")
        source = root.parent
        (source / "keep.py").write_text("def keep():return 1\n")
        self.deny(private)
        self.assertEqual(set(gen.manifest(source, excluded={"build"})), {"keep.py"})

    def test_missing_required_input_tree_is_not_an_empty_manifest(self):
        with self.assertRaises(FileNotFoundError):
            gen.manifest(self.base / "missing")

    def test_file_cannot_stand_in_for_a_required_directory(self):
        path = self.base / "file.py"
        path.write_text("def selected():return 7\n")
        with self.assertRaises(NotADirectoryError):
            gen.manifest(path)

    def test_directory_disappearing_after_parent_listing_refuses_the_walk(self):
        root, private = self.tree()
        original_scandir = os.scandir

        def disappeared(path):
            if Path(path) == private:
                raise FileNotFoundError(errno.ENOENT, "removed during inspection", str(private))
            return original_scandir(path)

        with patch.object(capture.os, "scandir", side_effect=disappeared):
            with self.assertRaises(FileNotFoundError):
                gen.manifest(root)

    def test_shared_tree_paths_expose_links_without_descending_through_them(self):
        root = self.base / "application"
        root.mkdir()
        external = self.base / "external"
        external.mkdir()
        (external / "hidden.py").write_text("def selected():return 7\n")
        (root / "linked").symlink_to(external, target_is_directory=True)
        self.assertEqual(list(capture.tree_paths(root)), [root / "linked"])
        with self.assertRaisesRegex(ValueError, "symlink"):
            gen.manifest(root)

    def test_sdk_test_directory_exclusion_does_not_require_its_contents(self):
        root = self.base / "sdk"
        _, private = self.tree(root=root / "adapters/python/tests")
        (root / "adapters/python/real.py").write_text("# retained SDK source\n")
        (root / ".venv/lib/python3.12/site-packages").mkdir(parents=True)
        self.deny(private)
        with patch.object(capture, "file_digest", return_value="fixed SDK fixture"):
            identities = capture.artefacts(root, "python", {})
        self.assertIn("adapters/python/real.py", identities)
        self.assertFalse(any("/tests/" in name for name in identities))

    def test_native_input_read_failure_retains_diagnostics_and_partial_path(self):
        workspace = self.base / "workspace"
        workspace.mkdir()
        with patch.object(native_profile, "prepare", return_value={"c": {}}), \
             patch.object(native_profile, "source_manifest", side_effect=PermissionError("required input unreadable")):
            with self.assertRaisesRegex(ValueError, "partial workspace"):
                native_profile.prepare_inputs(gen, self.base, self.base, workspace, {}, {})
        failure = gen.read(workspace / "discovery-failure.json")
        self.assertEqual(failure["phase"], "native build context")
        self.assertIn("required input unreadable", failure["error"])


if __name__ == "__main__":
    unittest.main()
