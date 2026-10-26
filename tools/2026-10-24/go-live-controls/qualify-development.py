"""Exercise all four Go startup states through the frozen public CLI."""

from datetime import datetime, timezone
import hashlib
import json
import os
from pathlib import Path
import subprocess
import time

ROOT = Path(__file__).resolve().parent
INDEX = json.loads((ROOT / "development-01.json").read_text())
SOURCE = Path(INDEX["source"])
SDK = ROOT.parent / "go-reuse-review-d2ec6bf/source"
SDK_INDEX = json.loads((SDK.parent / "inputs-before.json").read_text())
CLI = ROOT / "target-development-01/debug/quux-oteleq"
PYTHON = ROOT.parent / "python-live-metrics/env-312/bin/python"
GO = Path("/Users/sclarke/go/pkg/mod/golang.org/toolchain@v0.0.1-go1.27.3.darwin-arm64/bin/go")
DESTINATION = ROOT / "public-development-01"
DESTINATION.mkdir()
APPLICATION = DESTINATION / "application"
(APPLICATION / "counter").mkdir(parents=True)
(APPLICATION / "go.mod").write_text("module example.test/live\n\ngo 1.26.0\n")
STATES = [{"collection": c, "emission": e} for c, e in ((True, True), (False, True), (True, False), (False, False))]
METHODS = ("BothOn", "CollectionOff", "EmissionOff", "BothOff")
text = """package counter
type Counter struct {value int;calls int;self *Counter}
var shared *Counter
var total int
func New(seed int)*Counter{value:=&Counter{value:seed};value.self=value;shared=value;return value}
"""
for method in METHODS:
    text += "func(value *Counter) " + method + "(amount int)int{value.calls++;value.value+=amount;total+=amount;if amount<0{panic(\"known\")};return value.value}\n"
(APPLICATION / "counter/api.go").write_text(text)
POLICY = DESTINATION / "policy.toml"
text = """schema_version=1
languages=["go"]
[adapters.go]
backend="source-v1"
module_roots=["."]
build_timeout_ms=900000
[limits]
baseline_repeats=2
instrumented_repeats=2
case_timeout_ms=120000
[functions]
include=["*.Counter.BothOn","*.Counter.CollectionOff","*.Counter.EmissionOff","*.Counter.BothOff"]
"""
for method, initial in zip(METHODS, STATES):
    text += '\n[[fixtures]]\nfunction="*.Counter.' + method + '"\ncases=[[3]]\nreceiver={factory="New",arguments=[10]}\nsequence=['
    schedule = [initial, STATES[0], STATES[1], STATES[3], STATES[2]]
    for index, flags in enumerate(schedule):
        if index:
            text += ","
        arguments = '"case"' if index == 0 else "[" + str((2, 4, 1, -2)[index - 1]) + "]"
        text += '{action="call",arguments=' + arguments + ',metrics={collection=' + str(flags["collection"]).lower() + ',emission=' + str(flags["emission"]).lower() + "}"
        if index == 4:
            text += ',expected_baseline={kind="error",category="panic",type="go.string"}'
        text += "}"
    text += "]\n"
POLICY.write_text(text)
ENVIRONMENT = {key: value for key, value in os.environ.items() if not key.startswith(("OTEL", "OTELEQ", "GH_", "GITHUB_", "AWS_", "SONAR_"))}
ENVIRONMENT.update(OTELEQ_PYTHON=str(PYTHON), OTELC_PYTHON=str(PYTHON), OTELC_GO=str(GO),
                   OTELEQ_CLI=str(CLI), PYTHONDONTWRITEBYTECODE="1", PATH=str(GO.parent) + os.pathsep + ENVIRONMENT["PATH"])


def write(path, value):
    path.write_text(json.dumps(value, indent=2) + "\n")


def facts(path):
    value = path.stat()
    return {"sha256": hashlib.sha256(path.read_bytes()).hexdigest(), "facts": [value.st_dev, value.st_ino, value.st_mode,
            value.st_uid, value.st_gid, value.st_size, value.st_mtime_ns, value.st_ctime_ns]}


def inputs():
    tools = json.loads((SDK / "build/go-upstream/toolchain.json").read_text())
    return {"consumer": {name: facts(SOURCE / name) for name in INDEX["files"]},
            "sdk": {name: facts(SDK / name) for name in SDK_INDEX["files"]},
            "application": {name: facts(APPLICATION / name) for name in ("go.mod", "counter/api.go")},
            "tools": {str(path): facts(path) for path in [SDK / "build/go-upstream/toolchain.json", *[Path(tools[name]) for name in ("go", "weaver", "bundle")]]},
            "cli": facts(CLI)}


