"""Qualify source-bound Go receiver graphs through actual otelc builds and runs."""
import argparse
import hashlib
import json
import os
from pathlib import Path
import sys

from qualify_generation import command


SOURCE = r'''package counter
import ("math";"runtime/debug")
type Number int16
type Counter struct {
 value Number
 self *Counter
 pointer *Number
 view *int16
 array [2]uint64
 label string
 active bool
 ratio float32
 wide float64
}
var shared *Counter
var total Number
func instrumented()bool{info,ok:=debug.ReadBuildInfo();if !ok{return false};for _,dep:=range info.Deps{if dep.Path=="io.quux.otelc/go"{return true}};return false}
func (value *Counter) Add(amount Number)*Counter{value.value+=amount;total+=amount;value.array[1]++;value.pointer=&total;return value}
func (value *Counter) InstanceDifference(amount Number)int{value.value+=amount;if instrumented(){value.value++};return 7}
func (value *Counter) GlobalDifference(amount Number)int{total+=amount;if instrumented(){total++};return 7}
func (value *Counter) AliasDifference(amount Number)int{if instrumented(){other:=int16(value.value);value.view=&other};return 7}
func (value *Counter) Fail(amount Number)int{value.value+=amount;panic("known")}
func (value Counter) Copy(amount Number)Number{value.value+=amount;return value.value}
func (value *Counter) Void(amount Number){value.value+=amount}
func (value *Counter) Read(amount Number)Number{if value==nil{return amount};return value.value}
func (value *Counter) String()string{panic("APPLICATION_FORMATTER")}
func (value *Counter) MarshalJSON()([]byte,error){panic("APPLICATION_FORMATTER")}
func New(seed Number)*Counter{value:=&Counter{value:seed,label:"\xff\x00é😀",active:true,ratio:math.Float32frombits(0x80000000),wide:math.Float64frombits(0x7ff0000000000001),array:[2]uint64{18446744073709551615,0}};value.self=value;value.pointer=&value.value;value.view=(*int16)(&value.value);shared=value;return value}
func Nil(seed Number)*Counter{return nil}
'''
METHODS = ("Add", "InstanceDifference", "GlobalDifference", "AliasDifference", "Fail", "Copy", "Void", "Read", "Main")


def selected(name: str) -> str:
    """Source-qualified selectors keep the main and library callables distinct."""
    return ("cmd.api.Counter." if name == "Main" else "counter.api.Counter.") + name


def policy_text(methods: tuple[str, ...] = METHODS) -> str:
    """Explicit source selection and independent fixed construction inputs."""
    text = 'schema_version=1\nlanguages=["go"]\n[adapters.go]\nmodule_roots=["."]\n[functions]\ninclude=' + json.dumps([selected(name) for name in methods]) + '\n'
    for name in methods:
        text += '\n[[fixtures]]\nfunction=' + json.dumps(selected(name)) + '\ncases=[[3]]\nreceiver={factory="' + ("Nil" if name == "Read" else "New") + '",arguments=[10]}\n'
        if name == "InstanceDifference":
            text += 'domains=[{kind="integer",minimum=0,maximum=3}]\n'
        if name == "Fail":
            text += 'expected_baseline={kind="error",category="panic",type="go.string"}\n'
    return text


def prepare(cli: Path, provider: Path, folder: Path) -> Path:
    folder.mkdir()
    source = folder / "application"
    (source / "counter").mkdir(parents=True)
    (source / "go.mod").write_text("module example.test/receiver\n\ngo 1.27.2\n")
    (source / "counter/api.go").write_text(SOURCE)
    (source / "cmd").mkdir()
    (source / "cmd/api.go").write_text(SOURCE.replace("package counter", "package main")
                                      + "\nfunc main(){}\nfunc (value Counter) Main(amount Number)Counter{value.value+=amount;return value}\n")
    policy = folder / "equivalence.toml"
    policy.write_text(policy_text())
    workspace = Path(command([cli, "plan", "--source", source, "--otelc-root", provider,
                              "--workspace-parent", folder, "--config", policy], folder, "plan"))
    plan = json.loads((workspace / "plan.json").read_text())
    ready = [item for item in plan["inventory"] if item["status"] == "ready"]
    assert {item["name"] for item in ready} == {"Counter." + name for name in METHODS}, plan["inventory"]
    assert not any(item["status"] == "blocked" for item in plan["inventory"]), plan["inventory"]
    command([cli, "generate", "--workspace", workspace], folder, "generate")
    return workspace


