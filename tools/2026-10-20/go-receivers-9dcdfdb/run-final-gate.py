"""Record the final publication head and complete quality gate."""
import datetime
import json
import os
from pathlib import Path
import subprocess

ROOT = Path(__file__).resolve().parent
SOURCE = Path("/Users/sclarke/github/oteleq-qualification/work/oteleq-go-receivers")
PROVIDER = Path("/Users/sclarke/github/otelc-qualification/2026-10-20/integrated-provider/d6d03b7/provider")
PYTHON = PROVIDER / ".venv/bin/python"
def git(*arguments):
    return subprocess.check_output(["git", *arguments], cwd=SOURCE, text=True).strip()
assert not git("status", "--porcelain")
head = git("rev-parse", "HEAD")
manifest = json.loads((PROVIDER.parent / "manifest.json").read_text())
environment = {**os.environ, **manifest["environment"], "OTELEQ_PYTHON": str(PYTHON),
               "OTELC_JAVAC": "/opt/homebrew/opt/openjdk@21/bin/javac",
               "OTELC_CLANG": "/opt/homebrew/opt/llvm@22/bin/clang",
               "OTELC_CLANGXX": "/opt/homebrew/opt/llvm@22/bin/clang++",
               "PYTHONDONTWRITEBYTECODE": "1", "CARGO_INCREMENTAL": "0",
               "CARGO_TARGET_DIR": "/Users/sclarke/github/oteleq-qualification/work/java-quality-target",
               "PATH": "/Users/sclarke/.rustup/toolchains/1.98.1-aarch64-apple-darwin/bin:/Users/sclarke/.cargo/bin:/opt/homebrew/opt/llvm@22/bin:/opt/homebrew/opt/node@24/bin:/opt/homebrew/bin:/usr/bin:/bin"}
state = {"source_commit": head, "state": "running", "started_at": datetime.datetime.now(datetime.timezone.utc).isoformat()}
path = ROOT / "final-gate-state.json"
with (ROOT / "final-gate.log").open("xb") as log:
    child = subprocess.Popen(["make", "check", "PYTHON=" + str(PYTHON), "NODE=/opt/homebrew/opt/node@24/bin/node"],
                             cwd=SOURCE, env=environment, stdout=log, stderr=subprocess.STDOUT)
    state["pid"] = child.pid
    path.write_text(json.dumps(state, indent=2) + "\n")
    code = child.wait()
unchanged = head == git("rev-parse", "HEAD") and not git("status", "--porcelain")
state.update(state="completed", exit_code=code, source_unchanged=unchanged,
             completed_at=datetime.datetime.now(datetime.timezone.utc).isoformat())
path.write_text(json.dumps(state, indent=2) + "\n")
print(json.dumps(state), flush=True)
raise SystemExit(code if unchanged else 1)
