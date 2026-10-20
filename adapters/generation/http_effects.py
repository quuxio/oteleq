"""Bounded scripted loopback HTTP fixtures with matched per-case bindings."""
from collections.abc import Callable, Iterator
from contextlib import ExitStack, contextmanager
import json
from pathlib import Path
import re
import select
import socket
import threading
import time
from typing import Any

import filesystem_effects

PREFIX = "http:"
TOKEN = re.compile(rb"[!#$%&'*+.^_`|~0-9A-Za-z-]+")
MANAGED_HEADERS = {"content-length", "transfer-encoding", "connection", "trailer", "upgrade"}


class CaptureGap(ValueError):
    """A requested application observation cannot be captured completely."""


def header_name(value: Any, *, lowercase: bool = False) -> str:
    if type(value) is not str or not value.isascii() or not TOKEN.fullmatch(value.encode()) or len(value) > 128:
        raise ValueError("HTTP header names require bounded ASCII tokens")
    if lowercase and value != value.lower():
        raise ValueError("HTTP observed header names require lowercase tokens")
    return value


def response(value: Any, keys: Callable, integer: Callable) -> dict:
    """Freeze response bytes without allowing a second framing protocol."""
    keys(value, {"status", "hex", "headers"}, "http.responses")
    status = integer(value.get("status", 200), 200, 599, "HTTP response status")
    body = value.get("hex", "")
    if type(body) is not str or len(body) > 131072 or not re.fullmatch(r"(?:[0-9a-fA-F]{2})*", body):
        raise ValueError("HTTP response hex requires bounded complete byte pairs")
    if status in (204, 205, 304) and body:
        raise ValueError("HTTP no-content response status cannot carry a body")
    headers = value.get("headers", {})
    if type(headers) is not dict or len(headers) > 32:
        raise ValueError("HTTP response headers require a bounded table")
    selected = {}
    for name, content in headers.items():
        header_name(name)
        if name.lower() in MANAGED_HEADERS or name.lower() in selected:
            raise ValueError("HTTP response framing/duplicate header is unsupported")
        if type(content) is not str or not content.isascii() or len(content) > 1024 or any(ord(char) < 32 or ord(char) == 127 for char in content):
            raise ValueError("HTTP response header values require bounded visible ASCII")
        selected[name.lower()] = True
    if sum(len(name) + len(content) + 4 for name, content in headers.items()) > 8192:
        raise ValueError("HTTP response header budget exceeded")
    return {"status": status, "hex": body.lower(), "headers": headers.copy()}


