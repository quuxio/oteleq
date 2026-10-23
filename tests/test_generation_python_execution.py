"""Execution facts bind the actual owner, native bytes and final process pair."""

from dataclasses import replace
import hashlib
import json
import os
from pathlib import Path
import struct
import sys
import tempfile
import unittest

REPO = Path(__file__).resolve().parents[1]
sys.path[:0] = [str(REPO / "adapters/generation"), str(REPO / "examples")]
import python_execution as execution
import python_prepared as prepared
from test_generation_python_code import fixture as code_fixture
from test_generation_python_journal import frame
from test_generation_python_prepared import fixture as prepared_fixture

APP, SUPERVISOR, PARENT, SDK = 501, 502, 503, 504
VERSION = 0x030c0ff0
TOKEN = "b" * 32


def write(path: Path, value: dict | bytes) -> None:
    """Write private test receipts without changing their recorded identities."""
    path.write_bytes(value if type(value) is bytes else prepared.encoded(value))
    path.chmod(0o600)


def fixture(root: Path, *, plain: bool = False) -> tuple:
    """Construct the documented wire records independently of their reader."""
    intent, launch, catalogue = prepared_fixture(root.resolve(strict=True))
    if plain:
        intent = replace(intent, plain=True)
        request = prepared.expected_request(intent)
        plan = prepared.expected_plan(request)
        manifest = {**launch["prepared"], "request_sha256": prepared.digest(request), "plan_sha256": prepared.digest(plan)}
        launch = {**launch, "request": request, "plan": plan, "prepared": manifest}
        for name, value in (("python-request.json", request), ("python-resolved-plan.json", plan), ("python-prepared.json", manifest)):
            write(intent.runtime / name, value)
    owner = execution.Owner(SUPERVISOR, PARENT, tuple(prepared.expected_command(intent)), 0, VERSION)
    common = {"schema_version": 1, "supervisor_pid": SUPERVISOR, "parent_pid": PARENT,
              "process_group": SUPERVISOR, "request_sha256": prepared.digest(launch["request"]),
              "plan_sha256": prepared.digest(launch["plan"]), "prepared_sha256": prepared.digest(launch["prepared"])}
    write(intent.runtime / "python-supervisor-start.json", {**common, "kind": "otelc.python.supervisor"})
    app = {**common, "kind": "otelc.python.application", "application_pid": APP,
           "sdk_pid": None if plain else SDK, "sdk_ready": not plain, "sdk_launch_id": None if plain else TOKEN,
           "native_command": [launch["prepared"]["driver"]["path"], "3", launch["plan"]["python"],
                              launch["plan"]["argv0"], *launch["plan"]["native_arguments"]]}
    write(intent.runtime / "python-application-start.json", app)
    if not plain:
        directory = intent.runtime / "sdk"
        directory.mkdir(mode=0o700)
        write(directory / "python-sdk-spawned.json", {"schema_version": 1, "pid": SDK, "parent_pid": SUPERVISOR, "launch_id": TOKEN})
        write(directory / "python-sdk-ready.json", {"schema_version": 1, "pid": SDK, "launch_id": TOKEN})
    path = (intent.project / intent.entry).resolve(strict=True)
    content, info = path.read_bytes(), path.stat()
    seconds, nanos = divmod(info.st_mtime_ns, 10 ** 9)
    source = struct.pack("!QQQQqQQ", APP, info.st_dev, info.st_ino, len(content), seconds, nanos, info.st_mode) + content
    raw = frame(1, 1, source, os.fsencode(path))
    sources = [{"path_hex": os.fsencode(path).hex(), "sha256": hashlib.sha256(content).hexdigest(),
                "device": info.st_dev, "inode": info.st_ino, "mtime_ns": info.st_mtime_ns}]
    codes = []
    total = len(content)
    if not plain:
        descriptor = code_fixture()
        descriptor["nodes"][2]["value"] = str(path)
        encoded = json.dumps(descriptor).encode()
        raw += frame(4, 2, struct.pack("!7Q", APP, 1, 0, VERSION, 2, len(encoded), 0) + encoded, os.fsencode(path))
        total += len(encoded)
        codes.append({"id": 1, "path_hex": os.fsencode(path).hex(), "sha256": hashlib.sha256(encoded).hexdigest(),
                      "offset": 0, "python_version": VERSION, "descriptor_version": 2})
    count = 1 + len(codes)
    raw += frame(2, count + 1, struct.pack("!7Q", APP, count, total, 0, 0, 1, 1), b"")
    journal = intent.runtime / "python-inputs.journal"
    write(journal, raw)
    evidence = {"phase": "complete", "python_finalized": True, "capture_failures": 0, "journal_failures": 0,
                "journal": prepared.file_identity(journal), "sources": sources, "imports": [], "codes": codes}
    final = {**common, "kind": "otelc.python.execution", "phase": "closed", "plain": plain,
             "application": {"pid": APP, "returncode": 0},
             "sdk": None if plain else {"pid": SDK, "returncode": 0, "launch_id": TOKEN, "phase": "closed"},
             "entry_evidence": evidence, "input_recheck": True, "bootstrap_recheck": None if plain else True,
             "source_complete": False, "failures": {}}
    write(intent.runtime / "python-execution.json", final)
    return intent, launch, owner, catalogue


