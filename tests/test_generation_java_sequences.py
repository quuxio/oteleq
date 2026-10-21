"""Actual Java calls retain one receiver and complete intermediate graphs."""
import argparse
import copy
import json
import os
from pathlib import Path
import shutil
import subprocess
import sys
import tempfile
import unittest

REPO = Path(__file__).resolve().parents[1]
sys.path[:0] = [str(REPO / "adapters/generation"), str(REPO / "examples"), str(REPO / "tests")]
import generation
import harness
import java_graph
import policy
import sequences
import typed_capture
from qualify_java_receivers import check_state

JAVA = os.environ.get("OTELC_JAVA") or shutil.which("java")
JAVAC = os.environ.get("OTELC_JAVAC") or shutil.which("javac")
SOURCE = '''class Counter {
 private int value;
 private static int total;
 Counter self=this;
 Object[] shared=new Object[]{this,null};
 private Counter(int start){value=start;shared[1]=shared;}
 private static Counter make(int start){return new Counter(start);}
 private Counter run(int amount){value+=amount;total+=amount;return this;}
}
'''
STEPS = [{"action": "call", "arguments": "case"}, {"action": "call", "arguments": [2]}]


class JavaSequenceTests(unittest.TestCase):
    def worker(self, source=SOURCE, steps=None, arguments=None, factory="Counter", *, execute=True):
        """Discover, freeze, compile and execute the actual generated Java caller."""
        arguments = [7] if arguments is None else arguments
        with tempfile.TemporaryDirectory() as temporary:
            folder = Path(temporary)
            (folder / "Counter.java").write_text(source)
            parsed = subprocess.run([JAVA, REPO / "adapters/generation/Discover.java", folder / "Counter.java"],
                                    cwd=folder, capture_output=True, timeout=30, check=False)
            self.assertEqual(parsed.returncode, 0, parsed.stderr)
            discovered = json.loads(parsed.stdout)
            discovered["entrypoints"] = []
            config = policy.validate({"languages": ["java"], "functions": {"include": ["Counter.run(int)"]},
                                      "fixtures": [{"function": "Counter.run(int)", "cases": [arguments],
                                                    "receiver": {"factory": factory, "arguments": [10]},
                                                    "sequence": copy.deepcopy(STEPS if steps is None else steps)}]})
            function = next(item for item in discovered["functions"] if item["name"] == "Counter.run")
            entry = generation.inventory_entry(function, discovered, "Counter.java", "java", "a" * 64,
                                               folder, argparse.Namespace(configuration=config, cases=1))
            if not execute:
                return entry
            self.assertEqual(entry["status"], "ready", entry["reason"])
            case = generation.generation_case(entry, 0, arguments)
            driver = harness.materialise(folder, entry, arguments)
            built = subprocess.run([JAVAC, "Counter.java", driver], cwd=folder, capture_output=True, timeout=30, check=False)
            self.assertEqual(built.returncode, 0, built.stderr)
            output = folder / "observation"
            run = subprocess.run([JAVA, "-Xshare:off", "-cp", folder, "OteleqDriver"], cwd=folder,
                                 env={**os.environ, "OTELEQ_OBSERVATION": str(output)},
                                 capture_output=True, timeout=10, check=False)
            self.assertEqual(run.returncode, 0, run.stderr)
            raw = json.loads(output.read_text())
            observed = typed_capture.observation(output.read_bytes(), entry,
                                                {"case_id": case["id"], "function_id": entry["otelc_function"], "fixture_sha256": "b" * 64})
            return entry, case, raw, observed, run

    def test_one_private_receiver_and_factory_preserve_every_call_state_and_alias(self):
        for factory in ("Counter", "make"):
            with self.subTest(factory=factory):
                entry, case, raw, observed, run = self.worker(factory=factory)
                self.assertEqual(run.stdout + run.stderr, b"")
                self.assertEqual(raw["java_receiver_schema_version"], 2)
                self.assertEqual([item["arguments"] for item in case["sequence"]], [[7], [2]])
                self.assertEqual([step["id"] for step in observed["steps"]], ["step-0", "step-1"])
                for step, before, after, total, amount in zip(observed["steps"], (10, 17), (17, 19), (0, 7), (7, 2)):
                    self.assertEqual((step["action"], step["gaps"]), ("call", []))
                    check_state(step["before"], before, total, amount)
                    check_state(step["after"], after, total + amount, amount)
                    check_state(step["outcome"]["graph"], after, total + amount, amount, method="identity")
                self.assertEqual(observed["before"], observed["steps"][0]["before"])
                self.assertEqual(observed["after"], observed["steps"][-1]["after"])
                self.assertEqual(observed["outcome"], observed["steps"][-1]["outcome"])
                self.assertEqual(len(sequences.contracts(case, typed_capture.required_roots(entry))), 2)

    def test_declared_intermediate_error_can_be_followed_by_a_successful_call(self):
        source = SOURCE.replace("return this;", 'if(amount!=2)throw new IllegalArgumentException("expected");return this;')
        steps = copy.deepcopy(STEPS)
        steps[0]["expected_baseline"] = {"kind": "error", "category": "exception", "type": "java.lang.IllegalArgumentException"}
        _, case, _, observed, _ = self.worker(source, steps)
        self.assertEqual([step["outcome"]["kind"] for step in observed["steps"]], ["error", "return"])
        self.assertEqual(case["expected_baseline"], {"kind": "return"})
        check_state(observed["steps"][0]["outcome"]["graph"], 17, 7, 7, method="fail")

    def test_malformed_missing_reordered_or_contradictory_actions_cannot_pass_capture(self):
        entry, _, raw, _, _ = self.worker()
        variants = []
        for name, value in (("java_receiver_schema_version", 1), ("steps", []), ("steps", {})):
            altered = copy.deepcopy(raw);altered[name] = value;variants.append(altered)
        for edit in (lambda data: data.pop("steps"),
                     lambda data: data["steps"].reverse(),
                     lambda data: data["steps"].append(copy.deepcopy(data["steps"][0])),
                     lambda data: data["steps"][0].update(action="release"),
                     lambda data: data["steps"][0].update(id="step-1"),
                     lambda data: data["steps"][0].update(extra=True),
                     lambda data: data["steps"][0]["after"]["nodes"][0]["fields"].pop("value"),
                     lambda data: data["steps"][0]["before"]["roots"]["argument:0"].update(value="8"),
                     lambda data: data["after"]["nodes"][0]["fields"]["value"].update(value="20"),
                     lambda data: data["outcome"].update(kind="error")):
            altered = copy.deepcopy(raw);edit(altered);variants.append(altered)
        for index, altered in enumerate(variants):
            encoded = json.dumps(altered).encode()
            with self.subTest(index=index), self.assertRaises(ValueError):
                java_graph.boundaries(encoded, entry)

    def test_unavailable_actions_and_invalid_fixed_inputs_remain_inventory_blockers(self):
        for steps in ([*STEPS, {"action": "release"}],
                      [*STEPS, {"action": "release"}, {"action": "collect"}],
                      [STEPS[0], {"action": "call", "arguments": [2**40]}],
                      [STEPS[0], {"action": "call", "arguments": []}]):
            entry = self.worker(steps=steps, execute=False)
            self.assertEqual(entry["status"], "blocked")
            self.assertTrue(entry["reason"])

    def test_one_and_maximum_call_schedules_and_case_reuse_keep_frozen_inputs(self):
        for steps in ([STEPS[0]], [STEPS[0]] * 32):
            _, case, _, observed, _ = self.worker(steps=steps, arguments=[0])
            self.assertEqual(len(observed["steps"]), len(steps))
            for step in observed["steps"]:
                check_state(step["after"], 10, 0, 0)
            self.assertTrue(all(step["arguments"] == [0] for step in case["sequence"]))


if __name__ == "__main__":
    unittest.main()
