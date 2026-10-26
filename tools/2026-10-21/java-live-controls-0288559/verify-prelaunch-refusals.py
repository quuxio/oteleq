"""Requested live controls must refuse incompatible schedules before app launch."""
import json
import os
from pathlib import Path
import sys

ROOT = Path(__file__).resolve().parent
sys.path.insert(0, str(ROOT / "source/tests"))
from qualify_generation import command

cli = ROOT / "quux-oteleq"
os.environ.update(OTELEQ_PYTHON=sys.executable, OTELEQ_CLI=str(cli))
destination = ROOT / "prelaunch-refusals"
destination.mkdir(mode=0o700)
first = '{action="call",arguments="case",metrics={collection=true,emission=true}}'
cases = [
    ("legacy-controls", "legacy", [first], "live metrics require prepared Java"),
    ("missing-state", "prepared", [first, '{action="call",arguments=[2]}'], "explicit state for every call"),
    ("missing-positive", "prepared", ['{action="call",arguments="case",metrics={collection=false,emission=false}}'], "initial collection-on"),
]
results = []
for name, backend, schedule, expected in cases:
    folder = destination / name
    folder.mkdir()
    source = folder / "application"
    source.mkdir()
    (source / "Counter.java").write_text('class Counter {private int value; private Counter(int start){value=start;} int run(int amount){value+=amount;return value;}}\n')
    provider = Path('/Users/sclarke/github/otelc-qualification/2026-10-20/integrated-provider/d6d03b7/provider' if backend == "legacy" else '/Users/sclarke/github/oteleq-qualification/2026-10-21/java-prepared-f3279fd/prepared-provider')
    config = folder / "equivalence.toml"
    config.write_text('schema_version=1\nlanguages=["java"]\n[adapters.java]\nbackend=' + json.dumps(backend) + '\n[functions]\ninclude=["Counter.run(int)"]\n[[fixtures]]\nfunction="Counter.run(int)"\ncases=[[7]]\nreceiver={factory="Counter",arguments=[10]}\nsequence=[' + ','.join(schedule) + ']\n')
    workspace = Path(command([cli, "plan", "--source", source, "--otelc-root", provider, "--workspace-parent", folder, "--config", config], folder, "plan"))
    command([cli, "generate", "--workspace", workspace], folder, "generate")
    command([cli, "run", "--workspace", workspace, "--report-dir", folder / "comparison"], folder, "run", expected=3)
    report = json.loads((folder / "comparison/report.json").read_text())
    assert report["source_preserved"] and not report["cases"] and len(report["blocked"]) == 1
    assert expected in json.dumps(report["blocked"])
    assert not list((folder / "comparison").rglob("command.json"))
    assert not list((folder / "comparison").rglob("process.json"))
    results.append({"control": name, "exit_code": 3, "application_launches": 0, "reason": report["blocked"]})
(destination / "results.json").write_text(json.dumps(results, indent=2) + "\n")
print(json.dumps({"prelaunch_refusals": len(results), "application_launches": 0}))
