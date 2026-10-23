"""Bounded file-descriptor extended attributes on macOS and Linux."""

from __future__ import annotations

import ctypes
import os
import sys

from ci.evidence_index import require

LIMIT = 65536


def _native(name: str, signature: list):
    require(sys.platform == "darwin", "extended-attribute inspection is unsupported")
    function = getattr(ctypes.CDLL(None, use_errno=True), name)
    function.argtypes = signature
    function.restype = ctypes.c_ssize_t if name in ("flistxattr", "fgetxattr") else ctypes.c_int
    return function


def _checked(value: int) -> int:
    if value < 0:
        raise OSError(ctypes.get_errno(), "extended-attribute operation failed")
    require(value <= LIMIT, "extended attributes exceed byte budget")
    return value


def read(descriptor: int) -> dict[str, str]:
    """Retain byte-exact attribute names/values without following another path."""
    if hasattr(os, "listxattr"):
        names = [os.fsencode(name) for name in os.listxattr(descriptor)]
    else:
        function = _native("flistxattr", [ctypes.c_int, ctypes.c_void_p, ctypes.c_size_t, ctypes.c_int])
        size = _checked(function(descriptor, None, 0, 0))
        buffer = ctypes.create_string_buffer(size)
        used = _checked(function(descriptor, buffer, size, 0))
        raw = buffer.raw[:used]
        require(not raw or raw.endswith(b"\0"), "invalid extended-attribute names")
        names = raw.split(b"\0")[:-1] if raw else []
    require(len(names) <= 64 and len(set(names)) == len(names), "invalid extended-attribute count")
    result, total = {}, 0
    for name in names:
        require(0 < len(name) <= 255 and b"\0" not in name, "invalid extended-attribute name")
        if hasattr(os, "getxattr"):
            content = os.getxattr(descriptor, name)
        else:
            function = _native("fgetxattr", [ctypes.c_int, ctypes.c_char_p, ctypes.c_void_p,
                                            ctypes.c_size_t, ctypes.c_uint32, ctypes.c_int])
            size = _checked(function(descriptor, name, None, 0, 0, 0))
            buffer = ctypes.create_string_buffer(size)
            used = _checked(function(descriptor, name, buffer, size, 0, 0))
            content = buffer.raw[:used]
        total += len(name) + len(content)
        require(total <= LIMIT, "extended attributes exceed byte budget")
        result[name.hex()] = content.hex()
    return result


def write(descriptor: int, expected: dict[str, str]) -> None:
    """Reproduce attributes on a private new file, including removal of defaults."""
    for name in read(descriptor).keys() - expected.keys():
        if hasattr(os, "removexattr"):
            os.removexattr(descriptor, bytes.fromhex(name))
        else:
            function = _native("fremovexattr", [ctypes.c_int, ctypes.c_char_p, ctypes.c_int])
            _checked(function(descriptor, bytes.fromhex(name), 0))
    for name, content in expected.items():
        data = bytes.fromhex(content)
        if hasattr(os, "setxattr"):
            os.setxattr(descriptor, bytes.fromhex(name), data)
        else:
            function = _native("fsetxattr", [ctypes.c_int, ctypes.c_char_p, ctypes.c_void_p,
                                            ctypes.c_size_t, ctypes.c_uint32, ctypes.c_int])
            _checked(function(descriptor, bytes.fromhex(name), data, len(data), 0, 0))
    require(read(descriptor) == expected, "restored extended attributes differ")
