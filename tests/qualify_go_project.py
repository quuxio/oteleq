"""Qualify real Go packages, nested modules, build tags and retained generated suites."""
import argparse
import hashlib
import json
import os
from pathlib import Path
import sys

from qualify_generation import command


def fixture(folder: Path) -> tuple[Path, Path]:
    """All expected outcomes are specified here independently of captured lanes."""
    source = folder / "application"
    files = {
        "go.mod": "module example.test/root\n\ngo 1.27.2\n",
        "types/types.go": "package types\ntype Count int64\n",
        "internal/counter/api.go": '''package counter
import alias "example.test/root/types"
func selected(value alias.Count)alias.Count{state+=twice(value);return state}
func state_difference(value alias.Count)int{state=value;if active(){state++};return 7}
func fail(value alias.Count)int{state=value;panic("known")}
func echo_float(value float64)float64{state=1;return value}
''',
        "internal/counter/state.go": '''package counter
import ("bytes";"fmt";"os";"runtime/debug";"example.test/root/types")
var state=types.Count(5)
func twice(value types.Count)types.Count{return value*2}
func init(){value,err:=os.ReadFile("go.mod");if err!=nil||!bytes.Contains(value,[]byte("module example.test/root")){panic("wrong module cwd")};fmt.Print("INIT\\xff\\n");fmt.Fprint(os.Stderr,"ERR\\x00\\n")}
func active()bool{info,ok:=debug.ReadBuildInfo();if !ok{return false};for _,dep:=range info.Deps{if dep.Path=="io.quux.otelc/go"{return true}};return false}
''',
        "tagged/api.go": "//go:build oteleq_selected\n\npackage tagged\nvar enabled=false\nfunc selected(value bool)bool{enabled=value;return enabled}\n",
        "tagged/default.go": "//go:build !oteleq_selected\n\npackage tagged\nfunc default_target()int{return 0}\n",
        "services/api/go.mod": "module example.test/service\n\ngo 1.27.2\nrequire example.test/root v0.0.0\nreplace example.test/root => ../..\n",
        "services/api/cmd/api.go": 'package main\nimport named "example.test/root/types"\nfunc selected(value named.Count)named.Count{state+=value;main();return state}\n',
        "services/api/cmd/state.go": '''package main
import ("bytes";"fmt";"os";"example.test/root/types")
var state=types.Count(3)
func init(){value,err:=os.ReadFile("go.mod");if err!=nil||!bytes.Contains(value,[]byte("module example.test/service")){panic("wrong module cwd")};fmt.Print("INIT\\xff\\n");fmt.Fprint(os.Stderr,"ERR\\x00\\n")}
func main(){state++}
''',
    }
    for name, text in files.items():
        path = source / name
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(text)
    policy = folder / "equivalence.toml"
    text = '''schema_version=1
languages=["go"]
[adapters.go]
module_roots=[".","services/api"]
build_tags=["oteleq_selected"]
[functions]
include=["*.selected","*.echo_float","*.state_difference","*.fail"]
'''
    for name, value in (("*.selected", "7"), ("*.echo_float", "-0.0"),
                        ("*.state_difference", "7"), ("*.fail", "7")):
        # The tag-selected bool target has a separate source-scoped fixture.
        if name == "*.selected":
            for path in ("internal/counter/api.go", "services/api/cmd/api.go"):
                text += '\n[[fixtures]]\nsource=' + json.dumps(path) + '\nfunction="*.selected"\ncases=[[7]]\n'
            continue
        text += '\n[[fixtures]]\nfunction=' + json.dumps(name) + '\ncases=[[' + value + ']]\n'
        if name == "*.state_difference":
            text += 'domains=[{kind="integer",minimum=0,maximum=7}]\n'
        if name == "*.fail":
            text += 'expected_baseline={kind="error",category="panic",type="go.string"}\n'
    text += '\n[[fixtures]]\nsource="tagged/api.go"\nfunction="*.selected"\ncases=[[true]]\n'
    policy.write_text(text)
    return source, policy


