"""Public Python recipes cannot choose commands or replace caller-owned inputs."""

import copy
from dataclasses import replace
import json
import os
from pathlib import Path
import sys
import tempfile
import unittest
from unittest.mock import patch

REPO = Path(__file__).resolve().parents[1]
sys.path[:0] = [str(REPO / "adapters/generation"), str(REPO / "examples")]
import python_prepared as prepared


def fixture(root: Path):
    sdk, project, runtime = root / "sdk", root / "project", root / "runtime"
    for directory in (sdk, project):
        directory.mkdir()
    runtime.mkdir(mode=0o700)
    (project / "entry.py").write_text("raise AssertionError('metadata must not execute the app')\n")
    names = ["otelc/python_supervisor.py", "bin/quux-otelc", "ci/build_python_inputs.py",
             "requirements.txt", "requirements-dev.txt", "python", "policy.toml",
             "build/tools/python-inputs/" + "a" * 64 + "/otelc-python-inputs",
             "build/tools/python-inputs/" + "a" * 64 + "/build.json"]
    for name in names:
        path = sdk / name
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(name)
    intent = prepared.Intent(sdk, project, runtime, Path("entry.py"), sdk, sdk / "python",
                             {"version": "CPython test", "cache_tag": "cpython-test", "argv0": "/actual/framework/python"},
                             {"schema_version": 3}, sdk / "policy.toml", {"LANG": "C", "PYTHONPATH": "", "CREDENTIAL": "excluded"},
                             False, ("--", "-c", "", "\U0001f680"))
    original = prepared.expected_request(intent)
    plan = prepared.expected_plan(original)
    driver = sdk / "build/tools/python-inputs" / ("a" * 64) / "otelc-python-inputs"
    catalogue = {path.relative_to(sdk).as_posix(): prepared.capture.file_digest(path) for path in (driver, driver.parent / "build.json")}
    maintained = [sdk / "bin/quux-otelc", sdk / "otelc/python_supervisor.py", sdk / "ci/build_python_inputs.py",
                  sdk / "requirements.txt", sdk / "requirements-dev.txt"]
    manifest = {"schema_version": 1, "kind": "otelc.python.prepared", "request_sha256": prepared.digest(original),
                "plan_sha256": prepared.digest(plan), "driver": prepared.file_identity(driver),
                "build_manifest": prepared.file_identity(driver.parent / "build.json"),
                "producer": list(map(prepared.file_identity, maintained)),
                "entry": prepared.file_identity((project / "entry.py").resolve(strict=True)), "source_complete": False}
    value = {"schema_version": 1, "kind": "otelc.python.command", "request": original, "plan": plan,
             "prepared": manifest, "command": prepared.expected_command(intent), "source_complete": False}
    for name, document in (("python-request.json", original), ("python-resolved-plan.json", plan), ("python-prepared.json", manifest)):
        path = runtime / name
        path.write_bytes(prepared.encoded(document))
        path.chmod(0o600)
    return intent, value, catalogue