def node(graph: dict, reference: dict) -> dict:
    assert set(reference) == {"kind", "node_id"} and reference["kind"] == "reference"
    result = next(item for item in graph["nodes"] if item["id"] == reference["node_id"])
    return result["fields"]


def number(graph: dict, reference: dict) -> int:
    return int(node(graph, reference)["value"]["value"])


def state(graph: dict, method: str, argument: int, lane: str, *, after: bool) -> None:
    """Check every declared field/root, bits, byte strings and storage aliases."""
    roots = graph["roots"]
    assert roots["argument:0"]["value"] == str(argument)
    if method == "Read":
        assert roots["receiver"] == {"kind": "null"}
        assert node(graph, roots["global:shared"])["value"] == {"kind": "null"}
        assert number(graph, roots["global:total"]) == 0
        return
    receiver = roots["receiver"]
    fields = node(graph, node(graph, receiver)["value"])
    assert set(fields) == {"value", "self", "pointer", "view", "array", "label", "active", "ratio", "wide"}
    increment = argument if after and method in ("Add", "InstanceDifference", "Fail", "Void") else 0
    extra = int(after and method == "InstanceDifference" and lane == "instrumented_on")
    assert number(graph, fields["value"]) == 10 + increment + extra
    view = node(graph, node(graph, fields["view"])["value"])
    assert view["value"]["value"] == str(10 + increment + extra)
    shared = not (after and method == "AliasDifference" and lane == "instrumented_on")
    assert (view["location"] == node(graph, fields["value"])["location"]) == shared
    assert node(graph, fields["self"])["value"] == receiver
    assert node(graph, roots["global:shared"])["value"] == receiver
    total = argument if after and method in ("Add", "GlobalDifference") else 0
    total += int(after and method == "GlobalDifference" and lane == "instrumented_on")
    assert number(graph, roots["global:total"]) == total
    assert node(graph, fields["pointer"])["value"] == (roots["global:total"] if after and method == "Add" else fields["value"])
    array = node(graph, node(graph, fields["array"])["value"])
    assert set(array) == {"item:0", "item:1"}
    assert number(graph, array["item:0"]) == 18446744073709551615
    assert number(graph, array["item:1"]) == int(after and method == "Add")
    assert node(graph, fields["label"])["value"]["value"] == "ff00c3a9f09f9880"
    assert node(graph, fields["active"])["value"]["value"] is True
    assert node(graph, fields["ratio"])["value"]["bits"] == "80000000"
    assert node(graph, fields["wide"])["value"]["bits"] == "7ff0000000000001"


def copied_result(graph: dict, argument: int) -> None:
    """A value result copies slots but its internal pointers keep original aliases."""
    result = graph["roots"]["result"]
    receiver = graph["roots"]["receiver"]
    assert result != receiver
    fields = node(graph, result)
    original = node(graph, node(graph, receiver)["value"])
    assert set(fields) == set(original)
    assert all(fields[name] != original[name] for name in fields)
    assert number(graph, fields["value"]) == 10 + argument
    assert node(graph, fields["self"])["value"] == receiver
    assert node(graph, fields["pointer"])["value"] == original["value"]
    view = node(graph, node(graph, fields["view"])["value"])
    assert view["location"] == node(graph, original["value"])["location"]
    assert view["value"]["value"] == "10"
    array = node(graph, node(graph, fields["array"])["value"])
    assert set(array) == {"item:0", "item:1"}
    assert number(graph, array["item:0"]) == 18446744073709551615
    assert number(graph, array["item:1"]) == 0
    for name in ("label", "active", "ratio", "wide"):
        assert node(graph, fields[name])["value"] == node(graph, original[name])["value"]


