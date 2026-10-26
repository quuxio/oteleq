"""Demonstrate a signal delivered immediately before the native child spawn."""
import json, os, signal, subprocess, sys, tempfile, time
from pathlib import Path
from unittest.mock import patch
SOURCE = Path(__file__).resolve().parent / "source"
sys.path[:0] = [str(SOURCE), str(SOURCE / "tests")]
from otelc import go_supervisor
base = Path(__file__).resolve().parent
with tempfile.TemporaryDirectory(dir=base) as temporary:
 root = Path(temporary)
 owner = object.__new__(go_supervisor.Owner)
 owner.directory = root
 owner.original = {"plain": True, "launch_id": "0" * 32}
 owner.plan = {"argv": [sys.executable, "-I", "-S", "-c", "import time; time.sleep(30)"], "cwd": str(root), "binary": {}}
 owner.prepared = {}
 owner.application = None
 owner.stopping = None
 owner.interrupt(signal.SIGTERM, None)
 try:
  with patch.object(go_supervisor.files, "write"):
   owner.start()
  time.sleep(.1)
  alive = owner.application.poll() is None
  result = {"head": "67b1b0d960626dbd4a149e43ba0b24c886fa4cec", "signal": signal.SIGTERM,
     "signal_delivered_before_start": owner.stopping == signal.SIGTERM,
     "child_started_after_signal": True, "child_still_alive": alive,
     "actual_child_pid": owner.application.pid,
     "scope": "Real subprocess through unchanged Owner.start; minimal component fixture, not Go qualification."}
 finally:
  owner.cleanup()
 result["child_reaped_by_explicit_review_cleanup"] = owner.application.poll() is not None
 (base / "pending-signal-result.json").write_text(json.dumps(result, indent=2) + "\n")
 print(json.dumps(result))
 assert alive, "candidate did not reproduce the pending-signal problem"
