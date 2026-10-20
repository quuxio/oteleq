"""Real eight-language file-effect differences with unchanged returns and sources."""
import argparse
from collections import defaultdict
import copy
import hashlib
import json
import os
from pathlib import Path
import struct
import sys

from qualify_generation import command

C_SOURCE = '''#include <stdio.h>
#include <stdlib.h>
#include <sys/stat.h>
static void emit(int bad){char input[4096],output[4096];const char* root=getenv("APP_DATA_DIR");snprintf(input,sizeof(input),"%s/seed.bin",root);snprintf(output,sizeof(output),"%s/out.bin",root);unsigned char seed[2];FILE* file=fopen(input,"rb");if(!file||fread(seed,1,2,file)!=2)abort();fclose(file);file=fopen(output,"wb");if(!file)abort();fwrite(seed,1,2,file);fputs(bad?"bad":"good",file);fclose(file);chmod(output,0600);}
int write_match(int value){(void)value;emit(0);return 7;}
int write_difference(int value){emit(value>0 && getenv("OTELC_CONFIG")!=NULL);return 7;}
'''
PYTHON_SOURCE = '''import os,sys
from pathlib import Path
def emit(bad:bool):
 root=Path(os.environ["APP_DATA_DIR"])
 (root/"out.bin").write_bytes((root/"seed.bin").read_bytes()+(b"bad" if bad else b"good"))
 (root/"out.bin").chmod(0o600)
def write_match(value:int)->int:
 emit(False)
 return 7
def write_difference(value:int)->int:
 emit(value>0 and "quux.otelc" in tuple(sys.monitoring.get_tool(index) for index in range(6)))
 return 7
def write_symlink(value:int)->int:
 root=Path(os.environ["APP_DATA_DIR"])
 (root/"link").symlink_to(root/"seed.bin")
 return 7
def write_overflow(value:int)->int:
 Path(os.environ["APP_DATA_DIR"],"out.bin").write_bytes(b"x"*1025)
 return 7
'''
NODE_SOURCE = '''import fs from "node:fs";
function emit(bad){const root=process.env.APP_DATA_DIR;fs.writeFileSync(root+"/out.bin",Buffer.concat([fs.readFileSync(root+"/seed.bin"),Buffer.from(bad?"bad":"good")]),{mode:0o600});}
function write_match(value){emit(false);return 7;}
function write_difference(value){emit(value>0 && process.execArgv.join(" ").includes("/node/register.mjs"));return 7;}
'''
SOURCES = {
    "c": ("c_case.c", C_SOURCE),
    "cpp": ("cpp_case.cpp", C_SOURCE),
    "python": ("py_case.py", PYTHON_SOURCE),
    "javascript": ("js_case.mjs", NODE_SOURCE),
    "typescript": ("ts_case.mts", NODE_SOURCE.replace("(bad)", "(bad:boolean)").replace("(value)", "(value:number)")),
    "rust": ("rs_case.rs", '''use std::os::unix::fs::PermissionsExt;
fn emit(bad:bool){let root=std::path::PathBuf::from(std::env::var("APP_DATA_DIR").unwrap());let mut data=std::fs::read(root.join("seed.bin")).unwrap();data.extend_from_slice(if bad{b"bad"}else{b"good"});let output=root.join("out.bin");std::fs::write(&output,data).unwrap();std::fs::set_permissions(output,std::fs::Permissions::from_mode(0o600)).unwrap();}
fn active()->bool{let bytes=std::fs::read(std::env::current_exe().unwrap()).unwrap();let mut count=0;for part in bytes.windows(15){if part==b"quux_otelc_rust"{count+=1}}count>1}
fn write_match(value:i32)->i32{let _=value;emit(false);7}
fn write_difference(value:i32)->i32{emit(value>0 && active());7}
'''),
    "go": ("go_case.go", '''package main
import("os";"path/filepath";"runtime")
func emit(bad bool){root:=os.Getenv("APP_DATA_DIR");data,err:=os.ReadFile(filepath.Join(root,"seed.bin"));if err!=nil{panic(err)};suffix:="good";if bad{suffix="bad"};if err=os.WriteFile(filepath.Join(root,"out.bin"),append(data,[]byte(suffix)...),0600);err!=nil{panic(err)}}
func write_match(value int) int{emit(false);return 7}
func write_difference(value int) int{emit(value>0 && runtime.NumGoroutine()>1);return 7}
'''),
    "java": ("JvmCase.java", '''class JvmCase {
static void emit(boolean bad) throws Exception{java.nio.file.Path root=java.nio.file.Path.of(java.lang.System.getenv("APP_DATA_DIR"));byte[] seed=java.nio.file.Files.readAllBytes(root.resolve("seed.bin"));byte[] tail=(bad?"bad":"good").getBytes(java.nio.charset.StandardCharsets.UTF_8);byte[] data=java.util.Arrays.copyOf(seed,seed.length+tail.length);java.lang.System.arraycopy(tail,0,data,seed.length,tail.length);java.nio.file.Path output=root.resolve("out.bin");java.nio.file.Files.write(output,data);java.nio.file.Files.setPosixFilePermissions(output,java.nio.file.attribute.PosixFilePermissions.fromString("rw-------"));}
static int write_match(int value) throws Exception{emit(false);return 7;}
static int write_difference(int value) throws Exception{emit(value>0 && java.lang.management.ManagementFactory.getRuntimeMXBean().getInputArguments().toString().contains("-javaagent:"));return 7;}
}
'''),
}


