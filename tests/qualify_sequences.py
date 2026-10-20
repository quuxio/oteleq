"""Qualify ordered receiver state, collection boundaries, exports and scalar replay."""
import argparse
import copy
import hashlib
import json
import os
from pathlib import Path
import struct
import sys

from qualify_generation import command


CASES = {
    "identity.mjs": ("identity", "Counter", "javascript", 0),
    "async_factory.cjs": ("later", "make", "javascript", 0),
    "transient.mjs": ("transient", "Counter", "javascript", 1),
    "expected_error.mjs": ("fail", "Counter", "javascript", 0),
    "finalized.mjs": ("identity", "Counter", "javascript", 0),
    "retained.mjs": ("identity", "Counter", "javascript", 3),
    "typed_esm.mts": ("identity", "Counter", "typescript", 0),
    "typed_cjs.cts": ("identity", "Counter", "typescript", 0),
}
SOURCE = '''class Counter {
 constructor(start){this.value=start;this.self=this;}
 identity(value){this.value+=value;return this;}
 async later(value){await Promise.resolve();this.value+=value;return this;}
 transient(value){if(value===2)this.value=19;else this.value+=value+Number(process.execArgv.join(' ').includes('/node/register.mjs'));return 7;}
 fail(value){this.value+=value;if(value!==2)throw new TypeError('expected');return 7;}
}
function make(start){return new Counter(start);}
'''


def prepare(cli: Path, provider: Path, folder: Path) -> Path:
    folder.mkdir()
    source = folder / "application"
    source.mkdir()
    include, fixtures = [], []
    for filename, (method, factory, language, _) in CASES.items():
        text = SOURCE
        if language == "typescript":
            text = text.replace("constructor(start)", "constructor(start:number)").replace("make(start)", "make(start:number)")
            text = text.replace("(value)", "(value:number)")
        if filename == "retained.mjs":
            text = text.replace(" constructor(start)", " static held=null;\n constructor(start)").replace("this.value=start;", "Counter.held=this;this.value=start;")
        if filename == "finalized.mjs":
            text = 'import {register} from "./finalizers.mjs";\nlet completed=0;\nfunction mark(){completed++;}\n' + text.replace("this.value=start;", "register(this,mark);this.value=start;")
        (source / filename).write_text(text)
        identity = Path(filename).stem + ".Counter." + method
        include.append(identity)
        first = '{action="call",arguments="case"}'
        if method == "fail":
            first = '{action="call",arguments="case",expected_baseline={kind="error",category="exception",type="ecmascript.TypeError.prototype:TypeError"}}'
        steps = [first, '{action="call",arguments=[2]}', '{action="release"}']
        if language == "javascript":
            steps.append('{action="collect",gc_rounds=' + ("2" if filename == "retained.mjs" else "64") + ',settle_turns=4}')
        text = '\n[[fixtures]]\nsource=' + json.dumps(filename) + '\nfunction=' + json.dumps(identity) + '\ncases=[[7]]\nreceiver={factory=' + json.dumps(factory) + ',arguments=[10]}\nsequence=[' + ','.join(steps) + ']\n'
        if method == "transient":
            text += 'domains=[{kind="integer",minimum=0,maximum=7}]\n'
        fixtures.append(text)
    (source / "finalizers.mjs").write_text('const registry=new FinalizationRegistry(notify=>notify());\nexport function register(value,notify){registry.register(value,notify);}\n')
    config = folder / "equivalence.toml"
    config.write_text('schema_version=1\nlanguages=["javascript","typescript"]\n[functions]\ninclude=' + json.dumps(include) + '\n' + ''.join(fixtures))
    workspace = Path(command([cli, "plan", "--source", source, "--otelc-root", provider,
                              "--workspace-parent", folder, "--config", config], folder, "plan"))
    plan = json.loads((workspace / "plan.json").read_text())
    assert len([entry for entry in plan["inventory"] if entry["status"] == "ready"]) == len(CASES), plan["inventory"]
    assert not any(entry["status"] == "blocked" for entry in plan["inventory"]), plan["inventory"]
    command([cli, "generate", "--workspace", workspace], folder, "generate")
    return workspace


def number(value: dict) -> float:
    assert value["kind"] == "float" and len(value["bits"]) == 16
    return struct.unpack('>d', bytes.fromhex(value["bits"]))[0]


def receiver_value(snapshot: dict) -> float:
    root = snapshot["roots"]["receiver"]
    node = next(node for node in snapshot["nodes"] if node["id"] == root["node_id"])
    return number(node["fields"]["property:value"])


