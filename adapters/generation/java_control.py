"""Bounded independent client for the frozen Java SDK's live metric controls."""
import os
from pathlib import Path
import socket
import stat
import time
from typing import cast

from otelc_capture import strict_json

FIELDS = {"schema_version", "pid", "collection", "emission", "in_flight_exports",
          "effective_emission_off", "completed", "lifetime_lost"}
COMMANDS = {"status", "flush", "collection on", "collection off", "emission on", "emission off"}
MAX_REPLY = 4096
MAX_COUNTER = 2**63 - 1
MAX_STATUS_RECORDS = 256


def require(condition: bool, reason: str) -> None:
    """Unavailable or contradictory control evidence cannot qualify a live state."""
    if not condition:
        raise ValueError("Java metric controls: " + reason)


def status(value: object, pid: int) -> dict:
    """Bind a closed actual reply to the launched JVM and its effective barrier."""
    require(type(value) is dict and set(value) == FIELDS, "invalid status fields")
    value = cast(dict, value)
    require(type(value["schema_version"]) is int and value["schema_version"] == 1
            and type(value["pid"]) is int and type(pid) is int and value["pid"] == pid and pid > 0, "status process or schema differs")
    require(all(type(value[name]) is bool for name in ("collection", "emission", "effective_emission_off")),
            "invalid collection/emission flags")
    require(all(type(value[name]) is int and 0 <= value[name] <= MAX_COUNTER
                for name in ("in_flight_exports", "completed", "lifetime_lost")), "unknown or invalid control counters")
    require(value["effective_emission_off"] == (not value["emission"] and value["in_flight_exports"] == 0),
            "effective emission-off barrier contradicts exporter state")
    require(value["lifetime_lost"] == 0, "control reports lost lifetime observations")
    return value


def endpoint(path: Path) -> tuple[int, int]:
    """Only the known private runtime and its owned Unix socket can be queried."""
    parent, info = path.parent.lstat(), path.lstat()
    require(path.name == "control.sock" and path.parent.resolve() == path.parent
            and stat.S_ISDIR(parent.st_mode) and parent.st_uid == os.getuid()
            and stat.S_IMODE(parent.st_mode) == 0o700, "unsafe control runtime")
    require(stat.S_ISSOCK(info.st_mode) and info.st_uid == os.getuid()
            and info.st_mode & 0o077 == 0, "unsafe control socket")
    return info.st_dev, info.st_ino


def request(path: Path, command: str, pid: int, deadline: float) -> dict:
    """Read exactly one bounded newline frame within the shared case deadline."""
    require(command in COMMANDS, "unsupported control command")
    identity = endpoint(path)
    remaining = min(3., deadline - time.monotonic())
    require(remaining > 0, "control deadline exceeded")
    with socket.socket(socket.AF_UNIX) as client:
        client.settimeout(remaining)
        client.connect(str(path))
        require(endpoint(path) == identity, "control socket changed during connection")
        client.sendall(command.encode("ascii") + b"\n")
        data = bytearray()
        while not data.endswith(b"\n"):
            remaining = min(3., deadline - time.monotonic())
            require(remaining > 0, "control deadline exceeded")
            client.settimeout(remaining)
            piece = client.recv(MAX_REPLY + 1 - len(data))
            require(bool(piece) and len(data) + len(piece) <= MAX_REPLY, "incomplete or oversized control reply")
            data.extend(piece)
        require(data.count(b"\n") == 1 and endpoint(path) == identity, "extra control frames or replaced socket")
    return status(strict_json(bytes(data)), pid)


def switch(path: Path, pid: int, collection: bool, emission: bool, deadline: float) -> list[dict]:
    """Retain every acknowledgement and wait for the effective export-off barrier."""
    require(type(collection) is bool and type(emission) is bool, "requested states require booleans")
    history = [{"command": "status", "status": request(path, "status", pid, deadline)}]
    original = history[-1]["status"]
    for command, key, expected in (("collection " + ("on" if collection else "off"), "collection", collection),
                                    ("emission " + ("on" if emission else "off"), "emission", emission)):
        current = request(path, command, pid, deadline)
        history.append({"command": command, "status": current})
        require(current[key] == expected and current["completed"] == original["completed"],
                "transition changed the wrong state or selected calls ran during rendezvous")
        other = "emission" if key == "collection" else "collection"
        require(current[other] == history[-2]["status"][other], "transition changed an independent control")
    while not emission and not history[-1]["status"]["effective_emission_off"]:
        require(time.monotonic() < deadline, "export-off barrier deadline exceeded")
        require(len(history) < MAX_STATUS_RECORDS, "control status record budget exceeded")
        time.sleep(min(.01, max(0., deadline - time.monotonic())))
        current = request(path, "status", pid, deadline)
        history.append({"command": "status", "status": current})
        require(current["collection"] == collection and current["emission"] == emission
                and current["completed"] == original["completed"], "control changed while waiting for the barrier")
    return history