def check_report(path: Path, expected_cases: int = 9) -> int:
    """Each actual lane/repeat must satisfy an independent complete fixture oracle."""
    report = json.loads(path.read_text())
    assert report["source_preserved"] and not report["blocked"] and len(report["cases"]) == expected_cases
    launches = 0
    for case in report["cases"]:
        method = case["function"].rsplit(".", 1)[-1]
        assert case["exit_code"] == int(method in ("InstanceDifference", "GlobalDifference", "AliasDifference")), case
        bundle = json.loads((path.parent / case["case"] / "typed-bundle.json").read_text())["cases"][0]
        for lane in ("baseline", "instrumented_on"):
            assert len(bundle[lane]) == 2
            for index, attempt in enumerate(bundle[lane]):
                launches += 1
                observation = attempt["observation"]
                assert not observation["gaps"]
                state(observation["before"], method, case["arguments"][0], lane, after=False)
                state(observation["after"], method, case["arguments"][0], lane, after=True)
                outcome = observation["outcome"]
                state(outcome["graph"], method, case["arguments"][0], lane, after=True)
                if method == "Fail":
                    assert outcome["kind"] == "error" and outcome["category"] == "panic"
                    assert outcome["graph"]["roots"]["error"] == {"kind": "string", "type": "go.string", "encoding": "raw_bytes", "value": "6b6e6f776e"}
                else:
                    assert outcome["kind"] == "return"
                    result = outcome["graph"]["roots"]["result"]
                    if method == "Add":
                        assert result == outcome["graph"]["roots"]["receiver"]
                    elif method == "Main":
                        copied_result(outcome["graph"], case["arguments"][0])
                    elif method == "Void":
                        assert result == {"kind": "undefined"}
                    else:
                        expected = 10 + case["arguments"][0] if method == "Copy" else case["arguments"][0] if method == "Read" else 7
                        assert result["kind"] == "integer" and result["value"] == str(expected)
                folder = path.parent / case["case"] / (lane + "-" + str(index))
                assert (folder / "stdout").read_bytes() == (folder / "stderr").read_bytes() == b""
                if lane == "instrumented_on":
                    assert attempt["execution"]["witness"]["functions"] == {case["function"]: 1}
                identities = json.loads((folder / "build-identities.json").read_text())
                recipe = json.loads((folder / "go-bundle/recipe.json").read_text())
                helpers = [(name, value) for name, value in recipe["inputs"].items()
                           if name.endswith("/oteleq_generated_observer/observer.go")]
                assert len(helpers) == 1 and identities["loaded_input_count"] == len(recipe["inputs"])
                assert hashlib.sha256(Path(helpers[0][0]).read_bytes()).hexdigest() == helpers[0][1]["sha256"]
    return launches


def framework(workspace: Path, folder: Path, label: str) -> int:
    outputs = command([sys.executable, workspace / "tests/test_equivalence.py"], folder, label, expected=1)
    reports = [json.loads(line) for line in outputs.splitlines()]
    assert len(reports) == 9
    return sum(check_report(Path(item["report"]), 1) for item in reports)


def selected_case(plan: dict, corpus: list, name: str) -> dict:
    """An excluded same-named method cannot supply the selected shrink case."""
    entries = [item for item in plan["inventory"] if item["status"] == "ready" and item["name"] == name]
    assert len(entries) == 1
    cases = [item for item in corpus if item["function_id"] == entries[0]["id"]]
    assert len(cases) == 1
    return cases[0]