def check_report(path: Path, count: int = 8) -> int:
    report = json.loads(path.read_text())
    assert report["source_preserved"] and not report["blocked"] and len(report["cases"]) == count
    entries = {entry["otelc_function"]: entry for entry in report["inventory"]}
    launches = 0
    for case in report["cases"]:
        entry = entries[case["function"]]
        filename, method, argument = entry["path"], entry["name"].rsplit('.', 1)[-1], case["arguments"][0]
        expected = CASES[filename][3]
        assert case["exit_code"] == expected, case
        typed = json.loads((path.parent / case["case"] / "typed-bundle.json").read_text())["cases"][0]
        for lane in ("baseline", "instrumented_on"):
            assert len(typed[lane]) == 2
            for index, attempt in enumerate(typed[lane]):
                launches += 1
                observed, active = attempt["observation"], lane == "instrumented_on"
                steps = observed["steps"]
                assert len(steps) == (3 if entry["language"] == "typescript" else 4)
                assert receiver_value(observed["before"]) == 10
                first = 10 + argument + int(method == "transient" and active)
                assert receiver_value(steps[0]["after"]) == first
                assert receiver_value(steps[1]["before"]) == first
                assert receiver_value(steps[1]["after"]) == (19 if method == "transient" else 12 + argument)
                assert steps[0]["outcome"]["kind"] == ("error" if method == "fail" else "return")
                assert steps[1]["outcome"]["kind"] == "return"
                assert steps[2]["after"]["roots"]["receiver"] == {"kind": "null"}
                if method in ("identity", "later"):
                    for step in steps[:2]:
                        graph = step["outcome"]["graph"]
                        assert graph["roots"]["result"] == graph["roots"]["receiver"]
                if method == "transient":
                    assert number(observed["outcome"]["graph"]["roots"]["result"]) == 7
                if entry["language"] == "javascript":
                    collected = filename != "retained.mjs"
                    assert steps[3]["outcome"]["graph"]["roots"]["result"]["value"] is collected
                    assert bool(steps[3]["gaps"]) is (not collected)
                if filename == "finalized.mjs":
                    assert number(observed["before"]["roots"]["global:completed"]) == 0
                    assert number(steps[3]["after"]["roots"]["global:completed"]) == 1
                folder = path.parent / case["case"] / (lane + "-" + str(index))
                assert (folder / "stdout").read_bytes() == b"" and (folder / "stderr").read_bytes() == b""
                if active:
                    names = {case["function"]: 2}
                    if filename == "async_factory.cjs":
                        names["async_factory.make"] = 1
                    if entry["language"] == "javascript" and filename != "retained.mjs":
                        names[entry["node_class_label"] + " lifetime"] = 1
                    witness = attempt["execution"]["witness"]
                    assert witness["functions"] == names
                    assert bool(any(witness["losses"].values())) is (filename == "retained.mjs")
    return launches


def evidence_controls(cli: Path, report_path: Path, folder: Path) -> int:
    """Incomplete actions/witnesses and undeclared errors cannot produce a pass."""
    report = json.loads(report_path.read_text())
    cases = {item["function"]: item for item in report["cases"]}
    def bundle(function: str) -> dict:
        case = cases[function]
        return json.loads((report_path.parent / case["case"] / "typed-bundle.json").read_text())
    original = bundle("identity.Counter.identity")
    controls = []
    altered = copy.deepcopy(original)
    for lane in ("baseline", "instrumented_on"):
        for attempt in altered["cases"][0][lane]:
            attempt["observation"]["steps"].pop(0)
    controls.append(("missing-action", altered, 3))
    altered = copy.deepcopy(original)
    steps = altered["cases"][0]["instrumented_on"][0]["observation"]["steps"]
    steps[0], steps[1] = steps[1], steps[0]
    controls.append(("reordered-action", altered, 3))
    altered = copy.deepcopy(original)
    altered["cases"][0]["instrumented_on"][0]["observation"]["steps"][0]["gaps"] = [{"phase":"after", "path":"/receiver", "reason":"deliberate missing state"}]
    controls.append(("action-gap", altered, 3))
    altered = copy.deepcopy(original)
    altered["cases"][0]["instrumented_on"][0]["execution"]["witness"]["losses"]["deliberate"] = 1
    controls.append(("positive-witness-loss", altered, 3))
    altered = copy.deepcopy(original)
    del altered["cases"][0]["instrumented_on"][0]["execution"]["witness"]["functions"]["identity.Counter lifetime"]
    controls.append(("missing-lifetime-witness", altered, 3))
    altered = bundle("expected_error.Counter.fail")
    altered["cases"][0]["contract"]["steps"][0]["expected_baseline"] = {"kind":"return"}
    controls.append(("undeclared-intermediate-error", altered, 2))
    for name, data, expected in controls:
        path = folder / (name + ".json")
        path.write_text(json.dumps(data))
        command([cli, "compare-observations", path], folder, name, expected=expected)
    return len(controls)


