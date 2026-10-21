"""Generated Java checkpoints use one real JVM and the common cleanup budget."""
import argparse
import json
import os
from pathlib import Path
import shutil
import subprocess
import sys
import tempfile
import time
from types import SimpleNamespace as NS
import unittest
from unittest.mock import patch

REPO = Path(__file__).resolve().parents[1]
sys.path[:0] = [str(REPO / "adapters/generation"), str(REPO / "examples"), str(REPO / "tests")]
import generation
import harness
import java_control
import java_control_receipt
import java_live
import policy
import sequences
import typed_capture
from qualify_java_receivers import check_state
from test_generation_java_sequences import SOURCE
from test_generation_java_control_receipt import STATES
from test_generation_java_control_receipt import history as control_history, status as control_status

JAVA = os.environ.get("OTELC_JAVA") or shutil.which("java")
JAVAC = os.environ.get("OTELC_JAVAC") or shutil.which("javac")
STEPS = [{"action": "call", "arguments": "case" if index == 0 else [index + 1], "metrics": state.copy()}
         for index, state in enumerate(STATES)]


class JavaLiveTests(unittest.TestCase):
    def test_instrumented_session_retains_independent_setters_and_restores_emission(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary).resolve();bodies = []
            sequence = [{**step, "id": "step-" + str(index)} for index, step in enumerate(STEPS)]
            session = java_live.Session(root, root / "runtime", sequence, bodies, plain=False)
            session.pid = 123;session.record["pid"] = 123
            state, completed = STATES[0].copy(), 0
            def transition(path, pid, collection, emission, deadline):
                requested = dict(collection=collection, emission=emission)
                rows = control_history(state.copy(), requested, completed)
                state.update(requested)
                return rows
            def query(path, command, pid, deadline):
                if command == "flush" and state["emission"]:
                    bodies.append(("/v1/metrics", b"unit receipt"))
                return control_status(state, completed)
            for phase in session.phases:
                path = session.root / (phase + ".ready")
                path.write_text(session.token + " " + phase + "\n");path.chmod(0o600)
            with patch.object(java_control, "switch", side_effect=transition), patch.object(java_control, "request", side_effect=query):
                for index, size in enumerate((1, 2, 3, 4)):
                    session.before(index, time.monotonic() + 1)
                    if state["collection"]:
                        completed += size
                    session.after(index, time.monotonic() + 1)
                    session.holding["started_ns"] -= 1000000000
                    session.settle(time.monotonic() + 1)
                session.restore(time.monotonic() + 1)
            session.finish(NS(pid=123))
            entry = {"sequence_configuration": sequence}
            record = java_control_receipt.read(root, entry, 123, bodies, plain=False)
            self.assertEqual(record["restored"]["flush"]["completed"], 4)
            self.assertTrue(record["restored"]["flush"]["collection"])
            self.assertTrue(record["restored"]["flush"]["emission"])
            for index in (2, 3):
                self.assertEqual(record["steps"][index]["after"]["metric_bodies"], [])

    def test_control_metadata_and_status_histories_have_explicit_budgets(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary).resolve()
            session = java_live.Session(root, root / "runtime", [], [], plain=True)
            with self.assertRaises(ValueError):
                session.retain([{}] * (java_live.MAX_STATUSES + 1))
            session.record["extra"] = "x" * java_live.MAX_RECORD_BYTES
            with self.assertRaises(ValueError):
                session.save()

    def test_generated_private_receiver_checkpoints_complete_in_one_plain_jvm(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary).resolve();(root / "Counter.java").write_text(SOURCE)
            parsed = subprocess.run([JAVA, REPO / "adapters/generation/Discover.java", root / "Counter.java"],
                                    cwd=root, capture_output=True, timeout=30, check=False)
            self.assertEqual(parsed.returncode, 0, parsed.stderr)
            discovered = json.loads(parsed.stdout);discovered["entrypoints"] = []
            config = policy.validate({"languages": ["java"], "adapters": {"java": {"backend": "prepared"}},
                                      "functions": {"include": ["Counter.run(int)"]},
                                      "fixtures": [{"function": "Counter.run(int)", "cases": [[7]],
                                                    "receiver": {"factory": "Counter", "arguments": [10]}, "sequence": STEPS}]})
            function = next(item for item in discovered["functions"] if item["name"] == "Counter.run")
            entry = generation.inventory_entry(function, discovered, "Counter.java", "java", "a" * 64,
                                               root, argparse.Namespace(configuration=config, cases=1))
            self.assertEqual(entry["status"], "ready", entry["reason"])
            case = generation.generation_case(entry, 0, [7])
            driver = harness.materialise(root, entry, [7])
            compiled = subprocess.run([JAVAC, "Counter.java", driver], cwd=root, capture_output=True, timeout=30, check=False)
            self.assertEqual(compiled.returncode, 0, compiled.stderr)
            folder = root / "attempt";folder.mkdir()
            session = java_live.Session(folder, root / "unused-runtime", case["sequence"], [], plain=True)
            output = folder / "observation"
            environment = {**os.environ, **session.environment(), "OTELEQ_OBSERVATION": str(output)}
            with patch.object(java_control, "request", side_effect=AssertionError("plain lane queried SDK")):
                result = generation.execute([JAVA, "-Xshare:off", "-cp", root, "OteleqDriver"], root, environment,
                                             folder, timeout=10, record_process=True, interaction=session)
            self.assertEqual(result.returncode, 0, result.stderr)
            self.assertEqual(result.stdout + result.stderr, b"")
            process = json.loads((folder / "process.json").read_text())
            java_control_receipt.read(folder, entry, process["pid"], [], plain=True)
            observed = typed_capture.observation(output.read_bytes(), entry,
                                                {"case_id": case["id"], "function_id": entry["otelc_function"], "fixture_sha256": "b" * 64})
            value, total = 10, 0
            for step, amount in zip(observed["steps"], (7, 2, 3, 4)):
                check_state(step["before"], value, total, amount)
                value += amount;total += amount
                check_state(step["after"], value, total, amount)
                check_state(step["outcome"]["graph"], value, total, amount, method="identity")
            self.assertEqual((value, total), (26, 16))
            self.assertEqual(session.position, 9)

    def test_control_policy_requires_the_prepared_profile_and_a_frozen_positive_control(self):
        entry = {"language": "java", "java_backend": "prepared", "receiver_fixture": {},
                 "parameters": ["int"], "expected_baseline": {"kind": "return"}}
        steps = sequences.validate(STEPS, policy.expected_baseline)
        sequences.configure(entry, steps, harness.concrete_arguments)
        self.assertTrue(sequences.controls(entry))
        concrete = sequences.concrete(entry, [7], harness.concrete_arguments)
        self.assertEqual([row["metrics"] for row in concrete], STATES)
        concrete[0]["metrics"]["collection"] = False
        self.assertTrue(entry["sequence_configuration"][0]["metrics"]["collection"])
        for changes in ({"java_backend": "legacy"}, {"language": "javascript"}, {"language": "python"}):
            candidate = {**entry, **changes}
            with self.subTest(changes=changes), self.assertRaises(ValueError):
                sequences.configure(candidate, steps, harness.concrete_arguments)
        for altered in ([{**steps[0], "metrics": STATES[1]}], [steps[0], {"action": "call", "arguments": [2]}]):
            with self.assertRaises(ValueError):
                sequences.configure(entry, altered, harness.concrete_arguments)
        for settings in (None, {}, {"collection": 1, "emission": True}, {**STATES[0], "extra": True}):
            fixture = [{"action": "call", "arguments": "case", "metrics": settings}]
            with self.subTest(settings=settings), self.assertRaises(ValueError):
                sequences.validate(fixture, policy.expected_baseline)

    def test_unsafe_checkpoint_files_and_missing_or_extra_actions_refuse(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary).resolve();path = root / "ready"
            path.write_bytes(b"token");path.chmod(0o600)
            self.assertEqual(java_live.read_owned(path, 5), b"token")
            java_live.marker(path, b"token")
            path.chmod(0o644)
            with self.assertRaises(ValueError):
                java_live.read_owned(path, 5)
            path.chmod(0o600)
            with self.assertRaises(ValueError):
                java_live.marker(path, b"other")
            with self.assertRaises(ValueError):
                java_live.read_owned(path, 4)
            path.unlink();os.mkfifo(path, 0o600)
            with self.assertRaises(ValueError):
                java_live.read_owned(path, 5)
            path.unlink();path.symlink_to(root / "missing")
            with self.assertRaises(OSError):
                java_live.read_owned(path, 5)
            session = java_live.Session(root, root / "runtime", [{"id": "step-0", "metrics": STATES[0]}], [], plain=True)
            process = NS(pid=123)
            with self.assertRaises(ValueError):
                session.finish(process)
            session.pid = 123
            process, deadline = NS(pid=124), time.monotonic() + 1
            with self.assertRaises(ValueError):
                session.poll(process, deadline)

    def test_interaction_failure_still_reaps_the_actual_process_group(self):
        interaction = NS(poll=lambda *_: (_ for _ in ()).throw(ValueError("rendezvous failed")), finish=lambda _: None)
        with tempfile.TemporaryDirectory() as temporary:
            folder = Path(temporary)
            with patch.object(generation, "finish_process", wraps=generation.finish_process) as cleanup:
                with self.assertRaisesRegex(ValueError, "rendezvous failed"):
                    generation.execute([sys.executable, "-c", "import time;time.sleep(30)"], folder,
                                       dict(os.environ), folder / "attempt", interaction=interaction)
                cleanup.assert_called_once()
                self.assertIsNotNone(cleanup.call_args.args[0].poll())


if __name__ == "__main__":
    unittest.main()