def source_guards(cli: Path, workspace: Path, folder: Path, case: dict) -> int:
    """Changed source/module/snapshot inputs refuse before another launch."""
    plan = json.loads((workspace / "plan.json").read_text())
    runs = set((workspace / "runs").iterdir())
    paths = [Path(plan["source"]) / "go.mod", Path(plan["source"]) / "counter/api.go", Path(plan["source"]) / "cmd/api.go",
             workspace / "snapshot/counter/api.go"]
    for index, path in enumerate(paths):
        original = path.read_bytes()
        try:
            path.write_bytes(original + b"\n// changed input\n")
            command([cli, "replay", "--workspace", workspace, "--case", case["id"]],
                    folder, "changed-input-" + str(index), expected=4)
            assert "source or immutable snapshot changed" in (folder / ("changed-input-" + str(index) + ".stderr")).read_text()
            assert set((workspace / "runs").iterdir()) == runs
        finally:
            path.write_bytes(original)
    return len(paths)


def refusals(cli: Path, provider: Path, folder: Path) -> dict:
    """Missing/opaque fixtures and incomplete capture must never qualify."""
    folder.mkdir()
    controls = [
        ("missing-factory", SOURCE, "Add", "Missing", 3),
        ("wrong-factory", SOURCE, "Add", "instrumented", 3),
        ("opaque-global", SOURCE + "\nvar pending []int\n", "Add", "New", 3),
        ("helper-collision", SOURCE, "Add", "New", 3),
        ("factory-failure", SOURCE.replace("func New(seed Number)*Counter{", 'func New(seed Number)*Counter{panic("bad factory");'), "Add", "New", 4),
        ("float32-nan", SOURCE.replace("0x80000000", "0x7f800001"), "Add", "New", 4),
        ("complex-panic", SOURCE.replace('panic("known")', "panic(value)"), "Fail", "New", 4),
        ("nil-value-receiver", SOURCE, "Copy", "Nil", 4),
        ("initial-state", SOURCE.replace("func New(seed Number)*Counter{", "func New(seed Number)*Counter{if instrumented(){seed++};"), "Add", "New", 2),
    ]
    launches = 0
    for name, text, method, factory, expected in controls:
        target = folder / name
        source = target / "application"
        (source / "counter").mkdir(parents=True)
        (source / "go.mod").write_text("module example.test/receiver\n\ngo 1.27.2\n")
        (source / "counter/api.go").write_text(text)
        if name == "helper-collision":
            (source / "oteleq_generated_observer").mkdir()
            (source / "oteleq_generated_observer/keep.txt").write_text("application-owned\n")
        policy = target / "equivalence.toml"
        policy.write_text(policy_text((method,)).replace('factory="New"', 'factory=' + json.dumps(factory)))
        workspace = Path(command([cli, "plan", "--source", source, "--otelc-root", provider,
                                  "--workspace-parent", target, "--config", policy], target, "plan"))
        command([cli, "generate", "--workspace", workspace], target, "generate")
        comparison = target / "comparison"
        command([cli, "run", "--workspace", workspace, "--report-dir", comparison], target, "run", expected=expected)
        report = json.loads((comparison / "report.json").read_text())
        assert report["source_preserved"]
        raw = [path for path in comparison.rglob("command.json") if path.parent.name.startswith(("baseline-", "instrumented_on-"))]
        launches += len(raw)
        if expected == 3:
            assert report["blocked"] and not report["cases"] and not raw
        elif expected == 4:
            assert not report["blocked"] and len(report["cases"]) == 1 and report["cases"][0]["exit_code"] == 4
            assert len(raw) == 1 and not list(comparison.rglob("observation"))
        else:
            assert not report["blocked"] and len(report["cases"]) == 1 and len(raw) == 4
            typed = report["cases"][0]["comparison"]["cases"][0]
            assert typed["verdict"] == "blocked" and any(pair["comparison"]["initial_differences"] for pair in typed["pairs"])
        assert all(b"APPLICATION_FORMATTER" not in path.read_bytes() for path in comparison.rglob("stderr"))
    result = {"refusal_controls": len(controls), "actual_application_launches": launches,
              "prelaunch_refusals": 4, "incomplete_fixture_or_observer": 4, "initial_state_blocks": 1}
    (folder / "controls.json").write_text(json.dumps(result, indent=2) + "\n")
    return result


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--otelc-root", type=Path, required=True)
    parser.add_argument("--report-dir", type=Path, required=True)
    parser.add_argument("--cli", type=Path, required=True)
    args = parser.parse_args()
    provider, cli, folder = args.otelc_root.resolve(strict=True), args.cli.resolve(strict=True), args.report_dir.resolve()
    if folder.is_relative_to(provider) or folder.is_relative_to(Path(__file__).resolve().parents[1]):
        parser.error("report directory must be new and outside both repositories")
    folder.mkdir(mode=0o700)
    os.environ.update(OTELEQ_PYTHON=sys.executable, OTELEQ_CLI=str(cli))
    work = folder / "receivers"
    workspace = prepare(cli, provider, work)
    command([cli, "run", "--workspace", workspace, "--report-dir", work / "comparison"], work, "run", expected=1)
    launches = check_report(work / "comparison/report.json")
    launches += framework(workspace, work, "framework")
    exported = work / "exported"
    command([cli, "export-tests", "--workspace", workspace, "--destination", exported, "--apply"], work, "export")
    command([cli, "run", "--workspace", exported, "--report-dir", work / "export-comparison"], work, "export-run", expected=1)
    launches += check_report(work / "export-comparison/report.json")
    launches += framework(exported, work, "export-framework")
    corpus = json.loads((workspace / "tests/corpus.json").read_text())
    plan = json.loads((workspace / "plan.json").read_text())
    case = selected_case(plan, corpus, "Counter.InstanceDifference")
    controls = source_guards(cli, workspace, work, case)
    command([cli, "shrink", "--workspace", workspace, "--case", case["id"], "--trials", "1",
             "--report-dir", work / "shrink"], work, "shrink", expected=1)
    shrink = json.loads((work / "shrink/shrink.json").read_text())
    assert shrink["reduced_arguments"] == [0] and shrink["status"] == "candidate_rule_minimal"
    paths = [work / "shrink/original/report.json", work / "shrink/confirmation/report.json",
             *[Path(item["report"]) for item in shrink["trials"]]]
    launches += sum(check_report(path, 1) for path in paths)
    replay = json.loads(command([cli, "replay", "--workspace", shrink["workspace"], "--case", case["id"]], work, "replay", expected=1))
    launches += check_report(Path(replay["report"]), 1)
    refused = refusals(cli, provider, folder / "refusals")
    launches += refused["actual_application_launches"]
    for path in (workspace, exported, Path(shrink["workspace"])):
        frozen = json.loads((path / "plan.json").read_text())
        assert all(hashlib.sha256((Path(frozen["source"]) / name).read_bytes()).hexdigest() == value
                   for name, value in frozen["source_manifest"].items())
    commands = [path for path in folder.rglob("command.json") if path.parent.name.startswith(("baseline-", "instrumented_on-"))]
    unique = {hashlib.sha256(path.read_bytes()).hexdigest() for path in commands}
    assert len(unique) == launches
    result = {"claim": "equivalence over these tests and observations", "artefact_class": "diagnostic",
              "cli_sha256": hashlib.sha256(cli.read_bytes()).hexdigest(), "cases": 9, "matching_cases": 6,
              "difference_controls": 3, "actual_application_launches": launches, "source_preserved": True,
              "prelaunch_source_refusals": controls, "retained_attempt_folders": len(commands), "unique_command_identities": len(unique),
              "fixture_refusals": refused,
              "scope": "Declared same-package scalar factories, private struct/array slots, aliases/cycles, scalar panics and nil/value receivers. No maps/slices/interfaces, arbitrary arguments/actions, cross-boundary allocation identity or shipping qualification."}
    (folder / "QUALIFICATION.json").write_text(json.dumps(result, indent=2) + "\n")
    print(json.dumps(result), flush=True)


if __name__ == "__main__":
    main()