def prepare(cli: Path, provider: Path, folder: Path) -> Path:
    folder.mkdir()
    source = folder / "application"; source.mkdir()
    fixtures = []
    for language, (name, text) in SOURCES.items():
        (source / name).write_text(text)
        functions = ["write_match", "write_difference", *(["write_symlink", "write_overflow"] if language == "python" else [])]
        for function in functions:
            fixtures.append('\n[[fixtures]]\nlanguage=' + json.dumps(language) + '\nsource=' + json.dumps(name)
                            + '\nfunction=' + json.dumps('*' + function + '*') + '\ncases=[[7]]\ndomains=[{kind="integer",minimum=0,maximum=7}]\n')
    config = folder / "equivalence.toml"
    config.write_text('schema_version=1\n[functions]\ninclude=["*write_match*","*write_difference*","*write_symlink*","*write_overflow*"]\n'
                      '[[effects.filesystem]]\nname="data"\nenvironment="APP_DATA_DIR"\npath_mode="relative"\n'
                      'files=[{path="seed.bin",hex="00ff",mode=0o600}]\ndirectories=["empty"]\nmax_bytes=1024\nmax_entries=32\nmax_depth=4\n' + ''.join(fixtures))
    workspace = Path(command([cli, "plan", "--source", source, "--otelc-root", provider, "--workspace-parent", folder, "--config", config], folder, "plan"))
    inventory = json.loads((workspace / "plan.json").read_text())["inventory"]
    assert sum(item["status"] == "ready" for item in inventory) == 18 and not any(item["status"] == "blocked" for item in inventory), inventory
    command([cli, "generate", "--workspace", workspace], folder, "generate")
    return workspace


def expected(case: dict) -> int:
    if any(name in case["function"] for name in ("write_symlink", "write_overflow")):
        return 3
    return int("write_difference" in case["function"] and case["arguments"][0] > 0)


def actual_attempt(folder: Path, case_id: str) -> tuple[Path, Path]:
    """Copied shrink evidence retains its actual, original execution directory."""
    cwd = Path(json.loads((folder / "working-directory.json").read_text()))
    assert cwd.name == "project"
    actual = cwd.parent
    assert actual.name == folder.name and actual.parent.name == case_id
    if actual.resolve() != folder.resolve():
        assert folder.parent.parent.name == "original"
        assert actual.resolve().is_relative_to(folder.parents[3].resolve())
        for name in ("command.json", "working-directory.json", "filesystem-controls.json", "filesystem-data.json", "typed-observation.json", "http-capture.json"):
            assert (actual / name).read_bytes() == (folder / name).read_bytes(), name
    return cwd, actual


