"""Scripted independent HTTP fixtures, exact observations and bounded failures."""
from http.client import HTTPConnection
import json
from pathlib import Path
import socket
import sys
import tempfile
import time
import unittest
from unittest.mock import MagicMock, patch
from urllib.parse import urlsplit

ROOT = Path(__file__).resolve().parents[1]
sys.path[:0] = [str(ROOT / "adapters/generation"), str(ROOT / "examples")]
import http_effects as effects
import policy


def configuration(**changes):
    return policy.validate({"effects": {"http": [{"name": "service", "environment": "APP_SERVICE_URL", "headers": ["x-check"],
                                                "responses": [{"status": 201, "hex": "00ff"}], "min_requests": 1, **changes}]}})


def exchange(url, body=b"good", path="/observe", method="POST"):
    target = urlsplit(url)
    connection = HTTPConnection(target.hostname, target.port, timeout=2)
    try:
        connection.request(method, path, body, {"x-check": "fixture"})
        response = connection.getresponse()
        return response.status, response.read()
    finally:
        connection.close()


class MemoryConnection:
    def __init__(self, data, width=4096):
        self.data, self.width = data, width

    def settimeout(self, value):
        self.timeout = value

    def recv(self, _):
        block, self.data = self.data[:self.width], self.data[self.width:]
        return block


