"""Current-source suites must generate real cases and preserve owned boundaries."""
import argparse
from contextlib import redirect_stdout
import io
import json
import os
from pathlib import Path
import shutil
import subprocess
import sys
import tempfile
import tomllib
import unittest
from unittest.mock import patch

REPO = Path(__file__).resolve().parents[1]
sys.path[:0] = [str(REPO / "adapters/generation"), str(REPO / "examples")]
import generation as gen
import owned_workspace
import project_runner as runner
import project_tests


class ProjectSuiteTests(unittest.TestCase):
    def setUp(self):
        temporary = tempfile.TemporaryDirectory()
        self.addCleanup(temporary.cleanup)
        self.base = Path(temporary.name).resolve()
        self.source, self.provider = self.base / "application", self.base / "provider"
        self.source.mkdir()
        self.provider.mkdir()
        (self.source / "app.py").write_text("def selected(n:int)->int:return n+1\n")
        self.cli = self.base / "cli"
        self.cli.write_text("fixed CLI")
        for manager in (
            patch.dict(os.environ, {"OTELEQ_EXECUTABLE": str(self.cli), "OTELEQ_CLI": str(self.cli),
                                    "OTELEQ_WORKSPACE_PARENT": str(self.base), "OTELEQ_SOURCE": str(self.source)}),
            patch.object(gen.capture, "selected_tools", return_value={"python": Path(sys.executable)}),
            patch.object(gen.capture, "artefacts", return_value={"fixture": "pinned"}),
            patch.object(gen, "decoder", return_value=None),
            patch.object(runner, "ROOT", self.source / "equivalence-tests"),
            patch.object(sys, "dont_write_bytecode", True),
        ):
            manager.start()
            self.addCleanup(manager.stop)
        self.workspace = self.plan()
        with redirect_stdout(io.StringIO()):
            gen.generate(argparse.Namespace(workspace=self.workspace))
        self.bundle = runner.ROOT
        self.promote()

    def plan(self) -> Path:
        options = argparse.Namespace(source=self.source, otelc_root=self.provider,
            workspace_parent=self.base, language=["python"], exclude=[], cases=1)
        with redirect_stdout(io.StringIO()) as output:
            gen.plan(options)
        return Path(output.getvalue().strip())

    def promote(self, *, destination=None, apply=True) -> str:
        options = argparse.Namespace(workspace=self.workspace, source=self.source,
                                     destination=destination or self.bundle, apply=apply)
        with redirect_stdout(io.StringIO()) as output:
            gen.promote(options)
        return output.getvalue()

    def reseal(self, metadata: dict) -> None:
        gen.write(self.bundle / project_tests.PROJECT, metadata)
        marker = gen.read(self.bundle / gen.OWNED_MARKER)
        marker["project_sha256"] = gen.identity(metadata)
        gen.write(self.bundle / gen.OWNED_MARKER, marker)

    def test_promotion_defaults_to_a_reviewable_dry_run(self):
        destination = self.base / "external"
        result = json.loads(self.promote(destination=destination, apply=False))
        self.assertEqual(result["mode"], "dry-run")
        self.assertEqual(set(result["files"]), project_tests.FILES)
        self.assertFalse(destination.exists())

    def test_sealed_project_boilerplate_does_not_become_application_input(self):
        marker, metadata = owned_workspace.verify(gen, self.bundle)
        self.assertEqual(marker["kind"], project_tests.KIND)
        self.assertEqual(metadata["source_relative"], "..")
        data = gen.read(self.plan() / gen.PLAN_FILE)
        self.assertEqual(set(data["source_manifest"]), {"app.py"})
        self.assertEqual(data["owned_source_exclusions"][0]["reason"], "verified current-source oteleq suite")
        gen.load_workspace(self.workspace, generated=True)

    def test_current_application_changes_create_a_new_inventory(self):
        (self.source / "app.py").write_text("def selected(n:int)->int:return n+2\ndef additional()->int:return 3\n")
        data = gen.read(self.plan() / gen.PLAN_FILE)
        self.assertEqual({entry["name"] for entry in data["inventory"]}, {"selected", "additional"})
        self.assertTrue(all(entry["status"] == "ready" for entry in data["inventory"]))

    def test_changed_or_extra_files_cannot_hide_application_code(self):
        path = self.bundle / "hidden.py"
        path.write_text("def hidden():return 1\n")
        with self.assertRaisesRegex(ValueError, "invalid retained"):
            self.plan()
        path.unlink()
        path = self.bundle / project_tests.RUNNER
        path.write_text(path.read_text() + "\n# user edit\n")
        with self.assertRaisesRegex(ValueError, "content changed"):
            runner.verified_project()

    def test_resealed_foreign_boilerplate_is_still_refused(self):
        path = self.bundle / project_tests.RUNNER
        path.write_text("print('foreign')\n")
        metadata = gen.read(self.bundle / project_tests.PROJECT)
        metadata["files_sha256"][project_tests.RUNNER] = gen.capture.file_digest(path)
        self.reseal(metadata)
        with self.assertRaisesRegex(ValueError, "not recognised"):
            project_tests.verify(gen, self.bundle)

    def test_marker_metadata_policy_and_versions_are_validated(self):
        metadata = runner.verified_project()
        for change in ({"schema_version": True}, {"schema_version": 2}, {"kind": "foreign"},
                       {"cli": []}, {"tools": []}, {"source_relative": False}, {"extra": 1}):
            with self.subTest(change=change), self.assertRaises(ValueError):
                runner.validate_metadata({**metadata, **change})
        marker_path = self.bundle / gen.OWNED_MARKER
        marker_path.write_text("[]")
        with self.assertRaisesRegex(ValueError, "identity changed"):
            runner.verified_project()

    def test_policy_changes_are_refused_even_with_updated_content_digest(self):
        path = self.bundle / project_tests.POLICY
        path.write_text(path.read_text().replace('"cases_per_function"=1', '"cases_per_function"=2'))
        metadata = gen.read(self.bundle / project_tests.PROJECT)
        metadata["files_sha256"][project_tests.POLICY] = gen.capture.file_digest(path)
        self.reseal(metadata)
        with self.assertRaisesRegex(ValueError, "policy identity"):
            project_tests.verify(gen, self.bundle)

    def test_existing_destination_and_input_overlap_never_overwrite(self):
        for target in (self.bundle, self.source, self.workspace / "child", self.provider / "child", self.base):
            with self.subTest(target=target), self.assertRaises(ValueError):
                self.promote(destination=target)
        self.assertEqual((self.source / "app.py").read_text(), "def selected(n:int)->int:return n+1\n")

    def test_symlinks_and_special_files_are_refused_before_hashing(self):
        path = self.bundle / "README.txt"
        original = path.read_bytes()
        path.unlink()
        path.symlink_to(self.source / "app.py")
        with self.assertRaisesRegex(ValueError, "missing or extra"):
            runner.verified_project()
        with self.assertRaisesRegex(ValueError, "unowned files"):
            project_tests.verify(gen, self.bundle)
        path.unlink()
        path.write_bytes(original)
        fifo = self.base / "fifo"
        os.mkfifo(fifo)
        with self.assertRaisesRegex(ValueError, "regular file"):
            runner.file_hash(fifo)

    def test_external_suites_require_explicit_current_source(self):
        destination = self.base / "external"
        self.promote(destination=destination)
        with patch.object(runner, "ROOT", destination), patch.dict(os.environ):
            os.environ.pop("OTELEQ_SOURCE", None)
            metadata = runner.verified_project()
            with self.assertRaisesRegex(ValueError, "OTELEQ_SOURCE"):
                runner.source_path(metadata)
            os.environ["OTELEQ_SOURCE"] = str(self.source)
            self.assertEqual(runner.source_path(metadata), self.source)

    def test_in_repository_source_location_moves_with_the_checkout(self):
        moved = self.base / "moved"
        shutil.move(self.source, moved)
        with patch.object(runner, "ROOT", moved / self.bundle.name), patch.dict(os.environ):
            os.environ.pop("OTELEQ_SOURCE", None)
            self.assertEqual(runner.source_path(runner.verified_project()), moved)

    def test_duplicate_metadata_and_unowned_cleanup_are_not_accepted(self):
        path = self.bundle / project_tests.PROJECT
        path.write_text('{"value":1,"value":2}')
        with self.assertRaisesRegex(ValueError, "duplicate"):
            runner.read(path)
        options = argparse.Namespace(workspace=self.bundle)
        with self.assertRaises(ValueError):
            gen.clean(options)
        self.assertTrue(self.bundle.exists())

    def test_clean_removes_only_an_unchanged_owned_suite(self):
        gen.clean(argparse.Namespace(workspace=self.bundle))
        self.assertFalse(self.bundle.exists())
        self.assertTrue((self.source / "app.py").exists())

    def test_resolved_policy_roundtrips_without_a_second_input_strategy(self):
        data = gen.read(self.workspace / gen.PLAN_FILE)
        self.assertTrue(project_tests.policy_text(data["configuration"]))
        with self.assertRaises((ValueError, TypeError)):
            project_tests.policy_text({"invalid": None})

    def test_policy_export_preserves_non_bmp_strings_and_escaped_content(self):
        configuration = gen.project_policy.validate({"fixtures": [
            {"function": "*selected", "cases": [["\U0001f642", 'a"b\\c\n']]}]})
        self.assertEqual(gen.project_policy.validate(tomllib.loads(project_tests.policy_text(configuration))), configuration)

    def test_policy_export_preserves_escaped_ascii_control_characters(self):
        for codepoint in [*range(32), 127]:
            with self.subTest(codepoint=codepoint):
                original = '[[fixtures]]\nfunction="*selected"\ncases=[["\\u' + format(codepoint, "04x") + '"]]\n'
                configuration = gen.project_policy.validate(tomllib.loads(original))
                actual = project_tests.policy_text(configuration)
                self.assertEqual(gen.project_policy.validate(tomllib.loads(actual)), configuration)

    def test_resolved_optional_fields_and_unbounded_integer_expectations_roundtrip(self):
        configuration = gen.project_policy.validate({"fixtures": [{"function": "*selected", "cases": [[1]],
            "expected_baseline": {"kind": "return_value", "value": {
                "kind": "integer", "type": "python.int", "value": "2", "signed": True}}}]})
        self.assertIsNone(configuration["fixtures"][0]["language"])
        self.assertIsNone(configuration["fixtures"][0]["expected_baseline"]["value"]["bits"])
        text = project_tests.policy_text(configuration)
        self.assertEqual(gen.project_policy.validate(tomllib.loads(text)), configuration)

    def test_policy_export_retains_zero_false_and_empty_values(self):
        configuration = gen.project_policy.validate({"generation": {"seed": 0},
            "fixtures": [{"function": "*selected", "cases": [[0, False, ""]]}]})
        self.assertEqual(gen.project_policy.validate(tomllib.loads(project_tests.policy_text(configuration))), configuration)

    def test_generator_identity_includes_numeric_rules_and_project_boilerplate(self):
        original = gen.capture.file_digest
        before = gen.generator_identity()
        for name in ("preconditions.py", "project_tests.py", "project_runner.py"):
            with self.subTest(name=name), patch.object(gen.capture, "file_digest",
                side_effect=lambda path: "f" * 64 if Path(path).name == name else original(path)):
                self.assertNotEqual(gen.generator_identity(), before)

    def test_prepare_binds_fresh_plan_tools_and_retains_external_receipts(self):
        fresh = self.base / "fresh"
        fresh.mkdir()
        metadata = runner.verified_project()
        gen.write(fresh / gen.PLAN_FILE, gen.read(self.workspace / gen.PLAN_FILE))
        calls = []
        def command(arguments, folder, name):
            calls.append((arguments, folder, name))
            return str(fresh) if name == "plan" else ""
        with patch.object(runner, "command", side_effect=command), redirect_stdout(io.StringIO()):
            self.assertEqual(runner.prepare(metadata), fresh)
        self.assertEqual([name for _, _, name in calls], ["plan", "generate"])
        self.assertNotEqual(calls[0][1], fresh)
        data = gen.read(fresh / gen.PLAN_FILE)
        data["tools"] = {"python": "/relocated-identical-tool"}
        gen.write(fresh / gen.PLAN_FILE, data)
        with patch.object(runner, "command", side_effect=command), redirect_stdout(io.StringIO()):
            self.assertEqual(runner.prepare(metadata), fresh)
        data["artefacts"] = {}
        gen.write(fresh / gen.PLAN_FILE, data)
        with patch.object(runner, "command", side_effect=command), self.assertRaisesRegex(ValueError, "context changed"):
            runner.prepare(metadata)

    def test_prepare_refuses_changed_cli_and_source_contained_run_parent(self):
        metadata = runner.verified_project()
        wrong = {**metadata, "cli_sha256": "f" * 64}
        with self.assertRaisesRegex(ValueError, "CLI identity"):
            runner.prepare(wrong)
        with patch.dict(os.environ, {"OTELEQ_WORKSPACE_PARENT": str(self.source)}), self.assertRaisesRegex(ValueError, "outside"):
            runner.prepare(metadata)

    def test_command_keeps_tool_failures_and_output_limit_visible(self):
        self.assertEqual(runner.command([sys.executable, "-c", "print('prepared')"], self.base, "ok"), "prepared")
        with self.assertRaisesRegex(ValueError, "failed"):
            runner.command([sys.executable, "-c", "raise SystemExit(3)"], self.base, "bad")
        self.assertEqual((self.base / "bad.stdout").read_bytes(), b"")
        result = subprocess.CompletedProcess([], 0, b"x" * (4 * 1024 * 1024 + 1), b"")
        with patch.object(runner.subprocess, "run", return_value=result), self.assertRaisesRegex(ValueError, "failed"):
            runner.command([self.cli], self.base, "large")

    def test_framework_loads_actual_generated_tests_and_never_passes_empty_discovery(self):
        fresh = self.base / "fresh"
        (fresh / "tests").mkdir(parents=True)
        script = fresh / "tests/test_equivalence.py"
        script.write_text("import unittest\nclass Generated(unittest.TestCase):\n def test_case(self):self.assertEqual(1,1)\n")
        with patch.object(runner, "prepare", return_value=fresh):
            suite = runner.load_tests(unittest.TestLoader(), None, None)
            result = unittest.TestResult()
            suite.run(result)
            self.assertEqual(result.testsRun, 1)
            self.assertTrue(result.wasSuccessful())
        script.write_text("# no selected tests\n")
        with patch.object(runner, "prepare", return_value=fresh):
            suite = runner.load_tests(unittest.TestLoader(), None, None)
            result = unittest.TestResult()
            suite.run(result)
            self.assertEqual(result.testsRun, 1)
            self.assertEqual(len(result.failures), 1)
        with patch.object(runner, "prepare", side_effect=ValueError("refused")):
            suite = runner.load_tests(unittest.TestLoader(), None, None)
            result = unittest.TestResult()
            suite.run(result)
            self.assertEqual(len(result.failures), 1)


if __name__ == "__main__":
    unittest.main()
