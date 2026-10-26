"""Independently build the frozen SDK completion fix and recheck its source inputs."""
import hashlib
import json
import os
from pathlib import Path
import subprocess
import time

ROOT = Path(__file__).resolve().parent
SOURCE = ROOT / "source-42258a4"
MANIFEST = json.loads((ROOT / "source-42258a4.json").read_bytes())
REPOSITORY = Path("/Users/sclarke/github/oteleq-qualification/2026-10-24/java-generated-actions/clock-parent-preliminary-review/maven-repository")
COMMAND = ["/opt/homebrew/bin/mvn", "-o", "-Dmaven.repo.local=" + str(REPOSITORY), "-f", "adapters/java/pom.xml", "clean", "verify"]
for name, digest in MANIFEST["files"].items():
    assert hashlib.sha256((SOURCE / name).read_bytes()).hexdigest() == digest, name
started = time.monotonic()
with (ROOT / "maven-clean-verify.log").open("xb") as log:
    result = subprocess.run(COMMAND, cwd=SOURCE, env={**os.environ, "JAVA_HOME": "/opt/homebrew/opt/openjdk@21"}, stdout=log, stderr=subprocess.STDOUT, check=False)
changed = [name for name, digest in MANIFEST["files"].items() if hashlib.sha256((SOURCE / name).read_bytes()).hexdigest() != digest]
proof = {"head": MANIFEST["head"], "command": COMMAND, "exit_code": result.returncode, "seconds": round(time.monotonic() - started, 3), "source_files_checked": len(MANIFEST["files"]), "source_preserved": not changed, "changed": changed}
(ROOT / "maven-result.json").write_text(json.dumps(proof, indent=2) + "\n")
print(json.dumps(proof), flush=True)
assert not changed, changed
raise SystemExit(result.returncode)