class HttpEffectTests(unittest.TestCase):
    def test_defaults_script_bytes_and_cross_protocol_bindings_are_frozen(self):
        self.assertEqual(effects.selected(policy.validate({})), [])
        value = {"effects": {"http": [{"name": "service", "environment": "APP_SERVICE_URL", "responses": [{"hex": "00FF"}]}]}}
        selected = policy.validate(value)
        value["effects"]["http"][0]["responses"][0]["hex"] = "ff"
        self.assertEqual(effects.selected(selected)[0]["responses"][0]["hex"], "00ff")
        self.assertEqual(effects.channels(selected), ["http:service"])
        both = {"effects": {"http": [{"name": "data", "environment": "APP_DATA_DIR"}], "filesystem": [{"name": "data", "environment": "APP_DATA_DIR"}]}}
        with self.assertRaisesRegex(ValueError, "across protocols"):
            policy.validate(both)

    def test_invalid_policy_and_response_framing_refuse_before_execution(self):
        invalid = [{"name": "../service"}, {"environment": "NODE_OPTIONS"}, {"headers": "x-check"}, {"headers": ["X-Check"]},
                   {"headers": ["x-check", "x-check"]}, {"headers": ["bad:name"]}, {"headers": ["x" * 129]},
                   {"responses": []}, {"responses": {}}, {"responses": [{"hex": "f"}]}, {"responses": [{"hex": "gg"}]},
                   {"responses": [{"status": True}]}, {"responses": [{"status": 101}]},
                   {"responses": [{"status": 204, "hex": "ff"}]}, {"responses": [{"status": 205, "hex": "ff"}]},
                   {"responses": [{"status": 304, "hex": "ff"}]}, {"responses": [{"headers": {"Content-Length": "0"}}]},
                   {"responses": [{"headers": {"x": "a", "X": "b"}}]}, {"responses": [{"headers": {"x": "bad\r\n"}}]},
                   {"responses": [{"headers": {"x": "\u00ff"}}]}, {"responses": [{"headers": {"bad:key": "x"}}]},
                   {"responses": [{"unknown": 1}]}, {"responses": [{"headers": "x"}]},
                   {"responses": [{"headers": {"x": "a" * 1025}}]},
                   {"responses": [{"headers": {"x" + str(index): "a" * 1024 for index in range(9)}}]},
                   {"responses": [{"hex": "00" * 65536}, {"hex": "ff"}]},
                   {"max_requests": 0}, {"max_requests": True}, {"max_bytes": -1}, {"max_bytes": 65537},
                   {"request_timeout_ms": 49}, {"min_requests": 2}, {"unknown": True}]
        for supplied in invalid:
            with self.subTest(supplied=supplied), self.assertRaises(ValueError):
                configuration(**supplied)
        for value in ({}, [{}] * 9, [{"name": "a", "environment": "APP_A"}] * 2):
            with self.subTest(value=value), self.assertRaises(ValueError):
                policy.validate({"effects": {"http": value}})

    def test_framing_preserves_raw_target_headers_and_binary_body(self):
        settings = effects.selected(configuration())[0]
        data = b"POST /observe?x=%ff HTTP/1.1\r\nHost: fixture\r\nx-check:\tfirst \r\nX-Check: second\r\nContent-Length: 2\r\n\r\n\0\xff"
        reader = effects.Reader(MemoryConnection(data, 1), time.monotonic() + 2)
        observed = effects.request(reader, settings, 10)
        self.assertEqual(observed, {"method": "POST", "target_hex": b"/observe?x=%ff".hex(), "version": "HTTP/1.1",
                                    "header_lines_hex": [b"x-check:\tfirst ".hex(), b"X-Check: second".hex()], "body_hex": "00ff"})
        head = effects.response_wire({"status": 200, "hex": "00ff", "headers": {"X-Frozen": "yes"}}, "HEAD")
        self.assertTrue(head.endswith(b"\r\n\r\n"))
        self.assertIn(b"Content-Length: 2\r\n", head)
        self.assertIn(b"X-Frozen: yes\r\n", head)
        for status in (204, 304):
            self.assertNotIn(b"Content-Length", effects.response_wire({"status": status, "hex": "", "headers": {}}, "GET"))

    def test_malformed_truncated_oversized_and_unsupported_requests_never_complete(self):
        settings = effects.selected(configuration())[0]
        invalid = [b"BAD\r\n", b"GET http://remote/ HTTP/1.1\r\n\r\n", b"CONNECT host:443 HTTP/1.1\r\n\r\n",
                   b"GET / HTTP/2\r\n\r\n", b"GET / HTTP/1.1\r\n\r\n", b"GET / HTTP/1.1\r\nHost: x\r\nHost: y\r\n\r\n",
                   b"GET / HTTP/1.1\r\nHost: \r\n\r\n", b"GET / HTTP/1.1\r\nHost: x\r\n folded\r\n\r\n",
                   b"GET / HTTP/1.1\r\nHost: x\r\nbad\r\n\r\n", b"GET / HTTP/1.1\r\nHost: x\r\nx: \0\r\n\r\n",
                   b"POST / HTTP/1.1\r\nHost: x\r\nTransfer-Encoding: chunked\r\n\r\n0\r\n\r\n",
                   b"POST / HTTP/1.1\r\nHost: x\r\nExpect: 100-continue\r\n\r\n",
                   b"GET / HTTP/1.1\r\nHost: x\r\nUpgrade: h2c\r\n\r\n",
                   b"POST / HTTP/1.1\r\nHost: x\r\nContent-Length: -1\r\n\r\n",
                   b"POST / HTTP/1.1\r\nHost: x\r\nContent-Length: 2\r\nContent-Length: 2\r\n\r\nxx",
                   b"POST / HTTP/1.1\r\nHost: x\r\nContent-Length: 2, 2\r\n\r\nxx",
                   b"POST / HTTP/1.1\r\nHost: x\r\nContent-Length: 11\r\n\r\n01234567890",
                   b"POST / HTTP/1.1\r\nHost: x\r\nContent-Length: 2\r\n\r\nx",
                   b"GET / HTTP/1.0\r\n\r\ntrailing", b"GET / HTTP/1.1\r\nHost: x\r\n"]
        for data in invalid:
            reader = effects.Reader(MemoryConnection(data), time.monotonic() + 2)
            with self.subTest(data=data), self.assertRaises(effects.CaptureGap):
                effects.request(reader, settings, 10)
        reader = effects.Reader(MemoryConnection(b"x" * 128), time.monotonic() + 2)
        with self.assertRaisesRegex(effects.CaptureGap, "header budget"):
            reader.line(128)
        reader = effects.Reader(MemoryConnection(b"GET / HTTP/1.0\r\n\r\n"), time.monotonic() - 1)
        with self.assertRaisesRegex(effects.CaptureGap, "deadline"):
            effects.request(reader, settings, 10)

    def test_literal_binding_and_script_state_reset_across_all_four_attempts(self):
        configured = configuration(responses=[{"status": 201, "hex": "00ff"}, {"status": 202, "hex": "78"}])
        with tempfile.TemporaryDirectory() as temporary, effects.fixtures(configured) as fixtures:
            url = effects.bindings(fixtures)["APP_SERVICE_URL"]
            records = []
            for index in range(4):
                folder = Path(temporary) / str(index); folder.mkdir()
                with effects.observe(fixtures, folder, 65536) as captures:
                    self.assertEqual(exchange(url), (201, b"\0\xff"))
                    self.assertEqual(exchange(url, b"x", "/second"), (202, b"x"))
                channels, complete = effects.finish(captures)
                self.assertTrue(complete)
                records.append(channels["http:service"])
                observed = json.loads(bytes(records[-1]))
                self.assertEqual([row["response_index"] for row in observed["requests"]], [0, 1])
                self.assertEqual(observed["requests"][0]["body_hex"], b"good".hex())
                self.assertEqual(observed["requests"][0]["header_lines_hex"], [b"x-check: fixture".hex()])
                self.assertFalse(captures[0].thread.is_alive())
            self.assertTrue(all(value == records[0] for value in records))

    def test_missing_minimum_overflow_and_capture_budget_are_explicit_gaps(self):
        for supplied, calls, budget in (({}, 0, 65536), ({"max_requests": 1}, 2, 65536),
                                        ({"max_bytes": 1}, 1, 65536), ({}, 1, 1)):
            configured = configuration(**supplied)
            with self.subTest(supplied=supplied, calls=calls, budget=budget), tempfile.TemporaryDirectory() as temporary, effects.fixtures(configured) as fixtures:
                with effects.observe(fixtures, Path(temporary), budget) as captures:
                    for _ in range(calls):
                        try:
                            exchange(effects.bindings(fixtures)["APP_SERVICE_URL"])
                        except OSError:
                            # Rejection can close an unread request before the client finishes sending.
                            pass
                channels, complete = effects.finish(captures)
                self.assertFalse(complete)
                self.assertTrue(json.loads(bytes(channels["http:service"]))["gaps"])

    def test_deadline_and_eof_do_not_leave_a_live_receiver(self):
        configured = configuration(request_timeout_ms=50)
        with tempfile.TemporaryDirectory() as temporary, effects.fixtures(configured) as fixtures:
            address = fixtures[0].socket.getsockname()
            for index, fragment in enumerate((b"POST", b"POST / HTTP/1.1\r\nHost: x\r\nContent-Length: 2\r\n\r\nx")):
                folder = Path(temporary) / str(index); folder.mkdir()
                with effects.observe(fixtures, folder, 65536) as captures:
                    with socket.create_connection(address, timeout=2) as client:
                        client.sendall(fragment)
                        if index:
                            client.shutdown(socket.SHUT_WR)
                        self.assertIn(b"400 Incomplete", client.recv(4096))
                self.assertFalse(effects.finish(captures)[1])
                self.assertFalse(captures[0].thread.is_alive())

    def test_zero_request_and_multiple_fixtures_are_observed_independently(self):
        configured = policy.validate({"effects": {"http": [{"name": "a", "environment": "APP_A"}, {"name": "b", "environment": "APP_B"}]}})
        with tempfile.TemporaryDirectory() as temporary, effects.fixtures(configured) as fixtures:
            bindings = effects.bindings(fixtures)
            self.assertNotEqual(bindings["APP_A"], bindings["APP_B"])
            with effects.observe(fixtures, Path(temporary), 65536) as captures:
                self.assertEqual(exchange(bindings["APP_A"]), (200, b""))
            channels, complete = effects.finish(captures)
            self.assertTrue(complete)
            self.assertEqual(json.loads(bytes(channels["http:b"]))["requests"], [])

    def test_build_bind_failure_closes_its_socket_and_context_errors_retain_data(self):
        configured = configuration()
        broken = MagicMock(); broken.bind.side_effect = OSError("bind refused")
        selected = effects.selected(configured)[0]
        with patch.object(effects.socket, "socket", return_value=broken), self.assertRaisesRegex(OSError, "bind refused"):
            effects.Fixture(selected)
        broken.close.assert_called_once()
        with tempfile.TemporaryDirectory() as temporary, effects.fixtures(configured) as fixtures:
            with self.assertRaisesRegex(ValueError, "worker failed"):
                with effects.observe(fixtures, Path(temporary), 65536) as captures:
                    raise ValueError("worker failed")
            self.assertFalse(captures[0].thread.is_alive())
            self.assertTrue((Path(temporary) / "http-service.json").is_file())

    def test_unexpected_receiver_failure_is_a_tool_error_with_raw_records(self):
        with tempfile.TemporaryDirectory() as temporary, effects.fixtures(configuration()) as fixtures:
            with patch.object(effects.select, "select", side_effect=RuntimeError("receiver failed")), self.assertRaisesRegex(ValueError, "capture failed"):
                with effects.observe(fixtures, Path(temporary), 65536) as captures:
                    self.assertEqual(len(captures), 1)
            self.assertFalse(captures[0].thread.is_alive())
            self.assertFalse(json.loads((Path(temporary) / "http-service.json").read_text())["complete"])

    def test_cleanup_bound_cannot_report_success_when_a_receiver_does_not_stop(self):
        with tempfile.TemporaryDirectory() as temporary, effects.fixtures(configuration()) as fixtures:
            thread = MagicMock(); thread.is_alive.return_value = True
            with patch.object(effects.threading, "Thread", return_value=thread), self.assertRaisesRegex(ValueError, "capture failed"):
                with effects.observe(fixtures, Path(temporary), 65536) as captures:
                    captures[0].active = MagicMock()
                    self.assertEqual(len(captures), 1)
            captures[0].active.close.assert_called_once()
            self.assertFalse(json.loads((Path(temporary) / "http-service.json").read_text())["complete"])

    def test_failed_response_delivery_and_undrained_traffic_cannot_qualify(self):
        with tempfile.TemporaryDirectory() as temporary, effects.fixtures(configuration()) as fixtures:
            capture = effects.Capture(fixtures[0], Path(temporary), 65536)
            connection = MagicMock(); connection.sendall.side_effect = BrokenPipeError("response lost")
            record = {"method": "POST", "target_hex": "2f", "version": "HTTP/1.1", "header_lines_hex": [], "body_hex": ""}
            with patch.object(effects, "request", return_value=record):
                capture.handle(connection)
            self.assertIn("HTTP incomplete response could not be sent", capture.gaps)
            capture.stop_at = time.monotonic() - 1
            capture.run()
            self.assertTrue(fixtures[0].tainted)
            with effects.observe(fixtures, Path(temporary), 65536) as captures:
                self.assertEqual(len(captures), 1)
            self.assertFalse(effects.finish(captures)[1])


if __name__ == "__main__":
    unittest.main()
