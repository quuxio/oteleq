"""Independent v2 parsing binds actual logical context and preserves refusals."""

import copy
import json
import os
from pathlib import Path
import socket
import sys
import tempfile
import threading
import time
import unittest
from unittest.mock import patch

REPO = Path(__file__).resolve().parents[1]
sys.path[:0] = [str(REPO / "adapters/generation"), str(REPO / "examples")]
import java_witness as witness


def scope(complete=True):
    return {"cookie": "c" * 32, "sequence": "1", "thread_id": "41",
            "scope_id": "d" * 32 if complete else None,
            "case_id": "e" * 64 if complete else None,
            "attempt_id": "f" * 64 if complete else None,
            "phase": "complete" if complete else "ready", "failure": None,
            "trace_id": "1" * 32 if complete else None,
            "root_span_id": "2" * 16 if complete else None,
            "target_span_id": "3" * 16 if complete else None,
            "root_exited": complete, "envelope_exited": complete,
            "target_exited": complete, "target_entries": "1" if complete else "0",
            "export_failures": "0", "flush_failures": "0", "checkpoint": complete,
            "producer_complete": complete, "receiver_confirmation_required": True,
            "started_ids": ["2" * 16, "3" * 16] if complete else [],
            "ended_ids": ["2" * 16, "3" * 16] if complete else [],
            "exported_ids": ["2" * 16, "3" * 16] if complete else [],
            "pending_exports": "0", "queue_dropped": "0" if complete else None}


def reply(request_id="a" * 32, current=True):
    return {"schema_version": 2, "profile": witness.PROFILE, "runtime_id": "b" * 32, "pid": 123,
            "request_id": request_id, "error": None, "rejected_probes": "0",
            "max_scopes": 64, "max_spans_per_scope": 1024,
            "scope": scope() if current else None,
            **{name: format(index, "x") * 64 for index, name in enumerate(witness.HASH_FIELDS, 1)}}


def identity(value=None):
    value = reply() if value is None else value
    return witness.Identity.bind(value, {key: value[key] for key in witness.HASH_FIELDS}, pid=123)


def final_report():
    return {"schema_version": 2, "kind": "otelc.java-witness-final", "phase": "final",
            "pid": 123, "producer": reply(None, False),
            "queue_evidence": "derived_after_shutdown", "scopes": [scope()]}


