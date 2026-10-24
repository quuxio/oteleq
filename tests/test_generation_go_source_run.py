"""Public Go orchestration keeps independent inputs ahead of SDK commands."""

from contextlib import ExitStack
import copy
import json
from pathlib import Path
import subprocess
import sys
import tempfile
from types import SimpleNamespace
import unittest
from unittest.mock import Mock, patch

REPO = Path(__file__).resolve().parents[1]
sys.path[:0] = [str(REPO / "adapters/generation"), str(REPO / "examples")]
import generation
import go_build
import go_files
import go_source
import go_source_run as source_run


class GoSourceRunTests(unittest.TestCase):
    def setUp(self):
        temporary = tempfile.TemporaryDirectory()
        self.addCleanup(temporary.cleanup)
        self.base = Path(temporary.name).resolve()
        self.root, self.project, self.folder, context = [self.base / name for name in
                                                       ("sdk", "project", "attempt", "context")]
        for path in (self.project, self.folder, context, self.root / "adapters/go", self.root / "otelc"):
            path.mkdir(parents=True)
        (self.project / "go.mod").write_text("module example.test/app\n\ngo 1.26.0\n")
        (self.project / "app.go").write_text("package main\nfunc Add(value int)int{return value+1}\n")
        (self.root / "adapters/go/runtime.go").write_text("package runtime\n")
        (self.root / "otelc/go_supervisor.py").write_text('"""Literal producer input, never executed."""\n')
        (context / "context.go").write_text("package context\n")
        self.context = go_files.freeze(context)
        self.tools = {"go": self.base / "selected-go", "python-host": Path(sys.executable).absolute()}
        self.tools["go"].write_bytes(b"literal compiler input, never executed")
        self.tooling = {"go": str(self.tools["go"]), "bundle": str(self.base / "fixed-bundle")}
        self.entry = {"language": "go", "go_backend": "source-v1", "path": "app.go", "name": "Add",
                      "go_options": {"build_tags": []}, "go_build_timeout_ms": 1234,
                      "go_context": {"module_root": ".", "import_path": "example.test/app"}}
        self.config = self.folder / "policy.toml"
        self.config.write_text(go_source.policy(self.entry, "http://127.0.0.1:1", "unit"))
        self.settings = {"Module": {"Path": "example.test/app"}, "Go": "1.26.0"}
        self.before = [{"Path": "example.test/app", "Main": True}]
        self.after = [*self.before, {"Path": "go.opentelemetry.io/otel", "Version": "v1.47.0"}]
        self.commands, self.events = [], []
        self.original = go_files.freeze(self.project)
        self.caller = SimpleNamespace(target=".", targets=(go_build.Target("example.test/app.Add", "app.go", 2, 1),),
            state=lambda: {"literal": "independent caller"}, seal="a" * 64,
            verify=Mock(side_effect=self.original.verify), build_intent=self.intent)
        self.build = SimpleNamespace(identity={"sha256": "b" * 64},
            private=SimpleNamespace(root=self.folder / "go-build/private"),
            receipt={"plain": {"sha256": "c" * 64}, "instrumented": {"sha256": "d" * 64},
                     "selection": {"sha256": "e" * 64}, "modules_after": copy.deepcopy(self.after)},
            verify=Mock())
        self.checked = SimpleNamespace(intent=None, verify=Mock())
        self.session = SimpleNamespace(execution=None)
        self.build_action = None
        self.status = 0
        self.prepare_response = {"literal": "prepared response"}
        self.environment = {"GOFLAGS": "", "GOWORK": "off", "GOENV": "off"}
        self.workflow = SimpleNamespace(write=generation.write, execute=self.execute,
                                        BUILD_IDENTITIES=generation.BUILD_IDENTITIES)
        stack = ExitStack()
        self.addCleanup(stack.close)
        self.discover = stack.enter_context(patch.object(source_run.go_caller, "discover", side_effect=self.discovery))
        stack.enter_context(patch.object(source_run.go_source, "toolchain", return_value=self.tooling))
        stack.enter_context(patch.object(source_run.go_context, "prepare", return_value=self.context))
        self.reader = stack.enter_context(patch.object(source_run.go_build, "read", return_value=self.build))
        self.preparer = stack.enter_context(patch.object(source_run.go_prepared, "verify", side_effect=self.prepared))
        self.launcher = stack.enter_context(patch.object(source_run.go_launch, "Session", return_value=self.session))

    def intent(self, directory, sdk, tooling, settings, modules, context):
        self.events.append("intent")
        self.built_intent = go_build.Intent(directory, self.original, sdk, ".", self.caller.targets,
                                            tooling, settings, modules, context)
        return self.built_intent

    def discovery(self, original, entry, compiler, environment, execute):
        self.assertEqual(original.identities, self.original.identities)
        self.assertIs(entry, self.entry)
        self.assertEqual(compiler, self.tools["go"])
        self.assertIs(environment, self.environment)
        execute([compiler, "list", "-json"], self.project, input_data=b"literal compiler request")
        self.events.append("discovery")
        return self.caller

    def execute(self, argv, cwd, environment, folder, *, timeout, input_data, max_output_bytes):
        words = list(map(str, argv))
        self.commands.append((words, cwd))
        self.assertEqual(timeout, 1.234)
        self.assertIs(environment, self.environment)
        self.assertEqual(max_output_bytes, go_files.MAX_METADATA_BYTES)
        self.assertTrue((folder / "command.json").is_file())
        if input_data is not None:
            self.assertEqual((folder / "stdin").read_bytes(), input_data)
        if "go-build" in words:
            self.events.append("sdk-build")
            if self.build_action:
                self.build_action()
            response = {}
        elif "--prepare-only" in words:
            self.events.append("sdk-prepare")
            response = self.prepare_response
        elif words[1:] == ["mod", "edit", "-json"]:
            response = self.settings
        elif words[1:] == ["list", "-m", "-mod=readonly", "-json", "all"]:
            response = self.before if cwd == self.project else self.after
        else:
            response = {}
        raw = ("\n".join(map(json.dumps, response)) if isinstance(response, list) else json.dumps(response)).encode()
        (folder / "stdout").write_bytes(raw)
        (folder / "stderr").write_bytes(b"")
        return subprocess.CompletedProcess(words, self.status, raw, b"")

    def prepared(self, value, intent):
        self.assertEqual(value, self.prepare_response)
        self.checked.intent = intent
        return self.checked

    def run_prepare(self, lane="instrumented_on"):
        return source_run.prepare(self.workflow, self.root, self.project, self.entry, self.tools,
                                  self.environment, self.folder, self.config, lane, wait_ms=30000)

    def test_both_lanes_reconstruct_fixed_commands_and_keep_caller_inputs(self):
        for lane in ("baseline", "instrumented_on"):
            with self.subTest(lane=lane):
                self.folder = self.base / lane
                self.folder.mkdir()
                result = self.run_prepare(lane)
                self.assertIs(result.caller, self.caller)
                self.assertIs(result.session, self.session)
                self.assertEqual(result.sdk_version, "1.47.0")
                intent = self.checked.intent
                self.assertIs(intent.build, self.build)
                self.assertEqual(intent.plain, lane == "baseline")
                self.assertEqual(intent.policy, go_source.configuration(self.entry, "http://127.0.0.1:1", "unit"))
                self.assertEqual(intent.python, self.tools["python-host"])
                self.assertEqual(intent.producer.identities, go_files.freeze(self.root / "otelc").identities)
                prefix = list(map(str, go_source.cli(self.root, self.tools))) + ["--config", str(self.config)]
                build_command, _ = next(item for item in self.commands if "go-build" in item[0])
                self.assertEqual(build_command, prefix + ["go-build", "--root", str(self.project), "--target", ".",
                    "--output", str(self.folder / "go-build"), "--go", str(self.tools["go"]), "--prepared-tools"])
                prepare_command, _ = self.commands[-1]
                self.assertEqual(prepare_command, prefix + ["go", "--build", str(self.folder / "go-build"),
                    "--runtime", str(self.folder / "go-runtime"), "--prepare-only"] + (["--plain"] if lane == "baseline" else []))
                self.assertLess(self.events.index("discovery"), self.events.index("intent"))
                self.assertLess(self.events.index("intent"), self.events.index("sdk-build"))
                self.assertLess(self.events.index("sdk-build"), self.events.index("sdk-prepare"))
                retained = generation.read(self.folder / generation.BUILD_IDENTITIES)
                self.assertEqual(retained["caller_seal"], self.caller.seal)
                self.assertEqual(retained["selection_sha256"], "e" * 64)
                self.launcher.assert_called_with(self.checked, wait_ms=30000)
                self.commands.clear()
                self.events.clear()

    def test_unsupported_selection_refuses_before_any_compiler_or_sdk(self):
        for key, value in (("go_backend", "legacy"), ("go_options", {"build_tags": ["feature"]}),
                           ("sequence_configuration", {})):
            original = copy.deepcopy(self.entry)
            self.entry[key] = value
            with self.subTest(key=key), self.assertRaises(ValueError):
                self.run_prepare()
            self.entry = original
        for lane in ("other", "instrumented"):
            with self.assertRaises(ValueError):
                self.run_prepare(lane)
        self.discover.assert_not_called()
        self.assertEqual(self.commands, [])

    def test_source_service_is_bound_only_by_policy_without_ambient_sdk_settings(self):
        environment, scratch = generation.attempt_environment(self.base, self.root, self.project,
            self.entry, self.tools, "unit-service", self.folder)
        self.assertNotIn("OTEL_SERVICE_NAME", environment)
        self.assertFalse(any(name.startswith("OTEL_") for name in environment))
        self.assertEqual(environment["OTELC_GO"], str(self.tools["go"]))
        self.assertEqual(environment["GOCACHE"], str(self.base / "go-cache/build"))
        self.assertEqual(environment["GOFLAGS"], "")
        self.assertTrue(scratch.is_dir())
        legacy = {**self.entry, "go_backend": "legacy"}
        other = self.base / "legacy-attempt"
        other.mkdir()
        environment, _ = generation.attempt_environment(self.base, self.root, self.project,
            legacy, self.tools, "unit-service", other)
        self.assertEqual(environment["OTEL_SERVICE_NAME"], "unit-service")

    def test_policy_must_bind_independently_discovered_functions_before_build(self):
        self.config.write_text('[functions]\ninclude = ["another.Function"]\n')
        with self.assertRaisesRegex(ValueError, "policy differs"):
            self.run_prepare()
        self.assertNotIn("sdk-build", self.events)
        self.reader.assert_not_called()

    def test_nested_caller_metadata_mutation_during_sdk_build_cannot_be_repaired(self):
        self.build_action = lambda: self.built_intent.settings.update(Go="different")
        with self.assertRaisesRegex(ValueError, "inputs changed"):
            self.run_prepare()
        self.reader.assert_not_called()

    def test_changed_original_source_refuses_before_build_receipt_acceptance(self):
        self.build_action = lambda: (self.project / "app.go").write_text("package main\n")
        with self.assertRaises(ValueError):
            self.run_prepare()
        self.reader.assert_not_called()

    def test_independent_private_module_graph_and_sdk_version_are_required(self):
        for modules in ([*self.after, {"Path": "extra"}], self.before,
                        [*self.before, {"Path": "go.opentelemetry.io/otel", "Version": 1}],
                        [*self.before, {"Path": "go.opentelemetry.io/otel", "Version": "1.47.0"}]):
            self.after = modules
            self.build.receipt["modules_after"] = copy.deepcopy(modules) if len(modules) < 3 else []
            with self.subTest(modules=modules), self.assertRaises(ValueError):
                self.run_prepare()
            self.assertNotIn("sdk-prepare", self.events)
            self.commands.clear()
            self.events.clear()
            # Failed attempts use fresh output channels, as the public runner does.
            self.folder = self.base / ("failed-" + str(len(list(self.base.glob("failed-*")))))
            self.folder.mkdir()
        self.preparer.assert_not_called()

    def test_compiler_failure_retains_channels_and_prevents_build_acceptance(self):
        self.status = 17
        with self.assertRaisesRegex(ValueError, "retained compiler channels"):
            self.run_prepare()
        self.assertTrue((self.folder / "go-tooling/0/stdout").is_file())
        self.assertTrue((self.folder / "go-tooling/0/stderr").is_file())
        self.reader.assert_not_called()
        self.launcher.assert_not_called()

    def test_run_requires_completed_owned_execution_and_rechecks_every_boundary(self):
        result = self.run_prepare()
        with self.assertRaisesRegex(ValueError, "completed owned execution"):
            result.verify()
        execution = SimpleNamespace(verify=Mock())
        self.session.execution = execution
        result.verify()
        execution.verify.assert_called_once()
        self.checked.verify.assert_called()
        self.caller.verify.assert_called()
        self.caller.verify.side_effect = ValueError("changed caller")
        with self.assertRaisesRegex(ValueError, "changed caller"):
            result.verify()


if __name__ == "__main__":
    unittest.main()
