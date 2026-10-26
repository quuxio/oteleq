"""Exact-revision public CLI proof for receiver import-context preservation."""
import hashlib
import json
import os
from pathlib import Path
import sys

ROOT = Path(__file__).resolve().parent
sys.path.insert(0, str(ROOT / "source/tests"))
from qualify_generation import command

SOURCE = '''class Counter:
 def __init__(self,start:int):self.value=start
 def add(self,n:int)->int:
  assert __name__=="pkg.api" and __package__=="pkg"
  self.value+=n
  return self.value
def make_counter(start:int):return Counter(start)
'''


def integer(value):
    return {"kind": "integer", "type": "python.int", "value": str(value), "bits": None, "signed": True}


def graph(state, result=False):
    roots = {"arguments": {"kind": "reference", "node_id": "n0"}, "receiver": {"kind": "reference", "node_id": "n1"}}
    if result:
        roots["result"] = integer(17)
    return {"roots": roots, "nodes": [
        {"id": "n0", "type": "python.builtins.list", "fields": {"item:0": integer(7)}},
        {"id": "n1", "type": "python.pkg.api.Counter", "fields": {
            "order:0": {"kind": "string", "type": "python.string", "encoding": "codepoints32_be",
                        "value": "".join(ord(c).to_bytes(4, "big").hex() for c in "value")},
            "property:value": integer(state)}}]}


def check(path):
    report = json.loads(path.read_text())
    assert report["exit_code"] == 0 and report["source_preserved"] and not report["blocked"] and len(report["cases"]) == 1
    case = report["cases"][0]
    assert case["arguments"] == [7] and case["receiver_fixture"]["arguments"] == [10]
    bundle = json.loads((path.parent / case["case"] / "typed-bundle.json").read_text())["cases"][0]
    identities = set()
    for lane in ("baseline", "instrumented_on"):
        assert len(bundle[lane]) == 2
        for index, attempt in enumerate(bundle[lane]):
            observation = attempt["observation"]
            assert observation["gaps"] == [] and observation["before"] == graph(10)
            assert observation["after"] == graph(17) and observation["outcome"] == {"kind": "return", "graph": graph(17, True)}
            execution = attempt["execution"]
            assert execution["capture_complete"] and execution["termination"] == {"kind": "exit", "code": 0}
            assert execution["channels"] == {"stdout": [], "stderr": []}
            folder = path.parent / case["case"] / (lane + "-" + str(index))
            if lane == "instrumented_on":
                assert execution["witness"]["functions"] == {"src.pkg.api.Counter.add": 1}
                assert json.loads((folder / "http-capture.json").read_text())["bodies"]
            else:
                assert execution["witness"] is None and not json.loads((folder / "http-capture.json").read_text())["bodies"]
            arguments = [json.loads((folder / name).read_text()) for name in ("command.json", "working-directory.json")]
            identities.add(hashlib.sha256(json.dumps(arguments, sort_keys=True).encode()).hexdigest())
    assert len(identities) == 4
    return identities


def framework(workspace, folder, label, valid):
    output = command([sys.executable, workspace / "tests/test_equivalence.py"], folder, label, expected=0 if valid else 1)
    if not valid:
        assert not output
        assert not list((workspace / "runs").rglob("command.json"))
        return set()
    reports = [json.loads(line)["report"] for line in output.splitlines()]
    assert len(reports) == 1
    return check(Path(reports[0]))


