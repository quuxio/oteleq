"""Actual ordinary JDK readiness uses a private channel and real Java thread IDs."""

import hashlib
import os
from pathlib import Path
import shutil
import socket
import subprocess
import sys
import tempfile
import time
from types import SimpleNamespace
import unittest
from unittest.mock import patch

REPO = Path(__file__).resolve().parents[1]
sys.path[:0] = [str(REPO / "adapters/generation"), str(REPO / "examples")]
import java_action

JAVA = os.environ.get("OTELC_JAVA") or shutil.which("java")
JAVAC = os.environ.get("OTELC_JAVAC") or shutil.which("javac")
CASE, ATTEMPT = "a" * 64, "b" * 64
ACTIONS = ["c" * 64, "d" * 64, "e" * 64]


class JavaActionTests(unittest.TestCase):
    def make_harness(self, root, actions=None):
        harness = java_action.Harness(root / "wire", CASE, ATTEMPT, ACTIONS[:1] if actions is None else actions)
        self.addCleanup(harness.close)
        return harness

    def ready(self, harness, *, pid="123", thread="41", action=None):
        return (f"2 ready {harness.token} {CASE} {ATTEMPT} "
                f"{action or ACTIONS[0]} {pid} {thread}\n").encode()

    def connect(self, harness):
        channel = socket.socket(socket.AF_UNIX)
        self.addCleanup(channel.close)
        channel.settimeout(1)
        channel.connect(str(harness.path))
        return channel

    def poll_ready(self, harness, process):
        deadline = time.monotonic() + 1
        while time.monotonic() < deadline:
            value = harness.poll(process, deadline)
            if value is not None:return value
            time.sleep(.001)
        self.fail("harness readiness did not arrive")

    def test_private_wire_binds_process_thread_frozen_actions_and_one_release(self):
        with tempfile.TemporaryDirectory(dir="/tmp") as temporary:
            root = Path(temporary).resolve()
            actions = ACTIONS[:1]
            harness = self.make_harness(root, actions)
            actions[0] = "f" * 64
            process = SimpleNamespace(pid=123)
            self.assertIsNone(harness.poll(process, time.monotonic() + 1))
            channel = self.connect(harness)
            wire = self.ready(harness)
            channel.sendall(wire[:10])
            self.assertIsNone(harness.poll(process, time.monotonic() + 1))
            self.assertIsNone(harness.poll(process, time.monotonic() + 1))
            channel.sendall(wire[10:])
            value = self.poll_ready(harness, process)
            self.assertEqual((value["pid"], value["thread_id"]), (123, "41"))
            value["thread_id"] = "42"
            self.assertEqual(harness.poll(process, time.monotonic() + 1)["thread_id"], "41")
            record = harness.release(time.monotonic() + 1)
            self.assertEqual(channel.recv(512), wire.replace(b"2 ready ", b"2 release ", 1))
            self.assertEqual(record["thread_id"], "41")
            self.assertEqual(harness.position, 1)
            harness.finish(process)
            with self.assertRaises(ValueError):harness.release(time.monotonic() + 1)
            with self.assertRaises(ValueError):harness.poll(SimpleNamespace(pid=124), time.monotonic() + 1)

    def test_closed_readiness_refuses_foreign_process_action_context_or_extra_frames(self):
        changes = [lambda raw: raw.replace(b"2 ready", b"1 ready"),
                   lambda raw: raw.replace(CASE.encode(), b"f" * 64),
                   lambda raw: raw.replace(ATTEMPT.encode(), b"f" * 64),
                   lambda raw: raw.replace(ACTIONS[0].encode(), ACTIONS[1].encode()),
                   lambda raw: raw.replace(b"123 41", b"124 41"),
                   lambda raw: raw.replace(b"123 41", b"123 0"),
                   lambda raw: raw.replace(b"123 41", b"123 01"),
                   lambda raw: raw.replace(b"123 41", b"123 9223372036854775808"),
                   lambda raw: raw.replace(b"2 ready", b"2  ready"),
                   lambda raw: raw.replace(b"123 41", b"123 \xff"),
                   lambda raw: raw + raw,
                   lambda raw: b"x" * (java_action.MAX_READY + 1)]
        for change in changes:
            with self.subTest(change=change), tempfile.TemporaryDirectory(dir="/tmp") as temporary:
                harness = self.make_harness(Path(temporary).resolve())
                channel = self.connect(harness)
                channel.sendall(change(self.ready(harness)))
                with self.assertRaises(ValueError):self.poll_ready(harness, SimpleNamespace(pid=123))
                self.assertEqual(harness.records, [])

    def test_eof_missing_actions_deadlines_and_changed_endpoint_refuse(self):
        with tempfile.TemporaryDirectory(dir="/tmp") as temporary:
            harness = self.make_harness(Path(temporary).resolve())
            process = SimpleNamespace(pid=123)
            with self.assertRaises(ValueError):harness.finish(process)
            with self.assertRaises(ValueError):harness.poll(process, time.monotonic() - 1)
            with self.assertRaises(ValueError):harness.poll(SimpleNamespace(pid=True), time.monotonic() + 1)
            channel = self.connect(harness);channel.close()
            with self.assertRaises(ValueError):self.poll_ready(harness, process)
        with tempfile.TemporaryDirectory(dir="/tmp") as temporary:
            harness = self.make_harness(Path(temporary).resolve())
            harness.root.chmod(0o755)
            with self.assertRaises(ValueError):harness.poll(process, time.monotonic() + 1)
            harness.root.chmod(0o700)
            harness.path.chmod(0o666)
            with self.assertRaises(ValueError):harness.poll(process, time.monotonic() + 1)
            harness.path.unlink();harness.path.write_bytes(b"unrelated")
            with self.assertRaises(ValueError):harness.poll(process, time.monotonic() + 1)

    def test_invalid_plans_and_expired_release_cannot_create_successful_evidence(self):
        for case, attempt, actions in (("bad", ATTEMPT, ACTIONS), (CASE, "bad", ACTIONS),
                (CASE, ATTEMPT, []), (CASE, ATTEMPT, [ACTIONS[0]] * 2),
                (CASE, ATTEMPT, ["bad"]), (CASE, ATTEMPT, ACTIONS * 22)):
            with tempfile.TemporaryDirectory(dir="/tmp") as temporary, self.assertRaises(ValueError):
                java_action.Harness(Path(temporary).resolve() / "wire", case, attempt, actions)
        with self.assertRaises(ValueError):java_action.Harness(Path("relative"), CASE, ATTEMPT, ACTIONS)
        with tempfile.TemporaryDirectory(dir="/tmp") as temporary:
            root = Path(temporary).resolve()
            long = root / ("x" * 90)
            with self.assertRaises(ValueError):java_action.Harness(long, CASE, ATTEMPT, ACTIONS)
            harness = self.make_harness(root)
            channel = self.connect(harness);channel.sendall(self.ready(harness))
            self.poll_ready(harness, SimpleNamespace(pid=123))
            with self.assertRaises(ValueError):harness.release(time.monotonic() - 1)
            self.assertEqual(harness.records, [])

    def test_socket_setup_failure_closes_the_owned_descriptor(self):
        with tempfile.TemporaryDirectory(dir="/tmp") as temporary:
            root = Path(temporary).resolve()
            server = unittest.mock.Mock()
            server.bind.side_effect = OSError("bind failed")
            with patch.object(java_action.socket, "socket", return_value=server):
                with self.assertRaises(OSError):self.make_harness(root)
            server.close.assert_called_once()

    def compile(self, root, source):
        path = root / "Main.java";path.write_text(source)
        classes = root / "classes";classes.mkdir()
        result = subprocess.run([JAVAC, "-g", "-d", classes, java_action.HELPER, path], capture_output=True, timeout=30)
        self.assertEqual(result.returncode, 0, result.stderr)
        if os.environ.get("OTELEQ_JAVA_COVERAGE_CLASSES"):
            shutil.copyfile(classes / "OteleqRendezvous.class",
                            Path(os.environ["OTELEQ_JAVA_COVERAGE_CLASSES"]) / "OteleqRendezvous.class")
        return classes

    def java_command(self, classes):
        arguments = [JAVA]
        if os.environ.get("OTELEQ_JAVA_COVERAGE_AGENT"):
            arguments.append("-javaagent:" + os.environ["OTELEQ_JAVA_COVERAGE_AGENT"]
                             + "=destfile=" + os.environ["OTELEQ_JAVA_COVERAGE_EXEC"]
                             + ",append=true,includes=OteleqRendezvous")
        return [*arguments, "-Xshare:off", "-cp", classes, "Main"]

    def test_actual_jvm_private_calls_serial_actions_and_binary_application_channels(self):
        with tempfile.TemporaryDirectory(dir="/tmp") as temporary:
            root = Path(temporary).resolve()
            original = java_action.HELPER.read_bytes()
            calls = "".join('OteleqRendezvous.awaitRelease("' + action + '");value=target(value);' for action in ACTIONS)
            classes = self.compile(root, '''public final class Main {
private static int target(int value) {return value+1;}
public static void main(String[] args) throws Exception {
int value=7;
''' + calls + '''
if(value!=10)throw new AssertionError("wrong selected calls");
System.out.write(new byte[]{0,(byte)255,10});System.err.write(new byte[]{1,(byte)254,10});
java.nio.file.Files.writeString(java.nio.file.Path.of(System.getenv("OBSERVED_THREAD")),Long.toString(Thread.currentThread().threadId()));
}}
''')
            harness = self.make_harness(root, ACTIONS)
            environment = {**os.environ, **harness.environment(), "OBSERVED_THREAD": str(root / "thread")}
            with subprocess.Popen(self.java_command(classes), stdout=subprocess.PIPE,
                                  stderr=subprocess.PIPE, env=environment) as process:
                try:
                    deadline = time.monotonic() + 10
                    while process.poll() is None and time.monotonic() < deadline:
                        ready = harness.poll(process, deadline)
                        if ready is not None:harness.release(deadline)
                        time.sleep(.001)
                    stdout, stderr = process.communicate(timeout=1)
                    self.assertEqual((process.returncode, stdout, stderr), (0, b"\x00\xff\n", b"\x01\xfe\n"))
                    harness.finish(process)
                finally:
                    if process.poll() is None:process.kill();process.wait(timeout=5)
            actual = (root / "thread").read_text()
            self.assertEqual({record["thread_id"] for record in harness.records}, {actual})
            self.assertEqual({record["pid"] for record in harness.records}, {process.pid})
            self.assertEqual([record["action_id"] for record in harness.records], ACTIONS)
            self.assertEqual(hashlib.sha256(java_action.HELPER.read_bytes()).digest(), hashlib.sha256(original).digest())
            self.assertNotIn(b"io.quux.otelc", original)

    def test_actual_jvm_refuses_virtual_threads_and_wrong_release(self):
        for virtual in (False, True):
            with self.subTest(virtual=virtual), tempfile.TemporaryDirectory(dir="/tmp") as temporary:
                root = Path(temporary).resolve()
                action = 'OteleqRendezvous.awaitRelease("' + ACTIONS[0] + '");'
                body = 'try{' + action + '}catch(Exception expected){System.exit(74);}'
                if virtual:body = 'Thread thread=Thread.ofVirtual().start(()->{' + body + '});thread.join();'
                classes = self.compile(root, 'public final class Main {public static void main(String[] args) throws Exception {' + body + '}}')
                harness = self.make_harness(root)
                with subprocess.Popen(self.java_command(classes), stdout=subprocess.PIPE,
                                      stderr=subprocess.PIPE, env={**os.environ, **harness.environment()}) as process:
                    try:
                        if not virtual:
                            deadline = time.monotonic() + 5
                            while harness.poll(process, deadline) is None:time.sleep(.001)
                            expected = harness.current["ready"].replace("2 ready ", "2 release ", 1)
                            harness.connection.sendall(b"x" * len(expected.encode("ascii")))
                        stdout, stderr = process.communicate(timeout=5)
                        self.assertEqual((process.returncode, stdout, stderr), (74, b"", b""))
                        with self.assertRaises(ValueError):harness.finish(process)
                    finally:
                        if process.poll() is None:process.kill();process.wait(timeout=5)


if __name__ == "__main__":
    unittest.main()