class PythonExecutionTests(unittest.TestCase):
    def test_complete_lanes_keep_transport_facts_separate_from_source_admission(self) -> None:
        for plain in (False, True):
            with self.subTest(plain=plain), tempfile.TemporaryDirectory() as temporary:
                intent, launch, owner, catalogue = fixture(Path(temporary), plain=plain)
                value = execution.read(intent, launch, owner, catalogue)
                self.assertEqual((value.owner, value.application_pid), (owner, APP))
                self.assertEqual(value.sdk_pid, None if plain else SDK)
                self.assertEqual(value.launch_id, None if plain else TOKEN)
                self.assertTrue(value.journal.complete)
                self.assertEqual(len(value.descriptors), 0 if plain else 1)
                self.assertIs(value.final["source_complete"], False)

    def test_owner_is_independent_of_producer_claims_and_requires_successful_fixed_argv(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            intent, launch, owner, catalogue = fixture(Path(temporary))
            invalid = [None, replace(owner, pid=True), replace(owner, parent_pid=0), replace(owner, pid=PARENT),
                       replace(owner, parent_pid=999), replace(owner, returncode=True), replace(owner, returncode=-9),
                       replace(owner, argv=list(owner.argv)), replace(owner, argv=("other-command",)),
                       replace(owner, python_version=True), replace(owner, python_version=0x030b0ff0),
                       replace(owner, python_version=0x04000000), replace(owner, python_version=0x030d00f0)]
            for changed in invalid:
                with self.subTest(owner=changed), self.assertRaises(ValueError):
                    execution.read(intent, launch, changed, catalogue)
            self.assertFalse(execution.pid(False))

    def test_shared_records_require_exact_fields_types_hashes_and_actual_processes(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            intent, launch, owner, catalogue = fixture(Path(temporary))
            for name in ("python-supervisor-start.json", "python-application-start.json", "python-execution.json"):
                path = intent.runtime / name
                original, _ = prepared.read(path)
                for key, value in (("extra", None), ("schema_version", True), ("parent_pid", 900),
                                   ("supervisor_pid", 901), ("process_group", APP), ("kind", "other"),
                                   ("request_sha256", "a" * 64), ("plan_sha256", "a" * 64), ("prepared_sha256", "a" * 64)):
                    write(path, {**original, key: value})
                    with self.subTest(name=name, key=key), self.assertRaises(ValueError):
                        execution.read(intent, launch, owner, catalogue)
                write(path, original)

    def test_native_recipe_never_selects_another_command_or_descriptor(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            intent, launch, owner, catalogue = fixture(Path(temporary))
            path = intent.runtime / "python-application-start.json"
            original, _ = prepared.read(path)
            invalid = [None, [], [1], original["native_command"] + ["extra"]]
            for index, value in ((0, "/other/driver"), (1, "03"), (1, "2"), (1, "2147483648"),
                                 (1, "-1"), (1, "0"), (2, "/other/python"), (3, "/other/argv0"), (4, "-c")):
                command = original["native_command"].copy(); command[index] = value; invalid.append(command)
            for command in invalid:
                write(path, {**original, "native_command": command})
                with self.subTest(command=command), self.assertRaises(ValueError):
                    execution.read(intent, launch, owner, catalogue)
            for application in (True, 0, SUPERVISOR, PARENT):
                write(path, {**original, "application_pid": application})
                with self.subTest(application=application), self.assertRaises(ValueError):
                    execution.read(intent, launch, owner, catalogue)

    def test_sdk_spawn_ready_and_private_directory_belong_to_this_pair(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            intent, launch, owner, catalogue = fixture(Path(temporary))
            path = intent.runtime / "python-application-start.json"
            original, _ = prepared.read(path)
            for key, values in {"sdk_ready": [None, 1, False], "sdk_pid": [None, True, 0, APP, SUPERVISOR, PARENT],
                                "sdk_launch_id": [None, "", "a" * 31, "A" * 32]}.items():
                for value in values:
                    write(path, {**original, key: value})
                    with self.subTest(key=key, value=value), self.assertRaises(ValueError):
                        execution.read(intent, launch, owner, catalogue)
            write(path, original)
            for name in ("python-sdk-spawned.json", "python-sdk-ready.json"):
                record = intent.runtime / "sdk" / name
                value, _ = prepared.read(record)
                write(record, {**value, "pid": SDK + 1})
                with self.subTest(name=name), self.assertRaises(ValueError):
                    execution.read(intent, launch, owner, catalogue)
                write(record, value)
            (intent.runtime / "sdk").chmod(0o755)
            with self.assertRaisesRegex(ValueError, "not private"):
                execution.read(intent, launch, owner, catalogue)

    def test_plain_lane_refuses_sdk_or_health_files_including_broken_links(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            intent, launch, owner, catalogue = fixture(Path(temporary), plain=True)
            for name in ("sdk", "health.json"):
                path = intent.runtime / name
                path.symlink_to("missing")
                with self.subTest(name=name), self.assertRaisesRegex(ValueError, "plain Python"):
                    execution.read(intent, launch, owner, catalogue)
                path.unlink()

    def test_final_exit_recheck_failure_or_public_summary_alteration_cannot_pass(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            intent, launch, owner, catalogue = fixture(Path(temporary))
            path = intent.runtime / "python-execution.json"
            original, _ = prepared.read(path)
            variants = [("phase", "failed"), ("plain", 0), ("source_complete", True), ("input_recheck", False),
                        ("bootstrap_recheck", None), ("failures", {"missing": 1}), ("failures", []),
                        ("application", {"pid": APP, "returncode": True}), ("sdk", None),
                        ("sdk", {**original["sdk"], "returncode": 7}), ("entry_evidence", {})]
            for key, value in variants:
                write(path, {**original, key: value})
                with self.subTest(key=key, value=value), self.assertRaises(ValueError):
                    execution.read(intent, launch, owner, catalogue)

    def test_entry_bytes_metadata_completeness_and_lane_graphs_are_checked(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            intent, launch, owner, catalogue = fixture(Path(temporary))
            path = intent.runtime / "python-inputs.journal"
            original = path.read_bytes()
            # Change the source's recorded device without changing its bytes.
            changed = bytearray(original)
            offset = 36 + len(os.fsencode((intent.project / intent.entry).resolve())) + 8
            changed[offset:offset + 8] = struct.pack("!Q", 0)
            write(path, bytes(changed))
            with self.assertRaisesRegex(ValueError, "opened-file"):
                execution.entry_evidence(intent.runtime, intent, APP, VERSION)
            write(path, original[:-1])
            with self.assertRaises(ValueError):
                execution.entry_evidence(intent.runtime, intent, APP, VERSION)
            write(path, original)
            with self.assertRaisesRegex(ValueError, "interpreter"):
                execution.entry_evidence(intent.runtime, intent, APP, VERSION + 1)

    def test_changed_prepared_inputs_are_rechecked_after_execution(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            intent, launch, owner, catalogue = fixture(Path(temporary))
            (intent.project / intent.entry).write_text("changed source")
            with self.assertRaises(ValueError):
                execution.read(intent, launch, owner, catalogue)
