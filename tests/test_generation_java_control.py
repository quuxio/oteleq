"""Closed live-control replies, private sockets and independent state transitions."""
import copy
import json
from pathlib import Path
import socket
import sys
import tempfile
import threading
import time
import unittest
from unittest.mock import MagicMock, patch

REPO = Path(__file__).resolve().parents[1]
sys.path[:0] = [str(REPO / "adapters/generation"), str(REPO / "examples")]
import java_control as control
SOCKET = Path("/runtime/control.sock")
UNUSED = Path("/unused/control.sock")


def reply(**changes):
    return {"schema_version": 1, "pid": 123, "collection": True, "emission": True,
            "in_flight_exports": 0, "effective_emission_off": False, "completed": 7,
            "lifetime_lost": 0, **changes}


class JavaControlTests(unittest.TestCase):
    def test_incomplete_oversized_extra_or_invalid_reply_frames_refuse(self):
        variants = [b"", b"x" * 4097, b"{}\n{}\n", b'{"pid":123,"pid":123}\n',
                    json.dumps(reply(pid=124)).encode() + b"\n"]
        for payload in variants:
            connection = MagicMock()
            connection.__enter__.return_value.recv.return_value = payload
            with (self.subTest(payload=payload[:40]), patch.object(control, "endpoint", return_value=(1, 2)),
                  patch.object(control.socket, "socket", return_value=connection)):
                deadline = time.monotonic() + 1
                with self.assertRaises(ValueError):
                    control.request(SOCKET, "status", 123, deadline)

    def test_a_barrier_that_never_drains_cannot_exceed_the_record_budget(self):
        waiting = reply(collection=False, emission=False, in_flight_exports=1)
        states = [reply(), reply(collection=False), waiting, waiting]
        with (patch.object(control, "request", side_effect=states), patch.object(control, "MAX_STATUS_RECORDS", 4),
              patch.object(control.time, "sleep")):
            deadline = time.monotonic() + 1
            with self.assertRaisesRegex(ValueError, "record budget"):
                control.switch(SOCKET, 123, False, False, deadline)

    def test_closed_status_binds_real_pid_flags_counters_and_effective_barrier(self):
        self.assertEqual(control.status(reply(), 123), reply())
        disabled = reply(collection=False, emission=False, effective_emission_off=True)
        self.assertEqual(control.status(disabled, 123), disabled)
        variants = [{**reply(), "extra": 1}, {key: value for key, value in reply().items() if key != "completed"}]
        for key, value in (("schema_version", True), ("pid", 124), ("collection", 1), ("emission", None),
                           ("completed", None), ("completed", True), ("completed", -1), ("completed", 2**63),
                           ("in_flight_exports", "0"), ("effective_emission_off", True), ("lifetime_lost", 1)):
            variants.append(reply(**{key: value}))
        for value in variants:
            with self.subTest(value=value), self.assertRaises(ValueError):
                control.status(value, 123)

    def test_actual_private_socket_accepts_a_fragmented_reply_without_sdk_imports(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary).resolve();root.chmod(0o700)
            path = root / "control.sock"
            received = []
            with socket.socket(socket.AF_UNIX) as server:
                server.bind(str(path));path.chmod(0o600);server.listen(1);server.settimeout(3)
                def respond():
                    with server.accept()[0] as connection:
                        received.append(connection.recv(128))
                        raw = json.dumps(reply()).encode() + b"\n"
                        connection.sendall(raw[:10]);connection.sendall(raw[10:])
                thread = threading.Thread(target=respond)
                thread.start()
                try:
                    self.assertEqual(control.request(path, "status", 123, time.monotonic() + 2), reply())
                finally:
                    thread.join(timeout=3)
                self.assertFalse(thread.is_alive())
            self.assertEqual(received, [b"status\n"])

    def test_non_socket_symlink_or_accessible_runtime_cannot_be_queried(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary).resolve();root.chmod(0o700);path = root / "control.sock"
            path.write_bytes(b"not a socket")
            with self.assertRaises(ValueError):
                control.endpoint(path)
            path.unlink()
            with socket.socket(socket.AF_UNIX) as server:
                server.bind(str(path));path.chmod(0o666)
                with self.assertRaises(ValueError):
                    control.endpoint(path)
                path.chmod(0o600);root.chmod(0o755)
                with self.assertRaises(ValueError):
                    control.endpoint(path)
                root.chmod(0o700)
                alias = root / "alias";alias.symlink_to(root, target_is_directory=True)
                with self.assertRaises(ValueError):
                    control.endpoint(alias / "control.sock")

    def test_unknown_command_and_elapsed_deadline_refuse_before_connect(self):
        deadline = time.monotonic() + 1
        with self.assertRaises(ValueError):
            control.request(UNUSED, "off", 123, deadline)
        with patch.object(control, "endpoint", return_value=(1, 2)):
            deadline = time.monotonic() - 1
            with self.assertRaisesRegex(ValueError, "deadline"):
                control.request(UNUSED, "status", 123, deadline)

    def test_transition_waits_for_export_drain_without_altering_the_other_control(self):
        states = [reply(), reply(collection=False), reply(collection=False, emission=False, in_flight_exports=1),
                  reply(collection=False, emission=False, effective_emission_off=True)]
        with patch.object(control, "request", side_effect=states) as request:
            history = control.switch(SOCKET, 123, False, False, time.monotonic() + 1)
        self.assertEqual([row["command"] for row in history], ["status", "collection off", "emission off", "status"])
        self.assertTrue(history[-1]["status"]["effective_emission_off"])
        self.assertEqual(request.call_count, 4)

    def test_wrong_state_background_calls_and_barrier_state_changes_refuse(self):
        original = [reply(), reply(collection=False), reply(collection=False, emission=False, effective_emission_off=True)]
        variants = []
        for index, changes in ((1, {"collection": True}), (1, {"emission": False}),
                               (2, {"collection": True}), (2, {"completed": 8})):
            values = copy.deepcopy(original);values[index].update(changes);variants.append(values)
        for values in variants:
            deadline = time.monotonic() + 1
            with patch.object(control, "request", side_effect=values), self.assertRaises(ValueError):
                control.switch(SOCKET, 123, False, False, deadline)
        states = [reply(), reply(collection=False), reply(collection=False, emission=False, in_flight_exports=1),
                  reply(collection=False, emission=False, completed=8, effective_emission_off=True)]
        deadline = time.monotonic() + 1
        with patch.object(control, "request", side_effect=states), self.assertRaises(ValueError):
            control.switch(SOCKET, 123, False, False, deadline)


if __name__ == "__main__":
    unittest.main()