def prepare(cli: Path, provider: Path, folder: Path) -> Path:
    folder.mkdir()
    source, policy = fixture(folder)
    workspace = Path(command([cli, "plan", "--source", source, "--otelc-root", provider,
                              "--workspace-parent", folder, "--config", policy], folder, "plan"))
    plan = json.loads((workspace / "plan.json").read_text())
    assert len([entry for entry in plan["inventory"] if entry["status"] == "ready"]) == 6, plan["inventory"]
    assert not any(entry["status"] == "blocked" for entry in plan["inventory"]), plan["inventory"]
    command([cli, "generate", "--workspace", workspace], folder, "generate")
    return workspace


def check_report(path: Path, expected_cases: int = 6) -> int:
    """Check literal state/result/channel oracles and actual module-relative witnesses."""
    report = json.loads(path.read_text())
    assert report["source_preserved"] and not report["blocked"] and len(report["cases"]) == expected_cases
    entries = {entry["otelc_function"]: entry for entry in report["inventory"]}
    launches = 0
    for case in report["cases"]:
        entry = entries[case["function"]]
        name = entry["name"]
        difference = name == "state_difference"
        assert case["exit_code"] == int(difference), case
        bundle = json.loads((path.parent / case["case"] / "typed-bundle.json").read_text())["cases"][0]
        tagged = entry["path"] == "tagged/api.go"
        nested = entry["path"].startswith("services/")
        root = "global:enabled" if tagged else "global:state"
        before = False if tagged else 3 if nested else 5
        argument = case["arguments"][0]
        expected = True if tagged else 11 if nested else 1 if name == "echo_float" else 5 + argument * 2 if name == "selected" else argument
        for lane in ("baseline", "instrumented_on"):
            assert len(bundle[lane]) == 2
            for index, attempt in enumerate(bundle[lane]):
                launches += 1
                observed = attempt["observation"]
                assert not observed["gaps"]
                prior, after = observed["before"]["roots"][root], observed["after"]["roots"][root]
                assert (prior["value"] if tagged else int(prior["value"])) == before
                expected_after = expected + int(difference and lane == "instrumented_on")
                assert (after["value"] if tagged else int(after["value"])) == expected_after
                outcome = observed["outcome"]
                if name == "fail":
                    assert outcome["kind"] == "error" and outcome["category"] == "panic"
                else:
                    value = outcome["graph"]["roots"]["result"]
                    if name == "echo_float":
                        assert value["kind"] == "float" and value["bits"] == "8000000000000000"
                    elif tagged:
                        assert value["kind"] == "boolean" and value["value"] is True
                    else:
                        assert value["kind"] == "integer" and int(value["value"]) == (7 if difference else expected)
                folder = path.parent / case["case"] / (lane + "-" + str(index))
                assert (folder / "stdout").read_bytes() == (b"" if tagged else b"INIT\xff\n")
                assert (folder / "stderr").read_bytes() == (b"" if tagged else b"ERR\x00\n")
                if lane == "instrumented_on":
                    assert attempt["execution"]["witness"]["functions"] == {entry["otelc_runtime_function"]: 1}
                identities = json.loads((folder / "build-identities.json").read_text())
                inputs = identities["source_inputs"]
                assert len(inputs) >= (1 if tagged else 2)
                assert identities["compiler"]["environment"]["GOFLAGS"] == "-tags=oteleq_selected"
                check_build_context(folder, entry, case["case"], inputs)
    return launches


def check_build_context(folder: Path, entry: dict, case_id: str, inputs: dict) -> None:
    """Copied shrink evidence keeps its original build and working-directory provenance."""
    recipe = json.loads((folder / "go-bundle/recipe.json").read_text())
    module = Path(entry["go_context"]["module_root"])
    working_directory = Path(json.loads((folder / "working-directory.json").read_text()))
    project = working_directory
    for _ in module.parts:
        project = project.parent
    assert project.is_absolute() and project.name == "project" and project.parent.name == folder.name
    assert project.parent.parent.name == case_id
    assert Path(recipe["source_root"]) == working_directory == project / module
    assert all(str(project / name) in inputs for name in entry["go_context"]["files"])


def framework(workspace: Path, folder: Path, name: str) -> int:
    results = command([sys.executable, workspace / "tests/test_equivalence.py"], folder, name, expected=1)
    summaries = [json.loads(line) for line in results.splitlines()]
    assert len(summaries) == 6
    return sum(check_report(Path(item["report"]), 1) for item in summaries)


