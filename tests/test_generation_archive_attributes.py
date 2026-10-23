"""Exercise both attribute interfaces on every host without claiming emulation is native."""

from contextlib import contextmanager
import ctypes
import os
from types import SimpleNamespace
import unittest
from unittest import mock

from ci import evidence_attributes as attributes
from ci.evidence_index import ArchiveError


class AttributeInterfacesTests(unittest.TestCase):
    @contextmanager
    def darwin(self, initial=None, raw_names=None):
        data = dict(initial or {})

        def names(descriptor, buffer, size, options):
            self.assertEqual((descriptor, options), (19, 0))
            raw = raw_names if raw_names is not None else b"".join(name + b"\0" for name in data)
            if buffer is not None:
                self.assertGreaterEqual(size, len(raw))
                ctypes.memmove(buffer, raw, len(raw))
            return len(raw)

        def get(descriptor, name, buffer, size, position, options):
            self.assertEqual((descriptor, position, options), (19, 0, 0))
            content = data[name]
            if buffer is not None:
                self.assertGreaterEqual(size, len(content))
                ctypes.memmove(buffer, content, len(content))
            return len(content)

        def put(descriptor, name, content, size, position, options):
            self.assertEqual((descriptor, position, options), (19, 0, 0))
            data[name] = bytes(content)[:size]
            return 0

        def remove(descriptor, name, options):
            self.assertEqual((descriptor, options), (19, 0))
            del data[name]
            return 0

        library = SimpleNamespace(flistxattr=mock.Mock(side_effect=names),
                                  fgetxattr=mock.Mock(side_effect=get),
                                  fsetxattr=mock.Mock(side_effect=put),
                                  fremovexattr=mock.Mock(side_effect=remove))
        with mock.patch.object(attributes, "os", SimpleNamespace(fsencode=os.fsencode)), \
             mock.patch.object(attributes.sys, "platform", "darwin"), \
             mock.patch.object(attributes.ctypes, "CDLL", return_value=library):
            yield data, library

    def test_darwin_descriptor_abi_round_trips_exact_binary_and_empty_values(self):
        with self.darwin({b"user.old": b"old", b"user.empty": b""}) as (data, library):
            self.assertEqual(attributes.read(19), {
                b"user.old".hex(): b"old".hex(), b"user.empty".hex(): ""})
            expected = {b"user.binary".hex(): b"\x00\xff".hex(), b"user.empty".hex(): ""}
            attributes.write(19, expected)
            self.assertEqual(data, {b"user.binary": b"\x00\xff", b"user.empty": b""})
            self.assertEqual(attributes.read(19), expected)
            self.assertEqual(library.fgetxattr.restype, ctypes.c_ssize_t)
            self.assertEqual(len(library.fgetxattr.argtypes), 6)
            self.assertEqual(library.fsetxattr.restype, ctypes.c_int)

    def test_darwin_malformed_names_and_kernel_size_or_io_failures_refuse(self):
        for raw in (b"unterminated", b"\0", b"user.same\0user.same\0"):
            with self.subTest(raw=raw), self.darwin(raw_names=raw):
                with self.assertRaises(ArchiveError):
                    attributes.read(19)
        with self.darwin({b"user.data": b"x"}) as (_, library):
            library.fgetxattr.side_effect = None
            library.fgetxattr.return_value = attributes.LIMIT + 1
            with self.assertRaises(ArchiveError):
                attributes.read(19)
            library.fgetxattr.return_value = -1
            with self.assertRaises(OSError):
                attributes.read(19)

    def test_linux_descriptor_api_retains_and_removes_exact_attributes(self):
        data = {b"user.old": b"old"}

        def descriptor(value):
            self.assertEqual(value, 23)

        def names(value):
            descriptor(value)
            return list(data)

        def get(value, name):
            descriptor(value)
            return data[name]

        def put(value, name, content):
            descriptor(value)
            data[name] = content

        def remove(value, name):
            descriptor(value)
            del data[name]

        interface = SimpleNamespace(fsencode=os.fsencode, listxattr=names,
                                    getxattr=get, setxattr=put, removexattr=remove)
        expected = {b"user.binary".hex(): b"\x00\xff".hex()}
        with mock.patch.object(attributes, "os", interface):
            attributes.write(23, expected)
            self.assertEqual(attributes.read(23), expected)
        self.assertEqual(data, {b"user.binary": b"\x00\xff"})


if __name__ == "__main__":
    unittest.main()
