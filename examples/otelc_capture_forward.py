"""Bounded opt-in OTLP/HTTP capture and forwarding to a fixed local Collector."""

from contextlib import contextmanager
from collections.abc import Iterator
from email.message import Message
import hashlib
from http.client import HTTPConnection, HTTPException, HTTPResponse
import ipaddress
import json
import math
import os
from pathlib import Path
import socket
import stat
import threading
import time
from urllib.parse import urlsplit

import otelc_capture as capture

HEADER_LIMIT = 8192
ESSENTIAL_HEADERS = ('content-type', 'content-encoding', 'content-length',
                     'transfer-encoding', 'retry-after')


def destination(value: str) -> tuple[str, int]:
    """Select one literal loopback HTTP origin, without credentials or redirects."""
    if type(value) is not str or not value or any(ord(c) <= 32 or ord(c) == 127 for c in value):
        raise ValueError('Collector destination must be an explicit loopback HTTP origin')
    parsed = urlsplit(value)
    port = 80 if parsed.port is None else parsed.port
    if (parsed.scheme != 'http' or parsed.username is not None or parsed.password is not None
            or parsed.path not in ('', '/') or parsed.query or parsed.fragment
            or not parsed.hostname or '%' in parsed.hostname
            or not ipaddress.ip_address(parsed.hostname).is_loopback or not 1 <= port <= 65535):
        raise ValueError('Collector destination must be an explicit loopback HTTP origin')
    return parsed.hostname, port


def interrupt(connection) -> None:
    """Interrupt the particular owned socket, including a stalled header read."""
    try:
        connection.shutdown(socket.SHUT_RDWR)
    except OSError:
        pass  # It may already have completed and closed before the deadline.


def expire(connection, expired: threading.Event) -> None:
    """Mark a deadline before interrupting a potentially EOF-framed response."""
    expired.set()
    interrupt(connection)


def headers(message: Message) -> list[list[str]]:
    """Retain essential original headers and bound their total encoded size."""
    rows = [[name.lower(), value] for name, value in message.raw_items()
            if name.lower() in ESSENTIAL_HEADERS]
    if (any(any(char in value for char in ('\r', '\n', '\0')) for _, value in rows)
            or sum(len(name.encode()) + len(value.encode()) for name, value in rows) > HEADER_LIMIT):
        raise ValueError('invalid or over-budget essential HTTP headers')
    return rows


def fingerprint(path: Path, *, private: bool = False) -> tuple:
    """Hold original ordinary-file bytes and non-access-time facts."""
    before = path.lstat()
    if not stat.S_ISREG(before.st_mode) or path.is_symlink():
        raise ValueError('capture evidence is not an ordinary file')
    if private and (stat.S_IMODE(before.st_mode) != 0o600 or before.st_uid != os.getuid()
                    or before.st_nlink != 1):
        raise ValueError('capture evidence must remain an owned private single-link file')
    digest = capture.file_digest(path)
    after = path.lstat()
    def facts(info):
        return (info.st_dev, info.st_ino, info.st_mode, info.st_uid, info.st_gid,
                info.st_size, info.st_mtime_ns, info.st_ctime_ns, info.st_nlink)
    if facts(before) != facts(after):
        raise ValueError('capture evidence changed while being read')
    return digest, *facts(after)


class Errors(list[str]):
    """Keep protocol failure logging bounded even after the request quota."""

    def append(self, value: object) -> None:
        if len(self) < 32:
            super().append(str(value)[:256])


class HeaderReader:
    """Bound stdlib header parsing and distinguish its terminator from EOF."""

    def __init__(self, stream):
        self.stream, self.size, self.last = stream, 0, b''

    def readline(self, limit: int = -1) -> bytes:
        data = self.stream.readline(min(HEADER_LIMIT + 1, limit) if limit >= 0 else HEADER_LIMIT + 1)
        self.size += len(data)
        self.last = data
        if self.size > HEADER_LIMIT:
            raise HTTPException('Collector response headers exceed capture budget')
        return data


class Response(HTTPResponse):
    """An EOF before the header terminator cannot become an empty HTTP200."""

    def begin(self) -> None:
        stream = self.fp
        checked = HeaderReader(stream)
        self.fp = checked
        try:
            super().begin()
        finally:
            self.fp = stream
        if checked.last not in (b'\r\n', b'\n'):
            raise HTTPException('incomplete Collector response headers')


