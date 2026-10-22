"""Metadata-only compiler receipts retain bytes, configuration and source identity."""

import copy
import hashlib
from pathlib import Path
import sys
import tempfile
import unittest

REPO = Path(__file__).resolve().parents[1]
sys.path[:0] = [str(REPO / "adapters/generation"), str(REPO / "examples")]
import node_source_context as context


class NodeSourceContextTests(unittest.TestCase):
    def setUp(self):
        temporary = tempfile.TemporaryDirectory()
        self.addCleanup(temporary.cleanup)
        self.base = Path(temporary.name).resolve()
        self.provider = self.base / "provider"
        self.provider.mkdir()
        self.compiler = self.provider / "compiler"
        self.compiler.write_text("fixed installed compiler")
        self.project = self.base / "application"
        self.project.mkdir()
        self.directory = self.base / "compiler-evidence"
        self.directory.mkdir()
        self.source = b"throw Error('initialiser must never run');\n"
        self.digest = hashlib.sha256(self.source).hexdigest()

    def fixture(self, backend="native"):
        files = {}
        roles = ["input", "options", "output", "map"] + (["preparation_map"] if backend == "native" else [])
        for name in roles:
            content = self.source if name == "input" else name.encode()
            digest = hashlib.sha256(content).hexdigest()
            (self.directory / (digest + ".txt")).write_bytes(content)
            files[name] = {"file": digest + ".txt", "sha256": digest, "size": len(content)}
        compiler = {"backend": backend, "version": "7.0.2" if backend == "native" else "6.0.3",
                    "compiler_path": str(self.compiler), "cwd": str(self.project), "transformer_profile": "none", "files": files}
        if backend == "native":
            compiler["argv"] = [str(self.compiler), "--project", str(self.base / "private-compiler/tsconfig.json")]
        else:
            compiler["method"] = "transpileModule"
        config = self.project / "tsconfig.json"
        return {"profile": "module-format-only-v1", "compiler": compiler,
                "configuration_reads": [{"kind": "absent_config", "requested_path": str(config)}]}

    def validate(self, value, backend="native"):
        context.validate(value, self.digest, self.provider, backend, self.directory, cwd=self.project)

    def test_both_compilers_retain_complete_raw_artifacts_without_sdk_claims(self):
        for backend in ("native", "api"):
            with self.subTest(backend=backend):
                value = self.fixture(backend)
                self.validate(value, backend)
                self.assertEqual(set(value), {"profile", "compiler", "configuration_reads"})

    def test_unknown_compiler_recipe_profile_and_input_identity_refuse(self):
        value = self.fixture()
        variants = [{**value, "profile": "source-launch"}, {**value, "extra": True}]
        for key, changed in (("backend", "api"), ("version", "unknown"), ("cwd", str(self.base)),
                             ("transformer_profile", "original-identities-v1"), ("argv", ["arbitrary"])):
            variants.append({**value, "compiler": {**value["compiler"], key: changed}})
        for changed in variants:
            with self.subTest(changed=changed), self.assertRaises(ValueError):
                self.validate(changed)
        with self.assertRaises(ValueError):
            context.validate(value, "0" * 64, self.provider, "native", self.directory, cwd=self.project)
        api = self.fixture("api")
        api["compiler"]["method"] = "arbitrary"
        with self.assertRaises(ValueError):
            self.validate(api, "api")
        foreign = self.base / "foreign-compiler"
        foreign.write_text("foreign")
        value["compiler"]["compiler_path"] = str(foreign)
        with self.assertRaises(ValueError):
            self.validate(value)

    def test_artifact_drift_links_and_malformed_identities_cannot_pass(self):
        value = self.fixture()
        for key, changed in (("file", "../outside"), ("sha256", "G" * 64), ("size", True), ("path", "relative")):
            changed_value = copy.deepcopy(value)
            changed_value["compiler"]["files"]["input"][key] = changed
            with self.subTest(key=key), self.assertRaises(ValueError):
                self.validate(changed_value)
        path = self.directory / value["compiler"]["files"]["input"]["file"]
        path.write_bytes(b"changed")
        with self.assertRaises(ValueError):
            self.validate(value)
        path.unlink()
        foreign = self.base / "same-bytes"
        foreign.write_bytes(self.source)
        path.symlink_to(foreign)
        with self.assertRaises(ValueError):
            self.validate(value)

    def test_configuration_absence_real_reads_and_duplicate_reads_are_rechecked(self):
        value = self.fixture()
        config = self.project / "tsconfig.json"
        config.write_text('{"compilerOptions":{"target":"ES2022"}}')
        with self.assertRaises(ValueError):
            self.validate(value)
        record = {"requested_path": str(config), "resolved_path": str(config), "kind": "compiler_config",
                  "sha256": hashlib.sha256(config.read_bytes()).hexdigest(), "size": config.stat().st_size}
        value["configuration_reads"] = [record]
        self.validate(value)
        value["configuration_reads"].append(record.copy())
        with self.assertRaises(ValueError):
            self.validate(value)
        value["configuration_reads"].pop()
        config.write_text("changed")
        with self.assertRaises(ValueError):
            self.validate(value)

    def test_signature_normalises_copied_roots_and_preserves_foreign_origins(self):
        original = self.fixture()
        copied = copy.deepcopy(original)
        other = self.base / "snapshot"
        copied["configuration_reads"][0]["requested_path"] = str(other / "tsconfig.json")
        self.assertEqual(context.configuration_signature(original, self.project), context.configuration_signature(copied, other))
        copied["configuration_reads"][0]["requested_path"] = str(self.base / "foreign/tsconfig.json")
        self.assertNotEqual(context.configuration_signature(original, self.project), context.configuration_signature(copied, other))


if __name__ == "__main__":
    unittest.main()