def qualify(folder, kind, factory):
    folder.mkdir()
    application = folder / "application"
    api = application / "src/pkg/api.py"
    api.parent.mkdir(parents=True)
    api.write_text(SOURCE)
    if kind != "namespace":
        api.with_name("__init__.py").write_text("")
    roots = [".", "src"] if kind == "ambiguous" else ["first", "src"] if kind == "shadowed" else ["src"]
    if kind == "shadowed":
        other = application / "first/pkg/__init__.py"
        other.parent.mkdir(parents=True)
        other.write_text("")
    before = {p.relative_to(application).as_posix(): p.read_bytes() for p in application.rglob("*") if p.is_file()}
    configuration = folder / "equivalence.toml"
    configuration.write_text('schema_version=1\nlanguages=["python"]\n[adapters.python]\nimport_roots='
        + json.dumps(roots) + '\n[functions]\ninclude=["*.Counter.add"]\n[[fixtures]]\nfunction="*.Counter.add"\ncases=[[7]]\n'
        + 'receiver={factory=' + json.dumps(factory) + ',arguments=[10]}\n'
        + 'expected_baseline={kind="return_value",value={kind="integer",type="python.int",value="17",bits=0,signed=true}}\n')
    # Dynamic Python integers use unbounded widths; the policy codec represents this without bits.
    configuration.write_text(configuration.read_text().replace(',bits=0', ''))
    workspace = Path(command([ROOT / "quux-oteleq", "plan", "--source", application,
        "--otelc-root", PROVIDER, "--workspace-parent", folder, "--config", configuration], folder, "plan"))
    command([ROOT / "quux-oteleq", "generate", "--workspace", workspace], folder, "generate")
    plan = json.loads((workspace / "plan.json").read_text())
    selected = [e for e in plan["inventory"] if e["status"] != "excluded"]
    assert len(selected) == 1
    valid = kind == "regular"
    expected_error = {"namespace": "namespace", "ambiguous": "exactly one", "shadowed": "shadowed"}.get(kind)
    if valid:
        assert selected[0]["status"] == "ready" and selected[0]["python_import"] == {"module": "pkg.api", "roots": ["src"]}
    else:
        assert selected[0]["status"] == "blocked" and expected_error in selected[0]["reason"] and "python_import" not in selected[0]
    comparison = folder / "comparison"
    command([ROOT / "quux-oteleq", "run", "--workspace", workspace, "--report-dir", comparison], folder, "run", expected=0 if valid else 3)
    launches = check(comparison / "report.json") if valid else set()
    if not valid:
        report = json.loads((comparison / "report.json").read_text())
        assert report["source_preserved"] and not report["cases"] and len(report["blocked"]) == 1
        assert not list(comparison.rglob("command.json"))
    else:
        case = json.loads((workspace / "tests/corpus.json").read_text())[0]["id"]
        replay = json.loads(command([ROOT / "quux-oteleq", "replay", "--workspace", workspace, "--case", case], folder, "replay"))
        launches |= check(Path(replay["report"]))
    launches |= framework(workspace, folder, "framework", valid)
    exported = folder / "exported"
    command([ROOT / "quux-oteleq", "export-tests", "--workspace", workspace, "--destination", exported], folder, "export-dry-run")
    assert not exported.exists()
    command([ROOT / "quux-oteleq", "export-tests", "--workspace", workspace, "--destination", exported, "--apply"], folder, "export-apply")
    detached = folder / "detached-application"
    application.rename(detached)
    try:
        launches |= framework(exported, folder, "detached-framework", valid)
    finally:
        detached.rename(application)
    assert before == {p.relative_to(application).as_posix(): p.read_bytes() for p in application.rglob("*") if p.is_file()}
    return {"kind": kind, "factory": factory, "actual_application_launches": len(launches), "source_preserved": True}


PROVIDER = Path('/Users/sclarke/github/otelc-qualification/2026-10-20/integrated-provider/d6d03b7/provider')
if __name__ == "__main__":
    os.environ["OTELEQ_PYTHON"], os.environ["OTELEQ_CLI"] = sys.executable, str(ROOT / "quux-oteleq")
    destination = ROOT / "qualification"
    destination.mkdir()
    results = []
    for kind in ("regular", "namespace", "ambiguous", "shadowed"):
        for factory in ("Counter", "make_counter"):
            result = qualify(destination / (kind + "-" + factory), kind, factory)
            results.append(result)
            print(json.dumps(result), flush=True)
    (destination / "QUALIFICATION.json").write_text(json.dumps({"cases": results,
        "actual_application_launches": sum(x["actual_application_launches"] for x in results)}, indent=2) + "\n")
