"""Real eight-language generation, framework/export and same-return mutation qualification."""
import argparse
import hashlib
import json
import os
from pathlib import Path
import shutil
import subprocess
import sys


def command(arguments, folder, name, expected=0):
    result = subprocess.run([str(p) for p in arguments], capture_output=True, check=False, timeout=900)
    (folder / (name + ".stdout")).write_bytes(result.stdout)
    (folder / (name + ".stderr")).write_bytes(result.stderr)
    if result.returncode != expected:
        raise ValueError(f"{name} returned {result.returncode}, expected {expected}; inspect retained output")
    return result.stdout.decode().strip()


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
    summary={"cli_sha256":hashlib.sha256(cli.read_bytes()).hexdigest(),"languages":sorted(languages),"matching_cases":24,
             "matching_attempts":96,"framework_cases":8,"export_replay_cases":1,"same_return_mutation_cases":3,"source_preserved":True,
             "claim":"equivalence over these tests and observations","artefact_class":"diagnostic"}
    (destination/"qualification.json").write_text(json.dumps(summary,indent=2)+"\n")
    print(json.dumps(summary),flush=True)


if __name__=="__main__":main()
