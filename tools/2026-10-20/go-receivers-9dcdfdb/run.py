"""Run frozen Go qualification or the full gate with durable child status."""
import argparse
import datetime
import json
import os
from pathlib import Path
import subprocess

ROOT = Path(__file__).resolve().parent
SOURCE = ROOT / "consumer"
PROVIDER = Path("/Users/sclarke/github/otelc-qualification/2026-10-20/integrated-provider/d6d03b7/provider")
PYTHON = PROVIDER / ".venv/bin/python"
parser = argparse.ArgumentParser()
parser.add_argument("task", choices=("qualification", "gate"))
args = parser.parse_args()
manifest = json.loads((PROVIDER.parent / "manifest.json").read_text())
environment = {**os.environ, **manifest["environment"], "OTELEQ_PYTHON": str(PYTHON),
               "OTELC_JAVAC": "/opt/homebrew/opt/openjdk@21/bin/javac",
               "OTELC_CLANG": "/opt/homebrew/opt/llvm@22/bin/clang",
               "OTELC_CLANGXX": "/opt/homebrew/opt/llvm@22/bin/clang++",
               "PYTHONDONTWRITEBYTECODE": "1", "CARGO_INCREMENTAL": "0",
               "CARGO_TARGET_DIR": "/Users/sclarke/github/oteleq-qualification/work/java-quality-target",
               "PATH": "/Users/sclarke/.rustup/toolchains/1.98.1-aarch64-apple-darwin/bin:/Users/sclarke/.cargo/bin:/opt/homebrew/opt/llvm@22/bin:/opt/homebrew/opt/node@24/bin:/opt/homebrew/bin:/usr/bin:/bin"}
if args.task == "qualification":
    command = [str(PYTHON), "tests/qualify_go_receivers.py", "--otelc-root", str(PROVIDER),
               "--report-dir", str(ROOT / "actual"), "--cli", str(ROOT / "quux-oteleq")]
else:
    command = ["make", "check", "PYTHON=" + str(PYTHON), "NODE=/opt/homebrew/opt/node@24/bin/node"]
state = {"task": args.task, "state": "running", "source_commit": json.loads((ROOT / "runtime.json").read_text())["commit"],
         "started_at": datetime.datetime.now(datetime.timezone.utc).isoformat()}
path = ROOT / (args.task + "-state.json")
with (ROOT / (args.task + ".log")).open("xb") as log:
    child = subprocess.Popen(command, cwd=SOURCE, env=environment, stdout=log, stderr=subprocess.STDOUT)
    state["pid"] = child.pid
    path.write_text(json.dumps(state, indent=2) + "\n")
    code = child.wait()
state.update(state="completed", exit_code=code, completed_at=datetime.datetime.now(datetime.timezone.utc).isoformat())
path.write_text(json.dumps(state, indent=2) + "\n")
print(json.dumps(state), flush=True)
raise SystemExit(code)
