"""Source-build4 readers preserve caller inputs and never execute saved commands."""

import copy
from dataclasses import replace
import json
import os
from pathlib import Path
import shutil
import sys
import tempfile
import unittest
from unittest.mock import patch

REPO = Path(__file__).resolve().parents[1]
sys.path[:0] = [str(REPO / "adapters/generation"), str(REPO / "examples")]
import go_build as build
import go_files as files
from go_provider import selection_digest


def write(path: Path, value) -> None:
    path.write_text(json.dumps(value, sort_keys=True, indent=2) + "\n")


def fixture(base: Path) -> tuple:
    """Literal compiler/selection fields; the fixture runs no target or tool."""
    original, sdk, context, output, tools = [base / name for name in ("application", "installed-sdk", "qualified-context", "bundle", "tools")]
    for path in (original, sdk, context, output, tools):
        path.mkdir()
    (original / "go.mod").write_text("module example.test/app\n\ngo 1.26.0\n")
    (original / "app.go").write_text("package main\nfunc Add(value int)int{return value+1}\nfunc main(){Add(1)}\n")
    (sdk / "go.mod").write_text("module io.quux.otelc/go\n")
    (sdk / "runtime.go").write_text("package runtime\n")
    (context / "context.go").write_text("package context\n")
    identities = {}
    for name in ("go", "weaver", "bundle"):
        path = tools / name; path.write_bytes(("fixed-" + name).encode())
        identities[name] = str(path); identities[name + "_sha256"] = files.identity(path)["sha256"]
    for source, name in ((original, "private"), (sdk, "sdk"), (context, "context")):
        shutil.copytree(source, output / name)
    (output / "inspection").mkdir()
    for name in ("plain", "instrumented"):
        path = output / name; path.write_bytes(("fixed-" + name).encode()); path.chmod(0o700)
    row = {"file": "app.go", "gap": "", "generic": False, "line": 2,
        "name": "example.test/app.Add", "package": "example.test/app", "parameters": 1,
        "receiver": "", "receiver_id": "", "results": [
            {"error": False, "expression": "_unnamedRetVal0", "failure": "", "pointer": ""}],
        "sha256": files.identity(original / "app.go")["sha256"], "symbol": "Add", "variadic": False}
    main = {**row, "name": "example.test/app.main", "line": 3, "symbol": "main", "parameters": 0, "results": []}
    inventory = {"schema_version": 1, "root": str(original), "target": ".", "main": "example.test/app",
        "functions": [copy.deepcopy(row), main], "types": [], "allocations": [],
        "files": {"app.go": row["sha256"]}, "packages": {"example.test/app": {"name": "main", "directory": "."}},
        "compiler_inputs": {"app.go": row["sha256"]}}
    selection = {"schema_version": 1, "kind": "otelc.go-source-selection", "main": "example.test/app",
        "functions": [copy.deepcopy(row)], "types": [], "allocations": [], "releases": [],
        "context": {"tasks": False, "http": False}, "source_complete": False}
    selection["sha256"] = selection_digest(selection)
    golden = json.loads((REPO / "tests/fixtures/go-source-hooks.json").read_text())
    assert golden["selection_sha256"] == selection["sha256"]
    for name, text in golden["files"].items():
        path = output / "private" / name
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(text)
    (output / "private/go.sum").write_bytes(b"")
    settings = {"Go": "1.26.0", "Module": {"Path": "example.test/app"}}
    modules = [{"Path": "example.test/app", "Main": True, "GoVersion": "1.26.0"}]
    intent = build.Intent(output, files.freeze(original), files.freeze(sdk), ".",
        (build.Target("example.test/app.Add", "app.go", 2, 1),), identities, settings, modules, files.freeze(context))
    commands = build.commands(intent)
    write(output / "commands.json", commands)
    for index in range(len(commands)):
        (output / f"command-{index}.stdout").write_bytes(b"compiler channel\n")
        (output / f"command-{index}.stderr").write_bytes(b"")
    write(output / "command-10.stdout", settings)
    write(output / "inspection/inventory.json", inventory)
    receipt = {"schema_version": 4, "kind": "otelc.go-source-build", "root": str(original), "target": ".",
        "runtime_protocols": {"config": 2, "health": 4},
        "selection": selection, "inputs": intent.original.identities,
        "sdk_inputs": files.freeze(output / "sdk").identities,
        "private_inputs": files.freeze(output / "private").identities,
        "context_inputs": files.freeze(output / "context").identities,
        "inventory": files.identity(output / "inspection/inventory.json"),
        "plain": files.identity(output / "plain"), "instrumented": files.identity(output / "instrumented"),
        "modules_before": modules, "modules_after": copy.deepcopy(modules), "settings": settings,
        "toolchain": identities, "commands": commands, "source_complete": False,
        "launch_inputs": intent.original.identities, "source_roster": ["app.go"]}
    write(output / "build.json", receipt)
    return intent, copy.deepcopy(receipt), inventory


