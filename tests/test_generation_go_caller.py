"""Actual compiler-only binding of generated mains, libraries and receivers."""

import argparse
from dataclasses import replace
import json
import os
from pathlib import Path
import shutil
import subprocess
import sys
import tempfile
import unittest
from unittest.mock import patch

REPO = Path(__file__).resolve().parents[1]
sys.path[:0] = [str(REPO / "adapters/generation"), str(REPO / "examples")]
import generation
import go_caller
import go_files
import go_project
import go_receivers
import harness
import policy
from test_generation_go_source_build import fixture
import go_build


class GoCallerTests(unittest.TestCase):
    def setUp(self):
        temporary = tempfile.TemporaryDirectory(prefix="oteleq-go-caller-")
        self.addCleanup(temporary.cleanup)
        self.root = Path(temporary.name).resolve()
        self.project = self.root / "application"
        self.project.mkdir()
        (self.project / "go.mod").write_text("module example.test/caller\n\ngo 1.26.0\n")
        self.go = Path(os.environ.get("OTELC_GO") or shutil.which("go")).resolve()
        self.options = go_project.settings({"module_roots": ["."]})
        self.environment = {**os.environ, **go_project.environment(self.options),
                            "GOTOOLCHAIN": "local", "GOCACHE": str(REPO / "build/go-caller-cache")}

    def execute(self, argv, cwd, env=None, *, input_data=None, max_output_bytes=None):
        result = subprocess.run(argv, cwd=cwd, env=env or self.environment, input=input_data,
                                capture_output=True, timeout=90)
        self.assertLessEqual(len(result.stdout), max_output_bytes or go_files.MAX_METADATA_BYTES)
        return result

    def materialise(self, text, *, path="main.go", name="Add", receiver=False):
        source = self.project / path
        source.parent.mkdir(parents=True, exist_ok=True)
        source.write_text(text)
        discovered = go_project.discover(source, self.project, self.options, self.go, self.execute, {})
        discovered["entrypoints"] = [item for item in discovered["functions"] if item.get("entrypoint")]
        row = next(row for row in discovered["functions"] if row["name"] == name)
        args = argparse.Namespace(configuration=policy.validate({"adapters": {"go": self.options}}), cases=1)
        entry = generation.inventory_entry(row, discovered, path, "go", "a" * 64, self.project, args)
        entry["go_backend"] = "source-v1"
        if receiver:
            go_receivers.bind(entry, discovered, {"factory": "New", "arguments": [20]}, harness.concrete_arguments)
        harness.materialise(self.project, entry, [1])
        return entry

    def discover(self, entry, execute=None):
        return go_caller.discover(go_files.freeze(self.project), entry, self.go,
                                  self.environment, execute or self.execute)

    def test_generated_main_rebinds_line_without_running_initialisers(self):
        sentinel = self.root / "initialiser-ran"
        entry = self.materialise('package main\nimport "os"\nvar Total int\n'
                                 'func init(){os.WriteFile(' + json.dumps(str(sentinel)) + ',nil,0600)}\n'
                                 'func Add(value int)int{Total+=value;return Total+1}\nfunc main(){}\n')
        caller = self.discover(entry)
        self.assertEqual(caller.target, ".")
        self.assertEqual(caller.targets[0].name, "example.test/caller.Add")
        self.assertNotEqual(caller.targets[0].line, entry["line"])
        self.assertEqual(caller.targets[0].parameters, 1)
        self.assertEqual(caller.targets[0].receiver_id, "")
        self.assertIn("zz_oteleq_rendezvous.go", caller.compiler_inputs)
        self.assertFalse(sentinel.exists())
        caller.verify()
        toolchain = {"go": str(self.go), "go_sha256": caller.reads[str(self.go)][0]["sha256"]}
        with tempfile.TemporaryDirectory() as directory:
            output = Path(directory)
            intent = caller.build_intent(output, caller.original, toolchain, {}, [], caller.original)
            with self.assertRaisesRegex(ValueError, "compiler differs"):
                caller.build_intent(output, caller.original, {}, {}, [], caller.original)
        self.assertEqual(intent.compiler_inputs, caller.compiler_inputs)
        self.assertEqual(intent.packages, caller.packages)
        caller.compiler_inputs["main.go"] = "0" * 64
        with self.assertRaisesRegex(ValueError, "metadata changed"):
            caller.verify()

    def test_library_private_receiver_and_factory_keep_distinct_bindings(self):
        entry = self.materialise('package counter\ntype Counter struct{value int}\n'
                                 'func New(value int)*Counter{return &Counter{value:value}}\n'
                                 'func (c *Counter) Add(value int)int{c.value+=value;return c.value}\n',
                                 path="counter/api.go", name="Counter.Add", receiver=True)
        caller = self.discover(entry)
        self.assertEqual(caller.target, "./oteleq_generated_cmd")
        self.assertEqual([target.name for target in caller.targets],
                         ["example.test/caller/counter.Counter.Add", "example.test/caller/counter.New"])
        self.assertEqual([target.receiver_id for target in caller.targets], ["*Counter", ""])
        self.assertEqual(len(caller.packages), 3)
        self.assertIn("oteleq_generated_cmd/main.go", caller.compiler_inputs)
        caller.verify()

    def test_active_tag_and_embed_inputs_are_compiler_owned(self):
        self.options = go_project.settings({"module_roots": ["."], "build_tags": ["special"]})
        self.environment.update(go_project.environment(self.options))
        (self.project / "data.txt").write_bytes(b"payload")
        (self.project / "ordinary.go").write_text("//go:build !special\n\npackage main\nvar Other=2\n")
        (self.project / "special.go").write_text('//go:build special\n\npackage main\nimport _ "embed"\n'
                                                '//go:embed data.txt\nvar Data string\n')
        entry = self.materialise("package main\nfunc Add(value int)int{return value+len(Data)}\nfunc main(){}\n")
        caller = self.discover(entry)
        self.assertIn("special.go", caller.compiler_inputs)
        self.assertIn("data.txt", caller.compiler_inputs)
        self.assertNotIn("ordinary.go", caller.compiler_inputs)

    def test_missing_or_altered_planned_declaration_refuses(self):
        entry = self.materialise("package main\nfunc Add(value int)int{return value+1}\nfunc main(){}\n")
        for changed in ({**entry, "name": "Absent"}, {**entry, "parameters": []},
                        {**entry, "go_context": {**entry["go_context"], "import_path": "example.test/foreign"}}):
            with self.subTest(name=changed["name"], parameters=changed["parameters"]):
                with self.assertRaises(ValueError):
                    self.discover(changed)
        with self.assertRaisesRegex(ValueError, "module context"):
            go_caller.package_target({})
        nested = {**entry, "path": "service/main.go", "go_context": {
            **entry["go_context"], "module_root": "service", "directory": "service"}}
        self.assertEqual(go_caller.package_target(nested), (".", "main.go"))

    def test_source_and_tool_metadata_changes_refuse_reuse(self):
        entry = self.materialise("package main\nfunc Add(value int)int{return value+1}\nfunc main(){}\n")
        caller = self.discover(entry)
        caller.reads[str(self.go)][0]["sha256"] = "0" * 64
        with self.assertRaisesRegex(ValueError, "metadata changed"):
            caller.verify()
        caller = self.discover(entry)
        (self.project / "main.go").write_text("package main\nfunc main(){}\n")
        with self.assertRaises(ValueError):
            caller.verify()

    def test_compiler_metadata_denominators_and_read_budgets_refuse(self):
        entry = self.materialise("package main\nfunc Add(value int)int{return value+1}\nfunc main(){}\n")
        snapshot = go_files.freeze(self.project)
        module = {"Main": True, "Dir": str(self.project)}
        record = {"Dir": str(self.project), "ImportPath": "example.test/caller", "Name": "main",
                  "Module": module, "GoFiles": ["main.go"]}
        self.assertEqual(go_caller.active_inputs([record], snapshot)[1],
                         {"example.test/caller": {"name": "main", "directory": "."}})
        for records in ([], [record, record], [{**record, "Module": {}}],
                        [{**record, "GoFiles": "main.go"}], [{**record, "GoFiles": ["absent.go"]}]):
            with self.subTest(records=records):
                with self.assertRaises(ValueError):
                    go_caller.active_inputs(records, snapshot)
        with patch.object(go_caller.files, "MAX_TREE_BYTES", self.go.stat().st_size):
            with self.assertRaises(ValueError):
                go_caller.discover(snapshot, entry, self.go, self.environment, self.execute)

    def test_build_reader_refuses_rehashed_incomplete_active_input_denominators(self):
        original = self.root / "reader"
        original.mkdir()
        intent, receipt, inventory = fixture(original)
        intent = replace(intent, compiler_inputs=dict(inventory["compiler_inputs"]),
                         packages=dict(inventory["packages"]))
        go_build.read(intent).verify()
        for changed in ({}, {"extra.go": "a" * 64}):
            altered = {**inventory, "compiler_inputs": changed}
            with self.assertRaisesRegex(ValueError, "independent discovery"):
                go_build.source_inventory(altered, intent)
        with self.assertRaisesRegex(ValueError, "independent discovery"):
            go_build.source_inventory({**inventory, "packages": {}}, intent)
        incomplete = replace(intent, packages=None)
        with self.assertRaisesRegex(ValueError, "incomplete independent"):
            go_build.validate_intent(incomplete)


if __name__ == "__main__":
    unittest.main()
