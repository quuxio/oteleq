"""Real eight-language generation, framework/export and same-return mutation qualification."""
import argparse
import hashlib
import json
import os
from pathlib import Path
import shutil
import subprocess
import sys


def command(arguments, folder, name, expected=0, timeout=900):
    result = subprocess.run([str(p) for p in arguments], capture_output=True, check=False, timeout=timeout)
    (folder / (name + ".stdout")).write_bytes(result.stdout)
    (folder / (name + ".stderr")).write_bytes(result.stderr)
    if result.returncode != expected:
        raise ValueError(f"{name} returned {result.returncode}, expected {expected}; inspect retained output")
    return result.stdout.decode().strip()


def qualify_passive_observers(cli, root, destination):
    """Unsupported callbacks must fail capture before any equivalence verdict."""
    source = destination / "callback-application"
    source.mkdir()
    (source / "App.java").write_text('''class App {
static class E extends RuntimeException {
 public String getMessage(){System.out.println("CALLBACK");return "masked";}
}
static int selected(){throw new E();}
}
''')
    (source / "app.go").write_text('''package main
import "fmt"
type int struct{}
func (int) GoString() string {fmt.Println("CALLBACK");return "masked"}
func selected() int{return int{}}
''')
    (source / "app.rs").write_text('''#[allow(non_camel_case_types)]
struct i32;
impl std::fmt::Debug for i32 {
 fn fmt(&self,f:&mut std::fmt::Formatter)->std::fmt::Result {
  println!("CALLBACK");write!(f,"masked")
 }
}
fn selected()->i32{i32}
''')
    policy = destination / "callback-policy.toml"
    policy.write_text('schema_version=1\nlanguages=["java","go","rust"]\n[functions]\ninclude=["*selected*"]\n')
    workspace = Path(command([cli, "plan", "--source", source, "--otelc-root", root,
                              "--workspace-parent", destination, "--config", policy], destination, "callback-plan"))
    command([cli, "generate", "--workspace", workspace], destination, "callback-generate")
    captures = destination / "callback-comparison"
    command([cli, "run", "--workspace", workspace, "--report-dir", captures], destination, "callback-run", expected=4)
    report = json.loads((captures / "report.json").read_text())
    assert report["source_preserved"] and len(report["cases"]) == 3
    assert all(case["exit_code"] == 4 for case in report["cases"])
    assert all(b"CALLBACK" not in path.read_bytes() for path in captures.rglob("stdout"))


def fixture_control(cli, root, destination, name, source_text, expected_exit, expected_error=False):
    """Run one witnessed Python fixture contract with a separately declared outcome."""
    source = destination / (name + "-application")
    source.mkdir()
    (source / "case.py").write_text(source_text)
    policy = destination / (name + "-policy.toml")
    text = '''schema_version=1
languages=["python"]
[functions]
include=["*selected"]
[[fixtures]]
function="*selected"
cases=[[]]
'''
    if expected_error:
        text += 'expected_baseline={kind="error",category="exception",type="python.builtins.ValueError"}\n'
    policy.write_text(text)
    workspace = Path(command([cli, "plan", "--source", source, "--otelc-root", root,
                              "--workspace-parent", destination, "--config", policy], destination, name + "-plan"))
    command([cli, "generate", "--workspace", workspace], destination, name + "-generate")
    captures = destination / (name + "-comparison")
    command([cli, "run", "--workspace", workspace, "--report-dir", captures], destination, name + "-run", expected=expected_exit)
    report = json.loads((captures / "report.json").read_text())
    assert report["source_preserved"] and len(report["cases"]) == 1
    result = report["cases"][0]
    assert result["exit_code"] == expected_exit and result["comparison"]["typed_schema_version"] == 1
    return result["comparison"]["cases"][0]


def qualify_fixture_contracts(cli, root, destination):
    """Matching invalid errors and unequal initial state cannot qualify."""
    source = 'def selected()->int:\n raise ValueError("expected")\n'
    blocked = fixture_control(cli, root, destination, "unexpected-error", source, 2)
    assert blocked["verdict"] == "blocked" and blocked["reasons"]
    accepted = fixture_control(cli, root, destination, "expected-error", source, 0, expected_error=True)
    assert accepted["verdict"] == "equivalent_observed"
    source = '''import sys
state=int(any(sys.monitoring.get_tool(index)=="quux.otelc" for index in range(6)))
def selected()->int:
 return 7
'''
    blocked = fixture_control(cli, root, destination, "initial-state", source, 2)
    assert blocked["verdict"] == "blocked"
    assert any(pair["comparison"]["initial_differences"] for pair in blocked["pairs"])