def declaration(value: Any, keys: Callable, integer: Callable) -> dict:
    keys(value, {"name", "environment", "headers", "responses", "min_requests", "max_requests", "max_bytes", "max_header_bytes", "request_timeout_ms"}, "effects.http")
    name, environment = filesystem_effects.binding(value.get("name"), value.get("environment"))
    headers = value.get("headers", [])
    if type(headers) is not list or len(headers) > 32:
        raise ValueError("HTTP observed headers require a bounded array")
    headers = [header_name(item, lowercase=True) for item in headers]
    if len(headers) != len(set(headers)):
        raise ValueError("HTTP observed header names must be distinct")
    responses = value.get("responses", [{}])
    if type(responses) is not list or not 1 <= len(responses) <= 256:
        raise ValueError("HTTP responses require 1 through 256 scripted entries")
    responses = [response(item, keys, integer) for item in responses]
    if sum(len(item["hex"]) // 2 for item in responses) > 65536:
        raise ValueError("HTTP scripted response byte budget exceeded")
    result = {"name": name, "environment": environment, "headers": headers, "responses": responses}
    for key, default, low, high in (("max_requests", 64, 1, 256), ("max_bytes", 65536, 0, 65536),
                                    ("max_header_bytes", 8192, 128, 16384), ("request_timeout_ms", 1000, 50, 5000)):
        result[key] = integer(value.get(key, default), low, high, "http." + key)
    result["min_requests"] = integer(value.get("min_requests", 0), 0, result["max_requests"], "http.min_requests")
    if len(responses) > result["max_requests"] or result["min_requests"] > len(responses):
        raise ValueError("HTTP scripted response count conflicts with request bounds")
    return result


def settings(value: Any, keys: Callable, integer: Callable) -> list[dict]:
    if type(value) is not list or len(value) > 8:
        raise ValueError("effects.http requires at most eight fixtures")
    result = [declaration(item, keys, integer) for item in value]
    for key in ("name", "environment"):
        if len({item[key] for item in result}) != len(result):
            raise ValueError("HTTP fixture names and environments must be distinct")
    return result


def selected(configuration: dict) -> list[dict]:
    return configuration.get("effects", {}).get("http", [])


def channels(configuration: dict) -> list[str]:
    return [PREFIX + item["name"] for item in selected(configuration)]


class Reader:
    """Bound framing bytes and use one absolute deadline for the whole request."""
    def __init__(self, connection: socket.socket, deadline: float):
        self.connection, self.deadline = connection, deadline
        self.buffer = bytearray()

    def receive(self) -> None:
        remaining = self.deadline - time.monotonic()
        if remaining <= 0:
            raise CaptureGap("HTTP request deadline exceeded")
        self.connection.settimeout(remaining)
        block = self.connection.recv(4096)
        if not block:
            raise CaptureGap("HTTP request ended before its declared framing completed")
        self.buffer.extend(block)

    def line(self, limit: int) -> bytes:
        while True:
            end = self.buffer.find(b"\r\n")
            if end >= 0:
                if end + 2 > limit:
                    raise CaptureGap("HTTP header budget exceeded")
                value = bytes(self.buffer[:end]); del self.buffer[:end + 2]
                return value
            if len(self.buffer) >= limit:
                raise CaptureGap("HTTP header budget exceeded")
            self.receive()

    def body(self, length: int) -> bytes:
        while len(self.buffer) < length:
            self.receive()
        value = bytes(self.buffer[:length]); del self.buffer[:length]
        if self.buffer:
            raise CaptureGap("HTTP pipelining or unframed trailing bytes are unsupported")
        return value


def request(reader: Reader, settings_: dict, remaining: int) -> dict:
    line = reader.line(settings_["max_header_bytes"])
    parts = line.split(b" ")
    if len(parts) != 3 or not TOKEN.fullmatch(parts[0]) or parts[2] not in (b"HTTP/1.0", b"HTTP/1.1"):
        raise CaptureGap("HTTP request line requires the supported HTTP/1 profile")
    method, target, version = parts
    if method == b"CONNECT" or not (target.startswith(b"/") or method == b"OPTIONS" and target == b"*") or any(byte < 33 or byte > 126 for byte in target):
        raise CaptureGap("HTTP request target requires origin form or OPTIONS asterisk form")
    used, fields, captured = len(line) + 2, {}, []
    while True:
        line = reader.line(settings_["max_header_bytes"] - used)
        used += len(line) + 2
        if not line:
            break
        name, separator, value = line.partition(b":")
        if not separator or not TOKEN.fullmatch(name) or any(byte < 32 and byte != 9 or byte == 127 for byte in value):
            raise CaptureGap("HTTP header syntax/folding is unsupported")
        key = name.lower().decode("ascii")
        fields.setdefault(key, []).append(value.strip(b" \t"))
        if key in settings_["headers"]:
            captured.append(line.hex())
    if version == b"HTTP/1.1" and (len(fields.get("host", [])) != 1 or not fields["host"][0]):
        raise CaptureGap("HTTP/1.1 requires exactly one nonempty Host field")
    if "transfer-encoding" in fields or "expect" in fields or "upgrade" in fields:
        raise CaptureGap("HTTP transfer coding, expect/continue and upgrades require another profile")
    lengths = fields.get("content-length", [])
    if len(lengths) > 1 or lengths and (not re.fullmatch(rb"[0-9]{1,20}", lengths[0]) or int(lengths[0]) > remaining):
        raise CaptureGap("HTTP body framing/byte budget exceeded")
    length = int(lengths[0]) if lengths else 0
    body = reader.body(length)
    return {"method": method.decode("ascii"), "target_hex": target.hex(), "version": version.decode("ascii"),
            "header_lines_hex": captured, "body_hex": body.hex()}


def response_wire(value: dict, method: str) -> bytes:
    body = bytes.fromhex(value["hex"])
    lines = ["HTTP/1.1 " + str(value["status"]) + " Fixture", "Connection: close"]
    if value["status"] not in (204, 304):
        lines.append("Content-Length: " + str(len(body)))
    lines.extend(name + ": " + content for name, content in value["headers"].items())
    return ("\r\n".join(lines) + "\r\n\r\n").encode("ascii") + (b"" if method == "HEAD" else body)


class Fixture:
    """Reserve one literal loopback URL for every independent attempt of a case."""
    def __init__(self, settings_: dict):
        self.settings = settings_
        self.tainted = False
        self.socket = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        try:
            self.socket.bind(("127.0.0.1", 0))
            self.socket.listen(settings_["max_requests"])
        except OSError:
            self.socket.close()
            raise
        self.url = "http://127.0.0.1:" + str(self.socket.getsockname()[1])

    def close(self) -> None:
        self.socket.close()


class Capture:
    """Reconstruct response position/counters and retain bounded raw request records."""
    def __init__(self, fixture: Fixture, folder: Path, budget: int):
        self.fixture, self.folder, self.budget = fixture, folder, budget
        self.requests: list[dict] = []
        self.gaps: list[str] = []
        if fixture.tainted:
            self.gap("HTTP fixture has undrained traffic from an earlier incomplete attempt")
        self.bytes, self.encoded = 0, 64
        self.timeout = fixture.settings["request_timeout_ms"] / 1000
        self.stop = threading.Event()
        self.stop_at = float("inf")
        self.active: socket.socket | None = None
        self.failure: Exception | None = None
        self.thread = threading.Thread(target=self.run, daemon=True)

    def gap(self, reason: str) -> None:
        if len(self.gaps) < 8 and reason not in self.gaps:
            self.gaps.append(reason[:512])

    def handle(self, connection: socket.socket) -> None:
        settings_ = self.fixture.settings
        try:
            position = len(self.requests)
            if position >= settings_["max_requests"] or position >= len(settings_["responses"]):
                raise CaptureGap("HTTP request count or scripted response limit exceeded")
            reader = Reader(connection, min(time.monotonic() + self.timeout, self.stop_at))
            record = request(reader, settings_, settings_["max_bytes"] - self.bytes)
            wire = response_wire(settings_["responses"][position], record["method"])
            record.update(response_index=position, response_hex=wire.hex())
            self.encoded += len(json.dumps(record, separators=(",", ":"))) + 1
            if self.encoded > self.budget:
                raise CaptureGap("HTTP encoded observation budget exceeded")
            self.requests.append(record)
            self.bytes += len(record["body_hex"]) // 2
            connection.settimeout(max(0.001, reader.deadline - time.monotonic()))
            connection.sendall(wire)
        except (CaptureGap, OSError) as error:
            self.gap(str(error))
            try:
                connection.settimeout(0.05)
                connection.sendall(b"HTTP/1.1 400 Incomplete\r\nConnection: close\r\nContent-Length: 0\r\n\r\n")
            except OSError:
                self.gap("HTTP incomplete response could not be sent")

    def run(self) -> None:
        try:
            while True:
                if time.monotonic() >= self.stop_at:
                    self.fixture.tainted = True
                    self.gap("HTTP fixture queue did not drain before its deadline")
                    return
                ready, _, _ = select.select([self.fixture.socket], [], [], 0.01)
                if not ready:
                    if self.stop.is_set():
                        return
                    continue
                connection, _ = self.fixture.socket.accept()
                with connection:
                    self.active = connection
                    self.handle(connection)
                self.active = None
        except Exception as error:
            self.failure = error
            self.gap("HTTP fixture worker failed")

    def __enter__(self):
        self.thread.start()
        return self

    def __exit__(self, *_):
        self.stop_at = time.monotonic() + self.timeout
        self.stop.set()
        self.thread.join(self.timeout + 0.5)
        if self.thread.is_alive():
            self.fixture.close()
            if self.active is not None:
                self.active.close()
            self.thread.join(0.2)
            self.failure = ValueError("HTTP fixture worker did not terminate within its bound")
            self.gap(str(self.failure))
        if len(self.requests) < self.fixture.settings["min_requests"]:
            self.gap("HTTP fixture observed fewer than the declared minimum requests")
        self.raw = json.dumps({"http_schema_version": 1, "complete": not self.gaps, "requests": self.requests, "gaps": self.gaps}, sort_keys=True, separators=(",", ":")).encode()
        (self.folder / ("http-" + self.fixture.settings["name"] + ".json")).write_bytes(self.raw)
        if self.failure is not None:
            raise ValueError("HTTP fixture capture failed; inspect retained records") from self.failure


@contextmanager
def fixtures(configuration: dict) -> Iterator[list[Fixture]]:
    with ExitStack() as stack:
        result = []
        for item in selected(configuration):
            fixture = Fixture(item)
            stack.callback(fixture.close)
            result.append(fixture)
        yield result


def bindings(fixtures_: list[Fixture]) -> dict[str, str]:
    return {item.settings["environment"]: item.url for item in fixtures_}


@contextmanager
def observe(fixtures_: list[Fixture], folder: Path, budget: int) -> Iterator[list[Capture]]:
    with ExitStack() as stack:
        result = [stack.enter_context(Capture(item, folder, budget)) for item in fixtures_]
        yield result


def finish(captures: list[Capture]) -> tuple[dict[str, list[int]], bool]:
    return {PREFIX + item.fixture.settings["name"]: list(item.raw) for item in captures}, all(not item.gaps for item in captures)
