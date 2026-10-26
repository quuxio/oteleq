"""Seal the independent review without changing its frozen source tree."""

import hashlib
import json
from pathlib import Path
import re
import subprocess

root = Path(__file__).resolve().parent
tests = json.loads((root / "tests.json").read_text())
extra = json.loads((root / "python-default-integration.json").read_text())
proof = json.loads((root / "fifo-bindings/proof.json").read_text())
assert all(row["exit_code"] == 0 for row in tests["runs"])
assert extra["exit_code"] == 0 and extra["source_preserved"]
assert proof["reader_timed_out"] and proof["real_prepared_application_loaded"]
paths = subprocess.check_output(
    ["git", "diff", "--name-only", tests["base"], tests["head"]],
    cwd="/Users/sclarke/github/otelc", text=True,
).splitlines()
assert len(paths) == 26
review = {
    "head": tests["head"], "base": tests["base"],
    "archive_sha256": tests["archive_sha256"],
    "archive_independently_reproduced_from_git": True,
    "reviewed_files": paths, "whole_feature_reviewed": True,
    "verdict": "changes_requested",
    "findings": [{
        "priority": "P2", "file": "otelc/witness.py", "line": 255,
        "title": "Refuse nonregular bindings and bound the opened-file read",
        "explanation": "The size check accepts a real mode-0600 FIFO (size zero), then read_text blocks indefinitely during preparation. A real PreparedApplication loaded successfully before the bindings reader hung; the application was never executed. Regular-file validation must use the opened nonblocking descriptor, with a bounded read and stability checks, before the existing JSON/schema/digest validation.",
        "proof": "fifo-bindings/proof.json", "accepted_by_producer": True,
    }],
    "validation": {"maven_tests": 59, "maven_failures": 0,
        "maven_line_coverage": {"covered": 1330, "missed": 83},
        "python_integration_tests": sum(int(re.search(r"Ran (\d+) tests", (root / name).read_text())[1])
            for name in ("python.log", "python-default-integration.log")),
        "python_failures": 0,
        "source_files_preserved": 338},
    "consumer_admission": "not_qualified",
    "count_correction": "The earlier receipt stated 35 Python tests. Actual unittest footers show 30 plus 2 default tests: 32. Raw results are unchanged and retained.",
    "separate_required_consumer_work": "Versioned correlation with the SDK-free private harness's actual Java thread ID; foreign-envelope-ready-first must not be attributed to the intended action.",
    "evidence_sha256": {
        name: hashlib.sha256((root / name).read_bytes()).hexdigest()
        for name in ("tests.json", "python-default-integration.json",
                     "fifo-bindings/proof.json", "maven.log", "python.log",
                     "python-default-integration.log")
    },
}
(root / "review.json").write_text(json.dumps(review, indent=2) + "\n")
print(json.dumps({"verdict": review["verdict"], "files": len(paths),
    "review_sha256": hashlib.sha256((root / "review.json").read_bytes()).hexdigest()}))
