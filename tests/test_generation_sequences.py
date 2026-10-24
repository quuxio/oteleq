"""Frozen call/release/collection schedules and actual independent Node workers."""
import argparse
import copy
import json
import os
from pathlib import Path
import shutil
import struct
import subprocess
import sys
import tempfile
import unittest

REPO = Path(__file__).resolve().parents[1]
sys.path[:0] = [str(REPO / "adapters/generation"), str(REPO / "examples")]
import generation
import harness
import policy
import sequences
import typed_capture

NODE = os.environ.get("OTELC_NODE") or shutil.which("node")
SOURCE = """class Counter {
 constructor(start){this.value=start;this.alias=this;}
 add(value){this.value+=value;return this;}
}
function make(start){return new Counter(start);}
"""
STEPS = [{"action": "call", "arguments": "case"}, {"action": "call", "arguments": [2]},
         {"action": "release"}, {"action": "collect", "gc_rounds": 16, "settle_turns": 4}]


class SequenceTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.dependencies = tempfile.TemporaryDirectory()
        cls.addClassCleanup(cls.dependencies.cleanup)
        cls.provider = Path(cls.dependencies.name)
        package = cls.provider / "adapters/node"
        package.mkdir(parents=True)
        (package / "package.json").write_text('{"private":true}')
        (package / "node_modules").mkdir()
        (package / "node_modules/typescript").symlink_to(REPO / "ci/markdownlint/node_modules/typescript", target_is_directory=True)

    def candidate(self, folder, source=SOURCE, steps=None, path="sample.mjs", factory="Counter"):
        (folder / path).write_text(source)
        parsed = subprocess.run([NODE, REPO / "adapters/generation/discover.mjs", self.provider],
                                input=json.dumps({"filename": path, "source": source}).encode(),
                                capture_output=True, timeout=30, check=False)
        self.assertEqual(parsed.returncode, 0, parsed.stderr)
        discovered = json.loads(parsed.stdout)
        discovered["entrypoints"] = []
        config = policy.validate({"languages": ["javascript"], "functions": {"include": ["sample.Counter.add"]},
                                  "fixtures": [{"function": "sample.Counter.add", "cases": [[7]],
                                                "receiver": {"factory": factory, "arguments": [10]},
                                                "sequence": copy.deepcopy(STEPS if steps is None else steps)}]})
        function = next(item for item in discovered["functions"] if item["name"] == "Counter.add")
        entry = generation.inventory_entry(function, discovered, path, "javascript", "a" * 64,
                                           folder, argparse.Namespace(configuration=config, cases=1))
        self.assertEqual(entry["status"], "ready", entry["reason"])
        return entry

    def worker(self, source=SOURCE, steps=None, path="sample.mjs", factory="Counter", expose=True):
        with tempfile.TemporaryDirectory() as temporary:
            folder = Path(temporary)
            entry = self.candidate(folder, source, steps, path, factory)
            case = generation.generation_case(entry, 0, [7.0])
            driver = harness.materialise(folder, entry, case["arguments"])
            output = folder / "observation"
            flags = ["--expose-gc"] if expose else []
            result = subprocess.run([NODE, *flags, driver], cwd=folder,
                                    env={**os.environ, "OTELEQ_OBSERVATION": str(output)},
                                    capture_output=True, timeout=30, check=False)
            capture = json.loads(output.read_text()) if output.exists() else None
            if capture is None:
                return result, None, None, entry
            roots = typed_capture.required_roots(entry)
            contract = {"case_id": case["id"], "function_id": entry["otelc_function"], "fixture_sha256": "b" * 64}
            typed = typed_capture.observation(output.read_bytes(), entry, contract)
            self.assertEqual(len(sequences.contracts(case, roots)), len(case["sequence"]))
            return result, capture, typed, entry

    def test_calls_release_and_actual_collection_preserve_intermediate_state_and_aliases(self):
        for path in ("sample.mjs", "sample.cjs"):
            with self.subTest(path=path):
                result, raw, typed, _ = self.worker(path=path)
                self.assertEqual(result.returncode, 0, result.stderr)
                self.assertEqual(result.stdout, b"")
                self.assertEqual([step["action"] for step in raw["steps"]], ["call", "call", "release", "collect"])
                self.assertTrue(raw["steps"][-1]["collection"]["completed"])
                self.assertTrue(all(not step["gaps"] for step in typed["steps"]))
                self.assertEqual(typed["steps"][2]["after"]["roots"]["receiver"], {"kind": "null"})
                for step, expected in zip(typed["steps"][:2], (17, 19)):
                    graph = step["outcome"]["graph"]
                    self.assertEqual(graph["roots"]["result"], graph["roots"]["receiver"])
                    value = next(node for node in graph["nodes"] if node["id"] == graph["roots"]["receiver"]["node_id"])["fields"]["property:value"]
                    self.assertEqual(struct.unpack('>d', bytes.fromhex(value["bits"]))[0], expected)

    def test_uncollected_application_reference_is_a_gap_not_a_leak_or_matching_result(self):
        source = SOURCE.replace(" constructor(start)", " static held=null;\n constructor(start)").replace("this.value=start;", "Counter.held=this;this.value=start;")
        steps = copy.deepcopy(STEPS)
        steps[-1].update(gc_rounds=2, settle_turns=1)
        result, raw, typed, _ = self.worker(source, steps)
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertFalse(raw["steps"][-1]["collection"]["completed"])
        self.assertIn("not observed", typed["steps"][-1]["gaps"][0]["reason"])
        self.assertFalse(typed["steps"][-1]["outcome"]["graph"]["roots"]["result"]["value"])

    def test_fixed_calls_and_schedule_are_frozen_and_missing_gc_cannot_succeed(self):
        result, capture, _, _ = self.worker(expose=False)
        self.assertNotEqual(result.returncode, 0)
        self.assertIsNone(capture)
        self.assertIn(b'--expose-gc', result.stderr)
        steps = sequences.validate(STEPS, policy.expected_baseline)
        entry = {"language": "javascript", "parameters": ["number"], "receiver_fixture": {}, "expected_baseline": {"kind": "return"}}
        sequences.configure(entry, steps, harness.concrete_arguments)
        concrete = sequences.concrete(entry, [7.0], harness.concrete_arguments)
        self.assertEqual([step.get("arguments") for step in concrete[:2]], [[7.0], [2.0]])
        concrete[0]["arguments"][0] = 0
        self.assertEqual(entry["sequence_configuration"][0]["arguments"], "case")

    def test_async_factory_steps_carry_selected_creation_identity_and_missing_events_stay_required(self):
        result, _, typed, entry = self.worker(SOURCE.replace(" add(value)", " async add(value)"), factory="make")
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertEqual(sequences.creator(entry), "sample.make")
        provider = generation.policy(entry, "http://127.0.0.1:1234")
        self.assertIn('"sample.make"', provider)
        self.assertIn('[lifetimes]', provider)
        expected = sequences.expected_functions(entry, {"sample.Counter.add": 2})
        self.assertEqual(expected["sample.Counter lifetime"], 1)
        self.assertTrue(all(not step["gaps"] for step in typed["steps"]))

    def test_collection_uses_captured_native_gc_and_weakref_operations(self):
        source = 'globalThis.gc=()=>{throw Error("APPLICATION GC HOOK")};WeakRef.prototype.deref=()=>{throw Error("APPLICATION WEAK HOOK")};\n' + SOURCE
        result, raw, _, _ = self.worker(source)
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertTrue(raw["steps"][-1]["collection"]["completed"])

    def test_commonjs_hoisted_require_cannot_run_as_an_observer_bootstrap(self):
        with tempfile.TemporaryDirectory() as temporary:
            folder = Path(temporary)
            with self.assertRaisesRegex(AssertionError, "unshadowed module require"):
                self.candidate(folder, "function require(){throw Error('APPLICATION HOOK')}\n" + SOURCE, path="sample.cjs")

    def test_collection_raw_metadata_cannot_contradict_results_or_requested_bounds(self):
        result, raw, _, entry = self.worker()
        self.assertEqual(result.returncode, 0, result.stderr)
        variants = []
        changed = copy.deepcopy(raw); changed["steps"][-1]["collection"]["rounds"] = 65; variants.append(changed)
        changed = copy.deepcopy(raw); changed["steps"][-1]["collection"]["completed"] = False; variants.append(changed)
        changed = copy.deepcopy(raw)
        changed["steps"][-1]["collection"]["completed"] = False
        changed["steps"][-1]["outcome"]["value"]["roots"]["result"] = {"type": "boolean", "value": False}
        variants.append(changed)
        for capture in variants:
            with self.subTest(capture=capture["steps"][-1]["collection"]), self.assertRaisesRegex(ValueError, "collection evidence"):
                typed_capture.dynamic_steps(capture, entry)

    def test_malformed_schedules_and_unavailable_requested_adapters_refuse(self):
        invalid = [None, [], [{}], [1], [{"action": "release"}], [{"action": "collect"}],
                   [{"action": "call", "arguments": {}}], [{"action": "call", "arguments": [float('nan')]}],
                   [{"action": "call", "arguments": [1]}], [STEPS[0], STEPS[2], STEPS[0]],
                   [*STEPS, STEPS[-1]], [*STEPS[:-1], {"action": "collect", "gc_rounds": True}],
                   [*STEPS[:-1], {"action": "collect", "settle_turns": 0}],
                   [{**STEPS[0], "typo": 1}], [STEPS[0]] * 33]
        for value in invalid:
            with self.subTest(value=value), self.assertRaises(ValueError):
                sequences.validate(value, policy.expected_baseline)
        valid = sequences.validate(STEPS, policy.expected_baseline)
        for entry in ({"language": "python", "receiver_fixture": {}}, {"language": "typescript", "receiver_fixture": {}}, {"language": "javascript"}):
            with self.subTest(entry=entry), self.assertRaises(ValueError):
                sequences.configure(entry, valid, harness.concrete_arguments)
        with self.assertRaisesRegex(ValueError, "declared receiver"):
            policy.validate({"fixtures": [{"function": "x", "cases": [[1]], "sequence": STEPS}]})

    def test_go_calls_require_source_provider_and_refuse_unimplemented_actions_and_controls(self):
        calls = sequences.validate([{"action": "call", "arguments": "case"},
                                    {"action": "call", "arguments": [4]}], policy.expected_baseline)
        entry = {"language": "go", "go_backend": "source-v1", "receiver_fixture": {}, "parameters": ["int"],
                 "expected_baseline": {"kind": "return"}}
        sequences.configure(entry, calls, harness.concrete_arguments)
        self.assertEqual([step["arguments"] for step in sequences.concrete(entry, [3], harness.concrete_arguments)], [[3], [4]])
        with self.assertRaisesRegex(ValueError, "explicit source-v1"):
            sequences.configure({**entry, "go_backend": "legacy"}, calls, harness.concrete_arguments)
        for steps in ([*calls, {"action": "release"}], [{**calls[0], "metrics": {"collection": True, "emission": True}}]):
            with self.assertRaises(ValueError):
                sequences.configure(entry, steps, harness.concrete_arguments)


if __name__ == "__main__":
    unittest.main()