class PythonPreparedTests(unittest.TestCase):
    def test_fixed_recipe_keeps_absent_empty_environment_and_literal_arguments(self):
        with tempfile.TemporaryDirectory() as temporary:
            intent, value, catalogue = fixture(Path(temporary))
            prepared.verify(value, intent, catalogue)
            original = value["request"]
            self.assertIsNone(original["environment"]["PYTHONHOME"])
            self.assertEqual(original["environment"]["PYTHONPATH"], "")
            self.assertNotIn("CREDENTIAL", original["environment"])
            self.assertEqual(value["plan"]["native_arguments"], ["entry.py", "--", "-c", "", "\U0001f680"])
            self.assertEqual(value["command"][1:4], ["-I", "-S", "-B"])
            self.assertFalse(value["source_complete"])

    def test_changed_command_policy_interpreter_lane_and_type_cannot_be_resealed(self):
        with tempfile.TemporaryDirectory() as temporary:
            intent, value, catalogue = fixture(Path(temporary))
            invalid = [None, [], {**value, "extra": 1}, {**value, "schema_version": True},
                       {**value, "source_complete": 0}, {**value, "command": ["arbitrary executable"]},
                       {**value, "prepared": {}}]
            for section, key, candidate in (("request", "plain", True), ("request", "arguments", []),
                                             ("plan", "python", "/other/python"), ("plan", "native_arguments", ["-c", "print(1)"]),
                                             ("prepared", "request_sha256", "f" * 64), ("prepared", "producer", [])):
                changed = copy.deepcopy(value)
                changed[section][key] = candidate
                invalid.append(changed)
            for candidate in invalid:
                with self.subTest(candidate=candidate), self.assertRaises(ValueError):
                    prepared.verify(candidate, intent, catalogue)

    def test_native_product_must_match_fixed_namespace_and_preexisting_catalogue(self):
        with tempfile.TemporaryDirectory() as temporary:
            intent, value, catalogue = fixture(Path(temporary))
            for driver in (None, {"path": "/arbitrary/native"}, {"path": str(intent.provider_root / "build/tools/python-inputs/invalid/otelc-python-inputs")}):
                changed = {**value["prepared"], "driver": driver}
                with self.subTest(driver=driver), self.assertRaises(ValueError):
                    prepared.verify_products(changed, intent, catalogue)
            with self.assertRaisesRegex(ValueError, "frozen inputs"):
                prepared.verify_products(value["prepared"], intent, {})
            changed = {**value["prepared"], "build_manifest": {}}
            with self.assertRaisesRegex(ValueError, "identities differ"):
                prepared.verify_products(changed, intent, catalogue)

    def test_changed_retained_bytes_and_noncanonical_json_refuse(self):
        with tempfile.TemporaryDirectory() as temporary:
            intent, value, catalogue = fixture(Path(temporary))
            path = intent.runtime / "python-request.json"
            path.write_text(json.dumps(value["request"]))
            with self.assertRaisesRegex(ValueError, "prepared file differs"):
                prepared.verify(value, intent, catalogue)
            path.write_bytes(prepared.encoded(value["request"]))
            (intent.project / "entry.py").write_text("changed application")
            with self.assertRaisesRegex(ValueError, "independent intent"):
                prepared.verify(value, intent, catalogue)

    def test_private_files_require_owner_mode_one_link_object_and_bounded_complete_bytes(self):
        with tempfile.TemporaryDirectory() as temporary:
            intent, value, catalogue = fixture(Path(temporary))
            path = intent.runtime / "python-request.json"
            path.chmod(0o644)
            with self.assertRaisesRegex(ValueError, "private Python metadata"):
                prepared.read(path)
            path.chmod(0o600)
            link = path.with_suffix(".pending")
            os.link(path, link)
            with self.assertRaisesRegex(ValueError, "private Python metadata"):
                prepared.read(path)
            link.unlink()
            with patch.object(prepared, "MAX_METADATA", 1), self.assertRaises(ValueError):
                prepared.read(path)
            for raw in (b'[]', b'{"a":1,"a":1}', b'{"a":NaN}'):
                path.write_bytes(raw)
                with self.assertRaises(ValueError):
                    prepared.read(path)
            path.unlink(); path.symlink_to(intent.policy_file)
            with self.assertRaises(OSError):
                prepared.read(path)
            intent.runtime.chmod(0o755)
            with self.assertRaisesRegex(ValueError, "private directory"):
                prepared.verify(value, intent, catalogue)

    def test_invalid_caller_intent_refuses_before_any_launch(self):
        with tempfile.TemporaryDirectory() as temporary:
            intent, _, _ = fixture(Path(temporary))
            outside = Path(temporary) / "outside.py"
            outside.write_text("outside")
            for changed in (replace(intent, plain=1), replace(intent, arguments=("nul\0",)),
                            replace(intent, project=Path("relative")), replace(intent, entry=outside),
                            replace(intent, entry=Path("-option.py")), replace(intent, interpreter={}),
                            replace(intent, interpreter={**intent.interpreter, "argv0": ""})):
                with self.subTest(changed=changed), self.assertRaises(ValueError):
                    prepared.expected_request(changed)
            intent.policy_file.write_bytes(b" " * (1024 * 1024 + 1))
            with self.assertRaisesRegex(ValueError, "policy exceeds"):
                prepared.expected_request(intent)

    def test_interpreter_symlink_identity_is_kept_and_special_files_are_not_read(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            target = root / "real-python"
            target.write_bytes(b"interpreter")
            link = root / "python"
            link.symlink_to(target.name)
            identity = prepared.file_identity(link)
            self.assertEqual(identity["path"], str(link))
            self.assertEqual(identity["resolved_path"], str(target.resolve(strict=True)))
            self.assertEqual(identity["symlink"], target.name)
            fifo = root / "pipe"
            os.mkfifo(fifo)
            with self.assertRaisesRegex(ValueError, "regular file"):
                prepared.file_identity(fifo)
