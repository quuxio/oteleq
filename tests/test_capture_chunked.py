"""The explicit Node transport profile keeps chunked capture bounded and complete."""

from contextlib import closing
from http.client import HTTPConnection, HTTPResponse
from pathlib import Path
import socket
import sys
import threading
import unittest
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "examples"))
import otelc_capture as capture


class ChunkedCaptureTests(unittest.TestCase):
    def exchange(self, body: bytes, *, headers: bytes = b"Transfer-Encoding: chunked\r\n",
                 allow_chunked: bool = True, **limits):
        with capture.receiver(allow_chunked=allow_chunked, **limits) as (endpoint, bodies, errors):
            host, port = endpoint.removeprefix("http://").split(":")
            with socket.create_connection((host, int(port)), timeout=3) as connection:
                connection.sendall(b"POST /v1/traces HTTP/1.1\r\nHost: localhost\r\nConnection: close\r\n"
                                   + headers + b"\r\n" + body)
                connection.shutdown(socket.SHUT_WR)
                response = HTTPResponse(connection)
                response.begin()
                response.read()
                status = response.status
        return status, bodies, errors

    def test_complete_binary_chunks_are_recorded_as_one_exact_body(self):
        status, bodies, errors = self.exchange(b"2\r\n\x00\xff\r\n1\r\nx\r\n0\r\n\r\n")
        self.assertEqual(status, 200)
        self.assertEqual(bodies, [("/v1/traces", b"\x00\xffx")])
        self.assertFalse(errors)
        status, bodies, errors = self.exchange(b"0\r\n\r\n")
        self.assertEqual((status, bodies, errors), (200, [("/v1/traces", b"")], []))

    def test_fixed_length_requests_keep_their_existing_contract(self):
        status, bodies, errors = self.exchange(b"abc", headers=b"Content-Length: 3\r\n")
        self.assertEqual((status, bodies, errors), (200, [("/v1/traces", b"abc")], []))
        status, bodies, errors = self.exchange(b"1\r\nx\r\n0\r\n\r\n", allow_chunked=False)
        self.assertEqual((status, bodies), (400, []))
        self.assertTrue(errors)

    def test_ambiguous_or_unsupported_transfer_headers_refuse(self):
        variants = [b"Content-Length: 0\r\nTransfer-Encoding: chunked\r\n",
                    b"Transfer-Encoding: chunked\r\nTransfer-Encoding: chunked\r\n",
                    b"Transfer-Encoding: gzip, chunked\r\n", b"Transfer-Encoding: gzip\r\n",
                    b"Transfer-Encoding: chunked\r\nContent-Encoding: gzip\r\n"]
        for headers in variants:
            with self.subTest(headers=headers):
                status, bodies, errors = self.exchange(b"0\r\n\r\n", headers=headers)
                self.assertEqual((status, bodies), (400, []))
                self.assertTrue(errors)

    def test_incomplete_chunks_terminators_extensions_and_trailers_refuse(self):
        variants = [b"", b"x\r\n", b"+1\r\nx\r\n0\r\n\r\n", b"1;extension=x\r\nx\r\n0\r\n\r\n",
                    b"4\r\nx", b"1\r\nx--", b"1\r\nx\r\n", b"0\r\n",
                    b"0\r\nX-Trailer: x\r\n\r\n", b"1" * 67 + b"\r\n"]
        for body in variants:
            with self.subTest(body=body):
                status, bodies, errors = self.exchange(body)
                self.assertEqual((status, bodies), (400, []))
                self.assertTrue(errors)

    def test_chunk_and_total_body_budgets_refuse_before_recording_partial_bytes(self):
        with patch.object(capture, "MAX_REQUEST_CHUNKS", 1):
            status, bodies, errors = self.exchange(b"1\r\nx\r\n1\r\ny\r\n0\r\n\r\n")
            self.assertEqual((status, bodies), (413, []))
            self.assertTrue(errors)
        for limits in ({"max_bytes": 2}, {"max_requests": 0}):
            with self.subTest(limits=limits):
                status, bodies, errors = self.exchange(b"3\r\nxyz\r\n0\r\n\r\n", **limits)
                self.assertEqual((status, bodies), (413, []))
                self.assertTrue(errors)
        with patch.object(capture, "MAX_REQUEST_BYTES", 2):
            status, bodies, errors = self.exchange(b"3\r\nxyz\r\n0\r\n\r\n")
            self.assertEqual((status, bodies), (413, []))
            self.assertTrue(errors)

    def test_received_bytes_limit_includes_prior_chunked_requests(self):
        with capture.receiver(allow_chunked=True, max_bytes=3) as (endpoint, bodies, errors):
            statuses = []
            for _ in range(2):
                with closing(HTTPConnection(endpoint.removeprefix("http://"), timeout=3)) as connection:
                    connection.request("POST", "/v1/traces", [b"x", b"y"], encode_chunked=True)
                    response = connection.getresponse()
                    response.read()
                    statuses.append(response.status)
        self.assertEqual(statuses, [200, 413])
        self.assertEqual(bodies, [("/v1/traces", b"xy")])
        self.assertTrue(errors)

    def test_slow_chunk_header_cannot_extend_the_absolute_request_deadline(self):
        with patch.object(capture, "REQUEST_TIMEOUT", .08):
            with capture.receiver(allow_chunked=True) as (endpoint, bodies, errors):
                host, port = endpoint.removeprefix("http://").split(":")
                with socket.create_connection((host, int(port)), timeout=1) as connection:
                    connection.sendall(b"POST /v1/traces HTTP/1.1\r\nHost: localhost\r\n"
                                       b"Transfer-Encoding: chunked\r\nConnection: close\r\n\r\n")
                    stopped = threading.Event()

                    def drip():
                        for _ in range(60):
                            if stopped.is_set():
                                return
                            try:
                                connection.sendall(b"0")
                            except OSError:
                                return
                            stopped.wait(.02)

                    sender = threading.Thread(target=drip)
                    sender.start()
                    try:
                        response = HTTPResponse(connection)
                        response.begin()
                        response.read()
                        self.assertEqual(response.status, 408)
                    finally:
                        stopped.set()
                        sender.join(timeout=1)
                    self.assertFalse(sender.is_alive())
            self.assertEqual(bodies, [])
            self.assertTrue(errors)

    def test_chunked_mode_must_be_an_explicit_boolean(self):
        for value in (None, 0, 1, "true"):
            with self.subTest(value=value), self.assertRaises(ValueError):
                with capture.receiver(allow_chunked=value):
                    pass


if __name__ == "__main__":
    unittest.main()