def qualify_node_helper_scope(cli, root, destination):
    """Normal application lexical bindings cannot replace private observer APIs."""
    source = destination / "node-helper-application"
    source.mkdir()
    for extension in ("mjs", "mts"):
        annotation = ":number" if extension == "mts" else ""
        (source / ("scope." + extension)).write_text(
            "class Map {constructor(){console.log('CALLBACK')}}\n"
            "class JSON {static stringify(){console.log('CALLBACK')}}\n"
            + f"function selected(value{annotation}){{return {{value}};}}\n")
    policy = destination / "node-helper-policy.toml"
    policy.write_text('schema_version=1\nlanguages=["javascript","typescript"]\n[functions]\ninclude=["*selected"]\n[[fixtures]]\nfunction="*selected"\ncases=[[7]]\n')
    workspace = Path(command([cli, "plan", "--source", source, "--otelc-root", root,
                              "--workspace-parent", destination, "--config", policy], destination, "node-helper-plan"))
    command([cli, "generate", "--workspace", workspace], destination, "node-helper-generate")
    captures = destination / "node-helper-comparison"
    command([cli, "run", "--workspace", workspace, "--report-dir", captures], destination, "node-helper-run")
    report = json.loads((captures / "report.json").read_text())
    assert report["source_preserved"] and len(report["cases"]) == 2
    assert all(case["exit_code"] == 0 for case in report["cases"])
    assert all(b"CALLBACK" not in path.read_bytes() for path in captures.rglob("stdout"))


