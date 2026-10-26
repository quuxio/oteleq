"""Keep all 128 retained launches; complete only shrink/replay/refusal routes."""
import datetime
import hashlib
import json
import os
from pathlib import Path
import sys
import traceback

ROOT = Path(__file__).resolve().parent
sys.path.insert(0, str(ROOT / "reviewed-qualifier"))
import qualify_go_receivers as q

provider = Path("/Users/sclarke/github/otelc-qualification/2026-10-20/integrated-provider/d6d03b7/provider")
cli, work = ROOT / "quux-oteleq", ROOT / "actual/receivers"
workspace = Path((work / "plan.stdout").read_text().strip())
manifest = json.loads((provider.parent / "manifest.json").read_text())
os.environ.update(manifest["environment"])
os.environ.update(OTELEQ_PYTHON=sys.executable, OTELEQ_CLI=str(cli), PYTHONDONTWRITEBYTECODE="1")
record = {"state": "running", "started_at": datetime.datetime.now(datetime.timezone.utc).isoformat(),
          "runtime": json.loads((ROOT / "runtime.json").read_text()),
          "qualifier": json.loads((ROOT / "qualifier-identity.json").read_text())}


def phase(name):
    record["phase"] = name
    (ROOT / "continuation-state.json").write_text(json.dumps(record, indent=2) + "\n")
    print(name, flush=True)


try:
    phase("revalidate-retained-128-launches")
    reports = list(work.rglob("report.json"))
    sizes = [len(json.loads(path.read_text())["cases"]) for path in reports]
    assert sorted(sizes) == [1]*16 + [8]*2
    launches = sum(q.check_report(path, size) for path, size in zip(reports, sizes))
    assert launches == 128
    phase("source-guards-and-shrink")
    plan = json.loads((workspace / "plan.json").read_text())
    corpus = json.loads((workspace / "tests/corpus.json").read_text())
    case = q.selected_case(plan, corpus, "Counter.InstanceDifference")
    controls = q.source_guards(cli, workspace, work, case)
    assert controls == 4
    q.command([cli, "shrink", "--workspace", workspace, "--case", case["id"], "--trials", "1",
               "--report-dir", work / "shrink"], work, "shrink", expected=1)
    shrink = json.loads((work / "shrink/shrink.json").read_text())
    assert shrink["reduced_arguments"] == [0] and shrink["status"] == "candidate_rule_minimal"
    for path in [work / "shrink/original/report.json", work / "shrink/confirmation/report.json",
                 *[Path(item["report"]) for item in shrink["trials"]]]:
        launches += q.check_report(path, 1)
    phase("reduced-replay")
    replay = json.loads(q.command([cli, "replay", "--workspace", shrink["workspace"], "--case", case["id"]], work, "replay", expected=1))
    launches += q.check_report(Path(replay["report"]), 1)
    phase("refusal-controls")
    refused = q.refusals(cli, provider, ROOT / "actual/refusals")
    launches += refused["actual_application_launches"]
    phase("final-accounting")
    for path in (workspace, work / "exported", Path(shrink["workspace"])):
        frozen = json.loads((path / "plan.json").read_text())
        assert all(hashlib.sha256((Path(frozen["source"]) / name).read_bytes()).hexdigest() == value
                   for name, value in frozen["source_manifest"].items())
    commands = [path for path in (ROOT / "actual").rglob("command.json")
                if path.parent.name.startswith(("baseline-", "instrumented_on-"))]
    unique = {hashlib.sha256(path.read_bytes()).hexdigest() for path in commands}
    assert len(unique) == launches == 152
    result = {"claim": "equivalence over these tests and observations", "artefact_class": "diagnostic",
              "runtime": record["runtime"], "qualifier": record["qualifier"], "cases": 8, "matching_cases": 6,
              "same_return_state_differences": 2, "actual_application_launches": launches,
              "prelaunch_source_refusals": controls, "fixture_refusals": refused,
              "retained_attempt_folders": len(commands), "unique_command_identities": len(unique),
              "source_preserved": True, "scalar_shrink": {"original": [3], "reduced": [0]}}
    (ROOT / "QUALIFICATION.json").write_text(json.dumps(result, indent=2) + "\n")
    record.update(state="completed", exit_code=0, result=result)
except BaseException:
    record.update(state="completed", exit_code=1)
    traceback.print_exc()
finally:
    record["completed_at"] = datetime.datetime.now(datetime.timezone.utc).isoformat()
    (ROOT / "continuation-state.json").write_text(json.dumps(record, indent=2) + "\n")
raise SystemExit(record["exit_code"])
