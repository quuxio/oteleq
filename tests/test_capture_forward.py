"""A local forwarding witness must retain bytes and refuse incomplete delivery."""

from contextlib import contextmanager
from http.client import HTTPConnection, HTTPResponse
from http.server import BaseHTTPRequestHandler, HTTPServer
from pathlib import Path
import socket
import stat
import sys
import tempfile
import threading
import time
import unittest
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'examples'))
import otelc_capture_forward as forward


class CollectorHandler(BaseHTTPRequestHandler):
    def do_POST(self):
        body = self.rfile.read(int(self.headers['Content-Length']))
        self.server.calls.append((self.path, body, dict(self.headers)))
        mode = self.server.mode
        try:
            if mode in ('headers-hang', 'headers-eof'):
                self.wfile.write(b'HTTP/1.0 200 OK\r\nContent-Length: 0\r\n')
                self.wfile.flush()
                if mode == 'headers-hang':
                    self.server.release.wait(2)
                return
            self.send_response(self.server.status)
            self.send_header('Content-Type', 'application/x-protobuf')
            self.send_header('Retry-After', '5')
            if mode in ('chunked', 'ambiguous'):
                self.send_header('Transfer-Encoding', 'chunked')
            if mode not in ('chunked', 'eof-hang'):
                size = len(self.server.body) + (1 if mode == 'short' else 0)
                self.send_header('Content-Length', str(size))
            self.end_headers()
            if mode == 'chunked':
                body = self.server.body
                self.wfile.write(f'{len(body):x}\r\n'.encode() + body + b'\r\n0\r\n\r\n')
            else:
                self.wfile.write(self.server.body)
            self.wfile.flush()
            if mode == 'eof-hang':
                self.server.release.wait(2)
        except OSError:
            pass  # Tests deliberately interrupt slow or malformed responses.

    def log_message(self, *_):
        pass


@contextmanager
def collector(*, status=200, body=b'\x00\xffresponse', mode='normal'):
    server = HTTPServer(('127.0.0.1', 0), CollectorHandler)
    server.status, server.body, server.mode, server.calls = status, body, mode, []
    server.release = threading.Event()
    worker = threading.Thread(target=server.serve_forever, kwargs={'poll_interval': .01}, daemon=True)
    worker.start()
    try:
        yield server
    finally:
        server.release.set()
        server.shutdown()
        server.server_close()
        worker.join(timeout=3)