def source_controls(cli: Path, workspace: Path, folder: Path, case: dict) -> int:
    """Changed module, imported type or sibling state refuses before any launch."""
    plan = json.loads((workspace / "plan.json").read_text())
    source = Path(plan["source"])
    runs = set((workspace / "runs").iterdir())
    for index, name in enumerate(("go.mod", "types/types.go", "internal/counter/state.go")):
        path = source / name
        original = path.read_bytes()
        try:
            path.write_bytes(original + b"\n// deliberate input alteration\n")
            command([cli, "replay", "--workspace", workspace, "--case", case["id"]],
                    folder, "changed-source-" + str(index), expected=4)
            assert "source or immutable snapshot changed" in (folder / ("changed-source-" + str(index) + ".stderr")).read_text()
            assert set((workspace / "runs").iterdir()) == runs
        finally:
            path.write_bytes(original)
    return 3


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--otelc-root", type=Path, required=True)
    parser.add_argument("--report-dir", type=Path, required=True)
    parser.add_argument("--cli", type=Path, required=True)
    args = parser.parse_args()
    cli, provider, destination = args.cli.resolve(strict=True), args.otelc_root.resolve(strict=True), args.report_dir.resolve()
    if destination.is_relative_to(provider) or destination.is_relative_to(Path(__file__).resolve().parents[1]):
        parser.error("report directory must be new and outside both repositories")
    destination.mkdir(mode=0o700)
    os.environ.update(OTELEQ_PYTHON=sys.executable, OTELEQ_CLI=str(cli))
    folder = destination / "modules"
    workspace = prepare(cli, provider, folder)
    command([cli, "run", "--workspace", workspace, "--report-dir", folder / "comparison"], folder, "run", expected=1)
    launches = check_report(folder / "comparison/report.json")
    launches += framework(workspace, folder, "framework")
    exported = folder / "exported"
    command([cli, "export-tests", "--workspace", workspace, "--destination", exported, "--apply"], folder, "export")
    command([cli, "run", "--workspace", exported, "--report-dir", folder / "export-comparison"], folder, "export-run", expected=1)
    launches += check_report(folder / "export-comparison/report.json")
    launches += framework(exported, folder, "export-framework")
    corpus = json.loads((workspace / "tests/corpus.json").read_text())
    plan = json.loads((workspace / "plan.json").read_text())
    target = next(entry for entry in plan["inventory"] if entry["name"] == "state_difference")
    case = next(item for item in corpus if item["function_id"] == target["id"])
    controls = source_controls(cli, workspace, folder, case)
    command([cli, "shrink", "--workspace", workspace, "--case", case["id"],
             "--report-dir", folder / "shrink", "--trials", "1"], folder, "shrink", expected=1)
    shrink = json.loads((folder / "shrink/shrink.json").read_text())
    assert shrink["reduced_arguments"] == [0] and shrink["status"] == "candidate_rule_minimal"
    trials = [Path(item["report"]) for item in shrink["trials"]]
    assert len(trials) == 1
    launches += sum(check_report(path, 1) for path in trials)
    launches += check_report(folder / "shrink/original/report.json", 1)
    launches += check_report(folder / "shrink/confirmation/report.json", 1)
    reduced = Path(shrink["workspace"])
    replay = json.loads(command([cli, "replay", "--workspace", reduced, "--case", case["id"]], folder, "replay", expected=1))
    launches += check_report(Path(replay["report"]), 1)
    for path in (workspace, exported, reduced):
        frozen = json.loads((path / "plan.json").read_text())
        assert all(hashlib.sha256((Path(frozen["source"]) / name).read_bytes()).hexdigest() == value
                   for name, value in frozen["source_manifest"].items())
    result = {"claim": "equivalence over these tests and observations", "artefact_class": "diagnostic",
              "cli_sha256": hashlib.sha256(cli.read_bytes()).hexdigest(), "cases": 6, "matching_cases": 5,
              "difference_controls": 1, "actual_application_launches": launches, "source_preserved": True,
              "prelaunch_source_refusals": controls,
              "scope": "Ordinary source modules/packages, sibling state, imported named scalar types, fixed tags, nested in-snapshot local replacement; no generic/method/cgo/workspace/shipping qualification."}
    (destination / "QUALIFICATION.json").write_text(json.dumps(result, indent=2) + "\n")
    print(json.dumps(result), flush=True)


if __name__ == "__main__":
    main()
