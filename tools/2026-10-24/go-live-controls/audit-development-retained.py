"""Correct the audit-only directory typo without starting another application."""

import ast
import hashlib
import json
import os
from pathlib import Path
import stat
import subprocess
from unittest.mock import patch

ROOT = Path(__file__).resolve().parent
DESTINATION = ROOT / "public-development-01"
COMPARISON = DESTINATION / "comparison"
METHODS = ("BothOn", "CollectionOff", "EmissionOff", "BothOff")
STATES = [{"collection": c, "emission": e} for c, e in ((True, True), (False, True), (True, False), (False, False))]


def identity(path):
    value = path.lstat()
    if stat.S_ISLNK(value.st_mode):
        digest = hashlib.sha256(os.readlink(path).encode()).hexdigest()
    else:
        assert stat.S_ISREG(value.st_mode)
        with path.open("rb") as source:
            digest = hashlib.file_digest(source, "sha256").hexdigest()
    return [digest, value.st_dev, value.st_ino, value.st_mode, value.st_uid, value.st_gid,
            value.st_size, value.st_mtime_ns, value.st_ctime_ns, value.st_nlink]


def manifest():
    return {path.relative_to(COMPARISON).as_posix(): identity(path) for path in sorted(COMPARISON.rglob("*"))
            if path.is_symlink() or path.is_file()}


class CorrectDirectory(ast.NodeTransformer):
    def __init__(self):
        self.changes = 0

    def visit_Constant(self, node):
        if node.value == "go-worker-control":
            node.value = "go-runtime/oteleq-rendezvous"
            self.changes += 1
        return node


original = ROOT / "qualify-development.py"
source = ast.parse(original.read_text())
audit, = [node for node in source.body if isinstance(node, ast.FunctionDef) and node.name == "audit"]
correction = CorrectDirectory()
audit = correction.visit(audit)
assert correction.changes == 1
namespace = {"json": json, "METHODS": METHODS, "STATES": STATES}
exec(compile(ast.Module(body=[audit], type_ignores=[]), str(original) + " [audit-only directory correction]", "exec"), namespace)
before = manifest()
with patch.object(subprocess, "Popen", side_effect=AssertionError("retained audit cannot launch a process")):
    result = namespace["audit"](COMPARISON / "report.json")
    for path in COMPARISON.glob("*/*/go-controls.json"):
        value = json.loads(path.read_text())
        method = path.parent.parent.name
        actual = [step["requested"] for step in value["steps"]]
        assert actual[1:] == [STATES[0], STATES[1], STATES[3], STATES[2]], method
        root = path.parent / "go-runtime/oteleq-rendezvous"
        start = json.loads((root / "start.ready").read_text())
        phases = [phase + "-" + str(index) for index in range(5) for phase in ("before", "after")] + ["finish"]
        for phase in phases:
            ready, temporary = root / (phase + ".ready"), root / (phase + ".tmp")
            assert ready.stat() == temporary.stat()
            message = json.loads(ready.read_text())
            assert message == {"schema_version": 1, "kind": "oteleq.go.checkpoint", "phase": phase,
                               "token": start["token"], "pid": value["pid"], "parent_pid": value["supervisor_pid"]}
            acknowledgement, temporary = root / (phase + ".resume"), root / (phase + ".resume.tmp")
            assert acknowledgement.stat() == temporary.stat()
            assert acknowledgement.read_text() == start["token"] + " " + phase + "\n"
            for marker in (ready, acknowledgement):
                assert stat.S_IMODE(marker.stat().st_mode) == 0o600 and marker.stat().st_nlink == 2
        if value["plain"]:
            continue
        snapshots = []
        for index, step in enumerate(value["steps"]):
            before_count = 0 if index == 0 else index + 1
            for point, count in ((step["before"]["health"], before_count),
                                 (step["after"]["health"], index + 2),
                                 (step["after"]["settled"], index + 2)):
                assert int(point["probe_accounting"]["function_ended"]) == count
                assert int(point["trace_exports"]["exported_spans"]) == count
                assert point["trace_exports"]["queue_pending"] == "0"
                assert all(point["controls"][key] is flag for key, flag in step["requested"].items())
                snapshots.append(point)
        snapshots.append(value["restored"]["health"])
        attempts = [int(point["metric_flush"]["attempts"]) for point in snapshots]
        assert all(previous < current for previous, current in zip([0, *attempts], attempts))
after = manifest()
assert before == after
result.update(status="passed", new_application_launches=0, retained_files_checked=len(before),
              retained_bytes_and_file_facts_preserved=True,
              original_audit_status="failed: audit-only checkpoint directory name",
              original_runner_sha256=hashlib.sha256(original.read_bytes()).hexdigest(),
              audit_sha256=hashlib.sha256(Path(__file__).read_bytes()).hexdigest(),
              current_final_source_qualification=False)
(DESTINATION / "retained-audit-result.json").write_text(json.dumps(result, indent=2) + "\n")
print(json.dumps(result, indent=2), flush=True)
