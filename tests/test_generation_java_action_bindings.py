"""Offline compiler metadata cannot replace independent source/probe expectations."""

import copy
import hashlib
import json
import os
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest
from unittest.mock import patch

REPO = Path(__file__).resolve().parents[1]
sys.path[:0] = [str(REPO / "adapters/generation"), str(REPO / "examples")]
import java_action_bindings as bindings
import java_launch
import java_witness


def declarations():
    return {role: {"owner": "Work", "name": role, "descriptor": "()V" if role == "rendezvous" else "(I)I"}
            for role in bindings.ROLES}


def document(expected, class_sha):
    rows = {}
    for index, (role, value) in enumerate(expected.items(), 1):
        method_sha = str(index) * 64
        fields = [java_witness.PROFILE, role, *(value[key] for key in ("owner", "name", "descriptor")), class_sha, method_sha]
        rows[role] = {**value, "class_sha256": class_sha, "method_sha256": method_sha,
                      "probe_id": hashlib.sha256("\n".join(fields).encode()).hexdigest()}
    return {"schema_version": 2, "kind": "otelc.java-witness-bindings", "profile": java_witness.PROFILE, "bindings": rows}


class JavaActionBindingsTests(unittest.TestCase):
    def setUp(self):
        temporary = tempfile.TemporaryDirectory(dir="/tmp")
        self.addCleanup(temporary.cleanup)
        self.root = Path(temporary.name).resolve();self.root.chmod(0o700)
        self.project, self.sdk, self.build = [self.root / name for name in ("project", "sdk", "build")]
        for path in (self.project, self.sdk, self.build):path.mkdir()
        self.classes = self.build / java_launch.CLASSES;self.classes.mkdir(parents=True)
        product = self.classes / "Work.class";product.write_bytes(b"unit class fixture; actual compiler qualification is separate")
        self.class_sha = hashlib.sha256(product.read_bytes()).hexdigest()
        self.application = {"bindings": {"Work": {"class_sha256": self.class_sha}}}
        (self.build / java_launch.APPLICATION_FILE).write_text(json.dumps(self.application))
        self.tools = {"java": Path(sys.executable)}
        self.expected = declarations()
        self.value = document(self.expected, self.class_sha)

    def test_descriptor_primitives_objects_arrays_returns_and_slot_boundaries(self):
        for value in ("()V", "(I)I", "(BCDFIJSZ)J", "([J[[D)Ljava/lang/Object;", "([Lpkg/Thing$Inner;)Z",
                      "(" + "J" * 127 + "I)V", "(" + "I" * 255 + ")V", "(" + "[" * 255 + "I)V"):
            with self.subTest(value=value):self.assertTrue(bindings.descriptor(value))
        for value in (None, True, 2, "", "()", "(V)V", "(I", "I)V", "(L;)V", "(L/Thing;)V",
                      "(Lpkg//Thing;)V", "(Lpkg.Thing;)V", "(LThing)V", "(Q)V", "([V)V", "()VV",
                      "(I)Vextra", "(I)Q", "(" + "J" * 128 + ")V", "(" + "[" * 256 + "I)V",
                      "(I)\nV", "(" + "I" * bindings.MAX_TEXT + ")V"):
            with self.subTest(value=value):self.assertFalse(bindings.descriptor(value))

    def test_declarations_are_closed_distinct_and_frozen_without_coercion(self):
        result = bindings.declarations(self.expected)
        self.expected["target"]["name"] = "changed"
        self.assertEqual(result["target"]["name"], "target")
        for value in (None, [], {}, {**declarations(), "other": {}}):
            with self.assertRaises(ValueError):bindings.declarations(value)
        for key, value in (("owner", "../Work"), ("owner", "pkg//Work"), ("owner", "pkg\\Work"),
                           ("name", "<init>"), ("name", "target/other"), ("name", 1), ("descriptor", "bad")):
            changed = declarations();changed["target"][key] = value
            with self.subTest(key=key), self.assertRaises(ValueError):bindings.declarations(changed)
        for change in (None, {**declarations()["target"], "extra": 1}):
            changed = declarations();changed["target"] = change
            with self.assertRaises(ValueError):bindings.declarations(changed)
        changed = declarations();changed["target"] = changed["wrapper"].copy()
        with self.assertRaises(ValueError):bindings.declarations(changed)
        changed = declarations();changed["rendezvous"]["descriptor"] = "()I"
        with self.assertRaises(ValueError):bindings.declarations(changed)
        with patch.object(bindings, "MAX_BINDINGS", 1), self.assertRaises(ValueError):bindings.declarations(declarations())

    def test_binding_document_requires_the_explicit_version_and_all_exact_roles(self):
        self.assertEqual(bindings.verify(self.value, self.expected, self.application, self.classes), self.value)
        for key, value in (("schema_version", 1), ("schema_version", True), ("schema_version", "2"),
                           ("kind", "other"), ("profile", "java-sync-private-handle-v1"), ("bindings", {})):
            changed = copy.deepcopy(self.value);changed[key] = value
            with self.subTest(key=key), self.assertRaises(ValueError):bindings.verify(changed, self.expected, self.application, self.classes)
        for changed in (None, {**self.value, "extra": 1}):
            with self.assertRaises(ValueError):bindings.verify(changed, self.expected, self.application, self.classes)

    def test_each_declaration_hash_source_binding_and_probe_must_match(self):
        for key in bindings.BINDING_FIELDS:
            for value in ("different", None, True):
                changed = copy.deepcopy(self.value);changed["bindings"]["target"][key] = value
                with self.subTest(key=key, value=value), self.assertRaises(ValueError):
                    bindings.verify(changed, self.expected, self.application, self.classes)
        for value in (None, {**self.value["bindings"]["target"], "extra": 1}):
            changed = copy.deepcopy(self.value);changed["bindings"]["target"] = value
            with self.assertRaises(ValueError):bindings.verify(changed, self.expected, self.application, self.classes)
        for application in ({}, {"bindings": []}, {"bindings": {}}, {"bindings": {"Work": None}},
                            {"bindings": {"Work": {"class_sha256": "0" * 64}}}):
            with self.assertRaises(ValueError):bindings.verify(self.value, self.expected, application, self.classes)
        (self.classes / "Work.class").write_bytes(b"different original class")
        with self.assertRaises(ValueError):bindings.verify(self.value, self.expected, self.application, self.classes)

    def test_invalid_python_objects_are_refused_without_equality_callbacks(self):
        class Callback:
            def __eq__(self, other):raise AssertionError("application equality ran")
        changed = copy.deepcopy(self.value);changed["bindings"]["target"]["name"] = Callback()
        with self.assertRaises(ValueError):bindings.verify(changed, self.expected, self.application, self.classes)

    def test_shared_private_reader_refuses_paths_budgets_links_and_permissions(self):
        path = self.root / "bindings.json";path.write_text('{"valid":true}');path.chmod(0o600)
        self.assertEqual(java_witness.read_private(self.root, path.name, 100), {"valid": True})
        for name in ("", ".", "..", "../bindings.json", "/bindings.json", "bad\x00name", None):
            with self.assertRaises(ValueError):java_witness.read_private(self.root, name, 100)
        for maximum in (0, -1, True, None, java_witness.MAX_FINAL + 1, 1):
            with self.assertRaises(ValueError):java_witness.read_private(self.root, path.name, maximum)
        other = self.root / "alias.json";os.link(path, other)
        with self.assertRaises(ValueError):java_witness.read_private(self.root, path.name, 100)
        other.unlink();path.chmod(0o644)
        with self.assertRaises(ValueError):java_witness.read_private(self.root, path.name, 100)

    def compile(self, callback=None, *, source_inputs=None, folder=None, audits=2):
        destination = folder or self.root / "bindings"
        def execute(command, cwd, environment, output, **options):
            self.assertEqual(command[:7], [sys.executable, "-I", "-S", "-B", "-c", bindings.COMPILER, str(self.sdk)])
            self.assertEqual(cwd, self.sdk)
            self.assertEqual(options, {"max_output_bytes": bindings.MAX_BINDINGS})
            self.assertEqual(environment["OTELC_JAVA"], str(self.tools["java"].resolve(strict=True)))
            request = Path(command[-2]);target = Path(command[-1])
            self.assertEqual(request.stat().st_mode & 0o777, 0o600)
            target.write_text(json.dumps(self.value));target.chmod(0o600)
            result = subprocess.CompletedProcess(command, 0, json.dumps(self.value).encode(), b"")
            return callback(request, target, result) if callback else result
        with patch.object(bindings.java_build, "verify") as verify_build, \
                patch.object(bindings, "inputs", side_effect=source_inputs or [{"source": "a"}, {"source": "a"}]):
            try:
                return bindings.compile(self.sdk, self.project, self.build, destination, self.tools,
                                        self.expected, {"PYTHONDONTWRITEBYTECODE": "1"}, execute)
            finally:
                self.assertEqual(verify_build.call_args_list,
                                 [unittest.mock.call(self.project, self.classes, self.build)] * audits)

    def test_public_offline_bridge_retains_argv_inputs_and_matching_private_output(self):
        self.assertEqual(self.compile(), self.value)
        record = json.loads((self.root / "bindings/compiler-inputs.json").read_text())
        self.assertEqual(record["profile"], java_witness.PROFILE)
        self.assertEqual(record["bindings_sha256"], hashlib.sha256((self.root / "bindings/bindings.json").read_bytes()).hexdigest())
        self.assertEqual(record["sdk_inputs_sha256"], {"source": "a"})

    def test_offline_failures_changed_inputs_and_disagreeing_response_refuse(self):
        def failed(request, target, result):result.returncode = 1;return result
        def changed_request(request, target, result):request.write_text('{}');return result
        def different_reply(request, target, result):result.stdout = b'{}';return result
        def unsafe_output(request, target, result):target.chmod(0o644);return result
        for index, callback in enumerate((failed, changed_request, different_reply, unsafe_output)):
            with self.subTest(index=index), self.assertRaises(ValueError):
                self.compile(callback, folder=self.root / str(index))
        with self.assertRaises(ValueError):self.compile(source_inputs=[{"source": "a"}, {"source": "b"}])

    def test_outputs_cannot_enter_application_or_provider_sources(self):
        for folder in (self.project / "bindings", self.sdk / "bindings"):
            with self.assertRaises(ValueError):self.compile(folder=folder, audits=0)
            self.assertFalse(folder.exists())

    def test_execution_errors_and_cancellation_preserve_the_primary_exception_and_audit_inputs(self):
        for index, error in enumerate((ValueError("tool deadline"), KeyboardInterrupt("cancelled"))):
            def failed(request, target, result):raise error
            with self.assertRaises(type(error)) as caught:
                self.compile(failed, folder=self.root / str(index))
            self.assertIs(caught.exception, error)
            self.assertFalse((self.root / str(index) / "compiler-inputs.json").exists())

    def test_cancellation_retains_a_failed_input_audit_as_a_note(self):
        error = KeyboardInterrupt("cancelled")
        def failed(request, target, result):raise error
        with self.assertRaises(KeyboardInterrupt) as caught:
            self.compile(failed, source_inputs=[{"source": "before"}, {"source": "after"}])
        self.assertIs(caught.exception, error)
        self.assertTrue(any("offline compiler inputs changed" in note for note in error.__notes__))

    def test_offline_helper_must_be_an_actual_separately_frozen_regular_product(self):
        helper = self.sdk / bindings.java_provider.HELPER;helper.parent.mkdir(parents=True)
        modules = self.root / "jdk-modules";modules.write_bytes(b"unit JDK module image")
        with patch.object(bindings.java_provider, "artefacts", return_value={"source": "sha"}), \
                patch.object(bindings.java_build, "module_image", return_value=modules):
            with self.assertRaises(ValueError):bindings.inputs(self.sdk, self.tools)
            original = self.root / "helper.jar";original.write_bytes(b"helper")
            helper.symlink_to(original)
            with self.assertRaises(ValueError):bindings.inputs(self.sdk, self.tools)
            helper.unlink();helper.write_bytes(b"helper")
            value = bindings.inputs(self.sdk, self.tools)
            self.assertEqual(value[bindings.java_provider.HELPER], hashlib.sha256(b"helper").hexdigest())
            self.assertEqual(len(value["tool:python"]), 64)
            self.assertEqual(value["tool:jdk-modules"], hashlib.sha256(modules.read_bytes()).hexdigest())


if __name__ == "__main__":
    unittest.main()
