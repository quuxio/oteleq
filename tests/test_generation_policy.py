"""Project policy, explicit input and configured execution regressions."""
import argparse
from contextlib import redirect_stdout
import copy
import io
import json
import os
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "adapters/generation"))
sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "examples"))
import generation
import harness
import policy


class PolicyTests(unittest.TestCase):
    def load(self, document):
        with tempfile.TemporaryDirectory() as temporary:
            path = Path(temporary) / "equivalence.toml"
            path.write_text("")
            with patch.object(policy.tomllib, "loads", return_value=document):
                return policy.load(path)

    def test_defaults_are_complete_and_do_not_share_mutable_selections(self):
        first, second = policy.load(None), policy.load(None)
        self.assertEqual(first, policy.DEFAULTS)
        first["sources"]["include"].append("changed")
        first["adapters"]["rust"]["backend"] = "llvm"
        self.assertNotEqual(first, second)
        self.assertEqual(second["adapters"]["rust"]["backend"], "compiler")
        self.assertEqual(set(second["languages"]), set(policy.LANGUAGES))
        self.assertTrue(policy.selected("src/api.py", {"include": ["src/**"], "exclude": []}))
        self.assertFalse(policy.selected("src/test_api.py", {"include": ["src/**"], "exclude": ["**/test*"]}))

    def test_valid_policy_retains_concrete_cases_types_and_configured_budgets(self):
        config = self.load({"languages": ["python"], "sources": {"include": ["src/**"]},
                            "functions": {"exclude": ["*.internal"]},
                            "generation": {"seed": 7, "cases_per_function": 100},
                            "limits": {"baseline_repeats": 3, "instrumented_repeats": 4, "case_timeout_ms": 250},
                            "fixtures": [{"function": "src.api.run", "source": "src/api.py", "cases": [[True], [1], [1.0]]}]})
        self.assertEqual(config["generation"], {"seed": 7, "cases_per_function": 100})
        entry = {"otelc_function": "src.api.run", "path": "src/api.py"}
        self.assertEqual(policy.concrete_cases(entry, config), [[True], [1], [1.0]])
        self.assertIsNone(policy.concrete_cases({**entry, "path": "other.py"}, config))
        config["fixtures"].append(copy.deepcopy(config["fixtures"][0]))
        with self.assertRaisesRegex(ValueError, "multiple configured"):
            policy.concrete_cases(entry, config)

    def test_unknown_malformed_duplicate_and_unsafe_settings_are_rejected(self):
        invalid = [[], {"schema_version": True}, {"schema_version": 2}, {"unknown": 1},
                   {"languages": []}, {"languages": ["python", "python"]}, {"languages": ["unknown"]},
                   {"languages": [3]}, {"sources": []}, {"sources": {"includes": ["**"]}},
                   {"functions": {"include": [""]}}, {"generation": {"cases_per_function": 0}},
                   {"generation": {"seed": -1}}, {"generation": {"seed": True}},
                   {"limits": {"baseline_repeats": 1}}, {"limits": {"instrumented_repeats": 33}},
                   {"limits": {"case_timeout_ms": 0}}, {"limits": {"max_capture_bytes": 262145}},
                   {"limits": {"timeout": 5}}, {"fixtures": {}}, {"fixtures": [{}]},
                   {"fixtures": [{"function": "f", "cases": []}]},
                   {"fixtures": [{"function": "f", "cases": [1]}]},
                   {"fixtures": [{"function": "f", "cases": [[None]]}]},
                   {"fixtures": [{"function": "f", "cases": [[{}]]}]},
                   {"fixtures": [{"function": "f", "cases": [[float("nan")]]}]},
                   {"fixtures": [{"function": "f", "language": "unknown", "cases": [[1]]}]},
                   {"fixtures": [{"function": "f", "cases": [[1], [1]]}]}]
        invalid.extend([{"adapters": []}, {"adapters": {"go": {"backend": "compile"}}},
                        {"adapters": {"rust": []}}, {"adapters": {"rust": {"unknown": 1}}},
                        *[{"adapters": {"rust": {"backend": value}}} for value in (True, None, [], "native", "LLVM")]])
        for document in invalid:
            with self.subTest(document=document), self.assertRaises(ValueError):
                self.load(document)
        with tempfile.TemporaryDirectory() as temporary:
            path = Path(temporary) / "policy.toml"
            with self.assertRaisesRegex(ValueError, "regular file"):
                policy.load(path)
            path.write_text("schema_version = 1\nschema_version = 1\n")
            with self.assertRaises(ValueError):
                policy.load(path)
            path.write_bytes(b" " * (1024 * 1024 + 1))
            with self.assertRaisesRegex(ValueError, "at most"):
                policy.load(path)

    def test_rust_selection_is_frozen_and_emitted_without_changing_default_backend(self):
        function = {"name": "selected", "line": 1, "parameters": ["i32"], "output": "i32", "reason": ""}
        discovered = {"globals": [], "entrypoints": []}
        with tempfile.TemporaryDirectory() as temporary:
            folder = Path(temporary)
            (folder / "app.rs").write_text("fn selected(value:i32)->i32{value+1}\n")
            for backend in ("compiler", "llvm"):
                config = self.load({"adapters": {"rust": {"backend": backend}}})
                args = argparse.Namespace(configuration=config, cases=1)
                entry = generation.inventory_entry(function, discovered, "app.rs", "rust", "a" * 64, folder, args)
                self.assertEqual(entry["rust_backend"], backend)
                self.assertEqual(entry["status"], "ready")
                provider = policy.tomllib.loads(generation.policy(entry, "http://127.0.0.1:4318"))
                self.assertEqual(provider["adapters"]["rust"]["backend"], backend)
                self.assertEqual(provider["sources"]["include"], ["app.rs"] if backend == "llvm" else ["**"])
        default = generation.policy({"language": "rust", "otelc_function": "app.selected"}, "receiver")
        self.assertEqual(policy.tomllib.loads(default)["adapters"]["rust"]["backend"], "compiler")

    def test_fixture_scalars_are_checked_against_parameter_types_and_widths(self):
        def entry(language, name, values):
            return {"language": language, "parameters": [name], "input_cases": [[values]]}
        for language, name, value in (("python", "int", 2**100), ("java", "long", -(2**63)),
                                      ("go", "uint8", 255), ("rust", "i128", 2**100),
                                      ("cpp", "unsigned long long", 2**64 - 1),
                                      ("javascript", "dynamic", "domain"), ("java", "char", 55296)):
            with self.subTest(language=language, name=name):
                self.assertEqual(harness.corpus(entry(language, name, value), 1), [[value]])
        for language, name, value in (("java", "byte", 128), ("go", "int8", 128),
                                      ("rust", "u8", -1), ("cpp", "unsigned int", -1),
                                      ("python", "int", True), ("python", "bool", 1),
                                      ("python", "str", 1), ("python", "float", True),
                                      ("java", "float", 1e100), ("java", "Database", 1)):
            candidate = entry(language, name, value)
            with self.subTest(language=language, name=name), self.assertRaises(ValueError):
                harness.corpus(candidate, 1)
        with self.assertRaisesRegex(ValueError, "argument count"):
            harness.corpus({"language": "python", "parameters": ["int"], "input_cases": [[]]}, 1)
        self.assertEqual(harness.literal(-0.0, "float32", "go"), "__oteleq_math.Float32frombits(0x80000000)")
        self.assertEqual(harness.literal(-0.0, "float64", "go"), "__oteleq_math.Float64frombits(0x8000000000000000)")
        self.assertEqual(harness.literal(1.3, "float32", "go"), "__oteleq_math.Float32frombits(0x3fa66666)")
        self.assertEqual(harness.literal(-(2**63), "long", "java"), "(long)-9223372036854775808L")
        self.assertIn("ULL", harness.literal(2**64 - 1, "unsigned long long", "cpp"))
        self.assertIn("-9223372036854775807LL-1", harness.literal(-(2**63), "long long", "c"))
        self.assertIn("(char)0x0000", harness.literal("\x00", "String", "java"))
        for language, name in (("python", "str"), ("javascript", "number"), ("rust", "u8")):
            generated = harness.corpus({"language": language, "parameters": [name]}, 8)
            self.assertEqual(len(generated), 8)
        for value in ("0", "1025", "not-a-number"):
            with self.assertRaises(argparse.ArgumentTypeError):
                generation.case_budget(value)
        self.assertEqual(generation.case_budget("17"), 17)
        rounded = harness.corpus({"language": "rust", "parameters": ["f32"], "input_cases": [[1.3]]}, 1)[0][0]
        self.assertEqual(rounded, 1.2999999523162842)
        with self.assertRaisesRegex(ValueError, "duplicate target"):
            harness.corpus({"language": "javascript", "parameters": ["number"], "input_cases": [[1], [1.0]]}, 2)
        with self.assertRaisesRegex(ValueError, "target representation"):
            harness.corpus({"language": "javascript", "parameters": ["dynamic"], "input_cases": [[10**1000]]}, 1)
        with self.assertRaisesRegex(ValueError, "finite number"):
            harness.corpus({"language": "python", "parameters": ["float"], "input_cases": [[10**1000]]}, 1)


