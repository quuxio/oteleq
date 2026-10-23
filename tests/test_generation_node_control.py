"""Live Node controls require real private framing and independent flag setters."""

import copy
import json
import os
from pathlib import Path
import socketserver
import sys
import tempfile
import threading
import time
import unittest
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[1]
sys.path[:0] = [str(ROOT / "adapters/generation"), str(ROOT / "examples")]
import node_control as control
from node_control_fixture import status


class Reply(socketserver.StreamRequestHandler):
    def handle(self):
        self.server.requests.append(json.loads(self.rfile.readline(1025)))
        self.wfile.write(self.server.reply)


class NodeControlTests(unittest.TestCase):
    def test_live_status_requires_actual_flags_counters_identity_and_no_losses(self):
        self.assertEqual(control.status(status(), 101), status())
        changes = {"schema_version": True, "pid": 102, "sdk_pid": 101, "phase": "closed", "language": "python",
                   "launch_id": "bad", "collection": 1, "emission": 0, "effective_emission_off": True,
                   "function_completions": False, "active_functions": 1, "export_failed": 1,
                   "in_flight_exports": -1, "native_callback_failures": 1, "lifetime_lost": 1, "handoff_incomplete": 1}
        for key, value in changes.items():
            changed = {**status(), key: value}
            with self.subTest(key=key), self.assertRaises(ValueError):
                control.status(changed, 101)
        for changed in (None, {}, {**status(), "runtime_losses": {}},
                        {**status(), "runtime_losses": {**status()["runtime_losses"], "invalid": True}},
                        {**status(), "handoff": {**status()["handoff"], "accepted": 0}},
                        {**status(), "handoff": {**status()["handoff"], "sdk_process_failed": True}}):
            with self.assertRaises(ValueError):
                control.status(changed, 101)
        changed = {**status(), "language": []}
        with self.assertRaises(ValueError):
            control.status(changed, 101)

    def descriptor(self, root, port=1):
        filename = root / "control.json"
        value = {"schema_version": 1, "kind": "otelc.control.tcp", "host": "127.0.0.1", "port": port,
                 "pid": 101, "token": "b" * 64}
        filename.write_text(json.dumps(value))
        filename.chmod(0o600)
        return filename, value

    def test_only_the_fixed_private_descriptor_can_select_a_loopback_endpoint(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary).resolve()
            filename, value = self.descriptor(root)
            self.assertEqual(control.endpoint(filename, 101)[0], value)
            for key, replacement in (("schema_version", True), ("host", "localhost"), ("port", True),
                                     ("port", 0), ("pid", 102), ("token", "bad"), ("kind", "other")):
                filename.write_text(json.dumps({**value, key: replacement}))
                with self.subTest(key=key), self.assertRaises(ValueError):
                    control.endpoint(filename, 101)
            filename.write_text(json.dumps(value))
            filename.chmod(0o644)
            with self.assertRaises(ValueError):
                control.endpoint(filename, 101)
            filename.chmod(0o600)
            root.chmod(0o755)
            with self.assertRaises(ValueError):
                control.endpoint(filename, 101)
            root.chmod(0o700)
            alias = root / "alias"
            alias.symlink_to(filename)
            with self.assertRaises(ValueError):
                control.endpoint(alias, 101)
            deadline, expired = time.monotonic() + 1, time.monotonic() - 1
            with self.assertRaises(ValueError):
                control.request(filename, "on", 101, deadline)
            with self.assertRaises(ValueError):
                control.request(filename, "status", 101, expired)

    def test_actual_tcp_frames_are_authenticated_bounded_and_process_bound(self):
        replies = [json.dumps(status()).encode() + b"\n", b"{}\n{}\n", b"x" * 4097, b"", b"{}\n"]
        for index, reply in enumerate(replies):
            with self.subTest(index=index), tempfile.TemporaryDirectory() as temporary:
                root = Path(temporary).resolve()
                with socketserver.TCPServer(("127.0.0.1", 0), Reply) as server:
                    server.reply, server.requests = reply, []
                    filename, descriptor = self.descriptor(root, server.server_address[1])
                    thread = threading.Thread(target=server.handle_request)
                    thread.start()
                    deadline = time.monotonic() + 3
                    try:
                        if index == 0:
                            self.assertEqual(control.request(filename, "status", 101, time.monotonic() + 3), status())
                        else:
                            with self.assertRaises(ValueError):
                                control.request(filename, "status", 101, deadline)
                    finally:
                        thread.join(timeout=4)
                    self.assertFalse(thread.is_alive())
                    self.assertEqual(server.requests, [{"command": "status", "token": descriptor["token"]}])

    def test_setters_preserve_the_other_flag_and_wait_for_actual_export_drain(self):
        current = status()
        def request(path, command, pid, deadline):
            if command != "status":
                key, setting = command.split()
                current[key] = setting == "on"
                current["effective_emission_off"] = not current["emission"]
            return copy.deepcopy(current)
        with patch.object(control, "request", side_effect=request):
            rows = control.switch(Path("unused"), 101, {"collection": False, "emission": False}, time.monotonic() + 1)
        self.assertEqual([row["command"] for row in rows], ["status", "collection off", "emission off"])
        self.assertFalse(rows[-1]["status"]["collection"])
        active = status(collection=False, emission=False)
        active.update(in_flight_exports=1, effective_emission_off=False, export_started=1)
        drained = {**active, "in_flight_exports": 0, "effective_emission_off": True, "export_succeeded": 1}
        with patch.object(control, "request", side_effect=[status(), status(collection=False), active, drained]):
            rows = control.switch(Path("unused"), 101, {"collection": False, "emission": False}, time.monotonic() + 1)
        self.assertEqual(len(rows), 4)
        for replies in ([status(), status(collection=False, emission=False)],
                        [status(), status(1, collection=False)]):
            filename, deadline = Path("unused"), time.monotonic() + 1
            with patch.object(control, "request", side_effect=replies), self.assertRaises(ValueError):
                control.switch(filename, 101, {"collection": False, "emission": False}, deadline)
