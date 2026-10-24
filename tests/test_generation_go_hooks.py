"""Literal helper bytes and altered private trees check the independent recipe."""

import copy
import json
from pathlib import Path
import sys
import tempfile
import unittest
from unittest.mock import patch

REPO = Path(__file__).resolve().parents[1]
sys.path[:0] = [str(REPO / "adapters/generation"), str(REPO / "examples")]
import go_build as build
import go_files as files
import go_hooks as hooks
from test_generation_go_source_build import fixture, write


class GoHookTests(unittest.TestCase):
    def setUp(self):
        self.temporary = tempfile.TemporaryDirectory()
        self.addCleanup(self.temporary.cleanup)
        self.intent, self.receipt, self.inventory = fixture(Path(self.temporary.name).resolve())
        self.selection = self.receipt["selection"]

    def render(self):
        return hooks.generated(self.selection, self.inventory, "example.test/app")

    def publish_private(self):
        self.receipt["private_inputs"] = files.freeze(self.intent.directory / "private").identities
        write(self.intent.directory / "build.json", self.receipt)

    def test_exact_literal_recipe_accepts_without_importing_sdk_or_executing_tools(self):
        golden = json.loads((REPO / "tests/fixtures/go-source-hooks.json").read_text())
        with patch("subprocess.run", side_effect=AssertionError("reader executed a tool")), \
                patch("subprocess.Popen", side_effect=AssertionError("reader launched application")):
            self.assertEqual(self.render(), {name: text.encode() for name, text in golden["files"].items()})
            build.read(self.intent).verify()

    def test_main_can_be_selected_and_keeps_shutdown_before_its_own_call_hook(self):
        self.selection["functions"] = [self.inventory["functions"][1], self.inventory["functions"][0]]
        rules = self.render()["otelc_rules/otelc.yaml"].decode()
        prefix = "__otelc_" + self.selection["sha256"][:12] + "_"
        self.assertIn(prefix + "Runtime.Probes", next(text.decode() for name, text in self.render().items() if name.startswith("zz_")))
        self.assertIn("Runtime.Probes.Start(1)", rules)
        self.assertIn("Runtime.Close()\n          " + prefix + "Invocation := " + prefix + "Runtime.Probes.Start(0)", rules)

    def test_unselected_declarations_cannot_add_an_unrequested_hook(self):
        expected = self.render()
        self.inventory["functions"].append({**self.inventory["functions"][0],
                                            "name": "example.test/app.Other", "symbol": "Other"})
        self.assertEqual(self.render(), expected)

    def test_imported_receiver_package_gets_its_own_fixed_helper_and_receiver_rule(self):
        receiver = {**self.inventory["functions"][0], "name": "example.test/app/worker.Thing.Step",
                    "package": "example.test/app/worker", "file": "worker/call.go", "symbol": "Step", "receiver_id": "*Thing"}
        self.inventory["functions"][0] = receiver
        self.inventory["packages"]["example.test/app/worker"] = {"name": "worker", "directory": "worker"}
        self.selection["functions"] = [receiver]
        actual = self.render()
        self.assertEqual(len(actual), 5)
        self.assertTrue(next(text for name, text in actual.items() if name.startswith("worker/zz_")).startswith(b"package worker\n"))
        self.assertIn(b'  target: "example.test/app/worker"\n  where:\n    func: "Step"\n    recv: "*Thing"\n', actual["otelc_rules/otelc.yaml"])

    def test_only_closed_error_predicates_and_go_identifiers_can_enter_source(self):
        rows = [{"expression": "err", "error": True, "failure": "err != nil", "pointer": ""},
                {"expression": "other", "error": True, "failure": "true", "pointer": ""}]
        self.assertEqual(hooks.failure(rows), "err != nil || true")
        self.assertEqual(hooks.failure([]), "false")
        self.inventory["functions"][0]["results"] = rows
        self.assertIn(b"Invocation.End(err != nil || true)", self.render()["otelc_rules/otelc.yaml"])
        for value in ("", "_", "func", "9name", "x²", "x;panic()", "x\nother", None, False):
            self.assertFalse(hooks.identifier(value), value)
        for value in ("_named", "Field2", "Πράγμα", "x٣"):
            self.assertTrue(hooks.identifier(value), value)
        invalid = [None, {}, [None], [{**rows[0], "expression": "x);panic()"}],
                   [{**rows[0], "error": 1}], [{**rows[0], "pointer": False}],
                   [{**rows[0], "failure": "panic()"}], [{**rows[0], "error": False}],
                   [rows[0], rows[0]], [{**rows[0], "unknown": 1}]]
        for value in invalid:
            with self.subTest(value=value), self.assertRaises(ValueError):
                hooks.failure(value)

    def test_wrong_profile_digest_and_package_metadata_refuse(self):
        original_selection, original_inventory = copy.deepcopy(self.selection), copy.deepcopy(self.inventory)
        for key, value in (("context", {"tasks": 0, "http": False}), ("allocations", [{}]),
                           ("sha256", False), ("sha256", "x" * 64), ("sha256", "a")):
            self.selection = {**original_selection, key: value}
            with self.subTest(key=key), self.assertRaises(ValueError):
                self.render()
        self.selection = original_selection
        for value in ({}, [], {"elsewhere": {"name": "main", "directory": "."}},
                      {"example.test/app": {"name": "main;panic()", "directory": "."}},
                      {"example.test/app": {"name": "main", "directory": "../outside"}},
                      {"example.test/app": {"name": "main", "directory": ".", "unknown": 1}}):
            self.inventory = {**original_inventory, "packages": value}
            with self.subTest(packages=value), self.assertRaises(ValueError):
                self.render()

    def test_missing_repeated_or_invalid_main_shutdown_binding_refuses(self):
        original = copy.deepcopy(self.inventory)
        changes = ([original["functions"][0]], original["functions"] + [original["functions"][1]],
                   [original["functions"][0], {**original["functions"][1], "parameters": False}])
        for rows in changes:
            self.inventory = {**original, "functions": rows}
            with self.subTest(rows=rows), self.assertRaises(ValueError):
                self.render()

    def test_invalid_callable_package_directory_receiver_or_name_refuses(self):
        original = copy.deepcopy(self.inventory["functions"][0])
        for key, value in (("package", []), ("symbol", "Add;panic()"), ("file", "worker/app.go"),
                           ("receiver_id", "**Thing"), ("name", "example.test/app.Other")):
            row = {**original, key: value}
            self.inventory["functions"][0] = row
            self.selection["functions"] = [row]
            with self.subTest(key=key), self.assertRaises(ValueError):
                self.render()

    def test_rehashed_changed_helper_or_rule_still_refuses(self):
        private = self.intent.directory / "private"
        for name in self.render():
            path = private / name
            original = path.read_bytes()
            path.write_bytes(original + b"altered generated source\n")
            self.publish_private()
            with self.subTest(name=name), self.assertRaisesRegex(ValueError, "independent recipe"):
                build.read(self.intent)
            path.write_bytes(original)
            self.publish_private()
        build.read(self.intent).verify()

    def test_rehashed_missing_helper_or_added_private_source_refuses(self):
        private = self.intent.directory / "private"
        helper = next(private.glob("zz_*.go"))
        data = helper.read_bytes()
        helper.unlink()
        self.publish_private()
        with self.assertRaisesRegex(ValueError, "file denominator"):
            build.read(self.intent)
        helper.write_bytes(data)
        extra = private / "hidden.go"
        extra.write_text("package main\nfunc init(){panic(1)}\n")
        self.publish_private()
        with self.assertRaisesRegex(ValueError, "file denominator"):
            build.read(self.intent)

    def test_reserved_path_and_source_identifier_collisions_refuse(self):
        private = files.freeze(self.intent.directory / "private")
        for name in ("otelc_rules", "otel.instrumentation.go", "otelc.tool.go", next(name for name in self.render() if name.startswith("zz_"))):
            path = self.intent.original.root / name
            path.mkdir() if name == "otelc_rules" else path.write_bytes(b"collision")
            with self.subTest(name=name), self.assertRaisesRegex(ValueError, "collide"):
                hooks.verify(files.freeze(self.intent.original.root), private, self.selection, self.inventory, "example.test/app")
            path.rmdir() if path.is_dir() else path.unlink()
        path = self.intent.original.root / "app.go"
        path.write_text(path.read_text() + "// __otelc_" + self.selection["sha256"][:12] + "_\n")
        with self.assertRaisesRegex(ValueError, "identifier collides"):
            hooks.verify(files.freeze(self.intent.original.root), private, self.selection, self.inventory, "example.test/app")


if __name__ == "__main__":
    unittest.main()
