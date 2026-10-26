"""Reuse bounded descriptor attributes and preserve symbolic-link attributes."""

from __future__ import annotations

import ctypes
import os
from pathlib import Path
import stat

from ci import evidence_attributes as attributes
from ci.evidence_index import require


def _call(name: str, signature: list, *arguments) -> int:
    function = getattr(ctypes.CDLL(None, use_errno=True), name)
    function.argtypes = signature
    function.restype = ctypes.c_ssize_t if name in ("listxattr", "getxattr") else ctypes.c_int
    result = function(*arguments)
    if result < 0:
        raise OSError(ctypes.get_errno(), "symbolic-link attribute operation failed")
    require(result <= attributes.LIMIT, "symbolic-link attributes exceed budget")
    return result


def _link(path: Path) -> dict[str, str]:
    if hasattr(os, "listxattr"):
        return {os.fsencode(name).hex(): os.getxattr(path, name, follow_symlinks=False).hex()
                for name in os.listxattr(path, follow_symlinks=False)}
    raw = os.fsencode(path)
    signature = [ctypes.c_char_p, ctypes.c_void_p, ctypes.c_size_t, ctypes.c_int]
    size = _call("listxattr", signature, raw, None, 0, 1)
    buffer = ctypes.create_string_buffer(size)
    used = _call("listxattr", signature, raw, buffer, size, 1)
    names = buffer.raw[:used].split(b"\0")[:-1]
    result = {}
    signature = [ctypes.c_char_p, ctypes.c_char_p, ctypes.c_void_p,
                 ctypes.c_size_t, ctypes.c_uint32, ctypes.c_int]
    for name in names:
        size = _call("getxattr", signature, raw, name, None, 0, 0, 1)
        buffer = ctypes.create_string_buffer(size)
        used = _call("getxattr", signature, raw, name, buffer, size, 0, 1)
        result[name.hex()] = buffer.raw[:used].hex()
    return result


def read(path: Path) -> dict[str, str]:
    """Read attributes from this node, including a link without following it."""
    if stat.S_ISLNK(path.lstat().st_mode):
        result = _link(path)
        require(len(result) <= 64 and sum((len(k) + len(v)) // 2
                for k, v in result.items()) <= attributes.LIMIT,
                "symbolic-link attributes exceed budget")
        return result
    descriptor = os.open(path, os.O_RDONLY | os.O_NOFOLLOW)
    try:
        return attributes.read(descriptor)
    finally:
        os.close(descriptor)


def write(path: Path, expected: dict[str, str]) -> None:
    """Restore exact attributes; never inherit unrecorded defaults."""
    if not stat.S_ISLNK(path.lstat().st_mode):
        descriptor = os.open(path, os.O_RDONLY | os.O_NOFOLLOW)
        try:
            attributes.write(descriptor, expected)
        finally:
            os.close(descriptor)
        return
    current = read(path)
    for name in current.keys() - expected.keys():
        if hasattr(os, "removexattr"):
            os.removexattr(path, bytes.fromhex(name), follow_symlinks=False)
        else:
            _call("removexattr", [ctypes.c_char_p, ctypes.c_char_p, ctypes.c_int],
                  os.fsencode(path), bytes.fromhex(name), 1)
    for name, value in expected.items():
        content = bytes.fromhex(value)
        if hasattr(os, "setxattr"):
            os.setxattr(path, bytes.fromhex(name), content, follow_symlinks=False)
        else:
            _call("setxattr", [ctypes.c_char_p, ctypes.c_char_p, ctypes.c_void_p,
                              ctypes.c_size_t, ctypes.c_uint32, ctypes.c_int],
                  os.fsencode(path), bytes.fromhex(name), content, len(content), 0, 1)
    require(read(path) == expected, "restored symbolic-link attributes differ")