class ConfiguredWorkflowTests(unittest.TestCase):
    def test_unmatched_ambiguous_excluded_and_language_scoped_fixtures(self):
        with tempfile.TemporaryDirectory() as temporary:
            base = Path(temporary)
            source, root = base / "application", base / "otelc"
            source.mkdir();root.mkdir()
            (source / "source.py").write_text("def sample(x:int)->int:return x\n")
            cli = base / "cli";cli.write_text("chosen CLI")
            config = base / "policy.toml"
            documents = [
                ('[[fixtures]]\nfunction="missing"\ncases=[[1]]\n', "no selected callable"),
                ('[[fixtures]]\nfunction="*sample"\ncases=[[1]]\n[[fixtures]]\nfunction="*sample"\ncases=[[2]]\n', "multiple configured"),
                ('[functions]\nexclude=["*sample"]\n[[fixtures]]\nfunction="source.sample"\ncases=[[1]]\n', None),
                ('[[fixtures]]\nlanguage="java"\nfunction="Java.missing"\ncases=[[1]]\n', None),
            ]
            for text, error in documents:
                config.write_text(text)
                options = argparse.Namespace(source=source, otelc_root=root, workspace_parent=base,
                                             config=config, language=["python", "python"], exclude=[], cases=2)
                with patch.dict(os.environ, {"OTELEQ_EXECUTABLE": str(cli)}), \
                     patch.object(generation.capture, "selected_tools", return_value={"python": Path(sys.executable)}), \
                     patch.object(generation.capture, "artefacts", return_value={"pinned": "sha"}), \
                     redirect_stdout(io.StringIO()) as output:
                    if error:
                        with self.subTest(text=text), self.assertRaisesRegex(ValueError, error):
                            generation.plan(options)
                    else:
                        generation.plan(options)
                        data = generation.read(Path(output.getvalue().strip()) / generation.PLAN_FILE)
                        self.assertEqual(data["configuration"]["languages"], ["python"])
                        self.assertEqual(data["cases_per_function"], 2)

    def test_configuration_is_used_frozen_exported_and_source_preserving(self):
        with tempfile.TemporaryDirectory() as temporary:
            base = Path(temporary)
            source, root = base / "application", base / "otelc"
            source.mkdir();root.mkdir()
            (source / "api.py").write_text("def sample(x:int)->int:return x+1\ndef excluded(x:int)->int:return x\n")
            (source / "other.py").write_text("def ignored(x:int)->int:return x\n")
            cli, config = base / "cli", base / "equivalence.toml"
            cli.write_text("selected CLI")
            config.write_text('''schema_version=1
languages=["python"]
[sources]
include=["api.py"]
[functions]
exclude=["*.excluded"]
[generation]
seed=7
cases_per_function=8
[limits]
baseline_repeats=3
instrumented_repeats=4
case_timeout_ms=250
[[fixtures]]
function="api.sample"
cases=[[7],[41]]
expected_baseline={kind="return_value",value={kind="integer",type="python.int",value="8",signed=true}}
''')
            original = generation.manifest(source)
            options = argparse.Namespace(source=source, otelc_root=root, workspace_parent=base,
                                         config=config, language=None, exclude=[], cases=None)
            with patch.dict(os.environ, {"OTELEQ_EXECUTABLE": str(cli)}), \
                 patch.object(generation.capture, "selected_tools", return_value={"python": Path(sys.executable)}), \
                 patch.object(generation.capture, "artefacts", return_value={"pinned": "sha"}), redirect_stdout(io.StringIO()) as output:
                self.assertEqual(generation.plan(options), 0)
                workspace = Path(output.getvalue().strip())
                _, data = generation.load_workspace(workspace)
                self.assertEqual(data["excluded_files"], ["other.py"])
                self.assertEqual([e["status"] for e in data["inventory"]], ["ready", "excluded"])
                self.assertEqual(data["cases_per_function"], 8)
                with redirect_stdout(io.StringIO()):
                    generation.generate(argparse.Namespace(workspace=workspace))
                self.assertEqual([c["arguments"] for c in generation.read(workspace / "tests/corpus.json")], [[7], [41]])
                self.assertEqual(generation.manifest(source), original)
                config.write_text("changed outside the target repository")
                generation.load_workspace(workspace, generated=True)
                exported = base / "exported"
                with redirect_stdout(io.StringIO()):
                    generation.export_tests(argparse.Namespace(workspace=workspace, destination=exported, apply=True))
                self.assertEqual(generation.load_workspace(exported, generated=True)[1]["configuration"], data["configuration"])
                entry = data["inventory"][0]
                case = generation.read(workspace / "tests/corpus.json")[0]
                self.assertEqual(case["expected_baseline"], {
                    "kind": "return_value", "value": {"kind": "integer", "type": "python.int", "value": "8", "bits": None, "signed": True}})
                self.assertEqual(generation.read(exported / "tests/corpus.json")[0]["expected_baseline"], case["expected_baseline"])
                folder = base / "comparison";folder.mkdir()
                captured_graph = {"roots": {"arguments": {"type":"null"}}, "nodes": []}
                raw = json.dumps({"before":captured_graph,"after":captured_graph,
                                  "outcome":{"kind":"return","value":{"roots":{**captured_graph["roots"],"result":{"type":"int","value":"1"}},"nodes":[]}}}).encode()
                observed = {"witness": {"functions": {"api.sample": 1}},
                            "channels":{"stdout":[],"stderr":[],"state-and-outcome":list(raw)}}
                def captured(*arguments):
                    arguments[5].mkdir(exist_ok=True)
                    return observed
                result = subprocess.CompletedProcess([], 0, b'{"verdict":"equivalent_observed"}', b"")
                with patch.object(generation, "attempt", side_effect=captured) as attempt, \
                     patch.object(generation, "execute", return_value=result):
                    generation.compare_case(workspace, data, entry, case, folder, None)
                self.assertEqual(attempt.call_count, 7)
                bundle = generation.read(folder / "bundle.json")["cases"][0]
                self.assertEqual(len(bundle["baseline"]), 3)
                self.assertEqual(len(bundle["instrumented_on"]), 4)
                self.assertEqual(data["configuration_sha256"], generation.identity(data["configuration"]))
                data["configuration"]["limits"]["baseline_repeats"] = 5
                generation.write(workspace / generation.PLAN_FILE, data)
                marker = generation.read(workspace / generation.OWNED_MARKER)
                marker["plan_sha256"] = generation.identity(data)
                generation.write(workspace / generation.OWNED_MARKER, marker)
                with self.assertRaisesRegex(ValueError, "configuration identity"):
                    generation.load_workspace(workspace)

    def test_cleanup_refuses_unsealed_or_resealed_partial_workspaces(self):
        with tempfile.TemporaryDirectory() as temporary:
            workspace = Path(temporary) / "owned";workspace.mkdir()
            generation.write(workspace / generation.OWNED_MARKER, {"schema_version": 1})
            options = argparse.Namespace(workspace=workspace)
            with self.assertRaisesRegex(ValueError, "plan is unsealed"):
                generation.clean(options)
            generation.write(workspace / generation.PLAN_FILE, {"schema_version": 1, "source_manifest": {}})
            with self.assertRaisesRegex(ValueError, "plan identity changed"):
                generation.clean(options)
            data = generation.read(workspace / generation.PLAN_FILE)
            generation.write(workspace / generation.OWNED_MARKER, {"schema_version": 1, "plan_sha256": generation.identity(data)})
            (workspace / "snapshot").mkdir()
            (workspace / "tests").mkdir()
            (workspace / "tests/user-work").write_text("must survive")
            with self.assertRaisesRegex(ValueError, "suite is unsealed"):
                generation.clean(options)
            self.assertEqual((workspace / "tests/user-work").read_text(), "must survive")


if __name__ == "__main__":
    unittest.main()
