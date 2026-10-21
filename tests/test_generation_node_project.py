"""Actual Node loader formats and callers preserve the frozen package context."""
import argparse
from contextlib import redirect_stdout
import hashlib
import io
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
import harness
import node_project
import policy
import typed_capture

NODE = Path(os.environ.get("OTELC_NODE") or shutil.which("node"))


def execute(command, cwd, input_data=None, *, max_output_bytes=None):
    return subprocess.run(command, cwd=cwd, input=input_data, capture_output=True, timeout=15)


class NodeProjectTests(unittest.TestCase):
    def setUp(self):
        temporary = tempfile.TemporaryDirectory(prefix="node package context ")
        self.addCleanup(temporary.cleanup)
        self.base = Path(temporary.name).resolve()
        self.project = self.base / "application"
        self.project.mkdir()
        self.provider = self.base / "provider"
        plain = self.provider / "adapters/node/plain.mjs"
        plain.parent.mkdir(parents=True)
        # These unit fixtures use JS-compatible TS; actual SDK emit needs qualification.
        plain.write_text('import {registerHooks} from "node:module";\n'
                         'registerHooks({load(url,context,nextLoad){const result=nextLoad(url,context);'
                         'if(result.format?.endsWith("-typescript"))return {...result,format:result.format.replace("-typescript","")};'
                         'return result;}});\n')
        compiler = REPO / "ci/markdownlint/node_modules/typescript"
        self.assertTrue(compiler.is_dir(), "run make setup: the pinned TypeScript parser is required")
        compiler_link = plain.parent / "node_modules/typescript"
        compiler_link.parent.mkdir()
        compiler_link.symlink_to(compiler, target_is_directory=True)

    def inspect(self, path, language="javascript"):
        return node_project.context(path, self.project, language, self.provider, NODE, execute)

    def test_loader_reads_formats_and_packages_without_evaluating_the_application(self):
        cases = [(".cjs", None, "commonjs"), (".mjs", None, "module"),
                 (".js", None, "commonjs"), (".js", None, "module"),
                 (".js", "module", "module"), (".js", "commonjs", "commonjs"),
                 (".cts", None, "commonjs"), (".mts", None, "module"),
                 (".ts", "module", "module"), (".ts", "commonjs", "commonjs")]
        for index, (suffix, kind, expected) in enumerate(cases):
            with self.subTest(suffix=suffix, kind=kind, expected=expected):
                folder = self.project / str(index)
                folder.mkdir()
                package = folder / "package.json"
                if kind:
                    package.write_text(json.dumps({"type": kind}))
                source = folder / ("sample" + suffix)
                syntax = 'export const value=1;\n' if expected == "module" else 'const fs=require("node:fs");\n'
                source.write_text(syntax + 'throw Error("application must not execute");\n')
                original = source.read_bytes()
                language = "typescript" if suffix in (".ts", ".mts", ".cts") else "javascript"
                actual = self.inspect(source, language)
                self.assertEqual(actual["format"], expected)
                self.assertEqual(actual["source_sha256"], hashlib.sha256(original).hexdigest())
                self.assertEqual(source.read_bytes(), original)
                self.assertEqual(actual["package"], {"path": package.relative_to(self.project).as_posix(),
                    "sha256": hashlib.sha256(package.read_bytes()).hexdigest()} if kind else None)

    def test_nearest_package_overrides_parent_and_external_package_context_refuses(self):
        (self.project / "package.json").write_text('{"type":"module"}')
        child = self.project / "nested"
        child.mkdir()
        (child / "package.json").write_text('{"type":"commonjs"}')
        source = child / "sample.js"
        source.write_text('const fs=require("node:fs");')
        self.assertEqual(self.inspect(source)["format"], "commonjs")
        (self.project / "package.json").unlink()
        (child / "package.json").unlink()
        (self.base / "package.json").write_text('{"type":"module"}')
        with self.assertRaisesRegex(ValueError, "escapes the private snapshot"):
            self.inspect(source)

    def test_missing_or_contradictory_context_receipts_are_rejected(self):
        source = self.project / "sample.cjs"
        source.write_text("function sample(value){return value;}")
        value = self.inspect(source)
        variants = [None, {}, {**value, "schema_version": True}, {**value, "extra": "unknown"},
                    {**value, "source_sha256": "0" * 64}, {**value, "format": "unknown"},
                    {**value, "node_version": None}, {**value, "loader_hint": []},
                    {**value, "package": {}}, {**value, "package": {"path": "../outside", "sha256": "0" * 64}}]
        for changed in variants:
            result = subprocess.CompletedProcess([], 0, json.dumps(changed).encode(), b"")
            with self.subTest(changed=changed), self.assertRaises(ValueError):
                node_project.context(source, self.project, "javascript", self.provider, NODE,
                                     lambda *args, **kwargs: result)

    def test_original_and_private_package_formats_must_agree(self):
        source = self.project / "sample.js"
        source.write_text("function sample(value){return value;}")
        (self.project / "package.json").write_text('{"type":"commonjs"}')
        private = self.base / "private"
        shutil.copytree(self.project, private)
        (private / "package.json").write_text('{"type":"module"}')
        value = node_project.inventory_context(private / "sample.js", private, self.project,
                                               "javascript", self.provider, NODE, execute)
        self.assertIn("differs from the original application", value["node_context_error"])

    def test_changed_source_is_rejected_before_any_application_evaluation(self):
        source = self.project / "sample.cjs"
        marker = self.base / "application-ran"
        source.write_text('require("node:fs").writeFileSync(' + json.dumps(str(marker)) + ',"ran");')
        request = {"root": str(self.project), "filename": str(source), "source_sha256": "0" * 64}
        result = execute([NODE, REPO / "adapters/generation/node_context.mjs"], self.project,
                         input_data=json.dumps(request).encode())
        self.assertNotEqual(result.returncode, 0)
        self.assertIn(b"source changed before inspection", result.stderr)
        self.assertFalse(marker.exists())
        receipt = self.inspect(source)
        self.assertFalse(marker.exists())
        def change_source(*args, **kwargs):
            source.write_text(source.read_text() + "\n// changed\n")
            return subprocess.CompletedProcess([], 0, json.dumps(receipt).encode(), b"")
        with self.assertRaisesRegex(ValueError, "source changed during"):
            node_project.context(source, self.project, "javascript", self.provider, NODE, change_source)

    def test_unknown_bound_module_formats_cannot_fall_back(self):
        with self.assertRaisesRegex(ValueError, "unknown Node module context"):
            node_project.commonjs({"path": "sample.js", "node_context": {"format": "unknown"}})

    def test_free_callers_preserve_commonjs_and_module_startup_and_observe_the_target(self):
        for index, (suffix, kind) in enumerate(((".cjs", None), (".js", None), (".js", "commonjs"),
                                               (".mjs", None), (".js", "module"), (".cts", None), (".mts", None))):
            with self.subTest(suffix=suffix, kind=kind):
                folder = self.project / str(index)
                folder.mkdir()
                if kind:
                    (folder / "package.json").write_text(json.dumps({"type": kind}))
                source = folder / ("sample" + suffix)
                source.write_text('"use strict";\nlet state=2;\nfunction sample(value){state+=value;return state+value;}\n'
                                  'console.log(typeof require=== "function"?"commonjs":"module");\n')
                language = "typescript" if suffix in (".cts", ".mts") else "javascript"
                baseline = execute([NODE, source], folder)
                self.assertEqual(baseline.returncode, 0, baseline.stderr)
                context = self.inspect(source, language)
                entry = {"path": source.relative_to(self.project).as_posix(), "language": language,
                         "name": "sample", "globals": [{"name": "state"}], "binding_capture_offset": 13,
                         "node_context": context}
                harness.materialise(self.project, entry, [7])
                attempt = self.base / ("attempt-" + str(index))
                attempt.mkdir()
                node_project.verify_attempt(self.project, entry, self.provider, NODE, execute, attempt)
                observation = attempt / "observation.json"
                result = subprocess.run([NODE, source], cwd=self.project, capture_output=True, timeout=15,
                                        env={**os.environ, "OTELEQ_OBSERVATION": str(observation)})
                self.assertEqual(result.returncode, 0, result.stderr)
                self.assertEqual(result.stdout, baseline.stdout)
                raw = json.loads(observation.read_text())
                self.assertEqual(raw["outcome"]["kind"], "return")
                graph = typed_capture.dynamic_graph(raw["outcome"]["value"], language)
                self.assertEqual(graph["roots"]["result"]["bits"], "4030000000000000")
                before = typed_capture.dynamic_graph(raw["before"], language)
                after = typed_capture.dynamic_graph(raw["after"], language)
                self.assertEqual(before["roots"]["global:state"]["bits"], "4000000000000000")
                self.assertEqual(after["roots"]["global:state"]["bits"], "4022000000000000")
                self.assertTrue((attempt / "node-context.json").is_file())

    def test_inventory_retains_context_and_blocks_a_shadowed_commonjs_require(self):
        source = self.project / "sample.js"
        source.write_text("function sample(value){return value+1;}")
        function = {"name": "sample", "line": 1, "parameters": ["unknown"], "output": "unknown", "reason": ""}
        parsed = {"functions": [function], "globals": [], "entrypoints": [],
                  "node_context": self.inspect(source)}
        request = argparse.Namespace(configuration=policy.validate({"languages": ["javascript"]}), cases=1)
        digest = hashlib.sha256(source.read_bytes()).hexdigest()
        entry = generation.inventory_entry(function, parsed, "sample.js", "javascript", digest, self.project, request)
        self.assertEqual(entry["status"], "ready", entry["reason"])
        self.assertEqual(entry["node_context"]["format"], "commonjs")
        parsed["functions"].append({**function, "name": "require"})
        entry = generation.inventory_entry(function, parsed, "sample.js", "javascript", digest, self.project, request)
        self.assertEqual(entry["status"], "blocked")
        self.assertIn("unshadowed module require", entry["reason"])
        parsed["node_context_error"] = "unsupported project compiler context"
        entry = generation.inventory_entry(function, parsed, "sample.js", "javascript", digest, self.project, request)
        self.assertEqual(entry["status"], "blocked")
        self.assertEqual(entry["reason"], parsed["node_context_error"])

    def test_changed_package_bytes_refuse_the_materialised_attempt(self):
        package = self.project / "package.json"
        package.write_text('{"type":"commonjs"}')
        source = self.project / "sample.js"
        source.write_text("function sample(value){return value;}")
        entry = {"path": "sample.js", "language": "javascript", "node_context": self.inspect(source)}
        package.write_text('{"type":"module"}')
        with self.assertRaisesRegex(ValueError, "changed its source/package"):
            node_project.verify_attempt(self.project, entry, self.provider, NODE, execute, self.base)

    def test_actual_parser_and_loader_bind_commonjs_receiver_class_callers(self):
        source = self.project / "sample.js"
        source.write_text('class Counter {static total=2;constructor(start){this.value=start;}'
                          'add(amount){this.value+=amount;Counter.total+=amount;return this.value;}}\n')
        parsed = generation.discovery.discover(source, "javascript", self.provider, {"javascript": NODE}, execute)
        parsed["entrypoints"] = []
        parsed["node_context"] = self.inspect(source)
        request = argparse.Namespace(configuration=policy.validate({"languages": ["javascript"],
            "fixtures": [{"function": "sample.Counter.add", "cases": [[7]],
                          "receiver": {"factory": "Counter", "arguments": [10]}}]}), cases=1)
        function = next(item for item in parsed["functions"] if item["name"] == "Counter.add")
        entry = generation.inventory_entry(function, parsed, "sample.js", "javascript",
            hashlib.sha256(source.read_bytes()).hexdigest(), self.project, request)
        self.assertEqual(entry["status"], "ready", entry["reason"])
        self.assertEqual(entry["node_context"]["format"], "commonjs")
        parsed["node_context_error"] = "missing receiver package context"
        blocked = generation.inventory_entry(function, parsed, "sample.js", "javascript",
            hashlib.sha256(source.read_bytes()).hexdigest(), self.project, request)
        self.assertEqual(blocked["status"], "blocked")
        self.assertEqual(blocked["reason"], "missing receiver package context")
        parsed.pop("node_context_error")
        harness.materialise(self.project, entry, [7])
        node_project.verify_attempt(self.project, entry, self.provider, NODE, execute, self.base)
        observation = self.base / "observation.json"
        result = subprocess.run([NODE, source], cwd=self.project, capture_output=True, timeout=15,
                                env={**os.environ, "OTELEQ_OBSERVATION": str(observation)})
        self.assertEqual(result.returncode, 0, result.stderr)
        raw = json.loads(observation.read_text())
        graph = typed_capture.dynamic_graph(raw["outcome"]["value"], "javascript",
                                           ("declared:" + entry["node_class_label"],))
        self.assertEqual(graph["roots"]["result"]["bits"], "4031000000000000")

    def test_commonjs_startup_cannot_rebind_the_selected_function_or_observer_intrinsics(self):
        for index, mutation in enumerate(('sample=()=>99;',
                'Array.prototype.map=function(){throw Error("application callback must not execute")};')):
            with self.subTest(mutation=mutation):
                source = self.project / ("sample" + str(index) + ".cjs")
                source.write_text('function sample(value){return value+1;}\n' + mutation)
                entry = {"path": source.name, "language": "javascript", "name": "sample", "globals": [],
                         "node_context": self.inspect(source)}
                harness.materialise(self.project, entry, [7])
                observation = self.base / ("refused" + str(index) + ".json")
                result = subprocess.run([NODE, source], cwd=self.project, capture_output=True, timeout=15,
                                        env={**os.environ, "OTELEQ_OBSERVATION": str(observation)})
                self.assertNotEqual(result.returncode, 0)
                self.assertFalse(observation.exists())
                self.assertNotIn(b"application callback must not execute", result.stderr)

    def test_public_plan_generation_and_detached_export_keep_the_loader_context(self):
        source = self.project / "sample.js"
        source.write_text('function sample(value){return value+1;}\nthrow Error("application must not execute during planning");\n')
        cli = self.base / "cli"
        cli.write_text("fixed unit CLI")
        request = argparse.Namespace(source=self.project, otelc_root=self.provider, workspace_parent=self.base,
                                     config=None, language=["javascript"], exclude=[], cases=1)
        with patch.dict(os.environ, {"OTELEQ_EXECUTABLE": str(cli)}), \
             patch.object(generation.capture, "selected_tools", return_value={"javascript": NODE}), \
             patch.object(generation.capture, "artefacts", return_value={"fixture": "fixed"}):
            with redirect_stdout(io.StringIO()) as output:
                generation.plan(request)
            workspace = Path(output.getvalue().strip())
            plan = generation.read(workspace / "plan.json")
            self.assertEqual(len(plan["inventory"]), 1)
            entry = plan["inventory"][0]
            self.assertEqual(entry["status"], "ready", entry["reason"])
            self.assertEqual(entry["node_context"]["format"], "commonjs")
            self.assertEqual(entry["node_original_context"], entry["node_context"])
            with redirect_stdout(io.StringIO()):
                generation.generate(argparse.Namespace(workspace=workspace))
            destination = self.base / "exported"
            with redirect_stdout(io.StringIO()):
                generation.export_tests(argparse.Namespace(workspace=workspace, destination=destination, apply=True))
            shutil.rmtree(self.project)
            _, detached = generation.load_workspace(destination, generated=True)
            self.assertEqual(detached["inventory"][0]["node_context"], entry["node_context"])
            self.assertEqual(generation.clean(argparse.Namespace(workspace=destination)), 0)
            self.assertEqual(generation.clean(argparse.Namespace(workspace=workspace)), 0)

    def test_an_original_ambient_package_cannot_be_lost_in_the_private_snapshot(self):
        (self.base / "package.json").write_text('{"type":"module"}')
        source = self.project / "sample.js"
        source.write_text("function sample(value){return value+1;}")
        temporary = tempfile.TemporaryDirectory(prefix="node independent workspace ")
        self.addCleanup(temporary.cleanup)
        parent = Path(temporary.name).resolve()
        cli = parent / "cli"
        cli.write_text("fixed unit CLI")
        request = argparse.Namespace(source=self.project, otelc_root=self.provider, workspace_parent=parent,
                                     config=None, language=["javascript"], exclude=[], cases=1)
        with patch.dict(os.environ, {"OTELEQ_EXECUTABLE": str(cli)}), \
             patch.object(generation.capture, "selected_tools", return_value={"javascript": NODE}), \
             patch.object(generation.capture, "artefacts", return_value={"fixture": "fixed"}):
            with redirect_stdout(io.StringIO()) as output:
                generation.plan(request)
            workspace = Path(output.getvalue().strip())
            plan = generation.read(workspace / "plan.json")
            self.assertEqual(len(plan["inventory"]), 1)
            entry = plan["inventory"][0]
            self.assertEqual(entry["name"], "sample")
            self.assertEqual(entry["status"], "blocked")
            self.assertIn("escapes the private snapshot", entry["reason"])
            self.assertEqual(generation.clean(argparse.Namespace(workspace=workspace)), 0)


if __name__ == "__main__":
    unittest.main()