class GoSourceBuildTests(unittest.TestCase):
    def setUp(self):
        self.temporary = tempfile.TemporaryDirectory()
        self.addCleanup(self.temporary.cleanup)
        self.base = Path(self.temporary.name).resolve()
        self.intent, self.receipt, self.inventory = fixture(self.base)

    def publish(self):
        write(self.intent.directory / "build.json", self.receipt)

    def inventory_change(self):
        write(self.intent.directory / "inspection/inventory.json", self.inventory)
        self.receipt["inventory"] = files.identity(self.intent.directory / "inspection/inventory.json")
        self.publish()

    def tagged(self):
        """Extend the literal fixture independently with the explicit build-5 fields."""
        self.intent = replace(self.intent, build_tags=("feature", "tools", "\u03c0"))
        self.inventory.update(schema_version=2, build_tags=["feature", "tools", "\u03c0"])
        pin = self.intent.directory / "private/otel.instrumentation.go"
        pin.write_text(pin.read_text().replace("//go:build tools\n", "//go:build !feature\n", 1))
        self.receipt.update(schema_version=5, build_tags=["feature", "tools", "\u03c0"],
                            private_inputs=files.freeze(self.intent.directory / "private").identities)
        commands = copy.deepcopy(self.receipt["commands"])
        for row in commands[-2:]:
            position = row["argv"].index("-mod=readonly") + 1
            row["argv"].insert(position, "-tags=feature,tools,\u03c0")
        self.receipt["commands"] = commands
        write(self.intent.directory / "commands.json", commands)
        self.receipt["command_evidence"] = {name: files.identity(self.intent.directory / name) for name in
            ["commands.json", *[f"command-{index}.{suffix}" for index in range(len(commands))
                               for suffix in ("stdout", "stderr")]]}
        self.inventory_change()

    def test_tagged_profile_binds_unicode_tags_inventory_fixed_flags_and_private_pin(self):
        self.tagged()
        with patch("subprocess.run", side_effect=AssertionError("reader executed a compiler")), \
                patch("subprocess.Popen", side_effect=AssertionError("reader launched a target")):
            actual = build.read(self.intent)
            actual.verify()
        self.assertEqual(actual.receipt["schema_version"], 5)
        self.assertEqual(actual.inventory["schema_version"], 2)
        for row in build.commands(self.intent)[-2:]:
            self.assertEqual([arg for arg in row["argv"] if arg.startswith("-tags=")],
                             ["-tags=feature,tools,\u03c0"])
        with self.assertRaises(ValueError):
            build.read(replace(self.intent, build_tags=()))
        for tags in (["feature"], ("tools", "feature"), ("x", "x"), ("-race",)):
            with self.subTest(tags=tags), self.assertRaises(ValueError):
                build.validate_intent(replace(self.intent, build_tags=tags))

    def test_tagged_receipt_and_active_inventory_cannot_substitute_the_request(self):
        self.tagged()
        original = copy.deepcopy(self.receipt)
        for key, value in (("schema_version", 4), ("schema_version", True), ("build_tags", []),
                           ("build_tags", ["tools", "feature", "\u03c0"]),
                           ("build_tags", ["feature"]), ("command_evidence", {})):
            self.receipt = {**original, key: value}
            self.publish()
            with self.subTest(key=key), self.assertRaises(ValueError):
                build.read(self.intent)
        self.receipt = original
        for key, value in (("schema_version", 1), ("build_tags", ["tools"]), ("build_tags", None)):
            saved = copy.deepcopy(self.inventory)
            self.inventory[key] = value
            self.inventory_change()
            with self.subTest(key=key), self.assertRaises(ValueError):
                build.read(self.intent)
            self.inventory = saved
        self.inventory_change()
        build.read(self.intent).verify()

    def test_tagged_log_seals_and_rehashed_wrong_recipe_or_pin_refuse(self):
        self.tagged()
        checked = build.read(self.intent)
        log = self.intent.directory / "command-0.stderr"
        log.write_bytes(b"changed compiler diagnostic")
        with self.assertRaisesRegex(ValueError, "compiler evidence differs"):
            build.read(self.intent)
        with self.assertRaisesRegex(ValueError, "compiler evidence changed"):
            checked.verify()
        log.write_bytes(b"")
        commands = copy.deepcopy(self.receipt["commands"])
        commands[-1]["argv"].remove("-tags=feature,tools,\u03c0")
        self.receipt["commands"] = commands
        write(self.intent.directory / "commands.json", commands)
        self.receipt["command_evidence"]["commands.json"] = files.identity(self.intent.directory / "commands.json")
        self.publish()
        with self.assertRaisesRegex(ValueError, "command recipe differs"):
            build.read(self.intent)
        self.receipt["commands"] = build.commands(self.intent)
        write(self.intent.directory / "commands.json", self.receipt["commands"])
        self.receipt["command_evidence"]["commands.json"] = files.identity(self.intent.directory / "commands.json")
        pin = self.intent.directory / "private/otel.instrumentation.go"
        pin.write_text(pin.read_text().replace("//go:build !feature\n", "//go:build tools\n", 1))
        self.receipt["private_inputs"] = files.freeze(self.intent.directory / "private").identities
        self.publish()
        with self.assertRaisesRegex(ValueError, "helper differs"):
            build.read(self.intent)

    def test_complete_build_is_bound_without_compiler_or_target_execution(self):
        with patch("subprocess.run", side_effect=AssertionError("reader executed a command")), \
                patch("subprocess.Popen", side_effect=AssertionError("reader started a target")):
            actual = build.read(self.intent)
            actual.verify()
        self.assertEqual(len(actual.evidence), 35)
        self.assertEqual(actual.receipt["selection"]["functions"][0]["name"], "example.test/app.Add")

    def test_malformed_identity_tool_or_command_cannot_select_another_program(self):
        original = copy.deepcopy(self.receipt)
        for key, value in (("schema_version", True), ("schema_version", 2), ("schema_version", 3), ("kind", "legacy"),
                ("runtime_protocols", {"config": 1, "health": 3}), ("runtime_protocols", {"config": 2.0, "health": 4}),
                ("root", "/another"), ("target", "./other"), ("source_complete", 0),
                ("toolchain", {**self.intent.toolchain, "go": "/never-read-or-executed"}),
                ("plain", {**original["plain"], "size": True})):
            self.receipt = {**original, key: value}; self.publish()
            with self.subTest(key=key), self.assertRaises(ValueError):
                build.read(self.intent)
        self.receipt = copy.deepcopy(original); self.receipt["commands"][0]["argv"][0] = "/never-executed"; self.publish()
        with self.assertRaises(ValueError):
            build.read(self.intent)

    def test_command_log_and_compiler_output_are_preserved_after_acceptance(self):
        for name in ("commands.json", "command-0.stdout", "command-1.stderr"):
            actual = build.read(self.intent)
            path = self.intent.directory / name; original = path.read_bytes()
            path.write_bytes(original + b"changed")
            with self.subTest(name=name), self.assertRaisesRegex(ValueError, "compiler evidence changed: " + name):
                actual.verify()
            path.write_bytes(original)
        build.read(self.intent).verify()

    def test_missing_extra_or_changed_source_inventory_refuses(self):
        original = copy.deepcopy(self.inventory)
        for change in ("main", "empty", "hash", "line", "file", "duplicate", "extra"):
            self.inventory = copy.deepcopy(original)
            if change == "main": self.inventory["main"] = "another/module"
            elif change == "empty": self.inventory["compiler_inputs"] = {}
            elif change == "hash": self.inventory["files"]["app.go"] = "f" * 64
            elif change == "line": self.inventory["functions"][0]["line"] = True
            elif change == "file": self.inventory["functions"][0]["file"] = []
            elif change == "duplicate": self.inventory["functions"].append(self.inventory["functions"][0])
            else: self.inventory["unknown"] = 0
            self.inventory_change()
            with self.subTest(change=change), self.assertRaises(ValueError):
                build.read(self.intent)

    def test_rehashed_selection_cannot_change_caller_owned_declaration(self):
        original = copy.deepcopy(self.receipt["selection"])
        for key, value in (("name", "example.test/app.Other"), ("line", 2.0), ("parameters", True),
                           ("generic", True), ("variadic", True), ("gap", "unsupported")):
            selected = copy.deepcopy(original); selected["functions"][0][key] = value
            selected["sha256"] = selection_digest({k: v for k, v in selected.items() if k != "sha256"})
            self.receipt["selection"] = selected; self.publish()
            with self.subTest(key=key), self.assertRaises(ValueError):
                build.read(self.intent)

    def test_rehashed_sdk_context_or_program_copy_still_requires_expected_bytes(self):
        receipt = copy.deepcopy(self.receipt)
        for directory, name in (("sdk", "runtime.go"), ("context", "context.go"), ("private", "app.go")):
            self.receipt = copy.deepcopy(receipt)
            self.publish()
            build.read(self.intent).verify()
            path = self.intent.directory / directory / name; original = path.read_bytes()
            path.write_bytes(original + b"changed")
            self.receipt[directory + "_inputs"] = files.freeze(path.parent).identities; self.publish()
            reason = {"sdk": "private SDK differs", "context": "context differs", "private": "changed original program data"}[directory]
            with self.subTest(directory=directory), self.assertRaisesRegex(ValueError, reason):
                build.read(self.intent)
            path.write_bytes(original)
        self.receipt = receipt
        self.publish()
        build.read(self.intent).verify()

    def test_existing_module_and_language_settings_cannot_change(self):
        original = copy.deepcopy(self.receipt)
        for key in ("modules_before", "modules_after", "settings"):
            self.receipt = copy.deepcopy(original)
            if key == "settings": self.receipt[key]["Go"] = "1.27.0"
            else: self.receipt[key][0]["Main"] = 1
            self.publish()
            with self.subTest(key=key), self.assertRaises(ValueError):
                build.read(self.intent)
        self.receipt = original; self.publish()
        write(self.intent.directory / "command-10.stdout", {**self.intent.settings, "Go": "1.27.0"})
        with self.assertRaises(ValueError):
            build.read(self.intent)
        for graph in ([], [{"Path": "x"}, {"Path": "x"}], [None]):
            with self.assertRaises(ValueError):
                build.module_graph(graph)

    def test_touched_original_binary_and_malformed_caller_intent_refuse(self):
        actual = build.read(self.intent)
        path = self.intent.original.root / "app.go"; original = path.stat()
        os.utime(path, ns=(original.st_atime_ns, original.st_mtime_ns + 1_000_000))
        with self.assertRaises(ValueError):
            actual.verify()
        for invalid in (replace(self.intent, target="-C"), replace(self.intent, targets=()),
                        replace(self.intent, targets=(build.Target("x", "app.go", True, 1),))):
            with self.assertRaises(ValueError):
                build.validate_intent(invalid)

    def test_package_target_syntax_remains_canonical_and_is_not_a_suffix_match(self):
        for target in (".", "./worker", "./one/two"):
            with self.subTest(target=target):
                build.validate_target(target)
        for target in (None, True, 1, "", "worker", "../worker", "./", "./.", "./one/..", "./one//two"):
            with self.subTest(target=target), self.assertRaises(ValueError):
                build.validate_target(target)

    def test_accepted_build_and_caller_dictionaries_cannot_change_in_memory(self):
        actual = build.read(self.intent)
        cases = ((actual.receipt["selection"], "main", "another/module"),
                 (actual.inventory, "main", "another/module"), (actual.identity, "size", 1),
                 (self.intent.toolchain, "go", "/changed/compiler"), (self.intent.settings, "Go", "1.27.0"),
                 (self.intent.modules[0], "Main", 1), (actual.evidence, "../escape", ({}, ())))
        for target, key, value in cases:
            original = copy.deepcopy(target)
            target[key] = value
            with self.subTest(key=key), self.assertRaisesRegex(ValueError, "build metadata changed"):
                actual.verify()
            target.clear(); target.update(original)
            actual.verify()

    def test_caller_changes_before_build_sealing_cannot_become_the_new_expectation(self):
        freeze = files.freeze
        changed = False
        def mutate(path):
            nonlocal changed
            result = freeze(path)
            if not changed and path == self.intent.directory / "context":
                changed = True
                self.intent.settings["Go"] = "1.27.0"
            return result
        with patch.object(files, "freeze", side_effect=mutate), self.assertRaisesRegex(ValueError, "build metadata changed"):
            build.read(self.intent)


if __name__ == "__main__":
    unittest.main()
