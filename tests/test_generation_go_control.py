"""Go controls bind real TCP replies and paused health to one native process."""

import copy
import json
from pathlib import Path
import socketserver
import sys
import tempfile
import threading
import time
import unittest
from unittest.mock import patch

REPO = Path(__file__).resolve().parents[1]
sys.path[:0] = [str(REPO / "adapters/generation"), str(REPO / "examples")]
import go_control as control
from test_generation_go_health import PID, POLICY, SELECTION, report

OPTIONS = {"policy_sha256": POLICY, "selection_sha256": SELECTION}


def status(collection=True, emission=True):
    return {"schema_version": 1, "pid": PID, "collection": collection, "emission": emission,
            "effective_emission_off": not emission}


def live(collection=True, emission=True):
    value = report()
    value.update(phase="running", controls=status(collection, emission),
                 lifecycle={"flush": "not_started", "shutdown": "not_started"})
    for key in control.health.PROBES - {"function_started", "function_ended"}:
        value["probe_accounting"][key] = "0"
    for key in ("probe_accounting", "metric_exports", "trace_exports", "http_spans"):
        value[key]["closed"] = False
    return value


class Reply(socketserver.StreamRequestHandler):
    def handle(self):
        self.server.requests.append(json.loads(self.rfile.readline(1025)))
        self.wfile.write(self.server.reply)


class GoControlTests(unittest.TestCase):
    def test_closed_status_accepts_all_states_and_refuses_coerced_or_unbound_values(self):
        for collection in (False, True):
            for emission in (False, True):
                value = status(collection, emission)
                self.assertIs(control.status(value, PID), value)
        for value in (None, {}, {**status(), "extra": 1}, {key: item for key, item in status().items() if key != "collection"}):
            with self.assertRaises(ValueError):
                control.status(value, PID)
        for key, replacements in {"schema_version": (True, 1.0, 2), "pid": (True, PID + 1),
                                  "collection": (0, 1), "emission": (0, 1),
                                  "effective_emission_off": (0, True)}.items():
            for replacement in replacements:
                with self.subTest(key=key, replacement=replacement), self.assertRaises(ValueError):
                    control.status({**status(), key: replacement}, PID)
        for pid in (True, 1, 2**31):
            with self.assertRaises(ValueError):
                control.status(status(), pid)

    def test_live_health_requires_quiescent_selected_probes_but_not_atomic_export_snapshots(self):
        for collection in (False, True):
            for emission in (False, True):
                value = live(collection, emission)
                self.assertIs(control.live(value, PID, **OPTIONS), value)
        value = live()
        value["trace_exports"].update(attempts="1", succeeded="2", queue_pending="3")
        self.assertIs(control.live(value, PID, **OPTIONS), value)
        for section, key, replacement in ((None, "pid", PID + 1), (None, "phase", "final"),
                (None, "policy_sha256", "0" * 64), (None, "selection_sha256", "0" * 64),
                ("lifecycle", "shutdown", "pending"), ("probe_accounting", "function_active", "1"),
                ("probe_accounting", "function_ended", "2"), ("probe_accounting", "function_lost", "1"),
                ("probe_accounting", "observer_ended", "1"), ("probe_accounting", "closed", True),
                ("probe_accounting", "objects_pending", "1"), ("metric_flush", "failed_attempts", "1"),
                ("metric_exports", "failed", "1"), ("trace_exports", "queue_dropped", "1"),
                ("trace_exports", "closed", True), ("http_spans", "started", "1"),
                ("http_spans", "closed", True)):
            changed = live()
            (changed if section is None else changed[section])[key] = replacement
            with self.subTest(section=section, key=key), self.assertRaises(ValueError):
                control.live(changed, PID, **OPTIONS)
        value = live()
        value["trace_exports"] = value["http_spans"] = {"observed": False}
        with self.assertRaises(ValueError):
            control.live(value, PID, **OPTIONS)

    def test_each_command_uses_its_closed_reply_and_bounded_frame(self):
        path = Path("/runtime/control.json")
        for command in control.COMMANDS:
            value = live() if command == "health" else status()
            with patch.object(control.live_control, "exchange", return_value=value) as exchange:
                self.assertIs(control.request(path, command, PID, 99, **OPTIONS), value)
            self.assertEqual(exchange.call_args.kwargs, {"maximum": 65536 if command == "health" else 4096})
        with patch.object(control.live_control, "exchange") as exchange:
            for command in ("on", "off", "unknown", None, []):
                with self.assertRaises(ValueError):
                    control.request(path, command, PID, 99, **OPTIONS)
            exchange.assert_not_called()

    def test_independent_setters_cover_every_state_and_refuse_a_changed_other_flag(self):
        for collection in (False, True):
            for emission in (False, True):
                current = status()
                def request(path, command, pid, deadline, **options):
                    self.assertEqual(options, OPTIONS)
                    if command != "status":
                        key, setting = command.split()
                        current[key] = setting == "on"
                        current["effective_emission_off"] = not current["emission"]
                    return copy.deepcopy(current)
                requested = {"collection": collection, "emission": emission}
                with patch.object(control, "request", side_effect=request):
                    history = control.switch(Path("unused"), PID, requested, 99, **OPTIONS)
                self.assertEqual([row["command"] for row in history], ["status",
                                 "collection " + ("on" if collection else "off"),
                                 "emission " + ("on" if emission else "off")])
                self.assertEqual(history[-1]["response"], status(collection, emission))
        with patch.object(control, "request", side_effect=[status(), status(False, False)]), self.assertRaises(ValueError):
            control.switch(Path("unused"), PID, {"collection": False, "emission": False}, 99, **OPTIONS)
        with patch.object(control, "request") as request:
            for value in (None, {}, {"collection": 0, "emission": False}, {**status(), "collection": True}):
                with self.assertRaises(ValueError):
                    control.switch(Path("unused"), PID, value, 99, **OPTIONS)
            request.assert_not_called()

    def test_actual_loopback_frames_authenticate_and_reject_wrong_or_incomplete_replies(self):
        replies = [("status", status()), ("health", live()), ("status", {}), ("health", report()),
                   ("status", b"{}\n{}\n"), ("status", b"x" * 4097), ("status", b"")]
        for command, reply in replies:
            with self.subTest(command=command, reply=reply), tempfile.TemporaryDirectory() as temporary:
                root = Path(temporary).resolve()
                with socketserver.TCPServer(("127.0.0.1", 0), Reply) as server:
                    server.requests = []
                    server.reply = json.dumps(reply).encode() + b"\n" if type(reply) is dict else reply
                    descriptor = {"schema_version": 1, "kind": "otelc.control.tcp", "host": "127.0.0.1",
                                  "port": server.server_address[1], "pid": PID, "token": "b" * 64}
                    path = root / "control.json"
                    path.write_text(json.dumps(descriptor))
                    path.chmod(0o600)
                    thread = threading.Thread(target=server.handle_request)
                    thread.start()
                    try:
                        if reply == status() or reply == live():
                            self.assertEqual(control.request(path, command, PID, time.monotonic() + 3, **OPTIONS), reply)
                        else:
                            with self.assertRaises(ValueError):
                                control.request(path, command, PID, time.monotonic() + 3, **OPTIONS)
                    finally:
                        thread.join(timeout=4)
                    self.assertFalse(thread.is_alive())
                    self.assertEqual(server.requests, [{"command": command, "token": descriptor["token"]}])
