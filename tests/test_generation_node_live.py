"""Real generated Node calls yield to host checkpoints without inventing SDK data."""

import copy
import json
import os
from pathlib import Path
import shutil
import struct
import sys
import tempfile
import time
from types import SimpleNamespace
import unittest
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[1]
sys.path[:0] = [str(ROOT / "adapters/generation"), str(ROOT / "examples")]
import generation
import harness
import node_control
import node_control_receipt
import node_live
import node_source_worker
import policy
import sequences
import typed_capture
from node_control_fixture import status
import test_generation_sequences as sequence_tests
from test_generation_node_control_receipt import STATES

NODE = os.environ.get("OTELC_NODE") or shutil.which("node")
STEPS = [{"action": "call", "arguments": "case" if index == 0 else [index + 1], "metrics": state.copy()}
         for index, state in enumerate(STATES)]


class NodeLiveTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.dependencies = tempfile.TemporaryDirectory()
        cls.addClassCleanup(cls.dependencies.cleanup)
        cls.provider = Path(cls.dependencies.name)
        package = cls.provider / "adapters/node/node_modules"
        package.mkdir(parents=True)
        (package / "typescript").symlink_to(ROOT / "ci/markdownlint/node_modules/typescript", target_is_directory=True)

    def supervisor(self, folder, driver, *, delay_receipt=False):
        """The controlled plain fixture launches a real independent Node PID."""
        return [sys.executable, "-I", "-B", "-c",
                'import os,subprocess,sys,time;from pathlib import Path;sys.path[:0]='
                + repr([str(ROOT / "adapters/generation"), str(ROOT / "examples")])
                + ';from node_source_worker import write;'
                'folder=Path(sys.argv[1]);app=subprocess.Popen(sys.argv[2:]);'
                + ('time.sleep(.25);' if delay_receipt else '')
                + 'write(folder/"node-source-application.json",{"pid":app.pid,"supervisor_pid":os.getpid(),"group":os.getpgrp()});'
                'result=app.wait();'
                'write(folder/"node-source-completion.json",{"application_pid":app.pid,"sdk_pid":None});'
                'sys.exit(result)', folder, NODE, driver]

    def test_checkpoint_waits_for_delayed_atomic_application_pid_publication(self):
        with tempfile.TemporaryDirectory() as temporary:
            folder = Path(temporary).resolve();project = folder / "project";project.mkdir()
            sequence = [{"id": "step-0", "action": "call", "metrics": STATES[0]}]
            session = node_live.Session(folder, sequence, [], language="javascript", plain=True)
            driver = project / "driver.mjs"
            driver.write_text('import {checkpoint} from ' + json.dumps((ROOT / 'adapters/generation/node_checkpoint.mjs').as_uri())
                              + ';await checkpoint("before-0");await checkpoint("after-0");await checkpoint("finish");')
            result = generation.execute(self.supervisor(folder, driver, delay_receipt=True), project,
                                        {**os.environ, **session.environment()}, folder, timeout=5,
                                        record_process=True, interaction=session)
            self.assertEqual(result.returncode, 0, result.stderr)
            self.assertEqual(result.stdout + result.stderr, b"")
            self.assertEqual(session.position, 3)
            self.assertNotEqual(session.record["pid"], session.record["supervisor_pid"])
            self.assertIsNone(session.record["sdk_pid"])
            self.assertFalse(list(folder.glob('*.staging')))

    def test_pid_binding_waits_until_the_publication_staging_link_is_removed(self):
        with tempfile.TemporaryDirectory() as temporary:
            folder = Path(temporary).resolve()
            session = node_live.Session(folder, [], [], language="javascript", plain=True)
            session.supervisor = 100
            application = folder / "node-source-application.json"
            staged = application.with_name(application.name + ".staging")
            node_source_worker.write(application, {"pid": 101, "supervisor_pid": 100, "group": 100})
            os.link(application, staged)
            self.assertFalse(session.bind_application())
            self.assertIsNone(session.pid)
            staged.unlink()
            with patch.object(node_live.os, "getpgid", return_value=100):
                self.assertTrue(session.bind_application())
            self.assertEqual(session.pid, 101)

    def test_actual_generated_plain_sequence_completes_every_checkpoint_and_keeps_state(self):
        with tempfile.TemporaryDirectory() as temporary:
            folder = Path(temporary).resolve()
            project = folder / "project";project.mkdir()
            entry = sequence_tests.SequenceTests.candidate(self, project, steps=[{"action": "call", "arguments": "case"}])
            entry["node_backend"] = "source-v1"
            sequences.configure(entry, sequences.validate(STEPS, policy.expected_baseline), harness.concrete_arguments)
            case = generation.generation_case(entry, 0, [7.])
            driver = harness.materialise(project, entry, case["arguments"])
            environment = {**os.environ, "OTELEQ_OBSERVATION": str(folder / "observation")}
            options = generation.execution_options(entry, case, "baseline", folder, None, [], environment)
            with patch.object(node_control, "request", side_effect=AssertionError("plain queried SDK")):
                result = generation.execute(self.supervisor(folder, driver), project, environment, folder,
                                            timeout=15, **options)
            self.assertEqual(result.returncode, 0, result.stderr)
            self.assertEqual(result.stdout + result.stderr, b"")
            record = node_control_receipt.read(folder, entry, [], plain=True)
            self.assertEqual(options["interaction"].position, 9)
            self.assertEqual(len(record["steps"]), 4)
            observed = json.loads((folder / "observation").read_bytes())
            self.assertEqual(len(observed["steps"]), 4)
            self.assertTrue(all(not step["gaps"] for step in observed["steps"]))
            typed = typed_capture.observation((folder / "observation").read_bytes(), entry,
                                             {"case_id": case["id"], "function_id": entry["otelc_function"], "fixture_sha256": "b" * 64})
            for step, expected in zip(typed["steps"], (17, 19, 22, 26)):
                graph = step["outcome"]["graph"]
                self.assertEqual(graph["roots"]["result"], graph["roots"]["receiver"])
                node = next(value for value in graph["nodes"] if value["id"] == graph["roots"]["receiver"]["node_id"])
                self.assertEqual(struct.unpack('>d', bytes.fromhex(node["fields"]["property:value"]["bits"]))[0], expected)
            self.assertEqual(len(list((folder / "node-rendezvous").iterdir())), 18)

    def test_instrumented_host_retains_actual_states_and_restores_both_flags(self):
        with tempfile.TemporaryDirectory() as temporary:
            folder = Path(temporary).resolve();bodies = []
            steps = [{**step, "id": "step-" + str(index)} for index, step in enumerate(STEPS)]
            session = node_live.Session(folder, steps, bodies, language="javascript", plain=False)
            session.supervisor, session.pid = 100, 101
            current = status()
            def request(path, command, pid, deadline):
                if command not in ("status", "flush"):
                    key, flag = command.split()
                    current[key] = flag == "on"
                    current["effective_emission_off"] = not current["emission"]
                if command == "flush" and all(current[key] for key in ("collection", "emission")):
                    bodies.append(("/v1/metrics", b"controlled protocol fixture"))
                return copy.deepcopy(current)
            with patch.object(node_control, "request", side_effect=request), patch.object(node_live.os, "getpgid", return_value=100), \
                    patch.object(node_live.time, "monotonic_ns", side_effect=[0, 1000000000] * 4):
                for index in range(4):
                    session.before(index, time.monotonic() + 5)
                    current["function_completions"] += 1
                    session.after(index, time.monotonic() + 5)
                    session.settle(time.monotonic() + 5)
                session.restore(time.monotonic() + 5)
            self.assertEqual(session.position, 9)
            self.assertEqual(session.sdk_pid, 102)
            self.assertEqual([step["requested"] for step in session.record["steps"]], STATES)
            self.assertTrue(session.record["restored"]["flush"]["collection"])
            self.assertTrue(session.record["restored"]["flush"]["emission"])
            self.assertEqual(session.record["restored"]["flush"]["function_completions"], 4)
            self.assertNotIn(session.token, (folder / node_live.RECORD).read_text())

    def test_missing_checkpoints_changed_process_and_record_budgets_refuse(self):
        with tempfile.TemporaryDirectory() as temporary:
            folder = Path(temporary).resolve()
            session = node_live.Session(folder, [], [], language="javascript", plain=True)
            process = SimpleNamespace(pid=100)
            session.poll(process, time.monotonic() + 1)
            with self.assertRaises(ValueError):
                session.finish(process)
            foreign, deadline = SimpleNamespace(pid=101), time.monotonic() + 1
            with self.assertRaises(ValueError):
                session.poll(foreign, deadline)
            with patch.object(node_live, "MAX_RECORD_BYTES", 1), self.assertRaises(ValueError):
                session.save()
            session.statuses = node_control.MAX_STATUSES
            reply = {"command": "status", "status": status()}
            with self.assertRaises(ValueError):
                session.retain([reply])

    def test_live_policy_requires_explicit_source_backend_and_complete_call_states(self):
        base = {"language": "javascript", "node_backend": "source-v1", "receiver_fixture": {},
                "parameters": ["number"], "expected_baseline": {"kind": "return"}}
        steps = sequences.validate(STEPS, policy.expected_baseline)
        for language in ("javascript", "typescript"):
            entry = {**base, "language": language}
            sequences.configure(entry, steps, harness.concrete_arguments)
            self.assertTrue(sequences.controls(entry))
        for changed in ({"node_backend": "legacy"}, {"language": "python"}):
            with self.assertRaises(ValueError):
                sequences.configure({**base, **changed}, steps, harness.concrete_arguments)
        for schedule in ([{**steps[0], "metrics": STATES[1]}], [steps[0], {"action": "release"}],
                         [steps[0], {"action": "call", "arguments": [2]}]):
            with self.assertRaises(ValueError):
                sequences.configure(base, schedule, harness.concrete_arguments)

    def test_generator_identity_binds_the_execution_journal_verifier_and_new_controls(self):
        original = generation.generator_identity()
        digest = generation.capture.file_digest
        for name in ("node_execution.py", "node_control.py", "node_control_receipt.py", "node_live.py", "node_checkpoint.mjs"):
            def changed(path):
                return "0" * 64 if Path(path).name == name else digest(path)
            with self.subTest(name=name), patch.object(generation.capture, "file_digest", side_effect=changed):
                self.assertNotEqual(generation.generator_identity(), original)
