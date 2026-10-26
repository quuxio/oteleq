"""Bind the unchanged qualified binary to the rebased published source."""
import hashlib
import json
import os
from pathlib import Path
import subprocess
import sys

ROOT = Path("/Users/sclarke/github/oteleq-qualification/2026-10-22/regular-hashes-be6de0e")
SOURCE = Path("/Users/sclarke/github/oteleq-qualification/work/oteleq-file-hashes")
sys.path[:0] = [str(SOURCE / name) for name in ("tests", "adapters/generation", "examples")]
from qualify_generation import command
from qualify_retained_source import check_report, python_case_id

os.environ.update(OTELEQ_PYTHON=sys.executable, OTELEQ_CLI=str(ROOT / "quux-oteleq-rebased"),
                  PYTHONDONTWRITEBYTECODE="1")
workspace = Path((ROOT / "actual/replan-plan.stdout").read_text().strip())
plan = json.loads((workspace / "plan.json").read_text())
corpus = json.loads((workspace / "tests/corpus.json").read_text())
case = python_case_id(plan, corpus)
result = json.loads(command([ROOT / "quux-oteleq-rebased", "replay", "--workspace", workspace,
                             "--case", case], ROOT, "rebased-replay-qualified-host"))
report = Path(result["report"])
data = json.loads(report.read_text())
attempts = check_report(report, {item["path"] for item in data["owned_source_exclusions"]}, 1)
original = set(json.loads((ROOT / "actual/qualification.json").read_text())["actual_attempt_directories"])
assert len(attempts) == 4 and original.isdisjoint(attempts)
changed = subprocess.check_output(["git", "diff", "--name-only",
    "be6de0e1466ce70938a3096ee613cda82c7d3f36", "HEAD"], cwd=SOURCE, text=True).splitlines()
assert len(changed) == 4 and all(name.startswith("docs/") for name in changed)
digest = lambda name: hashlib.sha256((ROOT / name).read_bytes()).hexdigest()
assert digest("quux-oteleq") == digest("quux-oteleq-rebased")
record = {"qualified_build_revision": "be6de0e1466ce70938a3096ee613cda82c7d3f36",
          "published_runtime_revision": subprocess.check_output(["git", "rev-parse", "HEAD"],
                                                              cwd=SOURCE, text=True).strip(),
          "rebuild_byte_identical": True, "cli_sha256": digest("quux-oteleq-rebased"),
          "rebased_source_archive_sha256": digest("rebased-source.tar"),
          "documentation_only_source_delta": changed,
          "additional_rebuilt_cli_application_launches": 4,
          "additional_attempt_directories": sorted(attempts),
          "complete_oracles_and_witness_verified": True,
          "earlier_unqualified_host_refused": True}
(ROOT / "rebased-identity-verification.json").write_text(json.dumps(record, indent=2) + "\n")
print(json.dumps(record, indent=2))