class ForwardReceiver(capture.Receiver):
    """Use the original request framer, then relay one fixed upstream response."""

    def request_size(self) -> tuple[bool, int]:
        try:
            if self.response_event is not None:
                self.response_event['request_headers'] = headers(self.headers)
        except ValueError as error:
            raise capture.CaptureBodyError(431) from error
        if any(len(self.headers.get_all(name, [])) > 1 for name in ('Content-Type', 'Content-Encoding')):
            raise capture.CaptureBodyError(400)
        return super().request_size()

    def respond(self, status: int, body: bytes, *, origin: str, original_headers=()) -> None:
        """Record the exact response entity before attempting the client write."""
        event = self.response_event
        if event is not None:
            entity = (dict(event['upstream']['entity']) if origin == 'collector'
                      else self.server.entity(event, 'response', body))
            event['response'] = {'origin': origin, 'status': status,
                                 'entity': entity}
        self.send_response(status)
        for name, value in original_headers:
            if name in ('content-type', 'content-encoding', 'retry-after'):
                self.send_header(name, value)
        self.send_header('Content-Length', str(len(body)))
        self.end_headers()
        self.wfile.write(body)
        if event is not None:
            event['response_entity_written_ns'] = time.monotonic_ns()

    def send_error(self, code: int, message=None, explain=None) -> None:
        self.server.errors.append('HTTP request or forwarding refused: ' + str(code))
        self.respond(code, b'', origin='capture-error')

    def received_body(self, body: bytes) -> None:
        event = self.response_event
        if event is None:
            self.send_error(413)
            return
        self.record_body(body)
        try:
            event['request_entity'] = self.server.entity(event, 'request', body)
            status, response, original_headers = self.server.forward(event, self.path, body)
        except (OSError, HTTPException, ValueError) as error:
            self.server.errors.append('upstream forwarding failed: ' + type(error).__name__)
            event['forward_error'] = type(error).__name__
            event['forward_error_detail'] = (str(error)[:256] if isinstance(error, (ValueError, TimeoutError))
                                             else 'transport or capture I/O failed')
            self.respond(504 if isinstance(error, TimeoutError) else 502, b'', origin='capture-error')
            return
        if not 200 <= status < 300:
            self.server.errors.append('Collector returned HTTP ' + str(status))
        self.respond(status, response, origin='collector', original_headers=original_headers)


