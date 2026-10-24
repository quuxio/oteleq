"""Read the shared private TCP control descriptor and one bounded reply."""

import hashlib
import json
import math
import os
from pathlib import Path
import re
import socket
import stat
import time

from java_live import read_owned
from otelc_capture import strict_json

CONTROL_FILE = "control.json"
MAX_DESCRIPTOR = 4096


def require(condition: bool, reason: str) -> None:
    """Keep transport errors separate from each language's reply semantics."""
    if not condition:
        raise ValueError("Live control transport: " + reason)


def endpoint(path: Path, pid: int) -> tuple[dict, tuple[int, int, str]]:
    """Validate common owned metadata without retaining its authentication key."""
    parent = path.parent.lstat()
    require(path.name == CONTROL_FILE and path.parent.resolve(strict=True) == path.parent
            and stat.S_ISDIR(parent.st_mode) and parent.st_uid == os.getuid()
            and stat.S_IMODE(parent.st_mode) == 0o700, "unsafe control runtime")
    before = path.lstat()
    raw = read_owned(path, MAX_DESCRIPTOR)
    after = path.lstat()
    require((before.st_dev, before.st_ino) == (after.st_dev, after.st_ino),
            "endpoint was replaced while reading")
    value = strict_json(raw)
    require(type(value) is dict and set(value) == {"schema_version", "kind", "host", "port", "pid", "token"}
            and type(value["schema_version"]) is int and value["schema_version"] == 1
            and value["kind"] == "otelc.control.tcp" and value["host"] == "127.0.0.1"
            and type(value["port"]) is int and 1 <= value["port"] <= 65535
            and type(value["pid"]) is int and value["pid"] == pid
            and type(value["token"]) is str and re.fullmatch("[a-f0-9]{64}", value["token"]),
            "invalid private control descriptor")
    return value, (after.st_dev, after.st_ino, hashlib.sha256(raw).hexdigest())


def exchange(path: Path, command: str, pid: int, deadline: float, *, maximum: int = 4096) -> dict:
    """Read exactly one authenticated frame within the caller's case deadline."""
    require(type(deadline) in (int, float) and math.isfinite(deadline)
            and type(maximum) is int and 4096 <= maximum <= 262144, "invalid response budget")
    descriptor, identity = endpoint(path, pid)
    remaining = min(3., deadline - time.monotonic())
    require(remaining > 0, "control deadline exceeded")
    with socket.create_connection(("127.0.0.1", descriptor["port"]), timeout=remaining) as client:
        client.sendall(json.dumps({"token": descriptor["token"], "command": command}).encode("ascii") + b"\n")
        data = bytearray()
        while not data.endswith(b"\n"):
            remaining = min(3., deadline - time.monotonic())
            require(remaining > 0, "control deadline exceeded")
            client.settimeout(remaining)
            chunk = client.recv(maximum + 1 - len(data))
            require(chunk and len(data) + len(chunk) <= maximum, "incomplete or oversized control frame")
            data.extend(chunk)
        require(data.count(b"\n") == 1 and endpoint(path, pid)[1] == identity,
                "extra control frames or replaced endpoint")
    value = strict_json(bytes(data))
    require(type(value) is dict, "control reply must be an object")
    return value