def source_control(cli: Path, workspace: Path, folder: Path, case: dict) -> None:
    """A changed application source refuses before creating any new attempt."""
    plan = json.loads((workspace / "plan.json").read_text())
    path = Path(plan["source"]) / "identity.mjs"
    original = path.read_bytes()
    runs = set((workspace / "runs").iterdir())
    try:
        path.write_bytes(original + b"\n// deliberate input alteration\n")
        command([cli, "replay", "--workspace", workspace, "--case", case["case"]], folder, "changed-source", expected=4)
        assert "source or immutable snapshot changed" in (folder / "changed-source.stderr").read_text()
        assert set((workspace / "runs").iterdir()) == runs
    finally:
        path.write_bytes(original)


def framework(workspace: Path, folder: Path, name: str, count: int = 8) -> int:
    summaries = command([sys.executable, workspace / "tests/test_equivalence.py"], folder, name, expected=1)
    reports = [json.loads(line) for line in summaries.splitlines()]
    assert len(reports) == count
    return sum(check_report(Path(row["report"]), 1) for row in reports)


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--otelc-root", type=Path, required=True)
    parser.add_argument("--report-dir", type=Path, required=True)
    parser.add_argument("--cli", type=Path, required=True)
    args = parser.parse_args()
    cli, provider, folder = args.cli.resolve(strict=True), args.otelc_root.resolve(strict=True), args.report_dir.resolve()
    if folder.is_relative_to(provider) or folder.is_relative_to(Path(__file__).resolve().parents[1]):
        parser.error("qualification directory must be new and outside both repositories")
    folder.mkdir(mode=0o700)
    os.environ.update(OTELEQ_PYTHON=sys.executable, OTELEQ_CLI=str(cli))
    workspace = prepare(cli, provider, folder / "cases")
    command([cli, "run", "--workspace", workspace, "--report-dir", folder / "comparison"], folder, "run", expected=3)
    launches = check_report(folder / "comparison/report.json")
    controls = evidence_controls(cli, folder / "comparison/report.json", folder)
    report = json.loads((folder / "comparison/report.json").read_text())
    source_control(cli, workspace, folder, next(case for case in report["cases"] if case["function"] == "identity.Counter.identity"))
    launches += framework(workspace, folder, "framework")
    exported = folder / "exported"
    command([cli, "export-tests", "--workspace", workspace, "--destination", exported, "--apply"], folder, "export")
    command([cli, "run", "--workspace", exported, "--report-dir", folder / "export-comparison"], folder, "export-run", expected=3)
    launches += check_report(folder / "export-comparison/report.json")
    launches += framework(exported, folder, "export-framework")
    report = json.loads((folder / "comparison/report.json").read_text())
    target = next(case for case in report["cases"] if case["function"] == "transient.Counter.transient")
    command([cli, "shrink", "--workspace", workspace, "--case", target["case"], "--report-dir", folder / "shrink", "--trials", "1"], folder, "shrink", expected=1)
    shrink = json.loads((folder / "shrink/shrink.json").read_text())
    assert shrink["reduced_arguments"] == [0] and shrink["status"] == "candidate_rule_minimal"
    for path in [folder / "shrink/original/report.json", folder / "shrink/confirmation/report.json", *[Path(row["report"]) for row in shrink["trials"]]]:
        launches += check_report(path, 1)
    reduced = Path(shrink["workspace"])
    launches += framework(reduced, folder, "reduced-framework", 1)
    replay = json.loads(command([cli, "replay", "--workspace", reduced, "--case", target["case"]], folder, "replay", expected=1))
    launches += check_report(Path(replay["report"]), 1)
    assert launches == 148
    for path in (workspace, exported, reduced):
        plan = json.loads((path / "plan.json").read_text())
        assert all(hashlib.sha256((Path(plan["source"]) / name).read_bytes()).hexdigest() == sha for name, sha in plan["source_manifest"].items())
    result = {"claim": "equivalence over these tests and observations", "artefact_class": "diagnostic",
              "cli_sha256": hashlib.sha256(cli.read_bytes()).hexdigest(), "cases": 8, "matching_cases": 6,
              "transient_difference_controls": 1, "retained_collection_inconclusive_controls": 1,
              "actual_application_launches": launches, "source_preserved": True,
              "evidence_refusal_controls": controls, "prelaunch_source_refusals": 1,
              "scope": "Ordered ordinary Node receiver calls/release, JavaScript ESM/CommonJS collection, source factories, async methods and application finalizers; TypeScript call/release only; no GC timing/leak/shipping claim."}
    (folder / "QUALIFICATION.json").write_text(json.dumps(result, indent=2) + "\n")
    print(json.dumps(result), flush=True)


if __name__ == "__main__":main()
