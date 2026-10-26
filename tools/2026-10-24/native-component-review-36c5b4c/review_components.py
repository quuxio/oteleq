"""Independently build and check the pinned official native SDK component."""

import hashlib
import json
import os
from pathlib import Path
import subprocess
import time

ROOT = Path(__file__).resolve().parent
SOURCE = ROOT / "source"
INDEX = json.loads((ROOT / "source-index.json").read_text())


def source_facts() -> dict:
    result = {}
    for name, digest in INDEX["files"].items():
        path = SOURCE / name
        info = path.stat()
        assert hashlib.sha256(path.read_bytes()).hexdigest() == digest, name
        result[name] = (info.st_dev, info.st_ino, info.st_mode, info.st_size,
                        info.st_mtime_ns, info.st_ctime_ns)
    return result


before = source_facts()
environment = {key: value for key, value in os.environ.items()
               if not key.startswith(("OTEL", "OTELEQ", "GH_", "GITHUB_", "SONAR_", "AWS_"))}
environment.update(LLVM_CONFIG="/opt/homebrew/opt/llvm@22/bin/llvm-config",
                   OTELC_LLVM_BIN="/opt/homebrew/opt/llvm@22/bin", PYTHONDONTWRITEBYTECODE="1")
python = "/Users/sclarke/github/oteleq-qualification/2026-10-24/python-live-metrics/env-312/bin/python"
argv = ["make", "native-check", "PYTHON=" + python]
(ROOT / "command.json").write_text(json.dumps({"argv": argv, "cwd": str(SOURCE)}, indent=2) + "\n")
started = time.monotonic()
with (ROOT / "native-check.log").open("xb") as output:
    result = subprocess.run(argv, cwd=SOURCE, env=environment, stdout=output, stderr=subprocess.STDOUT)
held = source_facts() == before
receipt = {"head": INDEX["head"], "exit_code": result.returncode,
           "seconds": round(time.monotonic() - started, 3),
           "source_files_bytes_and_facts_held": len(before) if held else 0}
if result.returncode == 0:
    receipt["native_component"] = json.loads((SOURCE / "build/native-control-coverage.json").read_text())
(ROOT / "result.json").write_text(json.dumps(receipt, indent=2) + "\n")
print(json.dumps({key: value for key, value in receipt.items() if key != "native_component"}))
raise SystemExit(0 if result.returncode == 0 and held else 1)
