"""Validate independently declared scalar returns using the shared value format."""
from typing import Any

import typed_capture

MAX_TEXT = 262144


def require(condition: bool, reason: str) -> None:
    """Reject incomplete expectations before an application can be launched."""
    if not condition:
        raise ValueError("expected return: " + reason)


def fields(value: dict, required: set[str], optional: set[str] | frozenset[str] = frozenset()) -> None:
    """Use closed records, including exact types for optional fields."""
    require(required <= value.keys() <= required | optional, "invalid scalar fields")


def hex_bytes(value: Any) -> bytes:
    """Preserve exact lowercase bytes, without whitespace or truncation."""
    require(type(value) is str and len(value) <= MAX_TEXT * 2, "invalid byte payload")
    try:
        data = bytes.fromhex(value)
    except ValueError as error:
        raise ValueError("expected return: invalid byte payload") from error
    require(data.hex() == value, "noncanonical byte payload")
    return data


def string_payload(encoding: Any, value: Any) -> None:
    """Keep UTF code units and raw bytes distinct; never normalise strings."""
    data = hex_bytes(value)
    require(encoding in ("utf8", "utf16_be", "codepoints32_be", "raw_bytes"), "invalid string encoding")
    if encoding == "utf8":
        try:
            data.decode("utf8")
        except UnicodeError as error:
            raise ValueError("expected return: invalid UTF-8 payload") from error
    if encoding == "utf16_be":
        require(len(data) % 2 == 0, "incomplete UTF-16 unit")
    if encoding == "codepoints32_be":
        require(len(data) % 4 == 0 and all(int.from_bytes(data[i:i + 4], "big") <= 0x10ffff
                                         for i in range(0, len(data), 4)), "invalid code point")


def validate(value: Any) -> dict:
    """Return a closed typed scalar; graph references and opaque state need fixtures."""
    require(type(value) is dict, "requires a typed scalar record")
    kind = value.get("kind")
    if kind in ("null", "undefined"):
        fields(value, {"kind"})
        return value.copy()
    if kind == "boolean":
        fields(value, {"kind", "value"}, {"type"})
        require(type(value["value"]) is bool, "invalid boolean")
    else:
        layouts = {"unit": {"kind", "type"}, "integer": {"kind", "type", "value", "signed"},
                   "float": {"kind", "type", "bits"}, "string": {"kind", "type", "encoding", "value"},
                   "bytes": {"kind", "type", "hex"}}
        require(type(kind) is str and kind in layouts, "unsupported or incomplete scalar kind")
        fields(value, layouts[kind], {"bits"} if kind == "integer" else set())
    label = value.get("type")
    require(kind == "boolean" and "type" not in value or type(label) is str and 0 < len(label) <= 1024,
            "requires a bounded type label")
    return payload(value)


def payload(value: dict) -> dict:
    """Validate each primitive with the observer's exact representation."""
    kind = value["kind"]
    if kind == "integer":
        require(type(value["signed"]) is bool and type(value["value"]) is str
                and len(value["value"]) <= 4096, "invalid integer")
        width = value.get("bits")
        require(width is None or type(width) is int and width in (8, 16, 32, 64, 128), "invalid integer width")
        return typed_capture.integer(value["type"], value["value"], width, value["signed"])
    if kind == "float":
        bits = value["bits"]
        require(type(bits) is str and len(bits) in (4, 8, 16, 32), "invalid float width")
        hex_bytes(bits)
    if kind == "string":
        string_payload(value["encoding"], value["value"])
    if kind == "bytes":
        hex_bytes(value["hex"])
    return value.copy()
