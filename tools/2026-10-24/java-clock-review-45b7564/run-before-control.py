"""Require all three new clock regressions to fail against unchanged SDK production."""
import hashlib
import json
import os
from pathlib import Path
import subprocess
import xml.etree.ElementTree as ET

ROOT = Path(__file__).resolve().parent
SOURCE = ROOT / "source-before-1b02dbc"
MANIFEST = json.loads((ROOT / "before-inputs.json").read_bytes())
METHODS = {"nestedSpansShareTheParentClockWhenWallTimeMovesForward", "nestedSpansShareTheParentClockWhenWallTimeMovesBackwards", "asynchronousClockAndOriginalFutureRemainUnchanged"}
COMMAND = ["/opt/homebrew/bin/mvn", "-o", "-Dmaven.repo.local=/Users/sclarke/github/oteleq-qualification/2026-10-24/java-generated-actions/clock-parent-preliminary-review/maven-repository", "-f", "adapters/java/pom.xml", "-Dtest=ExtensionTests#" + "+".join(sorted(METHODS)), "clean", "test"]
with (ROOT / "before-control.log").open("xb") as log:
    result = subprocess.run(COMMAND, cwd=SOURCE, env={**os.environ, "JAVA_HOME": "/opt/homebrew/opt/openjdk@21"}, stdout=log, stderr=subprocess.STDOUT, check=False)
rows = []
for path in (SOURCE / "adapters/java/target/surefire-reports").glob("TEST-*.xml"):
    rows.extend(ET.parse(path).getroot().findall("testcase"))
assert {row.get("name") for row in rows} == METHODS and len(rows) == 3
assert result.returncode != 0
assert all(row.find("failure") is not None and row.find("error") is None and row.find("skipped") is None for row in rows)
assert all("child started before its parent" in row.find("failure").get("message", "") or "child ended after its parent" in row.find("failure").get("message", "") for row in rows)
changed = [name for name, digest in MANIFEST["files"].items() if hashlib.sha256((SOURCE / name).read_bytes()).hexdigest() != digest]
assert not changed, changed
proof = {"production_head": MANIFEST["production_head"], "test_source_head": MANIFEST["test_source_head"], "command": COMMAND, "exit_code": result.returncode, "expected_failed_tests": [{"name": row.get("name"), "reason": row.find("failure").get("message")} for row in rows], "source_preserved": True, "source_files_checked": len(MANIFEST["files"])}
(ROOT / "before-control.json").write_text(json.dumps(proof, indent=2) + "\n")
print(json.dumps(proof), flush=True)
