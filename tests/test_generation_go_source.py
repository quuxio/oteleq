"""Closed Go provider negotiation and complete installed-byte input scope."""

import copy
import hashlib
import json
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest
from unittest.mock import patch

REPO = Path(__file__).resolve().parents[1]
sys.path[:0] = [str(REPO / "adapters/generation"), str(REPO / "examples")]
import generation
import go_project
import go_source as source


class GoSourceTests(unittest.TestCase):
    def test_optional_protobuf_decoder_does_not_block_cli_help_or_planning(self):
        code = ("import sys;sys.path[:0]=" + repr([str(REPO / "adapters/generation"), str(REPO / "examples")])
                + ";import go_telemetry")
        result = subprocess.run([sys.executable, "-I", "-S", "-B", "-c", code], capture_output=True, timeout=10)
        self.assertEqual(result.returncode, 0, result.stderr.decode())

    def setUp(self):
        temporary = tempfile.TemporaryDirectory()
        self.addCleanup(temporary.cleanup)
        self.base = Path(temporary.name).resolve()
        self.root, self.workspace, self.installed = [self.base / name for name in ("sdk", "workspace", "installed")]
        for path in (self.root, self.workspace, self.installed):
            path.mkdir()
        for name in source.REQUIRED | {"bin/quux-otelc", "requirements.txt", "requirements-dev.txt"}:
            path = self.root / name
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_text("fixture input\n")
        native = self.base / "native-go"
        native.write_bytes(b"fixture compiler")
        weaver = self.root / "build/go-upstream/bin/otelc"
        weaver.parent.mkdir(parents=True)
        weaver.write_bytes(b"fixture weaver")
        bundle = self.base / "bundle.tgz"
        bundle.write_bytes(b"fixture bundle")
        digest = lambda path: hashlib.sha256(path.read_bytes()).hexdigest()
        self.toolchain = {"schema_version": 1, "module": "go.opentelemetry.io/otelc", "version": "v1.0.1",
                          "module_sum": "fixture", "module_go_sum": "fixture", "build_metadata": "fixture",
                          "go": str(native), "go_sha256": digest(native), "go_version": "go1.27.3",
                          "weaver": str(weaver), "weaver_sha256": digest(weaver),
                          "bundle": str(bundle), "bundle_sha256": digest(bundle),
                          "platform": {"GOOS": "darwin", "GOARCH": "arm64"}}
        self.publish()
        # Compact unit assets stub only the upstream hash boundary. Actual SDK
        # setup and application execution have separate qualification.
        boundary = patch.object(source.go_context, "BUNDLE_SHA256", digest(bundle))
        boundary.start()
        self.addCleanup(boundary.stop)
        roots = patch.object(source.python_inputs, "dependency_roots", return_value=[self.installed])
        roots.start()
        self.addCleanup(roots.stop)
        self.tools = {"go": native, "python-host": Path(sys.executable).absolute()}
        self.options = go_project.settings({"backend": "source-v1", "module_roots": ["service"]})
        self.entry = {"language": "go", "go_backend": "source-v1", "status": "ready", "id": "fixture",
                      "path": "service/api.go", "name": "Add", "go_options": self.options,
                      "go_context": {"module_root": "service", "directory": "service", "package": "main",
                                     "import_path": "example.test/app"}}
        source.configure(self.entry, self.options)

    def publish(self):
        (self.root / source.TOOLCHAIN_FILE).write_text(json.dumps(self.toolchain))

    def execute(self, command, cwd, env, folder, **options):
        command = list(map(str, command))
        self.assertEqual(command[:5], list(map(str, source.cli(self.root, self.tools))))
        protocols = {**source.PROTOCOLS, **({"build": 5, "inspection": 2} if "--build-tags" in command else {})}
        value = (protocols if "go-protocols" in command else {
            "policy": source.configuration(self.entry, "http://127.0.0.1:4318", "oteleq-go-provider"),
            "implemented": sorted(source.SDK_LANGUAGES), "remaining": [], "candidates": []})
        return subprocess.CompletedProcess(command, 0, json.dumps(value).encode(), b"")

    def test_selection_preserves_default_policy_and_binds_real_package_names(self):
        legacy = go_project.settings({})
        self.assertNotIn("backend", legacy)
        self.assertFalse(source.enabled({"language": "go"}))
        self.assertTrue(source.enabled(self.entry))
        self.assertEqual(self.entry["otelc_runtime_function"], "example.test/app.Add")
        config = source.configuration(self.entry, "http://127.0.0.1:1", "unit")
        self.assertEqual(config["functions"]["include"], ["example.test/app.Add"])
        self.assertEqual(config["sources"]["include"], ["api.go"])
        for invalid in (False, "other", None):
            with self.assertRaises(ValueError):
                go_project.settings({"backend": invalid})
        receiver = {**self.entry, "receiver_fixture": {"factory": "New", "source_path": "service/factory.go"}}
        config = source.configuration(receiver, "http://127.0.0.1:1", "unit")
        self.assertEqual(config["functions"]["include"], ["example.test/app.Add", "example.test/app.New"])
        self.assertEqual(config["sources"]["include"], ["api.go", "factory.go"])

    def test_installed_catalogue_retains_executable_cache_bytes(self):
        cache = self.root / "otelc/__pycache__/go_build.fixture.pyc"
        cache.parent.mkdir()
        cache.write_bytes(b"cached SDK code")
        installed = self.installed / "__pycache__/dependency.fixture.pyc"
        installed.parent.mkdir()
        installed.write_bytes(b"cached wheel code")
        original = source.artefacts(self.root, self.tools)
        self.assertIn("otelc/__pycache__/go_build.fixture.pyc", original)
        self.assertTrue(any(name.startswith("installed:") and name.endswith(".pyc") for name in original))
        cache.write_bytes(b"other cached SDK code")
        self.assertNotEqual(source.artefacts(self.root, self.tools), original)
        linked = self.installed / "linked"
        linked.symlink_to(self.root, target_is_directory=True)
        with self.assertRaisesRegex(ValueError, "linked Go provider"):
            source.artefacts(self.root, self.tools)

    def test_installed_records_cannot_select_a_different_executable(self):
        self.assertEqual(source.toolchain(self.root, self.tools), self.toolchain)
        original = copy.deepcopy(self.toolchain)
        for field, value in (("schema_version", True), ("go", "/another/compiler"),
                             ("weaver", "/another/weaver"), ("bundle_sha256", "0" * 64), ("extra", "argv")):
            self.toolchain = {**original, field: value}
            self.publish()
            with self.subTest(field=field), self.assertRaises(ValueError):
                source.toolchain(self.root, self.tools)
        self.toolchain = original
        self.publish()
        self.tools["go"].write_bytes(b"changed compiler")
        with self.assertRaises(ValueError):
            source.toolchain(self.root, self.tools)

    def test_complete_public_negotiation_and_retained_probe_seals(self):
        source.bind(self.entry, self.root, self.workspace, self.tools, self.execute)
        self.assertEqual(self.entry["status"], "ready")
        self.assertEqual(self.entry["go_provider"]["protocols"], source.PROTOCOLS)
        directory = self.workspace / source.DIRECTORY
        data = {"configuration": {"adapters": {"go": self.options}}, "inventory": [self.entry],
                "go_provider_manifest": generation.manifest(directory)}
        source.verify_probes(generation, self.workspace, data)
        self.entry["otelc_runtime_function"] = "foreign.Add"
        with self.assertRaisesRegex(ValueError, "context or runtime"):
            source.verify_probes(generation, self.workspace, data)
        self.entry["otelc_runtime_function"] = "example.test/app.Add"
        (directory / "extra").write_bytes(b"extra")
        with self.assertRaisesRegex(ValueError, "probes changed"):
            source.verify_probes(generation, self.workspace, data)

    def test_descriptor_receipts_cannot_repair_or_substitute_protocols(self):
        source.probe_protocols(self.root, self.workspace, self.tools, self.execute)
        cached = self.workspace / source.DIRECTORY / "protocol/response.json"
        record = json.loads(cached.read_text())
        source.probe_protocols(self.root, self.workspace, self.tools,
                               lambda *args, **kwargs: self.fail("cached probe was executed again"))
        for key, value in (("status", True), ("command", ["another"]), ("stdout", "{}")):
            changed = {**record, key: value}
            cached.write_text(json.dumps(changed))
            with self.subTest(key=key), self.assertRaises(ValueError):
                source.probe_protocols(self.root, self.workspace, self.tools, self.execute)

    def test_unavailable_requests_are_blocked_without_legacy_fallback(self):
        for values in ({"sequence_configuration": []}, {"go_context": None}):
            entry = copy.deepcopy(self.entry)
            entry.update(values)
            if entry.get("go_context") is None:
                entry.pop("go_context", None)
            source.bind(entry, self.root, self.workspace, self.tools,
                        lambda *args, **kwargs: self.fail("unsupported request started a probe"))
            self.assertEqual(entry["status"], "blocked")
            self.assertIn("unavailable", entry["reason"])
        legacy = {"language": "go", "status": "ready"}
        source.bind(legacy, self.root, self.workspace, self.tools, self.execute)
        self.assertNotIn("go_provider", legacy)

    def test_tagged_protocol_is_explicit_and_cannot_reuse_an_untagged_probe(self):
        self.entry["go_options"]["build_tags"] = ["feature", "tools", "\u03c0"]
        source.bind(self.entry, self.root, self.workspace, self.tools, self.execute)
        self.assertEqual(self.entry["status"], "ready")
        self.assertEqual(self.entry["go_provider"]["protocols"],
                         {**source.PROTOCOLS, "build": 5, "inspection": 2})
        cached = json.loads((self.workspace / source.DIRECTORY / "protocol/response.json").read_text())
        self.assertEqual(cached["command"][-3:], ["go-protocols", "--prepared-tools", "--build-tags"])
        with self.assertRaisesRegex(ValueError, "protocol probe failed"):
            source.probe_protocols(self.root, self.workspace, self.tools, self.execute)

    def test_source_tag_names_are_bounded_literals_and_keep_unicode_for_go(self):
        options = go_project.settings({"backend": "source-v1", "module_roots": ["."],
                                       "build_tags": ["\u03c0", "tools", "feature"]})
        self.assertEqual(options["build_tags"], ["feature", "tools", "\u03c0"])
        # Unicode category validation occurs in the pinned Go inspector before
        # compilation, rather than using Python's possibly different tables.
        self.assertEqual(go_project.canonical_tags(["\U0001f600"]), ("\U0001f600",))
        for invalid in (None, "tools", [True], [""], ["x,y"], ["x y"], ["-race"],
                        ["a\n"], ["\ud800"], ["a" * 257], ["\u03c0" * 129],
                        ["x", "x"], [str(i) for i in range(129)]):
            with self.subTest(value=repr(invalid)), self.assertRaises(ValueError):
                go_project.canonical_tags(invalid)
        with self.assertRaises(ValueError):
            go_project.settings({"module_roots": ["."], "build_tags": ["\u03c0"]})

    def test_tagged_request_cannot_fall_back_to_a_build4_descriptor(self):
        self.entry["go_options"]["build_tags"] = ["feature"]
        def untagged(command, *args, **kwargs):
            self.assertIn("--build-tags", command)
            return subprocess.CompletedProcess(command, 0, json.dumps(source.PROTOCOLS).encode(), b"")
        source.bind(self.entry, self.root, self.workspace, self.tools, untagged)
        self.assertEqual(self.entry["status"], "blocked")
        self.assertIn("unsupported prepared-tool Go protocols", self.entry["reason"])
        self.assertNotIn("go_provider", self.entry)

    def test_all_eight_capabilities_and_complete_common_policy_are_required(self):
        expected = source.configuration(self.entry, "http://127.0.0.1:1", "unit")
        valid = {"policy": expected, "implemented": ["python"], "candidates": ["go"],
                 "remaining": sorted(source.SDK_LANGUAGES - {"python"})}
        source.verify_capabilities(valid, expected)
        for field, value in (("policy", {}), ("candidates", ["unknown"]), ("remaining", []),
                             ("implemented", ["go", "go"])):
            changed = {**valid, field: value}
            with self.assertRaises(ValueError):
                source.verify_capabilities(changed, expected)


if __name__ == "__main__":
    unittest.main()