class ForwardCaptureTests(unittest.TestCase):
    def setUp(self):
        temporary = tempfile.TemporaryDirectory()
        self.addCleanup(temporary.cleanup)
        self.base = Path(temporary.name).resolve()

    def capture(self, upstream, **kwargs):
        return forward.forwarding_receiver(f'http://127.0.0.1:{upstream.server_port}',
                                           self.base / 'capture', **kwargs)

    def post(self, captured, body=b'\x00\xffrequest', *, path='/v1/traces'):
        connection = HTTPConnection('127.0.0.1', captured.server_port, timeout=3)
        try:
            connection.request('POST', path, body=body, headers={
                'Content-Type': 'application/x-protobuf', 'Authorization': 'not-retained'})
            response = connection.getresponse()
            return response.status, response.read(), dict(response.getheaders())
        finally:
            connection.close()

    def raw(self, captured, request):
        with socket.create_connection(('127.0.0.1', captured.server_port), timeout=3) as connection:
            connection.sendall(request)
            connection.shutdown(socket.SHUT_WR)
            response = HTTPResponse(connection)
            response.begin()
            return response.status, response.read()

    def test_exact_entities_status_headers_timing_and_fresh_private_receipt(self):
        with collector() as upstream:
            with self.capture(upstream) as captured:
                with self.assertRaises(ValueError): captured.receipt
                status, body, response_headers = self.post(captured)
                self.assertEqual((status, body), (200, upstream.body))
                self.assertEqual(response_headers['retry-after'], '5')
            captured.require_complete()
            record = captured.receipt
            record['events'].clear()
            event, = captured.receipt['events']
            self.assertEqual(upstream.calls[0][:2], ('/v1/traces', b'\x00\xffrequest'))
            self.assertNotIn('Authorization', upstream.calls[0][2])
            self.assertNotIn('not-retained', (captured.output / 'forward-capture.json').read_text())
            self.assertEqual((captured.output / event['request_entity']['file']).read_bytes(), b'\x00\xffrequest')
            self.assertEqual((captured.output / event['upstream']['entity']['file']).read_bytes(), upstream.body)
            self.assertEqual(event['response']['entity'], event['upstream']['entity'])
            self.assertTrue(event['upstream']['complete'])
            self.assertLessEqual(event['request_started_ns'], event['body_received_ns'])
            self.assertLessEqual(event['upstream']['started_ns'], event['upstream']['finished_ns'])
            self.assertLessEqual(event['headers_written_ns'], event['response_entity_written_ns'])
            self.assertLessEqual(event['response_entity_written_ns'], event['handler_finished_ns'])
            self.assertEqual(stat.S_IMODE(captured.output.stat().st_mode), 0o700)
            for path in captured.output.iterdir():
                self.assertEqual(stat.S_IMODE(path.stat().st_mode), 0o600)
                self.assertEqual(path.stat().st_nlink, 1)
            self.assertFalse(captured.worker.is_alive())
            captured.close()

    def test_chunked_requests_and_responses_keep_original_entity_bytes(self):
        with collector(mode='chunked') as upstream:
            with self.capture(upstream) as captured:
                status, body = self.raw(captured, b'POST /v1/metrics HTTP/1.1\r\nHost: local\r\n'
                    b'Transfer-Encoding: chunked\r\nContent-Type: application/x-protobuf\r\n\r\n'
                    b'2\r\n\x00\xff\r\n1\r\nx\r\n0\r\n\r\n')
            captured.require_complete()
            self.assertEqual((status, body), (200, upstream.body))
            self.assertEqual(upstream.calls[0][:2], ('/v1/metrics', b'\x00\xffx'))
            event, = captured.receipt['events']
            self.assertIn(['transfer-encoding', 'chunked'], event['upstream']['headers'])

    def test_collector_failure_is_relayed_without_a_synthetic_success(self):
        with collector(status=503, body=b'not accepted') as upstream:
            with self.capture(upstream) as captured:
                status, body, _ = self.post(captured)
            self.assertEqual((status, body), (503, b'not accepted'))
            with self.assertRaises(ValueError): captured.require_complete()
            event, = captured.receipt['events']
            self.assertEqual(event['response']['origin'], 'collector')
            self.assertTrue(event['upstream']['complete'])

    def test_connection_refusal_retains_attempt_and_returns_failure(self):
        with socket.socket() as probe:
            probe.bind(('127.0.0.1', 0))
            port = probe.getsockname()[1]
        with forward.forwarding_receiver(f'http://127.0.0.1:{port}', self.base / 'capture') as captured:
            status, body, _ = self.post(captured)
        self.assertEqual((status, body), (502, b''))
        with self.assertRaises(ValueError): captured.require_complete()
        event, = captured.receipt['events']
        self.assertIsNone(event['upstream']['status'])
        self.assertFalse(event['upstream']['complete'])
        self.assertEqual(event['response']['origin'], 'capture-error')

    def test_truncated_or_ambiguous_response_never_becomes_an_acknowledgement(self):
        for mode in ('short', 'ambiguous', 'headers-eof'):
            with self.subTest(mode=mode), collector(mode=mode) as upstream:
                folder = self.base / mode
                with forward.forwarding_receiver(f'http://127.0.0.1:{upstream.server_port}', folder) as captured:
                    status, _, _ = self.post(captured)
                self.assertEqual(status, 502)
                with self.assertRaises(ValueError): captured.require_complete()
                event, = captured.receipt['events']
                self.assertEqual(event['upstream']['status'], None if mode == 'headers-eof' else 200)
                self.assertFalse(event['upstream']['complete'])

    def test_header_and_eof_dribble_deadlines_cannot_look_like_empty_success(self):
        for mode in ('headers-hang', 'eof-hang'):
            with self.subTest(mode=mode), collector(mode=mode) as upstream:
                with forward.forwarding_receiver(f'http://127.0.0.1:{upstream.server_port}', self.base / mode,
                                                upstream_timeout=.05) as captured:
                    status, _, _ = self.post(captured)
                self.assertEqual(status, 504)
                with self.assertRaises(ValueError): captured.require_complete()
                self.assertFalse(captured.worker.is_alive())

    def test_response_and_aggregate_budgets_refuse_instead_of_truncating_success(self):
        with collector(body=b'12345') as upstream:
            with self.capture(upstream, max_response_bytes=4) as captured:
                status, _, _ = self.post(captured)
            self.assertEqual(status, 502)
            with self.assertRaises(ValueError): captured.require_complete()
        with collector(body=b'123') as upstream:
            with forward.forwarding_receiver(f'http://127.0.0.1:{upstream.server_port}', self.base / 'second',
                                            max_bytes=4) as captured:
                self.assertEqual(self.post(captured, b'a')[0], 200)
                self.assertEqual(self.post(captured, b'b')[0], 502)
            with self.assertRaises(ValueError): captured.require_complete()
            self.assertLessEqual(captured.receipt['upstream_response_bytes'], 4)

    def test_request_quota_and_malformed_framing_never_reach_collector(self):
        with collector(body=b'') as upstream:
            with self.capture(upstream, max_requests=1) as captured:
                self.assertEqual(self.post(captured, b'a')[0], 200)
                self.assertEqual(self.post(captured, b'b')[0], 413)
            self.assertEqual(len(upstream.calls), 1)
            with self.assertRaises(ValueError): captured.require_complete()
        with collector() as upstream:
            with forward.forwarding_receiver(f'http://127.0.0.1:{upstream.server_port}', self.base / 'malformed') as captured:
                status, _ = self.raw(captured, b'POST /v1/traces HTTP/1.1\r\nHost: local\r\n'
                    b'Content-Length: 0\r\nTransfer-Encoding: chunked\r\n\r\n0\r\n\r\n')
            self.assertEqual(status, 400)
            self.assertFalse(upstream.calls)
            with self.assertRaises(ValueError): captured.require_complete()

    def test_invalid_destination_configuration_and_existing_output_refuse_before_bind(self):
        destinations = (None, 'https://127.0.0.1:4320', 'http://localhost:4320', 'http://192.0.2.1',
                        'http://user:secret@127.0.0.1', 'http://127.0.0.1:0', 'http://127.0.0.1/x',
                        'http://127.0.0.1?x=1', 'http://127.0.0.1#x', ' http://127.0.0.1')
        for value in destinations:
            with self.subTest(value=value), self.assertRaises(ValueError):
                with forward.forwarding_receiver(value, self.base / 'invalid'):
                    self.fail('invalid destination admitted')
            self.assertFalse((self.base / 'invalid').exists())
        for change in ({'max_requests': True}, {'max_requests': 4097}, {'max_bytes': 0},
                       {'max_response_bytes': False}, {'allow_chunked': 1}, {'upstream_timeout': float('nan')}):
            with self.subTest(change=change), self.assertRaises(ValueError):
                with forward.forwarding_receiver('http://127.0.0.1:4320', self.base / 'invalid', **change):
                    self.fail('invalid configuration admitted')
        self.assertEqual(forward.destination('http://[::1]:4320/'), ('::1', 4320))
        with self.assertRaises(FileExistsError):
            with forward.forwarding_receiver('http://127.0.0.1:4320', self.base): pass

    def test_restored_entities_added_files_and_helper_changes_cannot_refresh_receipt(self):
        with collector(body=b'') as upstream:
            with self.capture(upstream) as captured:
                self.post(captured)
            captured.require_complete()
            path = captured.output / captured.receipt['events'][0]['request_entity']['file']
            raw = path.read_bytes()
            path.write_bytes(raw + b' changed')
            path.write_bytes(raw)
            with self.assertRaises(ValueError): captured.require_complete()
        with collector(body=b'') as upstream:
            with forward.forwarding_receiver(f'http://127.0.0.1:{upstream.server_port}', self.base / 'extra') as captured:
                self.post(captured)
            (captured.output / 'extra').write_bytes(b'not captured')
            with self.assertRaises(ValueError): captured.require_complete()

    def test_body_error_stays_primary_and_receiver_is_stopped(self):
        failure = KeyboardInterrupt('controlled cancellation')
        with collector() as upstream:
            with self.assertRaises(KeyboardInterrupt) as caught:
                with self.capture(upstream) as captured:
                    raise failure
        self.assertIs(caught.exception, failure)
        self.assertFalse(captured.worker.is_alive())
        captured.require_complete()

    def test_unsupported_methods_and_header_limits_never_forward(self):
        requests = [b'GET /v1/traces HTTP/1.0\r\n\r\n',
                    b'POST /v1/traces HTTP/1.0\r\nContent-Length: 0\r\nContent-Type: a\r\nContent-Type: b\r\n\r\n',
                    b'POST /v1/traces HTTP/1.0\r\nContent-Length: 0\r\nContent-Type: ' + b'x' * 8200 + b'\r\n\r\n']
        with collector() as upstream:
            for index, request in enumerate(requests):
                with forward.forwarding_receiver(f'http://127.0.0.1:{upstream.server_port}', self.base / str(index)) as captured:
                    status, _ = self.raw(captured, request)
                self.assertIn(status, (400, 431, 501))
                with self.assertRaises(ValueError): captured.require_complete()
            self.assertFalse(upstream.calls)

    def test_event_quota_cannot_be_bypassed_with_non_post_requests(self):
        with collector() as upstream:
            with self.capture(upstream, max_requests=1) as captured:
                self.raw(captured, b'GET /v1/traces HTTP/1.0\r\n\r\n')
                self.assertEqual(self.post(captured)[0], 413)
            self.assertFalse(upstream.calls)
            self.assertEqual(captured.receipt['unrecorded_events'], 1)
            with self.assertRaises(ValueError): captured.require_complete()

    def test_changed_helper_private_mode_and_output_directory_refuse(self):
        with collector() as upstream:
            with self.capture(upstream) as captured:
                helper = self.base / 'held-helper.py'
                helper.write_bytes(b'# held helper\n')
                captured.sources[helper] = forward.fingerprint(helper)
            captured.require_complete()
            helper.write_bytes(b'# changed helper\n')
            with self.assertRaises(ValueError): captured.require_complete()
        with collector() as upstream:
            with forward.forwarding_receiver(f'http://127.0.0.1:{upstream.server_port}', self.base / 'mode') as captured:
                self.post(captured)
            captured.output.chmod(0o755)
            with self.assertRaises(ValueError): captured.require_complete()
            captured.output.chmod(0o700)
        with self.assertRaises(ValueError): forward.fingerprint(self.base)

    def test_header_folding_and_unowned_or_linked_evidence_refuse(self):
        from email.message import Message
        message = Message()
        message['Content-Type'] = 'application/x-protobuf\r\nforged: value'
        with self.assertRaises(ValueError): forward.headers(message)
        path = self.base / 'body'
        path.write_bytes(b'body')
        path.chmod(0o644)
        with self.assertRaises(ValueError): forward.fingerprint(path, private=True)

    def test_worker_failure_is_not_an_empty_success_and_cleanup_keeps_primary_error(self):
        with patch.object(forward.ForwardCapture, 'handle_request', side_effect=RuntimeError('worker failed')):
            with forward.forwarding_receiver('http://127.0.0.1:4320', self.base / 'worker') as captured:
                captured.worker.join(timeout=1)
            with self.assertRaises(ValueError): captured.require_complete()
        failure = KeyboardInterrupt('body cancelled')
        original_close = forward.ForwardCapture.close
        def failing_close(server):
            original_close(server)
            raise OSError('close failed after stop')
        with patch.object(forward.ForwardCapture, 'close', failing_close), self.assertRaises(KeyboardInterrupt) as caught:
            with forward.forwarding_receiver('http://127.0.0.1:4320', self.base / 'cleanup'):
                raise failure
        self.assertIs(caught.exception, failure)
        self.assertTrue(any('OSError' in note for note in failure.__notes__))

    def test_slow_incoming_headers_have_an_absolute_stop_boundary(self):
        with patch.object(forward.capture, 'REQUEST_TIMEOUT', .03), \
                forward.forwarding_receiver('http://127.0.0.1:4320', self.base / 'slow', upstream_timeout=.03) as captured:
            with socket.create_connection(('127.0.0.1', captured.server_port), timeout=1) as client:
                for byte in b'POST /v1/traces HTTP/1.0\r\n':
                    try:
                        client.sendall(bytes([byte]))
                    except OSError:
                        break
                    time.sleep(.01)
        self.assertFalse(captured.worker.is_alive())
        with self.assertRaises(ValueError): captured.require_complete()

    def test_final_manifest_never_overwrites_an_existing_file(self):
        with self.assertRaises(FileExistsError):
            with forward.forwarding_receiver('http://127.0.0.1:4320', self.base / 'existing') as captured:
                manifest = captured.output / 'forward-capture.json'
                manifest.write_bytes(b'earlier evidence')
        self.assertEqual(manifest.read_bytes(), b'earlier evidence')
        self.assertFalse(captured.worker.is_alive())
        with self.assertRaises(ValueError): captured.require_complete()


if __name__ == '__main__':
    unittest.main()