def execute(name, arguments):
    command = list(map(str, [CLI, *arguments]))
    write(DESTINATION / (name + "-command.json"), command)
    state["phase"] = name
    write(DESTINATION / "status.json", state)
    started = time.monotonic()
    with (DESTINATION / (name + ".stdout")).open("xb") as stdout, (DESTINATION / (name + ".stderr")).open("xb") as stderr:
        result = subprocess.run(command, cwd=SOURCE, env=ENVIRONMENT, stdout=stdout, stderr=stderr, timeout=1800)
    state["commands"].append({"phase": name, "exit_code": result.returncode, "seconds": round(time.monotonic() - started, 3)})
    write(DESTINATION / "status.json", state)
    assert result.returncode == 0, state["commands"][-1]
    return (DESTINATION / (name + ".stdout")).read_text().strip()


def audit(report):
    data = json.loads(report.read_text())
    assert data["source_preserved"] and not data["blocked"] and len(data["cases"]) == 4
    applications, sdk = set(), 0
    for case in data["cases"]:
        method = case["function"].rsplit(".", 1)[-1]
        index = METHODS.index(method)
        assert case["exit_code"] == 0
        bundle = json.loads((report.parent / case["case"] / "typed-bundle.json").read_text())["cases"][0]
        expected_metrics = {"example.test/live/counter.Counter." + method: 2 + int(STATES[index]["collection"]),
                            "example.test/live/counter.New": int(STATES[index]["collection"])}
        for lane in ("baseline", "instrumented_on"):
            assert len(bundle[lane]) == 2
            for repeat, attempt in enumerate(bundle[lane]):
                folder = report.parent / case["case"] / (lane + "-" + str(repeat))
                observed = attempt["observation"]
                assert len(observed["steps"]) == 5 and not observed["gaps"]
                for step_index, step in enumerate(observed["steps"]):
                    assert step["id"] == "step-" + str(step_index) and not step["gaps"]
                    assert step["outcome"]["kind"] == ("error" if step_index == 4 else "return")
                start = json.loads((folder / "go-runtime/oteleq-go-start.json").read_text())
                owner = start["owner"]
                controls = json.loads((folder / "go-controls.json").read_text())
                assert controls["pid"] == owner["application_pid"] and controls["supervisor_pid"] == owner["pid"]
                assert controls["steps"][0]["requested"] == STATES[index]
                assert len(controls["steps"]) == 5
                assert len(list((folder / "go-worker-control").iterdir())) == 48
                application = json.loads((folder / "go-runtime/go-application-start.json").read_text())
                assert application["launch_id"] not in applications
                applications.add(application["launch_id"])
                if lane == "baseline":
                    assert attempt["execution"]["witness"] is None and controls["sdk_pid"] is None
                    continue
                sdk += 1
                receipt = json.loads((folder / "go-verified-telemetry.json").read_text())
                assert receipt["sdk_pid"] == owner["application_pid"] and receipt["spans"] == 6
                assert receipt["functions"] == {"example.test/live/counter.Counter." + method: 5, "example.test/live/counter.New": 1}
                assert receipt["controls"]["metric_functions"] == expected_metrics
                assert not any(receipt["losses"].values()) and receipt["pending"] == 0
                assert receipt["health"]["metric_exported_points"] is None
                for step in controls["steps"]:
                    if not all(step["requested"].values()):
                        assert step["after"]["held_ns"] >= 1_000_000_000 and not step["after"]["metric_bodies"]
                assert controls["restored"]["health"]["controls"]["collection"]
                assert controls["restored"]["health"]["controls"]["emission"]
    assert len(applications) == 16 and sdk == 8
    return {"actual_applications": 16, "actual_sdk_processes": 8, "initial_states": 4,
            "call_observations": 80, "complete_traces": 48, "scope": "development direct workflow only"}


before = inputs()
assert all(before["consumer"][name]["sha256"] == digest for name, digest in INDEX["files"].items())
write(DESTINATION / "inputs-before.json", before)
state = {"status": "running", "commands": [], "started": datetime.now(timezone.utc).isoformat(),
         "base_head": INDEX["base_head"], "dirty_development_snapshot": True, "sdk_head": SDK_INDEX["head"]}
try:
    workspace = Path(execute("plan", ["plan", "--source", APPLICATION, "--otelc-root", SDK, "--config", POLICY, "--workspace-parent", DESTINATION]))
    state["workspace"] = str(workspace)
    plan = json.loads((workspace / "plan.json").read_text())
    assert len([entry for entry in plan["inventory"] if entry["status"] == "ready"]) == 4
    assert not any(entry["status"] == "blocked" for entry in plan["inventory"])
    execute("generate", ["generate", "--workspace", workspace])
    execute("run", ["run", "--workspace", workspace, "--report-dir", DESTINATION / "comparison"])
    state["audit"] = audit(DESTINATION / "comparison/report.json")
    state["status"] = "passed"
except Exception as error:
    state.update(status="failed", error=repr(error))
finally:
    after = inputs()
    write(DESTINATION / "inputs-after.json", after)
    state["preservation"] = {name: before[name] == after[name] for name in before}
    if not all(state["preservation"].values()):
        state["status"] = "failed"
    state["finished"] = datetime.now(timezone.utc).isoformat()
    write(DESTINATION / "status.json", state)
    print(json.dumps(state, indent=2), flush=True)
    raise SystemExit(0 if state["status"] == "passed" else 1)
