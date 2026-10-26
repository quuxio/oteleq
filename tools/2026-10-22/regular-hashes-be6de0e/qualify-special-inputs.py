"""Check public CLI handling of FIFO SDK identities without executing an SDK."""
import json
import os
from pathlib import Path
import signal
import subprocess
import sys
import time

ROOT = Path("/Users/sclarke/github/oteleq-qualification/2026-10-22/regular-hashes-be6de0e")
CLI = ROOT / "quux-oteleq"
application = ROOT / "special-fixture/application"
provider = ROOT / "special-fixture/provider"
for path in (application, provider / "target/debug", provider / "adapters/python",
             provider / ".venv/lib/python3.12/site-packages"):
    path.mkdir(parents=True, exist_ok=False)
(application / "app.py").write_text("def selected_match(n:int)->int:return n+4\n")
(provider / "adapters/python/requirements.txt").write_text("")
os.environ.update(OTELEQ_PYTHON=sys.executable, PYTHONDONTWRITEBYTECODE="1")

def run(name, arguments, expected):
    started = time.monotonic()
    process = subprocess.Popen(list(map(str, [CLI, *arguments])), cwd=ROOT,
        stdout=subprocess.PIPE, stderr=subprocess.PIPE, start_new_session=True)
    try:
        stdout, stderr = process.communicate(timeout=20)
    except subprocess.TimeoutExpired:
        os.killpg(process.pid, signal.SIGKILL)
        stdout, stderr = process.communicate()
        (ROOT / (name + ".stdout")).write_bytes(stdout)
        (ROOT / (name + ".stderr")).write_bytes(stderr)
        raise AssertionError("CLI blocked on synthetic SDK identity: " + name)
    (ROOT / (name + ".stdout")).write_bytes(stdout)
    (ROOT / (name + ".stderr")).write_bytes(stderr)
    assert process.returncode == expected, (name, process.returncode, stderr.decode())
    return stdout.decode().strip(), time.monotonic() - started

records = []
target = provider / "target/debug/quux-otelc"
pipe = ROOT / "special-fixture/tool-pipe"
os.mkfifo(pipe)
try:
    for label in ("fifo", "symlink-to-fifo"):
        if label == "fifo":
            os.mkfifo(target)
        else:
            target.symlink_to(pipe)
        try:
            text, seconds = run(label + "-plan", ["plan", "--source", application,
                "--otelc-root", provider, "--workspace-parent", ROOT, "--language", "python"], 0)
            workspace = Path(text)
            plan = json.loads((workspace / "plan.json").read_text())
            assert len(plan["inventory"]) == 1
            entry = plan["inventory"][0]
            assert entry["status"] == "blocked" and "not a regular file" in entry["reason"], entry
            run(label + "-generate", ["generate", "--workspace", workspace], 0)
            report = ROOT / (label + "-report")
            run(label + "-run", ["run", "--workspace", workspace, "--report-dir", report], 3)
            summary = json.loads((report / "report.json").read_text())
            assert summary["cases"] == [] and len(summary["blocked"]) == 1
            assert summary["source_preserved"] and summary["exit_code"] == 3
            records.append({"input_kind": label, "planning_completed_seconds": seconds,
                "selected_blockers": 1, "strict_run_exit": 3, "actual_application_launches": 0})
        finally:
            target.unlink()
finally:
    pipe.unlink()
assert not list(ROOT.rglob("typed-observation.json"))
result = {"scope": "synthetic SDK identity failure only; no SDK or application execution",
          "controls": records, "actual_application_launches": 0,
          "source_preserved": (application / "app.py").read_text() == "def selected_match(n:int)->int:return n+4\n"}
(ROOT / "special-input-controls.json").write_text(json.dumps(result, indent=2) + "\n")
print(json.dumps(result, indent=2))

