"""Server response evidence must stay bounded and distinct from client receipt."""
from contextlib import closing
from http.client import HTTPConnection
from http.server import BaseHTTPRequestHandler
import json
from pathlib import Path
import socket
import sys
import tempfile
import unittest
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "examples"))
import otelc_capture as capture


class HttpResponseEvidenceTests(unittest.TestCase):
    def setUp(self):
        temporary = tempfile.TemporaryDirectory()
        self.addCleanup(temporary.cleanup)
        self.path = Path(temporary.name) / "http-responses.json"

    def request(self, endpoint: str, path: str = "/v1/traces") -> int:
        with closing(HTTPConnection(endpoint.removeprefix("http://"), timeout=3)) as connection:
            connection.request("POST", path, b"\x00\xff")
            response = connection.getresponse()
            response.read()
            return response.status

    def test_complete_headers_record_server_events_without_claiming_client_acknowledgement(self):
        with capture.receiver(response_path=self.path) as (endpoint, bodies, errors):
            self.assertEqual(self.request(endpoint), 200)
        self.assertFalse(errors)
        self.assertEqual(bodies, [("/v1/traces", b"\x00\xff")])
        record = json.loads(self.path.read_text())
        self.assertEqual(record["schema_version"], 1)
        self.assertEqual(record["scope"], "server response headers; client acknowledgement is not observed")
        self.assertEqual(record["unrecorded_events"], 0)
        event, = record["events"]
        self.assertEqual(event["path"], "/v1/traces")
        self.assertEqual(event["status"], 200)
        self.assertEqual(event["body_index"], 0)
        self.assertFalse(event["headers_write_failed"])
        times = [event[name] for name in ("request_started_ns", "body_received_ns", "response_started_ns",
                                          "headers_written_ns", "handler_finished_ns")]
        self.assertTrue(all(type(value) is int and value > 0 for value in times))
        self.assertEqual(times, sorted(times))

    def test_rejected_target_records_no_body_or_unbounded_request_text(self):
        with capture.receiver(response_path=self.path) as (endpoint, bodies, errors):
            self.assertEqual(self.request(endpoint, "/foreign-secret-name"), 400)
        event, = json.loads(self.path.read_text())["events"]
        self.assertEqual(event["status"], 400)
        self.assertIsNone(event["path"])
        self.assertIsNone(event["body_index"])
        self.assertIsNone(event["body_received_ns"])
        self.assertNotIn("foreign-secret-name", self.path.read_text())
        self.assertEqual(bodies, [])
        self.assertTrue(errors)

    def test_failed_header_write_cannot_be_recorded_as_success(self):
        with patch.object(BaseHTTPRequestHandler, "end_headers", side_effect=BrokenPipeError):
            with capture.receiver(response_path=self.path) as (endpoint, bodies, errors):
                with self.assertRaises(OSError):
                    self.request(endpoint)
        event, = json.loads(self.path.read_text())["events"]
        self.assertEqual(event["status"], 200)
        self.assertEqual(event["body_index"], 0)
        self.assertTrue(event["headers_write_failed"])
        self.assertIsNone(event["headers_written_ns"])
        self.assertIsNotNone(event["handler_finished_ns"])
        self.assertEqual(bodies, [("/v1/traces", b"\x00\xff")])
        self.assertTrue(errors)

    def test_header_timeout_keeps_an_unfinished_response_visible(self):
        with patch.object(capture, "REQUEST_TIMEOUT", 0.05):
            with capture.receiver(response_path=self.path) as (endpoint, _, errors):
                host, port = endpoint.removeprefix("http://").split(":")
                with socket.create_connection((host, int(port)), timeout=3) as connection:
                    connection.sendall(b"POST /v1/traces HTTP/1.0")
                    self.assertEqual(connection.recv(4096), b"")
        event, = json.loads(self.path.read_text())["events"]
        self.assertIsNone(event["status"])
        self.assertIsNone(event["headers_written_ns"])
        self.assertIsNotNone(event["handler_finished_ns"])
        self.assertTrue(errors)

    def test_response_event_limit_is_independent_of_rejected_request_count(self):
        with capture.receiver(max_requests=1, response_path=self.path) as (endpoint, bodies, errors):
            self.assertEqual(self.request(endpoint), 200)
            self.assertEqual(self.request(endpoint), 413)
        record = json.loads(self.path.read_text())
        self.assertEqual(len(record["events"]), 1)
        self.assertEqual(record["unrecorded_events"], 1)
        self.assertEqual(len(bodies), 1)
        self.assertTrue(errors)

    def test_existing_response_file_is_never_overwritten(self):
        self.path.write_text("existing evidence\n")
        with self.assertRaises(FileExistsError):
            with capture.receiver(response_path=self.path):
                pass
        self.assertEqual(self.path.read_text(), "existing evidence\n")


if __name__ == "__main__":
    unittest.main()
