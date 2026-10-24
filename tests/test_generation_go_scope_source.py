"""Explicit scope-safe negotiation cannot substitute a legacy source profile."""

import json
from pathlib import Path
import subprocess
import sys
import unittest

REPO = Path(__file__).resolve().parents[1]
sys.path[:0] = [str(REPO / "adapters/generation"), str(REPO / "examples")]
import generation
import go_project
import go_rendezvous
import go_source as source
import go_tooling
from go_provider import SCOPE_HELPER_PROFILE
import test_generation_go_source as source_tests
from test_generation_go_tooling import fixture as tooling_fixture


class GoScopeSourceTests(unittest.TestCase):
    setUp = source_tests.GoSourceTests.setUp
    publish = source_tests.GoSourceTests.publish

    def execute(self, command, *args, **options):
        value = source_tests.GoSourceTests.execute(self, command, *args, **options)
        if "go-protocols" in command:
            self.assertIn("--scope-safe", command)
            tags = "--build-tags" in command
            result = {**source.PROTOCOLS, "build": 7 if tags else 6, "inspection": 2 if tags else 1,
                      "helper_profile": SCOPE_HELPER_PROFILE, "prepared_tools": 2}
            value.stdout = json.dumps(result).encode()
        return value

    def select(self, tags=()):
        self.options = go_project.settings({"backend": source.SCOPE_SOURCE, "module_roots": ["service"],
                                            "build_tags": list(tags)})
        self.entry["go_options"] = self.options
        source.configure(self.entry, self.options)

    def test_scope_selection_binds_exact_untagged_and_tagged_descriptors(self):
        for tags in ((), ("tools", "\u03c0", "feature")):
            with self.subTest(tags=tags):
                self.workspace = self.base / ("tagged" if tags else "untagged")
                self.workspace.mkdir()
                self.select(tags)
                source.bind(self.entry, self.root, self.workspace, self.tools, self.execute)
                self.assertEqual(self.entry["status"], "ready")
                self.assertTrue(source.scope_safe(self.entry))
                self.assertTrue(go_rendezvous.enabled(self.entry))
                protocols = self.entry["go_provider"]["protocols"]
                self.assertEqual((protocols["build"], protocols["inspection"], protocols["prepared_tools"]),
                                 (7, 2, 2) if tags else (6, 1, 2))
                self.assertEqual(protocols["helper_profile"], SCOPE_HELPER_PROFILE)
                cached = json.loads((self.workspace / source.DIRECTORY / "protocol/response.json").read_text())
                self.assertEqual(cached["command"][5:], ["go-protocols", "--scope-safe", "--prepared-tools"]
                                 + (["--build-tags"] if tags else []))

    def test_old_descriptor_missing_profile_and_numeric_substitutions_refuse(self):
        self.select()
        valid = {**source.PROTOCOLS, "build": 6, "inspection": 1,
                 "helper_profile": SCOPE_HELPER_PROFILE, "prepared_tools": 2}
        candidates = [source.PROTOCOLS, {name: value for name, value in valid.items() if name != "helper_profile"},
                      *[{**valid, key: value} for key, value in
                        (("build", 7), ("inspection", True), ("prepared_tools", 1),
                         ("prepared_tools", 2.0), ("helper_profile", "legacy"))]]
        for index, value in enumerate(candidates):
            workspace = self.base / ("refusal-" + str(index))
            workspace.mkdir()
            execute = lambda command, *args, **options: subprocess.CompletedProcess(command, 0, json.dumps(value).encode(), b"")
            with self.subTest(value=value), self.assertRaisesRegex(ValueError, "unsupported prepared-tool"):
                source.probe_protocols(self.root, workspace, self.tools, execute, backend=source.SCOPE_SOURCE)

    def test_cached_scope_probe_cannot_select_the_old_source_backend(self):
        self.select()
        source.probe_protocols(self.root, self.workspace, self.tools, self.execute, backend=source.SCOPE_SOURCE)
        with self.assertRaisesRegex(ValueError, "protocol probe failed"):
            source.probe_protocols(self.root, self.workspace, self.tools, self.execute)
        data = {"configuration": {"adapters": {"go": self.options}}, "inventory": [self.entry],
                "go_provider_manifest": generation.manifest(self.workspace / source.DIRECTORY)}
        source.verify_probes(generation, self.workspace, data)
        self.entry["go_backend"] = source.SOURCE
        with self.assertRaisesRegex(ValueError, "backend differs"):
            source.verify_probes(generation, self.workspace, data)

    def test_installed_scope_catalogue_preserves_every_source_and_manifest(self):
        directory, compiler, tools, _ = tooling_fixture(self, self.base,
            directory=self.root / go_tooling.DIRECTORY)
        self.tools["go"] = compiler
        for name in ("ci/go_scope_patch.py", "otelc/go_prepared_tools.py"):
            (self.root / name).write_text("fixture private tooling input\n")
        self.assertEqual(source.toolchain(self.root, self.tools, backend=source.SCOPE_SOURCE), tools)
        catalogue = source.artefacts(self.root, self.tools, backend=source.SCOPE_SOURCE)
        self.assertIn(go_tooling.DIRECTORY + "/" + go_tooling.MANIFEST, catalogue)
        self.assertIn(go_tooling.DIRECTORY + "/source/" + go_tooling.PATCH_FILE, catalogue)
        self.assertIn(go_tooling.DIRECTORY + "/source/go.mod", catalogue)
        (directory / "source/go.mod").write_bytes(b"module another/module\n")
        with self.assertRaisesRegex(ValueError, "single reviewed backport"):
            source.toolchain(self.root, self.tools, backend=source.SCOPE_SOURCE)


if __name__ == "__main__":
    unittest.main()