class ForwardCapture(capture.CaptureServer):
    """Own one serial receiver, its accepted sockets and private retained entities."""

    def __init__(self, collector_base: str, output: Path, *, max_requests: int,
                 max_bytes: int, max_response_bytes: int, allow_chunked: bool,
                 upstream_timeout: float):
        self.upstream = destination(collector_base)
        if (type(max_requests) is not int or not 1 <= max_requests <= 4096
                or type(max_bytes) is not int or not 1 <= max_bytes <= 128 * 1024**2
                or type(max_response_bytes) is not int or not 1 <= max_response_bytes <= capture.MAX_REQUEST_BYTES
                or type(allow_chunked) is not bool or type(upstream_timeout) not in (int, float)
                or not math.isfinite(upstream_timeout) or not 0 < upstream_timeout <= 10
                or not isinstance(output, Path)):
            raise ValueError('invalid bounded forwarding capture configuration')
        self.output = output.resolve()
        self.output.mkdir(mode=0o700, exist_ok=False)
        self.output.chmod(0o700)
        self.output_facts = self.output.stat().st_dev, self.output.stat().st_ino
        self.collector_base, self.upstream_timeout = collector_base, upstream_timeout
        self.max_response_bytes, self.response_bytes = max_response_bytes, 0
        self.seals = {}
        self.sources = {Path(module.__file__).resolve(): fingerprint(Path(module.__file__).resolve())
                        for module in (capture, capture.otelc_collection, capture.otelc_resource)}
        self.sources[Path(__file__).resolve()] = fingerprint(Path(__file__).resolve())
        self.stopping = threading.Event()
        self.lock = threading.Lock()
        self.inbound = self.upstream_socket = None
        self.inbound_timer = None
        self.closed = self.drained = False
        self.worker = None
        super().__init__(max_requests, max_bytes=max_bytes, allow_chunked=allow_chunked)
        self.errors = Errors()
        self.RequestHandlerClass = ForwardReceiver
        self.timeout = .05

    @property
    def endpoint(self) -> str:
        return f'http://127.0.0.1:{self.server_port}'

    def begin_response_event(self) -> dict | None:
        event = super().begin_response_event()
        if event is None:
            self.errors.append('request event budget exceeded')
        else:
            event.update(index=len(self.response_events) - 1, request_headers=[], request_entity=None,
                         upstream=None, response=None, forward_error=None, forward_error_detail=None,
                         response_entity_written_ns=None)
        return event

    def get_request(self):
        connection, address = super().get_request()
        with self.lock:
            self.inbound = connection
            self.inbound_timer = threading.Timer(capture.REQUEST_TIMEOUT + self.upstream_timeout,
                                                interrupt, args=(connection,))
            self.inbound_timer.daemon = True
            self.inbound_timer.start()
        return connection, address

    def close_request(self, connection: socket.socket) -> None:
        super().close_request(connection)
        with self.lock:
            if self.inbound is connection:
                self.inbound = None
                self.inbound_timer.cancel()
                self.inbound_timer = None

    def entity(self, event: dict, role: str, body: bytes) -> dict:
        """Publish a new private file; roles distinguish Collector and client bytes."""
        name = f"{event['index']:04d}-{role}.entity"
        descriptor = os.open(self.output / name, os.O_WRONLY | os.O_CREAT | os.O_EXCL | os.O_NOFOLLOW, 0o600)
        with os.fdopen(descriptor, 'wb') as stream:
            os.fchmod(stream.fileno(), 0o600)
            stream.write(body)
        self.seals[name] = fingerprint(self.output / name, private=True)
        return {'file': name, 'sha256': self.seals[name][0], 'size': len(body)}

    def forward(self, event: dict, path: str, body: bytes) -> tuple[int, bytes, list[list[str]]]:
        """Forward once without proxy environment, redirect following or retry."""
        forwarded_headers = {name: value for name, value in event['request_headers']
                             if name in ('content-type', 'content-encoding')}
        connection = HTTPConnection(*self.upstream, timeout=self.upstream_timeout)
        connection.response_class = Response
        upstream = {'status': None, 'headers': [], 'entity': None, 'complete': False,
                    'started_ns': time.monotonic_ns(), 'finished_ns': None}
        event['upstream'] = upstream
        response_body = bytearray()
        timer = None
        expired = threading.Event()
        deadline = time.monotonic() + self.upstream_timeout
        try:
            connection.connect()
            with self.lock:
                self.upstream_socket = connection.sock
            timer = threading.Timer(max(.001, deadline - time.monotonic()), expire,
                                    args=(connection.sock, expired))
            timer.daemon = True
            timer.start()
            connection.request('POST', path, body=body, headers=forwarded_headers)
            response = connection.getresponse()
            upstream.update(status=response.status, headers=headers(response.headers))
            lengths = response.headers.get_all('Content-Length', [])
            transfers = response.headers.get_all('Transfer-Encoding', [])
            if (len(lengths) > 1 or lengths and transfers or len(transfers) > 1
                    or lengths and (not lengths[0].isascii() or not lengths[0].isdecimal())
                    or transfers and transfers[0].strip().lower() != 'chunked'):
                raise ValueError('ambiguous Collector response framing')
            limit = min(self.max_response_bytes, self.max_bytes - self.response_bytes)
            if lengths and int(lengths[0]) > limit:
                raise ValueError('Collector response exceeds capture budget')
            while True:
                remaining = deadline - time.monotonic()
                if remaining <= 0:
                    raise TimeoutError('Collector response deadline exceeded')
                if self.upstream_socket is not None:
                    self.upstream_socket.settimeout(remaining)
                chunk = response.read1(min(65536, limit - len(response_body) + 1))
                if not chunk:
                    break
                if len(response_body) + len(chunk) > limit:
                    raise ValueError('Collector response exceeds capture budget')
                response_body.extend(chunk)
                if not response.chunked and response.length == 0:
                    break
            if lengths and len(response_body) != int(lengths[0]):
                raise ValueError('incomplete Collector response entity')
            if expired.is_set() or time.monotonic() > deadline:
                raise TimeoutError('Collector response deadline exceeded')
            upstream['complete'] = True
            return response.status, bytes(response_body), upstream['headers']
        except (OSError, HTTPException) as error:
            if expired.is_set():
                raise TimeoutError('Collector response deadline exceeded') from error
            raise
        finally:
            if timer is not None:
                timer.cancel()
            connection.close()
            with self.lock:
                self.upstream_socket = None
            self.response_bytes += len(response_body)
            upstream['entity'] = self.entity(event, 'upstream', bytes(response_body))
            upstream['finished_ns'] = time.monotonic_ns()

    def run(self) -> None:
        try:
            while not self.stopping.is_set():
                self.handle_request()
        except BaseException as error:
            self.errors.append('receiver worker failed: ' + type(error).__name__)

    def start(self) -> None:
        self.worker = threading.Thread(target=self.run, daemon=True)
        self.worker.start()

    def close(self) -> None:
        """Drain the accepted handler, then interrupt stalled sockets within a bound."""
        if self.closed:
            return
        self.stopping.set()
        self.worker.join(timeout=capture.REQUEST_TIMEOUT + self.upstream_timeout + 1)
        if self.worker.is_alive():
            self.errors.append('accepted forwarding request did not drain')
            with self.lock:
                for connection in (self.inbound, self.upstream_socket):
                    if connection is not None:
                        interrupt(connection)
            self.worker.join(timeout=1)
        self.drained = not self.worker.is_alive()
        self.server_close()
        record = {'schema_version': 1, 'kind': 'oteleq.otlp-http-forward', 'clock': 'monotonic_ns',
                  'endpoint': self.endpoint, 'collector_base': self.collector_base,
                  'closed': True, 'drained': self.drained, 'errors': list(self.errors),
                  'requests': self.requests, 'request_bytes': self.received_bytes,
                  'upstream_response_bytes': self.response_bytes, 'events': self.response_events,
                  'unrecorded_events': self.unrecorded_response_events,
                  'limits': {'max_requests': self.max_requests, 'max_request_bytes': capture.MAX_REQUEST_BYTES,
                             'max_bytes_each_direction': self.max_bytes, 'max_response_bytes': self.max_response_bytes,
                             'essential_header_bytes': HEADER_LIMIT, 'max_error_entries': 32,
                             'upstream_header_bytes': HEADER_LIMIT,
                             'upstream_timeout': self.upstream_timeout},
                  'source_inputs': {str(path): facts[0] for path, facts in self.sources.items()},
                  'scope': 'Transfer-decoded entities and essential headers; not wire packets, client acknowledgement, OTLP partial-rejection decoding or downstream ingestion proof.'}
        self.entity({'index': 0}, 'manifest', json.dumps(record, indent=2).encode() + b'\n')
        os.link(self.output / '0000-manifest.entity', self.output / 'forward-capture.json', follow_symlinks=False)
        (self.output / '0000-manifest.entity').unlink()
        self.seals.pop('0000-manifest.entity')
        self.seals['forward-capture.json'] = fingerprint(self.output / 'forward-capture.json', private=True)
        self.closed = True

    @property
    def receipt(self) -> dict:
        if not self.closed:
            raise ValueError('capture receipt requires a closed receiver')
        self.verify_files()
        return capture.strict_json((self.output / 'forward-capture.json').read_bytes())

    def verify_files(self) -> None:
        state = self.output.lstat()
        if ((state.st_dev, state.st_ino) != self.output_facts or not stat.S_ISDIR(state.st_mode)
                or stat.S_IMODE(state.st_mode) != 0o700 or state.st_uid != os.getuid()
                or {p.name for p in self.output.iterdir()} != set(self.seals)):
            raise ValueError('capture output directory changed')
        for name, expected in self.seals.items():
            if fingerprint(self.output / name, private=True) != expected:
                raise ValueError('original capture file facts changed')
        if any(fingerprint(path) != expected for path, expected in self.sources.items()):
            raise ValueError('original capture helper inputs changed')

    def require_complete(self) -> None:
        record = self.receipt
        if (not record['drained'] or record['errors'] or record['unrecorded_events']
                or any(event['response'] is None or event['handler_finished_ns'] is None
                       or event['headers_write_failed'] or event['response_entity_written_ns'] is None
                       for event in record['events'])):
            raise ValueError('incomplete capture or forwarding; inspect forward-capture.json')


@contextmanager
def forwarding_receiver(collector_base: str, output: Path, *, max_requests: int = 4096,
                        max_bytes: int = 32 * 1024**2, max_response_bytes: int = capture.MAX_REQUEST_BYTES,
                        allow_chunked: bool = True, upstream_timeout: float = 2) -> Iterator[ForwardCapture]:
    """Yield an ephemeral endpoint; inspect the final receipt after bounded drain."""
    server = ForwardCapture(collector_base, output, max_requests=max_requests, max_bytes=max_bytes,
                            max_response_bytes=max_response_bytes, allow_chunked=allow_chunked,
                            upstream_timeout=upstream_timeout)
    server.start()
    failure = None
    try:
        yield server
    except BaseException as error:
        failure = error
        raise
    finally:
        try:
            server.close()
        except BaseException as error:
            if failure is None:
                raise
            failure.add_note('forwarding capture cleanup also failed: ' + type(error).__name__)