def check_report(path: Path, count: int = 18) -> int:
    """Literal input/output/file oracles are independent of agreement between lanes."""
    report = json.loads(path.read_text())
    assert report["source_preserved"] and not report["blocked"] and len(report["cases"]) == count
    inventory = {item["otelc_function"]: item for item in report["inventory"]}
    launches = 0
    for case in report["cases"]:
        assert case["exit_code"] == expected(case), case
        entry = inventory[case["function"]]
        bundle = json.loads((path.parent / case["case"] / "typed-bundle.json").read_text())["cases"][0]
        incomplete = expected(case) == 3
        for lane in ("baseline", "instrumented_on"):
            assert len(bundle[lane]) == 2
            for index, attempt in enumerate(bundle[lane]):
                launches += 1
                execution, observation = attempt["execution"], attempt["observation"]
                value = observation["outcome"]["graph"]["roots"]["result"]
                actual = struct.unpack('>d', bytes.fromhex(value["bits"]))[0] if value["kind"] == "float" else int(value["value"])
                assert actual == 7 and observation["outcome"]["kind"] == "return"
                assert execution["channels"]["stdout"] == execution["channels"]["stderr"] == []
                effect = json.loads(bytes(execution["channels"]["filesystem:data"]))
                before = {bytes.fromhex(item["path_hex"]): item for item in effect["before"]["entries"]}
                assert set(before) == {b"", b"empty", b"seed.bin"}
                assert before[b"seed.bin"] == {"path_hex": b"seed.bin".hex(), "kind": "file", "mode": 0o600, "hex": "00ff"}
                assert effect["before"]["complete"] and not effect["before"]["gaps"]
                assert effect["after"]["complete"] is (not incomplete) and execution["capture_complete"] is (not incomplete)
                if incomplete:
                    assert effect["after"]["gaps"]
                else:
                    after = {bytes.fromhex(item["path_hex"]): item for item in effect["after"]["entries"]}
                    assert set(after) == {b"", b"empty", b"seed.bin", b"out.bin"}
                    bad = lane == "instrumented_on" and expected(case) == 1
                    assert after[b"out.bin"]["hex"] == (b"\0\xff" + (b"bad" if bad else b"good")).hex()
                    assert after[b"out.bin"]["mode"] == 0o600
                    assert after[b"seed.bin"] == before[b"seed.bin"]
                folder = path.parent / case["case"] / (lane + "-" + str(index))
                controls = json.loads((folder / "filesystem-controls.json").read_text())
                binding = controls["environment"]["APP_DATA_DIR"]
                assert not Path(binding).is_absolute()
                cwd, actual = actual_attempt(folder, case["case"])
                assert (cwd / binding).resolve() == (actual / "filesystem-fixtures/data").resolve()
                if lane == "instrumented_on":
                    assert execution["witness"]["functions"] == {entry.get("otelc_runtime_function", case["function"]): 1}
                    assert not any(execution["witness"]["losses"].values())
        if case["exit_code"] == 1:
            compared = case["comparison"]["cases"][0]
            assert {item["path"] for item in compared["execution"]["differences"]} == {"channels.filesystem:data"}
            assert all(not pair["comparison"]["differences"] for pair in compared["pairs"])
    return launches


def framework(workspace: Path, folder: Path, name: str, count: int = 18, *, resume: bool = False) -> int:
    retained = folder / (name + ".stdout")
    text = retained.read_text() if resume and retained.is_file() else command([sys.executable, workspace / "tests/test_equivalence.py"], folder, name, expected=1)
    reports = [json.loads(line) for line in text.splitlines()]
    assert len(reports) == count
    return sum(check_report(Path(row["report"]), 1) for row in reports)


def evidence_controls(cli: Path, folder: Path) -> int:
    report = json.loads((folder / "comparison/report.json").read_text())
    controls = 0
    for case in report["cases"]:
        if "write_match" not in case["function"]:continue
        original = json.loads((folder / "comparison" / case["case"] / "typed-bundle.json").read_text())
        for kind in ("missing", "incomplete"):
            altered = copy.deepcopy(original)
            execution = altered["cases"][0]["instrumented_on"][0]["execution"]
            if kind == "missing":del execution["channels"]["filesystem:data"]
            else:execution["capture_complete"] = False
            name = "control-" + case["case"] + "-" + kind
            path = folder / (name + ".json");path.write_text(json.dumps(altered))
            command([cli, "compare-observations", path], folder, name, expected=3)
            controls += 1
    assert controls == 16
    return controls


def retained_workflows(cli: Path, provider: Path, folder: Path, resume: bool) -> tuple[Path, Path, int, int]:
    """Revalidate completed routes on resume without repeating application launches."""
    if resume:
        plans = list((folder / "cases").glob("*/plan.json"))
        assert len(plans) == 1
        assert Path(json.loads(plans[0].read_text())["otelc_root"]).resolve() == provider
        workspace = plans[0].parent
        command([cli, "export-tests", "--workspace", workspace, "--destination", folder / "resume-identity-check"], folder, "resume-identity-check")
    else:
        folder.mkdir(mode=0o700)
        workspace = prepare(cli, provider, folder / "cases")
        command([cli, "run", "--workspace", workspace, "--report-dir", folder / "comparison"], folder, "run", expected=3)
    launches = check_report(folder / "comparison/report.json")
    controls = evidence_controls(cli, folder)
    launches += framework(workspace, folder, "framework", resume=resume)
    exported = folder / "exported"
    if not resume:
        command([cli, "export-tests", "--workspace", workspace, "--destination", exported, "--apply"], folder, "export")
        command([cli, "run", "--workspace", exported, "--report-dir", folder / "export-comparison"], folder, "export-run", expected=3)
    launches += check_report(folder / "export-comparison/report.json")
    launches += framework(exported, folder, "export-framework", resume=resume)
    return workspace, exported, launches, controls


