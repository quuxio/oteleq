"""Helper collisions require independently derived mappings and exact private bytes."""
import json
from pathlib import Path
import shutil
import subprocess
import sys
import tempfile
import unittest
import zipfile

REPO = Path(__file__).resolve().parents[1]
sys.path[:0] = [str(REPO / "adapters/generation"), str(REPO / "examples")]
import java_helper_binding as helpers
import java_provider as provider


class JavaHelperBindingTests(unittest.TestCase):
    def setUp(self):
        temporary = tempfile.TemporaryDirectory(prefix="java helper binding ")
        self.addCleanup(temporary.cleanup)
        self.base = Path(temporary.name).resolve()
        self.root = self.base / "provider"
        self.folder = self.base / "attempt"
        self.folder.mkdir()
        self.runtime = self.base / "runtime"
        self.runtime.mkdir()
        self.classes = self.base / "classes"
        self.classes.mkdir()
        extension = self.root / provider.EXTENSION
        extension.parent.mkdir(parents=True)
        with zipfile.ZipFile(extension, "w") as archive:
            archive.writestr("io/quux/otelc/methods/Runtime.class", b"known helper payload")
            archive.writestr("licence.txt", b"preserved")
        (self.root / provider.HELPER).write_bytes(b"pinned relocation tool")
        self.context = {"entries": []}
        self.calls = []

    def execute(self, command, *args, **kwargs):
        self.calls.append(list(map(str, command)))
        # A narrow transformation fixture supplies known output; actual ASM is qualified separately.
        shutil.copyfile(command[4], command[5])
        return subprocess.CompletedProcess(command, 0, b"", b"")

    def prepare(self):
        helpers.prepare(self.root, [self.classes], self.context, Path("/known/java"), self.folder, {}, self.execute)

    def collision(self):
        self.context["entries"] = [{"classes": {"io.quux.otelc.methods.Application": {}}}]

    def private_files(self):
        proof = self.folder / helpers.PROOF
        for name in ("helpers-extension.jar", "helpers.properties"):
            shutil.copyfile(proof / name, self.runtime / name)
        record = json.loads((proof / "binding.json").read_text())
        (self.runtime / "helpers.json").write_text(json.dumps({"schema_version": 1, "kind": "otelc.java-helper-map", **record}))

    def verify(self):
        return helpers.verify(self.root, [self.classes], self.context, self.folder, self.runtime)

    def test_no_collision_keeps_the_frozen_extension_and_refuses_hidden_relocation(self):
        self.prepare()
        self.assertEqual(self.calls, [])
        self.assertEqual(self.verify(), (self.root / provider.EXTENSION, set()))
        (self.runtime / "helpers.json").write_text("{}")
        with self.assertRaisesRegex(ValueError, "unexpected helper relocation"):
            self.verify()

    def test_collision_derives_mapping_invokes_only_the_known_tool_and_binds_private_bytes(self):
        self.collision()
        self.prepare()
        self.private_files()
        extension, extra = self.verify()
        self.assertEqual(extension, self.runtime / "helpers-extension.jar")
        self.assertEqual({path.name for path in extra}, {"helpers-extension.jar", "helpers.properties", "helpers.json"})
        self.assertEqual(self.calls[0][:4], ["/known/java", "-cp", str(self.root / provider.HELPER),
                                           "io.quux.otelc.tools.HelperRelocator"])
        self.assertEqual((extension).read_bytes(), (self.root / provider.EXTENSION).read_bytes())

    def test_application_owned_generated_prefix_advances_the_independent_nonce(self):
        self.collision()
        mapping = helpers.packages(self.root, [self.classes], self.context)
        prefix = next(iter(mapping.values())).removesuffix("methods.")
        self.context["entries"][0]["classes"][prefix + "Application"] = {}
        advanced = helpers.packages(self.root, [self.classes], self.context)
        self.assertIn("x1.methods.", advanced["io.quux.otelc.methods."])

    def test_rehashed_descriptor_and_changed_private_proof_or_properties_refuse(self):
        self.collision()
        self.prepare()
        self.private_files()
        for name in ("helpers.properties", "helpers-extension.jar", "helpers.json"):
            path = self.runtime / name
            original = path.read_bytes()
            path.write_bytes(original + b"changed")
            with self.subTest(name=name), self.assertRaises((ValueError, json.JSONDecodeError)):
                self.verify()
            path.write_bytes(original)
        proof = self.folder / helpers.PROOF / "binding.json"
        record = json.loads(proof.read_text())
        record["tool_sha256"] = "0" * 64
        proof.write_text(json.dumps(record))
        with self.assertRaisesRegex(ValueError, "proof changed"):
            self.verify()

    def test_failed_fixed_tool_execution_cannot_create_a_verified_mapping(self):
        self.collision()
        def failed(*args, **kwargs):
            return subprocess.CompletedProcess([], 1, b"", b"failure")
        with self.assertRaisesRegex(ValueError, "relocation failed"):
            helpers.prepare(self.root, [self.classes], self.context, Path("/known/java"), self.folder, {}, failed)


if __name__ == "__main__":
    unittest.main()
