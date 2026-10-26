"""Check the embedded CLI's planning and refusal contract without app execution."""
import hashlib
import json
import os
from pathlib import Path
import subprocess
import sys

ROOT = Path(__file__).resolve().parent
CLI = ROOT / "quux-oteleq-0177499"
PROVIDER = Path("/Users/sclarke/github/otelc-qualification/2026-10-20/integrated-provider/d6d03b7/provider")
FOLDER = ROOT / "preflight"
FOLDER.mkdir(exist_ok=False)
SOURCE = FOLDER / "application"
SOURCE.mkdir()
APPLICATION = SOURCE / "region.py"
APPLICATION.write_text('raise RuntimeError("application initialiser must not execute")\n'
                       'def distance(start:int,end:int)->int:return end-start\n')
SOURCE_SHA = hashlib.sha256(APPLICATION.read_bytes()).hexdigest()
os.environ.update(OTELEQ_PYTHON=sys.executable, OTELEQ_CLI=str(CLI), PYTHONDONTWRITEBYTECODE="1")


def command(arguments: list, name: str, expected=0) -> str:
    result = subprocess.run([str(value) for value in arguments], capture_output=True, check=False, timeout=120)
    (FOLDER / (name + ".stdout")).write_bytes(result.stdout)
    (FOLDER / (name + ".stderr")).write_bytes(result.stderr)
    assert result.returncode == expected, (name, result.returncode)
    return result.stdout.decode().strip()


def plan(name: str, right: int) -> Path:
    config = FOLDER / (name + ".toml")
    config.write_text('schema_version=1\nlanguages=["python"]\n[generation]\ncases_per_function=3\n'
        '[[fixtures]]\nfunction="*distance"\n'
        'domains=[{kind="integer",minimum=7,maximum=9},{kind="integer",minimum=7,maximum=9}]\n'
        'preconditions=[{left=0,operator="<",right=' + str(right) + '}]\n')
    return Path(command([CLI, "plan", "--source", SOURCE, "--otelc-root", PROVIDER,
                         "--workspace-parent", FOLDER, "--config", config], name + "-plan"))


valid = plan("valid", 1)
data = json.loads((valid / "plan.json").read_text())
assert len(data["inventory"]) == 1 and data["inventory"][0]["status"] == "ready"
assert data["inventory"][0]["input_cases"] == [[7, 9], [7, 8], [8, 9]]
assert data["inventory"][0]["input_preconditions"] == [{"left": 0, "operator": "<", "right": 1}]
command([CLI, "generate", "--workspace", valid], "valid-generate")
corpus = json.loads((valid / "tests/corpus.json").read_text())
assert [case["arguments_requested"] for case in corpus] == [[7, 9], [7, 8], [8, 9]]
blocked = plan("blocked", 0)
data = json.loads((blocked / "plan.json").read_text())
assert len(data["inventory"]) == 1 and data["inventory"][0]["status"] == "blocked"
assert "no generated inputs" in data["inventory"][0]["reason"]
command([CLI, "generate", "--workspace", blocked], "blocked-generate")
assert json.loads((blocked / "tests/corpus.json").read_text()) == []
command([CLI, "run", "--workspace", blocked, "--report-dir", FOLDER / "refused-report"], "blocked-run", 3)
report = json.loads((FOLDER / "refused-report/report.json").read_text())
assert report["source_preserved"] and report["cases"] == [] and len(report["blocked"]) == 1
command([sys.executable, blocked / "tests/test_equivalence.py"], "blocked-suite", 1)
assert "no generated inputs" in (FOLDER / "blocked-suite.stderr").read_text()
assert "Ran 1 test" in (FOLDER / "blocked-suite.stderr").read_text()
assert not list(FOLDER.rglob("typed-observation.json"))
assert hashlib.sha256(APPLICATION.read_bytes()).hexdigest() == SOURCE_SHA
result = {"scope": "planning/generation and prelaunch refusal only; no target execution",
          "revision": "0177499cf482d0cb9a9c4f274ce11d4ef1d376c1", "cli_sha256": hashlib.sha256(CLI.read_bytes()).hexdigest(),
          "frozen_valid_cases": [[7, 9], [7, 8], [8, 9]], "selected_blockers": 1,
          "strict_refusal_exit": 3, "generated_blocker_suite_exit": 1,
          "actual_application_launches": 0, "source_preserved": True}
(ROOT / "preflight.json").write_text(json.dumps(result, indent=2) + "\n")
print(json.dumps(result, indent=2))