def reduce_case(cli: Path, workspace: Path, folder: Path, case: dict, resume: bool) -> tuple[int, dict]:
    target = folder / ("shrink-" + case["case"])
    if not (resume and (target / "shrink.json").is_file()):
        command([cli, "shrink", "--workspace", workspace, "--case", case["case"], "--report-dir", target, "--trials", "8"], folder, target.name, expected=1)
    shrink = json.loads((target / "shrink.json").read_text())
    assert shrink["reduced_arguments"] == [1] and shrink["status"] == "candidate_rule_minimal"
    launches = sum(check_report(path, 1) for path in [target / "original/report.json", target / "confirmation/report.json", *[Path(row["report"]) for row in shrink["trials"]]])
    reduced = Path(shrink["workspace"])
    launches += framework(reduced, folder, "reduced-" + case["case"], 1, resume=resume)
    name = "replay-" + case["case"]
    retained = folder / (name + ".stdout")
    text = retained.read_text() if resume and retained.is_file() else command([cli, "replay", "--workspace", reduced, "--case", case["case"]], folder, name, expected=1)
    replay = json.loads(text)
    launches += check_report(Path(replay["report"]), 1)
    print(json.dumps({"completed_reduction": case["function"], "arguments": shrink["reduced_arguments"], "actual_launches": launches}), flush=True)
    return launches, {"function": case["function"], "arguments": shrink["reduced_arguments"]}


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--otelc-root", type=Path, required=True)
    parser.add_argument("--report-dir", type=Path, required=True)
    parser.add_argument("--cli", type=Path, required=True)
    parser.add_argument("--resume", action="store_true", help="revalidate retained completed routes/shrinks and continue; never restart an unfinished shrink")
    args = parser.parse_args()
    cli, provider, folder = args.cli.resolve(strict=True), args.otelc_root.resolve(strict=True), args.report_dir.resolve()
    if any(folder.is_relative_to(path) for path in (provider, Path(__file__).resolve().parents[1])):
        parser.error("qualification directory must be new and outside both repositories")
    os.environ.update(OTELEQ_PYTHON=sys.executable, OTELEQ_CLI=str(cli))
    workspace, exported, launches, controls = retained_workflows(cli, provider, folder, args.resume)
    report = json.loads((folder / "comparison/report.json").read_text())
    reductions = []
    for case in report["cases"]:
        if "write_difference" not in case["function"]:continue
        actual, reduction = reduce_case(cli, workspace, folder, case, args.resume)
        launches += actual
        reductions.append(reduction)
    assert len(reductions) == 8
    identities = defaultdict(list)
    for path in folder.rglob("command.json"):
        if (path.parent / "http-capture.json").is_file():identities[hashlib.sha256(path.read_bytes()).hexdigest()].append(str(path.parent))
    assert len(identities) == launches
    for path in (workspace, exported):
        plan = json.loads((path / "plan.json").read_text())
        assert all(hashlib.sha256((Path(plan["source"]) / name).read_bytes()).hexdigest() == sha for name, sha in plan["source_manifest"].items())
    result = {"claim": "equivalence over these tests and observations", "artefact_class": "diagnostic",
              "cli_sha256": hashlib.sha256(cli.read_bytes()).hexdigest(), "cases": 18, "matching_cases": 8,
              "same_return_filesystem_difference_cases": 8, "incomplete_effect_cases": 2,
              "actual_application_launches": launches, "source_preserved": True,
              "altered_evidence_controls": controls, "reductions": reductions,
              "raw_attempt_folders": sum(map(len, identities.values())), "unique_command_identities": len(identities),
              "scope": "Eight-language seeded filesystem boundary bytes/kinds/permissions, matched relative bindings, generated/exported suites and scalar reduction/replay; no atomic/transient/network/hidden-identity/shipping proof."}
    (folder / "QUALIFICATION.json").write_text(json.dumps(result, indent=2) + "\n")
    print(json.dumps(result), flush=True)


if __name__ == "__main__":
    main()