def main():
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--otelc-root",type=Path,required=True)
    parser.add_argument("--report-dir",type=Path,required=True)
    parser.add_argument("--cli",type=Path,default=Path(__file__).resolve().parents[1]/"target/debug/quux-oteleq")
    args=parser.parse_args()
    cli=args.cli.resolve(strict=True)
    root=args.otelc_root.resolve(strict=True)
    destination=args.report_dir.resolve()
    repo=Path(__file__).resolve().parents[1]
    if destination.is_relative_to(root) or destination.is_relative_to(repo):
        parser.error("report directory must be new and outside both repositories")
    destination.mkdir(mode=0o700,exist_ok=False)
    os.environ["OTELEQ_PYTHON"]=sys.executable
    source=destination/"application"
    shutil.copytree(Path(__file__).with_name("generation-fixtures"),source)
    workspace=Path(command([cli,"plan","--source",source,"--otelc-root",root,"--workspace-parent",destination],destination,"plan"))
    command([cli,"generate","--workspace",workspace],destination,"generate")
    command([cli,"run","--workspace",workspace,"--report-dir",destination/"comparisons"],destination,"run")
    report=json.loads((destination/"comparisons/report.json").read_text())
    languages={entry["language"] for entry in report["inventory"] if entry["status"]=="ready"}
    if len(languages)!=8 or len(report["cases"])!=24 or any(case["exit_code"] for case in report["cases"]):
        raise ValueError("qualification did not complete all 24 cases/eight languages")
    data=json.loads((workspace/"plan.json").read_text())
    cases=json.loads((workspace/"tests/corpus.json").read_text())
    selected=["GeneratedEquivalence.test_"+next(case["id"] for case in cases if case["function_id"]==entry["id"]).replace("-","_") for entry in data["inventory"] if entry["status"]=="ready"]
    command([sys.executable,workspace/"tests/test_equivalence.py",*selected],destination,"framework")
    exported=destination/"exported"
    command([cli,"export-tests","--workspace",workspace,"--destination",exported,"--apply"],destination,"export")
    python_entry=next(entry for entry in data["inventory"] if entry["language"]=="python" and entry["status"]=="ready")
    python_case=next(case for case in cases if case["function_id"]==python_entry["id"])
    command([cli,"replay","--workspace",exported,"--case",python_case["id"]],destination,"export-replay")
    negative=destination/"mutation-application";negative.mkdir()
    (negative/"mutation.py").write_text('''import sys
class Cell:
    def __init__(self):self.value=0
state={"cell":Cell()}
alias=state["cell"]
def same_result(x:int)->int:
    for tool in range(6):
        if sys.monitoring.get_tool(tool)=="quux.otelc":state["cell"].value+=1
    return x+1
''')
    negative_workspace=Path(command([cli,"plan","--source",negative,"--otelc-root",root,"--workspace-parent",destination,"--exclude","*.Cell.__init__"],destination,"mutation-plan"))
    command([cli,"generate","--workspace",negative_workspace],destination,"mutation-generate")
    command([cli,"run","--workspace",negative_workspace,"--report-dir",destination/"mutation-comparison"],destination,"mutation-run",expected=1)
    mutation=json.loads((destination/"mutation-comparison/report.json").read_text())
    for case in mutation["cases"]:
        if case["exit_code"]!=1:raise ValueError("same-return mutation was not detected")
        bundle=json.loads((destination/"mutation-comparison"/case["case"]/"bundle.json").read_text())
        attempts=bundle["cases"][0]
        plain=json.loads(bytes(attempts["baseline"][0]["channels"]["state-and-outcome"]))
        on=json.loads(bytes(attempts["instrumented_on"][0]["channels"]["state-and-outcome"]))
        if plain["outcome"]["value"]["roots"]["result"]!=on["outcome"]["value"]["roots"]["result"] or plain["before"]!=on["before"] or plain["after"]==on["after"]:
            raise ValueError("mutation control did not retain identical return/initial state and differing final state")
    rebound=destination/"rebound-application";rebound.mkdir()
    (rebound/"bindings.py").write_text('''counter=0
def selected(value:int)->int:
    global counter
    counter+=value+1
    return counter
selected(0)
def replacement(value:int)->int:
    return counter
globals().update(selected=replacement)
''')
    for extension in ("mjs", "mts"):
        annotation = ":number" if extension == "mts" else ""
        (rebound/("bindings."+extension)).write_text(
            "#!/usr/bin/env node\n'use strict';\n// Unicode prologue: \U0001f600\nlet counter=0;\n"
            + f"function selected(value{annotation}){annotation}{{counter+=value+1;return counter;}}\n"
            + f"selected(0);\nselected=(value{annotation}){annotation}=>counter;\n")
    binding_policy=destination/"binding-policy.toml"
    binding_policy.write_text('''schema_version=1
languages=["python","javascript","typescript"]
[functions]
include=["*.selected"]
[[fixtures]]
function="*.selected"
cases=[[7]]
''')
    binding_workspace=Path(command([cli,"plan","--source",rebound,"--otelc-root",root,
                                    "--workspace-parent",destination,"--config",binding_policy],destination,"binding-plan"))
    command([cli,"generate","--workspace",binding_workspace],destination,"binding-generate")
    command([cli,"run","--workspace",binding_workspace,"--report-dir",destination/"binding-comparison"],destination,"binding-run",expected=4)
    binding=json.loads((destination/"binding-comparison/report.json").read_text())
    assert binding["source_preserved"] and len(binding["cases"])==3
    assert all(case["exit_code"]==4 for case in binding["cases"])
    assert any(b"selected function binding differs" in path.read_bytes()
               for path in (destination/"binding-comparison").rglob("stderr"))
    qualify_passive_observers(cli, root, destination)
    qualify_fixture_contracts(cli, root, destination)
    qualify_node_helper_scope(cli, root, destination)
    summary={"cli_sha256":hashlib.sha256(cli.read_bytes()).hexdigest(),"languages":sorted(languages),"matching_cases":24,
             "matching_attempts":96,"framework_cases":8,"export_replay_cases":1,"same_return_mutation_cases":3,"source_preserved":True,
             "rebound_callable_with_startup_witness_rejected":True,
             "static_observer_callback_controls_refused":3,
             "typed_fixture_contract_controls":3,"node_helper_lexical_shadow_cases":2,
             "claim":"equivalence over these tests and observations","artefact_class":"diagnostic"}
    (destination/"qualification.json").write_text(json.dumps(summary,indent=2)+"\n")
    print(json.dumps(summary),flush=True)


if __name__=="__main__":main()
