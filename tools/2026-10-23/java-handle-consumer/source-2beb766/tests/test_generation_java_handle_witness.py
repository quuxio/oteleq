"""Explicit handle framing must retain independent route and decoded receipt checks."""

import copy
import json
from pathlib import Path
import socket
import tempfile
import threading
import time
import unittest

import test_generation_java_witness as direct
import test_generation_java_action_receipt as decoded
import java_action_receipt as receipt
import java_witness as witness

PROFILE = witness.HANDLE_PROFILE
ROUTE = "9" * 64


def reply(request_id="a" * 32, current=True):
    value = direct.reply(request_id, current)
    value.update(schema_version=3, profile=PROFILE, route_binding_sha256=ROUTE)
    if current:
        value["scope"]["route_verified"] = True
    return value


def identity(value=None):
    value = reply() if value is None else value
    return witness.Identity.bind(value, {key: value[key] for key in witness.hash_fields(PROFILE)},
                                 pid=123, profile=PROFILE)


def final_report():
    value = direct.final_report()
    value.update(schema_version=3, producer=reply(None, False))
    value["scopes"][0]["route_verified"] = True
    return value


class JavaHandleWitnessTests(unittest.TestCase):
    def test_profile_is_explicit_and_each_header_field_remains_closed(self):
        value = reply()
        self.assertIs(witness.reply(value, "a" * 32, profile=PROFILE), value)
        for invalid in (None, True, "future", [], "java-sync-private-handle-v2"):
            with self.subTest(profile=invalid), self.assertRaises(ValueError):
                witness.reply(value, "a" * 32, profile=invalid)
        with self.assertRaises(ValueError):witness.reply(value, "a" * 32)
        with self.assertRaises(ValueError):witness.reply(direct.reply(), "a" * 32, profile=PROFILE)
        for key in value:
            changed = value.copy();del changed[key]
            with self.subTest(missing=key), self.assertRaises(ValueError):
                witness.reply(changed, "a" * 32, profile=PROFILE)
        for key, replacement in (("schema_version", True), ("schema_version", 2), ("profile", witness.PROFILE),
                                 ("route_binding_sha256", None), ("route_binding_sha256", "0" * 63), ("extra", 1)):
            with self.subTest(key=key), self.assertRaises(ValueError):
                witness.reply({**value, key: replacement}, "a" * 32, profile=PROFILE)

    def test_route_flag_is_typed_and_required_for_completion(self):
        value = reply()["scope"]
        for replacement in (False, None, 1, "true"):
            with self.subTest(value=replacement), self.assertRaises(ValueError):
                witness.read_scope({**value, "route_verified": replacement}, profile=PROFILE)
        incomplete = direct.scope(False)
        incomplete["route_verified"] = False
        self.assertFalse(witness.read_scope(incomplete, profile=PROFILE)["producer_complete"])
        with self.assertRaises(ValueError):witness.read_scope(value)
        with self.assertRaises(ValueError):witness.read_scope(direct.scope(), profile=PROFILE)

    def test_frozen_identity_requires_the_independent_route_and_exact_profile(self):
        value = reply();bound = identity(value)
        bound.check(value)
        self.assertEqual(bound.profile, PROFILE)
        self.assertEqual(dict(bound.hashes)["route_binding_sha256"], ROUTE)
        for key, replacement in (("route_binding_sha256", "0" * 64), ("profile", witness.PROFILE),
                                 ("schema_version", 2), ("schema_version", True)):
            with self.subTest(key=key), self.assertRaises(ValueError):bound.check({**value, key: replacement})
        expected = {key: value[key] for key in witness.HASH_FIELDS}
        with self.assertRaises(ValueError):witness.Identity.bind(value, expected, pid=123, profile=PROFILE)
        with self.assertRaises(ValueError):witness.Identity.bind(value, expected, pid=123)
        with self.assertRaises(ValueError):identity({**value, "schema_version": 2})
        expected["route_binding_sha256"] = "0" * 64
        with self.assertRaises(ValueError):witness.Identity.bind(value, expected, pid=123, profile=PROFILE)

    def test_wire_three_requires_route_after_the_actual_logical_thread(self):
        arguments = ("b" * 32, "c" * 32, "1", "d" * 64, "e" * 64,
                     "1" * 64, "2" * 64, "3" * 64, "4" * 64, "5" * 64, "41", ROUTE)
        wire = witness.command("arm", arguments, "a" * 32, profile=PROFILE)
        self.assertEqual(wire, ("3 " + "a" * 32 + " arm " + " ".join(arguments) + "\n").encode())
        self.assertEqual(witness.command("status", (), "a" * 32, profile=PROFILE),
                         ("3 " + "a" * 32 + " status\n").encode())
        for changed in (arguments[:-1], (*arguments[:-1], "bad"), (*arguments[:-2], ROUTE, "41")):
            with self.subTest(arguments=changed), self.assertRaises(ValueError):
                witness.command("arm", changed, "a" * 32, profile=PROFILE)
        with self.assertRaises(ValueError):witness.command("arm", arguments, "a" * 32)

    def test_final_file_binds_route_profile_pid_and_each_closed_scope(self):
        value = final_report();bound = identity()
        self.assertIs(witness.final_report(value, pid=123, identity=bound), value)
        with tempfile.TemporaryDirectory(dir="/tmp") as temporary:
            root = Path(temporary).resolve();root.chmod(0o700)
            path = root / "witness-health.json";path.write_text(json.dumps(value));path.chmod(0o600)
            self.assertEqual(witness.read_final(root, pid=123, identity=bound), value)
        for key, replacement in (("schema_version", 2), ("pid", 124)):
            with self.subTest(key=key), self.assertRaises(ValueError):
                witness.final_report({**value, key: replacement}, pid=123, identity=bound)
        changed = copy.deepcopy(value);changed["producer"]["route_binding_sha256"] = "0" * 64
        with self.assertRaises(ValueError):witness.final_report(changed, pid=123, identity=bound)
        changed = copy.deepcopy(value);changed["scopes"][0]["route_verified"] = False
        with self.assertRaises(ValueError):witness.final_report(changed, pid=123, identity=bound)
        with self.assertRaises(ValueError):witness.final_report(value, pid=123, identity=direct.identity())

    def test_private_socket_keeps_the_explicit_request_and_reply_profile(self):
        with tempfile.TemporaryDirectory(dir="/tmp") as temporary:
            root = Path(temporary).resolve();root.chmod(0o700)
            path = root / "witness.sock"
            with socket.socket(socket.AF_UNIX) as server:
                server.bind(str(path));path.chmod(0o600);server.listen(1);server.settimeout(3)
                errors = []
                def respond():
                    try:
                        channel, _ = server.accept()
                        with channel:
                            channel.settimeout(3);wire = bytearray()
                            while not wire.endswith(b"\n"):
                                part = channel.recv(1024)
                                self.assertTrue(part)
                                wire.extend(part);self.assertLessEqual(len(wire), 1024)
                            words = wire.decode().strip().split(" ")
                            self.assertEqual((words[0], words[2]), ("3", "status"))
                            channel.sendall(json.dumps(reply(words[1])).encode() + b"\n")
                    except BaseException as error:errors.append(error)
                worker = threading.Thread(target=respond, daemon=True);worker.start()
                try:
                    value = witness.request(path, "status", deadline=time.monotonic() + 3, profile=PROFILE)
                    self.assertEqual(value["route_binding_sha256"], ROUTE)
                finally:
                    worker.join(timeout=4)
                self.assertFalse(worker.is_alive())
                self.assertEqual(errors, [])

    def test_decoded_handle_receipt_keeps_route_and_complete_tree_obligations(self):
        for recursive in (False, True):
            for failed in (False, True):
                report, message = decoded.fixture(recursive=recursive, failed=failed)
                report.update(schema_version=3, producer=reply(None, False))
                report["scopes"][0]["route_verified"] = True
                options = {"service": decoded.SERVICE, "decoder": decoded.ExportTraceServiceRequest.FromString}
                arguments = ([decoded.expected(failed=failed)], decoded.TARGET,
                             [("/v1/traces", message.SerializeToString())])
                result = receipt.qualify(report, identity(), *arguments, **options)
                self.assertIn(PROFILE, result["decoder"])
                self.assertEqual(result["scoped_spans"], 5 if recursive else 3)
                report["scopes"][0]["route_verified"] = False
                with self.assertRaises(ValueError):receipt.qualify(report, identity(), *arguments, **options)


if __name__ == "__main__":
    unittest.main()