class JavaWitnessTests(unittest.TestCase):
    def test_exact_v2_and_large_decimal_values(self):
        value = reply()
        self.assertEqual(witness.reply(value, "a" * 32), value)
        self.assertEqual(witness.counter("9007199254740993"), 9007199254740993)
        self.assertEqual(witness.counter(str(2**63 - 1)), 2**63 - 1)
        self.assertTrue(witness.hex_id(None, 32, nullable=True))
        self.assertFalse(witness.hex_id(None, 32))
        self.assertTrue(witness.failure(None))
        self.assertTrue(witness.failure("wrong_thread"))

    def test_noncanonical_unavailable_and_overflow_counters_refuse(self):
        for value in (None, True, 0, -1, "", "01", "-1", "1.0", "1e2", " 1", "1\n", "\u0661", "1\u0661", str(2**63)):
            with self.subTest(value=value), self.assertRaises(ValueError):
                witness.counter(value)
        with self.assertRaises(ValueError):
            witness.counter("0", positive=True)

    def test_reply_fields_versions_request_limits_and_hashes_refuse(self):
        for key in reply():
            value = reply();del value[key]
            with self.subTest(missing=key), self.assertRaises(ValueError):
                witness.reply(value, "a" * 32)
        for key, replacement in (("schema_version", True), ("schema_version", 1),
                ("profile", "java-sync-action-v1"), ("request_id", "c" * 32),
                ("pid", True), ("pid", 0),
                ("runtime_id", "B" * 32), ("max_scopes", True), ("max_scopes", 65),
                ("max_spans_per_scope", 1025), ("rejected_probes", None),
                ("error", "Error"), ("error", []), *[(name, "bad") for name in witness.HASH_FIELDS]):
            value = reply();value[key] = replacement
            with self.subTest(key=key, value=replacement), self.assertRaises(ValueError):
                witness.reply(value, "a" * 32)
        for value in (None, [], {**reply(), "new": 1}):
            with self.assertRaises(ValueError):
                witness.reply(value, "a" * 32)
        with self.assertRaises(ValueError):
            witness.reply(reply(), "bad")
        self.assertEqual(witness.reply(reply(current=False), "a" * 32)["scope"], None)

    def test_scope_closed_fields_and_all_typed_dimensions_refuse(self):
        for key in scope():
            value = scope();del value[key]
            with self.subTest(missing=key), self.assertRaises(ValueError):
                witness.read_scope(value)
        edits = [("cookie", "bad"), ("phase", []), ("phase", "other"), ("failure", 1),
                 ("sequence", "0"), ("thread_id", "0"),
                 ("receiver_confirmation_required", False)]
        edits += [(key, 1) for key in ("root_exited", "envelope_exited", "target_exited", "checkpoint",
                                      "producer_complete", "receiver_confirmation_required")]
        edits += [(key, True) for key in ("target_entries", "export_failures", "flush_failures", "pending_exports", "queue_dropped")]
        edits += [(key, "bad") for key in ("scope_id", "case_id", "attempt_id", "trace_id", "root_span_id", "target_span_id")]
        for key, replacement in edits:
            value = scope();value[key] = replacement
            with self.subTest(key=key, value=replacement), self.assertRaises(ValueError):
                witness.read_scope(value)
        with self.assertRaises(ValueError):
            witness.read_scope({**scope(), "new": 1})
        value = scope(False);value["case_id"] = "e" * 64
        with self.assertRaises(ValueError):witness.read_scope(value)

    def test_completion_requires_each_exit_and_exact_actual_span_accounting(self):
        edits = [(key, False) for key in ("checkpoint", "root_exited", "envelope_exited", "target_exited")]
        edits += [("phase", "incomplete"), ("failure", "late_span"), ("target_entries", "0"),
                  ("pending_exports", "1"), ("queue_dropped", "1"), ("trace_id", "0" * 32),
                  ("trace_id", None), ("root_span_id", "4" * 16), ("target_span_id", "2" * 16),
                  ("scope_id", None), ("ended_ids", []), ("exported_ids", [])]
        for key, replacement in edits:
            value = scope();value[key] = replacement
            with self.subTest(key=key), self.assertRaises(ValueError):witness.read_scope(value)
        value = scope();value.update(scope_id=None, case_id=None, attempt_id=None)
        with self.assertRaises(ValueError):witness.read_scope(value)
        value = scope();value["producer_complete"] = False
        with self.assertRaises(ValueError):witness.read_scope(value)

    def test_incomplete_contexts_and_successful_flush_retry_remain_data(self):
        for phase in witness.PHASES - {"complete"}:
            value = scope(False);value["phase"] = phase
            self.assertFalse(witness.read_scope(value)["producer_complete"])
        value = scope();value["flush_failures"] = "1";value["queue_dropped"] = None
        self.assertTrue(witness.read_scope(value)["producer_complete"])

    def test_duplicate_zero_foreign_and_excessive_span_sets_refuse(self):
        for key in ("started_ids", "ended_ids", "exported_ids"):
            for values in (None, ["bad"], ["0" * 16], ["2" * 16] * 2, ["2" * 16] * 1025):
                value = scope();value[key] = values
                with self.subTest(key=key, value=values and len(values)), self.assertRaises(ValueError):
                    witness.read_scope(value)
        for key in ("ended_ids", "exported_ids"):
            value = scope(False);value[key] = ["4" * 16]
            with self.assertRaises(ValueError):witness.read_scope(value)

    def test_frozen_identity_rejects_substitution_and_is_immutable(self):
        value = reply()
        expected = {key: value[key] for key in witness.HASH_FIELDS}
        bound = witness.Identity.bind(value, expected, pid=123, runtime_id="b" * 32)
        bound.check(value)
        expected["build_sha256"] = "f" * 64
        bound.check(value)
        with self.assertRaises(ValueError):witness.Identity.bind(value, expected, pid=123)
        for current in ({}, {**expected, "extra": "a" * 64}):
            with self.assertRaises(ValueError):witness.Identity.bind(value, current, pid=123)
        expected["build_sha256"] = "bad"
        with self.assertRaises(ValueError):witness.Identity.bind(value, expected, pid=123)
        with self.assertRaises(ValueError):
            witness.Identity.bind(value, {key: value[key] for key in witness.HASH_FIELDS}, pid=123, runtime_id="c" * 32)
        for pid in (True, 0, 124):
            with self.assertRaises(ValueError):
                witness.Identity.bind(value, {key: value[key] for key in witness.HASH_FIELDS}, pid=pid)
        with self.assertRaises(ValueError):bound.check({**value, "pid": 124})
        for key in ("runtime_id", *witness.HASH_FIELDS):
            changed = copy.deepcopy(value);changed[key] = "f" * len(changed[key])
            with self.subTest(key=key), self.assertRaises(ValueError):bound.check(changed)

    def test_context_requires_the_private_harness_thread_and_all_action_identities(self):
        value = reply()
        arguments = {"thread_id": "41", "cookie": "c" * 32, "sequence": "1",
                     "case_id": "e" * 64, "attempt_id": "f" * 64, "scope_id": "d" * 32}
        self.assertEqual(witness.context(value, identity(), **arguments), scope())
        for key in arguments:
            changed = arguments.copy();changed[key] = "42" if key in ("thread_id", "sequence") else "a" * len(changed[key])
            with self.subTest(key=key), self.assertRaises(ValueError):
                witness.context(value, identity(), **changed)
        for key in ("cookie", "case_id", "attempt_id", "scope_id"):
            with self.subTest(invalid=key), self.assertRaises(ValueError):
                witness.context(value, identity(), **{**arguments, key: "bad"})
        for changed in (reply(current=False), {**value, "error": "wrong_thread"}):
            with self.assertRaises(ValueError):witness.context(changed, identity(), **arguments)

    def test_closed_commands_include_the_expected_logical_thread(self):
        request = "a" * 32
        self.assertEqual(witness.command("status", (), request), f"2 {request} status\n".encode())
        self.assertEqual(witness.command("end", ("b" * 32, "c" * 32), request).split()[2], b"end")
        self.assertEqual(witness.command("cancel", ("b" * 32, "c" * 32), request).split()[2], b"cancel")
        self.assertEqual(len(witness.command("status", ("b" * 32, "c" * 32), request).split()), 5)
        arguments = ("b" * 32, "c" * 32, "1", "d" * 64, "e" * 64,
                     "1" * 64, "2" * 64, "3" * 64, "4" * 64, "5" * 64, "41")
        self.assertEqual(witness.command("arm", arguments, request).split()[-1], b"41")
        self.assertEqual(len(witness.command("arm", arguments, request).split()), 14)
        for operation, values in (("arm", arguments[:-1]), ("shell", ()), ("end", ()),
                                  ("status", ("b" * 32,)), ("status", ("bad", "c" * 32)),
                                  ("arm", (*arguments[:-1], "0")), ("status", (True,))):
            with self.subTest(operation=operation, values=values), self.assertRaises(ValueError):
                witness.command(operation, values, request)
        with self.assertRaises(ValueError):witness.command("status", (), "bad")

    def read_final(self, root, value, **overrides):
        path = root / "witness-health.json"
        path.write_text(json.dumps(value));path.chmod(0o600)
        return witness.read_final(root, **{"pid": 123, "identity": identity(), **overrides})

    def test_final_private_actual_pid_context_order_and_queue_evidence(self):
        with tempfile.TemporaryDirectory(dir="/tmp") as temporary:
            root = Path(temporary).resolve();root.chmod(0o700)
            value = final_report()
            self.assertEqual(self.read_final(root, value), value)
            value["scopes"][0]["queue_dropped"] = None;value["queue_evidence"] = "unavailable"
            self.assertEqual(self.read_final(root, value), value)
            for key, replacement in (("schema_version", True), ("schema_version", 1), ("kind", "other"),
                    ("phase", "running"), ("pid", True), ("pid", 124), ("scopes", None),
                    ("scopes", [scope()] * 65), ("queue_evidence", "unknown")):
                changed = final_report();changed[key] = replacement
                with self.subTest(key=key), self.assertRaises(ValueError):self.read_final(root, changed)
            changed = final_report();changed["producer"]["scope"] = scope()
            with self.assertRaises(ValueError):self.read_final(root, changed)
            changed = final_report();changed["queue_evidence"] = "unavailable"
            with self.assertRaises(ValueError):self.read_final(root, changed)
            changed = final_report();changed["scopes"] *= 2
            with self.assertRaises(ValueError):self.read_final(root, changed)
            for key in ("cookie", "scope_id", "sequence"):
                changed = final_report();other = copy.deepcopy(scope())
                other.update(cookie="a" * 32, scope_id="a" * 32, sequence="2")
                other[key] = changed["scopes"][0][key];changed["scopes"].append(other)
                with self.subTest(key=key), self.assertRaises(ValueError):self.read_final(root, changed)
            changed = final_report();other = scope(False);other.update(cookie="a" * 32, sequence="3")
            changed["scopes"].append(other)
            self.assertEqual(len(self.read_final(root, changed)["scopes"]), 2)
            with self.assertRaises(ValueError):self.read_final(root, final_report(), pid=True)

    def test_final_actual_pid_cannot_disagree_with_frozen_producer_identity(self):
        with tempfile.TemporaryDirectory(dir="/tmp") as temporary:
            root = Path(temporary).resolve();root.chmod(0o700)
            contradictory = final_report();contradictory["pid"] = 124
            with self.assertRaises(ValueError):
                self.read_final(root, contradictory, pid=124)

    def test_final_fifo_symlink_permissions_oversize_duplicate_json_and_no_fd_leak(self):
        with tempfile.TemporaryDirectory(dir="/tmp") as temporary:
            root = Path(temporary).resolve();root.chmod(0o700)
            self.read_final(root, final_report())
            path = root / "witness-health.json"
            for mode in (0o644, 0o400):
                path.chmod(mode)
                with self.assertRaises(ValueError):witness.read_final(root, pid=123, identity=identity())
            path.chmod(0o600)
            path.write_bytes(b"x" * (witness.MAX_FINAL + 1))
            with self.assertRaises(ValueError):witness.read_final(root, pid=123, identity=identity())
            path.write_bytes(b'{"schema_version":2,"schema_version":2}')
            with self.assertRaises(ValueError):witness.read_final(root, pid=123, identity=identity())
            path.unlink();path.symlink_to(root / "absent")
            with self.assertRaises(OSError):witness.read_final(root, pid=123, identity=identity())
            path.unlink();os.mkfifo(path, 0o600)
            descriptors = Path("/proc/self/fd") if Path("/proc/self/fd").is_dir() else Path("/dev/fd")
            count = len(list(descriptors.iterdir()))
            for _ in range(10):
                with self.assertRaises(ValueError):witness.read_final(root, pid=123, identity=identity())
            self.assertEqual(len(list(descriptors.iterdir())), count)
            path.unlink()
            root.chmod(0o755)
            with self.assertRaises(ValueError):witness.read_final(root, pid=123, identity=identity())
            root.chmod(0o700)
            alias = root / "alias";alias.symlink_to(root, target_is_directory=True)
            with self.assertRaises(ValueError):witness.read_final(alias, pid=123, identity=identity())

    def test_final_detects_replaced_path_while_descriptor_is_open(self):
        with tempfile.TemporaryDirectory(dir="/tmp") as temporary:
            root = Path(temporary).resolve();root.chmod(0o700)
            self.read_final(root, final_report())
            path = root / "witness-health.json"
            fdopen = os.fdopen

            class Replacement:
                def __init__(self, stream):self.stream = stream
                def __enter__(self):return self
                def __exit__(self, *args):return self.stream.__exit__(*args)
                def read(self, maximum):
                    raw = self.stream.read(maximum)
                    path.unlink();path.write_bytes(raw);path.chmod(0o600)
                    return raw

            with patch.object(witness.os, "fdopen", side_effect=lambda *args, **kwargs: Replacement(fdopen(*args, **kwargs))):
                with self.assertRaisesRegex(ValueError, "changed while reading"):
                    witness.read_final(root, pid=123, identity=identity())

    def exchange(self, callback, *, deadline=None, mode=0o600):
        with tempfile.TemporaryDirectory(dir="/tmp") as temporary:
            root = Path(temporary).resolve();root.chmod(0o700)
            path = root / "witness.sock"
            with socket.socket(socket.AF_UNIX) as server:
                server.bind(str(path));path.chmod(mode);server.listen(1);server.settimeout(.3)
                errors = []

                def serve():
                    try:
                        with server.accept()[0] as channel:
                            channel.settimeout(.5)
                            data = bytearray()
                            while not data.endswith(b"\n"):
                                part = channel.recv(2048)
                                if not part:break
                                data.extend(part)
                            result = callback(bytes(data))
                            if result is not None:channel.sendall(result)
                    except (TimeoutError, BrokenPipeError):
                        pass
                    except Exception as error:errors.append(error)

                worker = threading.Thread(target=serve);worker.start()
                try:
                    return witness.request(path, "status", deadline=deadline or time.monotonic() + 2)
                finally:
                    worker.join(1)
                    self.assertFalse(worker.is_alive())
                    self.assertEqual(errors, [])

    def test_live_socket_binds_fresh_request_and_refuses_unbounded_or_extra_frames(self):
        def good(data):
            version, request, operation = data.decode().split()
            self.assertEqual((version, operation), ("2", "status"))
            return json.dumps(reply(request)).encode() + b"\n"
        self.assertEqual(self.exchange(good)["scope"]["thread_id"], "41")
        for response in (b"", b"{}", b"{}\n{}\n", b"x" * (witness.MAX_REPLY + 1),
                         b'{"x":1,"x":1}\n', json.dumps(reply()).encode() + b"\n"):
            with self.subTest(size=len(response)), self.assertRaises(ValueError):
                self.exchange(lambda _, value=response: value)

    def test_socket_private_runtime_and_common_deadline_refuse(self):
        with self.assertRaises(ValueError):self.exchange(lambda _: b"{}\n", mode=0o666)
        with self.assertRaises(ValueError):self.exchange(lambda _: b"{}\n", deadline=time.monotonic() - 1)
        with tempfile.TemporaryDirectory(dir="/tmp") as temporary:
            root = Path(temporary).resolve();root.chmod(0o700)
            path = root / "witness.sock";path.write_text("{}");path.chmod(0o600)
            with self.assertRaises(ValueError):witness.endpoint(path)
            path.unlink()
            with socket.socket(socket.AF_UNIX) as server:
                server.bind(str(path));path.chmod(0o600)
                root.chmod(0o755)
                with self.assertRaises(ValueError):witness.endpoint(path)


if __name__ == "__main__":
    unittest.main()
