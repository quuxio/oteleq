"""Retained suites must not become application inputs on the next plan."""
import argparse
from contextlib import redirect_stdout
import io
import os
from pathlib import Path
import shutil
import sys
import tempfile
import unittest
from unittest.mock import patch

REPO = Path(__file__).resolve().parents[1]
sys.path[:0] = [str(REPO / "adapters/generation"), str(REPO / "examples")]
import discovery
import generation as gen
import java_project
import native_profile
import owned_workspace
import qualify_retained_source


class OwnedInputTests(unittest.TestCase):
    def setUp(self):
        temporary = tempfile.TemporaryDirectory()
        self.addCleanup(temporary.cleanup)
        self.base = Path(temporary.name).resolve()
        self.source, self.provider = self.base / "application", self.base / "provider"
        self.source.mkdir()
        self.provider.mkdir()
        self.original = "def selected(n:int)->int:return n+1\n"
        (self.source / "app.py").write_text(self.original)
        self.cli = self.base / "cli"
        self.cli.write_text("fixed CLI")
        for manager in (
            patch.dict(os.environ, {"OTELEQ_EXECUTABLE": str(self.cli)}),
            patch.object(gen.capture, "selected_tools", return_value={"python": Path(sys.executable)}),
            patch.object(gen.capture, "artefacts", return_value={"fixture": "pinned"}),
            patch.object(gen, "decoder", return_value=None),
        ):
            manager.start()
            self.addCleanup(manager.stop)
        self.workspace = self.plan()
        with redirect_stdout(io.StringIO()):
            gen.generate(argparse.Namespace(workspace=self.workspace))
        self.retained = self.source / "equivalence-tests"
        with redirect_stdout(io.StringIO()):
            gen.export_tests(argparse.Namespace(workspace=self.workspace, destination=self.retained, apply=True))

    def plan(self) -> Path:
        """Create a real Python plan with only the external SDK boundary stubbed."""
        options = argparse.Namespace(source=self.source, otelc_root=self.provider,
                                     workspace_parent=self.base, language=["python"], exclude=[], cases=1)
        with redirect_stdout(io.StringIO()) as output:
            gen.plan(options)
        return Path(output.getvalue().strip())

    def reseal(self, data: object) -> None:
        """Prepare an explicit metadata control while preserving private data seals."""
        gen.write(self.retained / gen.PLAN_FILE, data)
        marker = gen.read(self.retained / gen.OWNED_MARKER)
        marker["plan_sha256"] = gen.identity(data)
        gen.write(self.retained / gen.OWNED_MARKER, marker)

    def test_replan_excludes_valid_retained_snapshot_tests_and_helpers(self):
        workspace = self.plan()
        data = gen.read(workspace / gen.PLAN_FILE)
        self.assertEqual(set(data["source_manifest"]), {"app.py"})
        self.assertEqual([entry["name"] for entry in data["inventory"]], ["selected"])
        self.assertEqual(data["inventory"][0]["status"], "ready")
        self.assertEqual(data["owned_source_exclusions"][0]["path"], "equivalence-tests")
        self.assertEqual(gen.manifest(workspace / "snapshot"), data["source_manifest"])
        # New legitimate output need not invalidate an earlier source identity.
        gen.load_workspace(self.workspace, generated=True)

    def test_export_rebases_exclusion_scope_and_runs_without_original_tree(self):
        workspace = self.plan()
        with redirect_stdout(io.StringIO()):
            gen.generate(argparse.Namespace(workspace=workspace))
            destination = self.base / "detached"
            gen.export_tests(argparse.Namespace(workspace=workspace, destination=destination, apply=True))
        self.source.rename(self.base / "offline")
        _, data = gen.load_workspace(destination, generated=True)
        self.assertEqual(data["owned_source_exclusions"], [])
        self.assertEqual(data["original_owned_source_exclusions"][0]["path"], "equivalence-tests")

    def test_report_lists_actual_output_exclusions_and_app_edits_still_fail(self):
        destination = self.base / "report"
        with patch.object(gen, "compare_case", return_value={"exit_code": 0}), redirect_stdout(io.StringIO()):
            gen.run(argparse.Namespace(command="run", workspace=self.workspace, report_dir=destination))
        self.assertEqual(gen.read(destination / "report.json")["owned_source_exclusions"][0]["path"],
                         "equivalence-tests")
        (self.source / "app.py").write_text(self.original + "changed=1\n")
        with self.assertRaisesRegex(ValueError, "application source"):
            gen.load_workspace(self.workspace)

    def test_edited_or_unsealed_bundle_never_hides_source(self):
        controls = (
            (self.retained / "snapshot/app.py", "def hidden():return 2\n"),
            (self.retained / "tests/user.py", "def hidden():return 2\n"),
            (self.retained / gen.PLAN_FILE, "{}"),
            (self.retained / gen.GENERATED_MANIFEST, "{}"),
            (self.retained / gen.OWNED_MARKER, "{}"),
            (self.retained / gen.OWNED_MARKER, "[]"),
            (self.retained / gen.OWNED_MARKER, "null"),
            (self.retained / gen.OWNED_MARKER, '{"schema_version":true}'),
            (self.retained / gen.OWNED_MARKER, '{"schema_version":1,"id":[]}'),
            (self.retained / "user.py", "def hidden():return 2\n"),
        )
        for path, replacement in controls:
            with self.subTest(path=str(path)):
                original = path.read_bytes() if path.exists() else None
                path.write_text(replacement)
                with self.assertRaisesRegex(ValueError, "invalid retained"):
                    self.plan()
                if original is None:
                    path.unlink()
                else:
                    path.write_bytes(original)
        gen.load_workspace(self.workspace)

    def test_non_object_or_wrong_version_plan_cannot_be_hidden_by_a_resealed_marker(self):
        original = gen.read(self.retained / gen.PLAN_FILE)
        for data in ([], None, {"schema_version": True}, {"schema_version": 2}):
            with self.subTest(data=data):
                self.reseal(data)
                with self.assertRaisesRegex(ValueError, "plan identity"):
                    self.plan()
        self.reseal(original)

    def test_unsealed_marker_and_missing_private_trees_are_visible_errors(self):
        marker = gen.read(self.retained / gen.OWNED_MARKER)
        gen.write(self.retained / gen.OWNED_MARKER, {"schema_version": 1})
        with self.assertRaisesRegex(ValueError, "plan identity"):
            self.plan()
        gen.write(self.retained / gen.OWNED_MARKER, marker)
        for name in ("snapshot", "tests"):
            with self.subTest(name=name):
                (self.retained / name).rename(self.base / name)
                with self.assertRaisesRegex(ValueError, "invalid retained"):
                    self.plan()
                (self.base / name).rename(self.retained / name)

    def test_old_tool_identity_does_not_require_original_toolchain(self):
        data = gen.read(self.retained / gen.PLAN_FILE)
        data.update(generator_sha256="old frozen generator", cli_sha256="old frozen CLI")
        self.reseal(data)
        with patch.object(gen, "generator_identity", side_effect=AssertionError("tool execution")):
            records = owned_workspace.exclusions(gen, self.source)
        self.assertEqual(records[0]["path"], "equivalence-tests")

    def test_unknown_context_and_linked_root_cannot_be_excluded_or_cleaned(self):
        cleanup = argparse.Namespace(workspace=self.retained)
        for name in (native_profile.DIRECTORY, gen.java_project.DIRECTORY, gen.java_provider.DIRECTORY):
            with self.subTest(name=name):
                (self.retained / name).mkdir()
                with self.assertRaises(ValueError):
                    self.plan()
                with self.assertRaises(ValueError):
                    gen.clean(cleanup)
                (self.retained / name).rmdir()
        (self.retained / "runs").symlink_to(self.base, target_is_directory=True)
        with self.assertRaisesRegex(ValueError, "unowned"):
            self.plan()
        (self.retained / "runs").unlink()

    def test_missing_native_context_and_invalid_reserved_directory_are_refused(self):
        data = gen.read(self.retained / gen.PLAN_FILE)
        data["native_projects"] = {"c": {"profile": "test"}}
        self.reseal(data)
        with self.assertRaisesRegex(ValueError, "native context is missing"):
            self.plan()
        data.pop("native_projects")
        self.reseal(data)
        (self.retained / "runs").write_text("user data")
        with self.assertRaisesRegex(ValueError, "invalid owned directory"):
            self.plan()

    def test_java_all_source_roots_exclude_retained_units_including_generated_roots(self):
        (self.source / "App.java").write_text("class App {}\n")
        duplicate = self.retained / "snapshot/App.java"
        duplicate.write_text("class App {}\n")
        data = gen.read(self.retained / gen.PLAN_FILE)
        data["source_manifest"]["App.java"] = gen.capture.file_digest(duplicate)
        self.reseal(data)
        roots = [record["path"] for record in owned_workspace.exclusions(gen, self.source)]
        self.assertEqual(java_project.source_files(self.source, {"source_roots": ["."]},
                         discovery.IGNORED, excluded_roots=roots), ["App.java"])
        generated = self.source / "build/generated"
        generated.mkdir(parents=True)
        (generated / "Generated.java").write_text("class Generated {}\n")
        shutil.copytree(self.retained, generated / "retained")
        records = owned_workspace.exclusions(gen, self.source, ["build/generated"])
        roots = [record["path"] for record in records]
        self.assertEqual(roots, ["build/generated/retained", "equivalence-tests"])
        contents = gen.java_source_manifest(self.source, {"source_roots": ["build/generated"]}, {},
                                           excluded_roots=roots)
        self.assertEqual(set(contents), {"build/generated/Generated.java"})
        with self.assertRaisesRegex(ValueError, "inside a retained"):
            java_project.source_files(self.source, {"source_roots": ["equivalence-tests/snapshot"]}, set())

    def test_explicit_native_build_inputs_cannot_reintroduce_retained_source(self):
        roots = ["equivalence-tests"]
        for profile in (
            {"directories": ["."], "local_inputs": {"equivalence-tests/snapshot/app.py": "unused"}},
            {"directories": ["equivalence-tests/snapshot"], "local_inputs": {}},
        ):
            with self.subTest(profile=profile), self.assertRaisesRegex(ValueError, "inside a retained"):
                native_profile.source_manifest(gen, self.source, {"c": profile}, excluded_roots=roots)
        source = self.source / "build/generated.c"
        source.parent.mkdir()
        source.write_text("int original(void){return 1;}\n")
        profile = {"directories": ["build"], "local_inputs": {"build/generated.c": gen.capture.file_digest(source)}}
        contents = native_profile.source_manifest(gen, self.source, {"c": profile}, excluded_roots=roots)
        self.assertEqual(set(contents), {"app.py", "build/generated.c"})

    def test_ignored_output_stays_ignored_but_explicit_java_root_checks_it(self):
        generated = self.source / "build/generated"
        generated.mkdir(parents=True)
        bad = generated / "unsealed"
        bad.mkdir()
        (bad / owned_workspace.MARKER).write_text("{}")
        self.assertEqual(len(owned_workspace.exclusions(gen, self.source)), 1)
        with self.assertRaisesRegex(ValueError, "invalid retained"):
            owned_workspace.exclusions(gen, self.source, ["build/generated"])
        with self.assertRaisesRegex(ValueError, "inside a retained"):
            owned_workspace.exclusions(gen, self.retained)

    def test_sealed_run_and_cache_trees_remain_reserved_owned_output(self):
        for name in ("runs", "go-cache"):
            (self.retained / name).mkdir()
            (self.retained / name / "generated.txt").write_text("reserved tool output")
        self.assertEqual(len(owned_workspace.exclusions(gen, self.source)), 1)
        gen.clean(argparse.Namespace(workspace=self.retained))
        self.assertFalse(self.retained.exists())

    def test_qualifier_resolves_corpus_language_through_its_inventory_binding(self):
        data = {"inventory": [{"id": "native", "language": "c", "status": "ready"},
                              {"id": "python", "language": "python", "status": "ready"}]}
        corpus = [{"id": "native-case", "function_id": "native"},
                  {"id": "python-case", "function_id": "python"}]
        self.assertEqual(qualify_retained_source.python_case_id(data, corpus), "python-case")


if __name__ == "__main__":
    unittest.main()
