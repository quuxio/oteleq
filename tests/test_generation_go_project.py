"""Real Go package inclusion, semantic types, private callers and refusal controls."""
import argparse
import json
import os
from pathlib import Path
import shutil
import subprocess
import sys
import tempfile
import unittest
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "adapters/generation"))
sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "examples"))
import generation
import go_project
import harness
import policy


class GoProjectTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.cache = tempfile.TemporaryDirectory()
        cls.addClassCleanup(cls.cache.cleanup)

    def setUp(self):
        self.temporary = tempfile.TemporaryDirectory()
        self.addCleanup(self.temporary.cleanup)
        self.base = Path(self.temporary.name).resolve()
        self.snapshot = self.base / "snapshot"
        self.module = self.snapshot / "services/api"
        self.module.mkdir(parents=True)
        (self.module / "go.mod").write_text("module example.test/service\n\ngo 1.20\n")
        self.go = Path(os.environ.get("OTELC_GO") or shutil.which("go"))
        self.options = go_project.settings({"module_roots": ["services/api"]})
        self.env = {**os.environ, **go_project.environment(self.options), "GOTOOLCHAIN": "local",
                    "GOCACHE": str(Path(self.cache.name) / "build"), "GOMODCACHE": str(self.base / "modules")}

    def source(self, name, text):
        path = self.module / name
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(text)
        return path

    def execute(self, command, cwd, input_data=None):
        return subprocess.run(command, cwd=cwd, input=input_data, env=self.env,
                              capture_output=True, check=False, timeout=90)

    def discover(self, source, cache=None):
        return go_project.discover(source, self.snapshot, self.options, self.go, self.execute,
                                   {} if cache is None else cache)

    def entry(self, source, discovered, name="selected"):
        discovered["entrypoints"] = [item for item in discovered["functions"] if item.get("entrypoint")]
        function = next(item for item in discovered["functions"] if item["name"] == name)
        configuration = policy.validate({"adapters": {"go": self.options}})
        args = argparse.Namespace(configuration=configuration, cases=1)
        return generation.inventory_entry(function, discovered, str(source.relative_to(self.snapshot)),
                                          "go", "a" * 64, self.snapshot, args)

    def run_worker(self, source, discovered, expected):
        entry = self.entry(source, discovered)
        self.assertEqual(entry["status"], "ready", entry["reason"])
        private = self.base / "private"
        shutil.copytree(self.snapshot, private)
        driver = harness.materialise(private, entry, [3])
        self.assertEqual(driver, generation.driver_path(private, entry))
        observation = self.base / "observation"
        environment = {**self.env, "OTELEQ_OBSERVATION": str(observation)}
        executed = subprocess.run([self.go, "run", driver], cwd=private / "services/api", env=environment,
                                  capture_output=True, check=False, timeout=90)
        self.assertEqual(executed.returncode, 0, executed.stderr)
        self.assertEqual(executed.stdout, b"")
        self.assertIn(expected, observation.read_bytes())
        self.assertEqual(entry["otelc_function"], "services.api." + entry["otelc_runtime_function"])
        self.assertIn(json.dumps(entry["otelc_runtime_function"]), generation.policy(entry, "http://example.test"))
        return entry, observation.read_bytes()

    def test_library_uses_internal_imports_named_types_and_sibling_globals(self):
        self.source("types/types.go", "package types\ntype Count int64\n")
        source = self.source("internal/counter/api.go", 'package counter\nimport alias "example.test/service/types"\nfunc selected(v alias.Count) alias.Count {state+=v;return state}\n')
        sibling = self.source("internal/counter/state.go", 'package counter\nimport "example.test/service/types"\nvar state=types.Count(7)\nvar _=1\n')
        before = generation.manifest(self.snapshot)
        cache = {}
        discovered = self.discover(source, cache)
        self.assertEqual(discovered["globals"], [{"name": "state", "type": "int64"}])
        self.assertEqual(discovered["functions"][0]["parameters"], ["int64"])
        self.assertEqual(discovered["functions"][0]["go_parameter_types"], ["alias.Count"])
        with patch.object(go_project, "load_package", side_effect=AssertionError("cache miss")):
            self.assertEqual(self.discover(sibling, cache)["globals"], discovered["globals"])
        entry, observation = self.run_worker(source, discovered, b"return:@int64|types.Count:10")
        self.assertIn(b"state:@int64|types.Count:7", observation)
        self.assertEqual(entry["otelc_runtime_function"], "internal.counter.api.selected")
        self.assertEqual(generation.manifest(self.snapshot), before)

    def test_main_target_builds_siblings_and_replaces_the_real_sibling_entrypoint(self):
        source = self.source("cmd/api.go", "package main\nfunc selected(v int)int {main();main:=func(){state+=2};main();state+=v;return helper()}\n")
        self.source("cmd/state.go", 'package main\nvar state=4\nfunc helper()int{return state}\nfunc main(){state++}\n')
        entry, _ = self.run_worker(source, self.discover(source), b"return:int:10")
        self.assertEqual(go_project.worker_path(entry["go_context"]), "services/api/cmd")
        with self.assertRaisesRegex(ValueError, "resolved binding"):
            go_project.rename_entrypoint("package main\n", [0])

    def test_startup_methods_and_inactive_build_files_remain_explicit_inventory(self):
        source = self.source("counter/api.go", "package counter\ntype Count int\nfunc init(){}\nfunc init(){}\nfunc (*Count) Read()int{return 0}\nfunc selected(v int)int{return v}\n")
        inactive = self.source("counter/other.go", "//go:build oteleq_other\n\npackage counter\nfunc alternative(v int)int{return v}\n")
        test_source = self.source("counter/api_test.go", 'package counter\nimport "testing"\nfunc TestSelected(t *testing.T){}\n')
        cache = {}
        discovered = self.discover(source, cache)
        names = [item["name"] for item in discovered["functions"]]
        self.assertEqual(names[:3], ["init@api.go:3", "init@api.go:4", "Count.Read"])
        self.assertIn("startup fixture", self.entry(source, discovered, names[0])["reason"])
        self.assertEqual(self.entry(source, discovered, "Count.Read")["status"], "blocked")
        for path in (inactive, test_source):
            result = self.discover(path, cache)
            self.assertIn("excluded by", result["functions"][0]["reason"])
            self.assertFalse(result["functions"][0]["entrypoint"])
        self.options["build_tags"] = ["oteleq_other"]
        self.env.update(go_project.environment(self.options))
        self.assertEqual(self.discover(inactive)["functions"][0]["reason"], "")

    def test_unsupported_state_sibling_recovery_and_reserved_names_refuse(self):
        source = self.source("counter/api.go", "package counter\nfunc selected(v int)int{return v}\n")
        sibling = self.source("counter/state.go", "package counter\nvar state=[]int{1}\n")
        self.assertIn("unobserved globals", self.entry(source, self.discover(source))["reason"])
        sibling.write_text("package counter\nfunc recover()any{return nil}\n")
        self.assertIn("shadowed Go", self.entry(source, self.discover(source))["reason"])
        for name in ("__oteleq", go_project.BRIDGE):
            sibling.write_text("package counter\n// " + name + "\n")
            with self.subTest(name=name):
                self.assertIn("collides", self.discover(source)["functions"][0]["reason"])
        sibling.write_text("package counter\n")
        (self.module / go_project.COMMAND_DIRECTORY).mkdir()
        self.assertIn("command directory", self.discover(source)["functions"][0]["reason"])

    def test_invalid_project_context_keeps_each_syntactic_callable_visible(self):
        source = self.source("counter/api.go", "package counter\nfunc one(){}\nfunc two(){}\n")
        (self.module / "go.mod").write_text("invalid module syntax\n")
        result = self.discover(source)
        self.assertEqual([item["name"] for item in result["functions"]], ["one", "two"])
        self.assertTrue(all("discovery failed" in item["reason"] for item in result["functions"]))
        (self.module / "go.mod").unlink()
        result = self.discover(source)
        self.assertTrue(all("inside the source" in item["reason"] for item in result["functions"]))

    def test_library_function_named_main_is_not_an_application_entrypoint(self):
        source = self.source("counter/api.go", "package counter\nfunc main(v int)int{return v}\n")
        discovered = self.discover(source)
        self.assertFalse(discovered["functions"][0]["entrypoint"])
        self.assertEqual(self.entry(source, discovered, "main")["status"], "ready")

    def test_standalone_main_references_are_renamed_without_local_shadows(self):
        source = self.source("app.go", "package main\nvar state int\nfunc selected(v int)int{main();main:=func(){state+=v};main();return state}\nfunc main(){state++}\n")
        result = self.execute([self.go, "run", Path(go_project.__file__).with_name("discover.go"), "--", source], self.base)
        self.assertEqual(result.returncode, 0, result.stderr)
        inventory = json.loads(result.stdout)
        self.assertEqual(len(inventory["main_renames"]), 2)
        rewritten = go_project.rename_entrypoint(source.read_text(), inventory["main_renames"])
        self.assertIn("__oteleq_original_main();main:=func()", rewritten)
        self.assertIn(";main();return state", rewritten)

    def test_policy_roots_tags_workspace_and_dependency_boundaries(self):
        self.assertEqual(policy.load(None)["adapters"]["go"], {"module_roots": [], "build_tags": []})
        invalid = [[], {"backend": "compile"}, {"module_roots": "src"}, {"module_roots": [1]},
                   *[{"module_roots": [name]} for name in ("", "/tmp", "../outside", "a/../b", "a//b", "a\\b", "a:b")],
                   {"module_roots": [".", "."]}, {"build_tags": ["integration"]},
                   *[{"module_roots": ["."], "build_tags": tags} for tags in (None, "tag", [""], ["x x"], [1], ["x", "x"])]]
        for value in invalid:
            with self.subTest(value=value), self.assertRaises(ValueError):
                go_project.settings(value)
        source = self.source("counter/api.go", "package counter\n")
        self.assertEqual(go_project.module_root(self.snapshot, source, ["services/api"]), self.module)
        with self.assertRaisesRegex(ValueError, "not configured"):
            go_project.module_root(self.snapshot, source, ["."])
        (self.snapshot / "go.work").write_text("go 1.20\nuse ./services/api\n")
        with self.assertRaisesRegex(ValueError, "workspaces"):
            go_project.module_root(self.snapshot, source, ["services/api"])
        (self.snapshot / "go.work").unlink()
        (self.module / "go.mod").unlink()
        with self.assertRaisesRegex(ValueError, "inside the source"):
            go_project.module_root(self.snapshot, source, ["."])
        for record in ({"Module": {"Replace": {"Dir": str(self.base), "Path": "../outside"}}},
                       {"Dir": str(source.parent), "CgoFiles": ["native.go"]},
                       {"Dir": str(source.parent), "SFiles": ["native.s"]}):
            with self.subTest(record=record), self.assertRaises(ValueError):
                go_project.package_inputs([record], self.snapshot)
        go_project.package_inputs([{"Dir": str(self.base / "modules"), "Module": {"Replace": {"Version": "v1.0.0"}}}], self.snapshot)
        self.assertEqual(go_project.documents(b' {"x":1}\n {"y":2} \n'), [{"x": 1}, {"y": 2}])
        with self.assertRaisesRegex(ValueError, "non-object"):
            go_project.documents(b'[]')
        with self.assertRaisesRegex(ValueError, "failed.*diagnostic"):
            go_project.check_result(subprocess.CompletedProcess([], 1, b"", b"diagnostic"), "failed")


if __name__ == "__main__":
    unittest.main()
