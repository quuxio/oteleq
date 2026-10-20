"""Qualify actual C++ private storage, compiler identities and alias differences."""
import argparse
import hashlib
import json
import os
from pathlib import Path
import sys

from qualify_generation import command

SOURCE = r'''#include <cstdint>
#include <cstdlib>
#include <stdexcept>
namespace sample {
using Count=std::int16_t;
struct Child {int value=19;};
class Counter {
 Count value_,other_;
 Counter* self_;
 Count* pointer_;
 Child child_;
 int array_[2];
 float small_;
 double wide_;
 inline static Count total_=0;
 static bool active(){return std::getenv("OTELC_CONFIG")!=nullptr;}
 static Counter create(Count seed){return Counter(seed);}
 int secret(Count amount){value_+=amount;return value_;}
public:
 explicit Counter(Count seed):value_(seed),other_(seed),self_(this),pointer_(&value_),child_{},array_{11,12},small_(0.0f),wide_(-0.0){
  unsigned bits=0x7fa00017;__builtin_memcpy(__builtin_addressof(small_),__builtin_addressof(bits),4);
 }
 Counter* operator&(){throw 77;}
 Counter& identity(Count amount){value_+=amount;total_+=amount;return *this;}
 int read(Count amount)const{return value_+amount;}
 int array(Count amount){array_[1]+=amount;return array_[1];}
 void touch(Count amount){value_+=amount;}
 int instance(Count amount){value_+=amount+active();return 7;}
 int static_only(Count amount){total_+=amount+active();return 7;}
 int alias(Count){pointer_=active()?&other_:&value_;return 7;}
 int fail(Count amount){value_+=amount;throw std::runtime_error("expected");}
};
Counter make(Count seed){return Counter(seed);}
}
'''
METHODS = ("identity", "read", "array", "touch", "secret", "instance", "static_only", "alias", "fail")
DIFFERENCES = {"instance", "static_only", "alias"}
BINDING_SOURCE = '''class Graph {
 short value_;
 Graph* self_;
public:
 explicit Graph(short seed):value_(seed),self_(this){}
 Graph& add(short amount){value_+=amount;return *this;}
};
extern "C" int plain(int value){return value+1;}
extern "C" int _named(int value){return value+1;}
extern "C" int _Zbad(int value){return value+1;}
class UnicodeCounter {
 int value_;
 int& \u6570\u636e;
 int& read_alias()const{++calls_;return \u6570\u636e;}
public:
 inline static int calls_=0;
 explicit UnicodeCounter(int seed):value_(seed),\u6570\u636e(value_){}
 int add(int amount){value_+=amount;return value_;}
};
#define \u6570\u636e read_alias()
'''
BINDING_FUNCTIONS = ("Graph::add(short)", "plain", "_named", "_Zbad", "UnicodeCounter::add(int)")
BINDING_FACTORIES = {BINDING_FUNCTIONS[0]: 'Graph', BINDING_FUNCTIONS[4]: 'UnicodeCounter'}
BINDING_STATIC = 'global:UnicodeCounter::calls_'


def function(name: str) -> str:
    """The selected LLVM ABI name includes const and canonical alias domains."""
    return "sample::Counter::" + name + "(short)" + (" const" if name == "read" else "")


def prepare(cli: Path, provider: Path, folder: Path, source_text: str = SOURCE,
            methods: tuple[str, ...] = METHODS, factory: str | None = None) -> Path:
    """Freeze concrete scalar inputs and existing independently called factories."""
    folder.mkdir()
    source = folder / "application"
    source.mkdir()
    (source / "app.cpp").write_text(source_text)
    policy = folder / "equivalence.toml"
    text = 'schema_version=1\nlanguages=["cpp"]\n[functions]\ninclude=' + json.dumps([function(name) for name in methods]) + '\n'
    for name in methods:
        selected = factory or ("sample::Counter::create" if name == "secret" else "sample::make" if name == "read" else "sample::Counter")
        text += '\n[[fixtures]]\nfunction=' + json.dumps(function(name)) + '\ncases=[[3]]\n'
        text += 'receiver={factory=' + json.dumps(selected) + ',arguments=[10]}\n'
        text += 'domains=[{kind="integer",minimum=0,maximum=3}]\n'
        if name == "fail":
            text += 'expected_baseline={kind="error",category="exception",type="cpp.exception.std::runtime_error"}\n'
    policy.write_text(text)
    workspace = Path(command([cli, "plan", "--source", source, "--otelc-root", provider,
                              "--workspace-parent", folder, "--config", policy], folder, "plan"))
    command([cli, "generate", "--workspace", workspace], folder, "generate")
    return workspace


def node(graph: dict, value: dict) -> dict:
    """Resolve local storage identity; no application equality or raw addresses."""
    return next(item for item in graph["nodes"] if item["id"] == value["node_id"])


def scalar(graph: dict, value: dict, expected: int, *, short: bool = False) -> None:
    """The qualified native profile has independently expected 16/32-bit slots."""
    assert node(graph, value)["fields"]["value"] == {
        "kind": "integer", "type": "cpp.short" if short else "cpp.int", "value": str(expected),
        "bits": 16 if short else 32, "signed": True}


def check_state(graph: dict, value: int, total: int, amount: int, *, array: int = 12, alias: bool = False) -> None:
    """Independent literals check every field, input, static, float and alias."""
    roots = graph["roots"]
    receiver = node(graph, roots["receiver"])
    fields = receiver["fields"]
    assert set(fields) == {"location", "field:value_", "field:other_", "field:self_", "field:pointer_",
                           "field:child_", "field:array_", "field:small_", "field:wide_"}
    scalar(graph, fields["field:value_"], value, short=True)
    scalar(graph, fields["field:other_"], 10, short=True)
    assert node(graph, fields["field:small_"])["fields"]["value"] == {"kind": "float", "type": "cpp.float", "bits": "7fa00017"}
    assert node(graph, fields["field:wide_"])["fields"]["value"] == {"kind": "float", "type": "cpp.double", "bits": "8000000000000000"}
    scalar(graph, roots["argument:0"], amount, short=True)
    scalar(graph, roots["global:sample::Counter::total_"], total, short=True)
    assert node(graph, fields["field:self_"])["fields"]["value"] == roots["receiver"]
    assert node(graph, fields["field:pointer_"])["fields"]["value"] == fields["field:other_" if alias else "field:value_"]
    assert receiver["fields"]["location"] == node(graph, fields["field:value_"])["fields"]["location"]
    child = node(graph, fields["field:child_"])
    assert set(child["fields"]) == {"location", "field:value"}
    scalar(graph, child["fields"]["field:value"], 19)
    assert child["fields"]["location"] == node(graph, child["fields"]["field:value"])["fields"]["location"]
    items = node(graph, fields["field:array_"])["fields"]
    assert set(items) == {"location", "item:0", "item:1"}
    scalar(graph, items["item:0"], 11)
    scalar(graph, items["item:1"], array)
    assert items["location"] == node(graph, items["item:0"])["fields"]["location"]


def check_report(path: Path, expected_cases: int) -> tuple[int, dict]:
    """Check every repeat/lane, including exact error and ordinary return values."""
    report = json.loads(path.read_text())
    assert report["source_preserved"] and not report["blocked"] and len(report["cases"]) == expected_cases
    launches = 0
    for case in report["cases"]:
        method = next(name for name in METHODS if function(name) == case["function"])
        assert case["exit_code"] == int(method in DIFFERENCES)
        assert case["receiver_fixture"]["arguments"] == [10]
        bundle = json.loads((path.parent / case["case"] / "typed-bundle.json").read_text())["cases"][0]
        assert set(bundle["contract"]["required_roots"]) == {"receiver", "argument:0", "global:sample::Counter::total_"}
        for lane in ("baseline", "instrumented_on"):
            assert len(bundle[lane]) == 2
            for attempt in bundle[lane]:
                launches += 1
                observed = attempt["observation"]
                assert all(attempt['execution']['channels'][name] == [] for name in ('stdout', 'stderr'))
                assert not observed["gaps"]
                amount, active = case["arguments"][0], int(lane == "instrumented_on")
                check_state(observed["before"], 10, 0, amount)
                value = 10 + amount + active if method == "instance" else 10 + amount if method in ("identity", "touch", "secret", "fail") else 10
                total = amount + active if method == "static_only" else amount if method == "identity" else 0
                options = {"array": 12 + amount if method == "array" else 12, "alias": method == "alias" and bool(active)}
                check_state(observed["after"], value, total, amount, **options)
                outcome = observed["outcome"]
                graph = outcome["graph"]
                check_state(graph, value, total, amount, **options)
                if method == "fail":
                    assert outcome["kind"] == "error" and outcome["category"] == "exception"
                    assert graph["roots"]["error"] == {"kind": "bytes", "type": "cpp.exception.std::runtime_error", "hex": b"expected".hex()}
                else:
                    assert outcome["kind"] == "return"
                    result = graph["roots"]["result"]
                    if method == "identity":
                        returned = node(graph, result)
                        assert returned["fields"]["value"] == graph["roots"]["receiver"]
                        assert returned["fields"]["location"] == node(graph, graph["roots"]["receiver"])["fields"]["location"]
                    elif method == "touch":
                        assert result == {"kind": "unit", "type": "cpp.unit"}
                    else:
                        expected = value if method == "secret" else 10 + amount if method == "read" else 12 + amount if method == "array" else 7
                        scalar(graph, result, expected)
                if lane == "instrumented_on":
                    assert attempt["execution"]["witness"]["functions"] == {case["function"]: 1}
    return launches, report


def framework(workspace: Path, folder: Path, name: str, expected_cases: int = len(METHODS)) -> int:
    """Each retained unittest verdict must match its declared deliberate controls."""
    output = command([sys.executable, workspace / "tests/test_equivalence.py"], folder, name, expected=1)
    summaries = [json.loads(line) for line in output.splitlines()]
    assert len(summaries) == expected_cases
    return sum(check_report(Path(item["report"]), 1)[0] for item in summaries)


def reduction(cli: Path, workspace: Path, folder: Path, report: dict) -> int:
    """Reduce scalar method inputs while preserving construction and alias failure."""
    target = next(case for case in report["cases"] if case["function"] == function("alias"))
    reduced = folder / "shrinking"
    command([cli, "shrink", "--workspace", workspace, "--case", target["case"], "--report-dir", reduced, "--trials", "16"], folder, "shrink", expected=1)
    result = json.loads((reduced / "shrink.json").read_text())
    assert result["original_arguments"] == [3] and result["reduced_arguments"] == [0]
    assert result["status"] == "candidate_rule_minimal" and result["source_preserved"]
    reports = [reduced / "original/report.json", reduced / "confirmation/report.json", *(Path(item["report"]) for item in result["trials"])]
    launches = sum(check_report(path, 1)[0] for path in reports)
    replay_workspace = Path(result["workspace"])
    launches += framework(replay_workspace, folder, "shrunk-framework", 1)
    replay = json.loads(command([cli, "replay", "--workspace", replay_workspace, "--case", target["case"]], folder, "shrunk-replay", expected=1))
    return launches + check_report(Path(replay["report"]), 1)[0]


def refusals(cli: Path, provider: Path, folder: Path) -> tuple[int, int]:
    """Unsupported storage and failed fixtures cannot qualify as matching outcomes."""
    controls = [
        ("missing-factory", SOURCE, "missing", 3),
        ("uninitialised", SOURCE.replace("value_(seed),", ""), None, 3),
        ("opaque", SOURCE.replace("Count value_,other_;", "std::exception opaque_;Count value_,other_;").replace("value_(seed),", "opaque_{},value_(seed),"), None, 3),
        ("local-static", SOURCE.replace("int fail(Count amount){", "int fail(Count amount){static int hidden=0;++hidden;"), None, 3),
        ("macro-storage", '#define STORAGE(name) int name=0;\nSTORAGE(hidden)\n' + SOURCE, None, 3),
        ("thread-local", SOURCE + '\nthread_local int hidden=0;\n', None, 3),
        ("template-storage", SOURCE + '\ntemplate<class T>struct Holder{inline static int state=0;};\n', None, 3),
        ("virtual", SOURCE.replace("public:", "public: virtual ~Counter(){}"), None, 3),
        ("collision", SOURCE + "\n// __oteleq_cpp\n", None, 3),
        ("budget", SOURCE.replace("int array_[2];", "int array_[4096];"), None, 4),
        ("constructor-failure", SOURCE.replace("unsigned bits=", 'throw std::runtime_error("construction");unsigned bits='), None, 4),
        ("custom-error", ('#include <cstdio>\n' + SOURCE).replace("namespace sample {", 'class Unknown:public std::runtime_error {public:using std::runtime_error::runtime_error;const char* what()const noexcept override {std::puts("APP_CALLBACK");return "masked";}};\nnamespace sample {').replace('throw std::runtime_error("expected")', 'throw Unknown("expected")'), None, 4),
        ("initial-state", SOURCE.replace("value_(seed)", "value_(seed+active())"), None, 2),
    ]
    launches = 0
    for name, source, factory, expected in controls:
        destination = folder / ("refusal-" + name)
        workspace = prepare(cli, provider, destination, source, ("fail",), factory)
        report_dir = destination / "run"
        command([cli, "run", "--workspace", workspace, "--report-dir", report_dir], destination, "run", expected=expected)
        report = json.loads((report_dir / "report.json").read_text())
        assert report["source_preserved"]
        if expected == 3:
            assert report["blocked"] and not report["cases"]
        else:
            assert len(report["cases"]) == 1 and report["cases"][0]["exit_code"] == expected
        if expected == 2:
            comparison = report["cases"][0]["comparison"]["cases"][0]
            assert comparison["verdict"] == "blocked"
            assert any(pair["comparison"]["initial_differences"] for pair in comparison["pairs"])
        attempts = [path for path in report_dir.rglob("command.json") if path.parent.name.startswith(("baseline-", "instrumented_on-"))]
        assert len(attempts) == (0 if expected == 3 else 4 if expected == 2 else 1)
        assert all(b"APP_CALLBACK" not in path.read_bytes() for path in report_dir.rglob("stdout"))
        launches += len(attempts)
    return launches, len(controls)


def verify_launches(folder: Path, expected: int) -> dict:
    """Fresh original replay counts once; its copied shrink evidence counts zero."""
    raw = [path for path in folder.rglob("command.json")
           if path.parent.name.startswith(("baseline-", "instrumented_on-"))]
    unique = {hashlib.sha256(path.read_bytes()).hexdigest() for path in raw}
    assert len(unique) == expected and len(raw) == expected + 4
    return {"unique_application_launches": len(unique), "raw_attempt_folders": len(raw)}


def check_bindings(path: Path, expected_cases: int) -> int:
    """Global source types and C ABI names must call the actual intended function."""
    report = json.loads(path.read_text())
    assert report["source_preserved"] and not report["blocked"] and len(report["cases"]) == expected_cases
    launches = 0
    for case in report["cases"]:
        assert case["function"] in BINDING_FUNCTIONS and case["exit_code"] == 0 and case["arguments"] == [3]
        bundle = json.loads((path.parent / case["case"] / "typed-bundle.json").read_text())["cases"][0]
        receiver = case["function"] in BINDING_FACTORIES
        assert set(bundle["contract"]["required_roots"]) == ({"receiver", "argument:0", BINDING_STATIC} if receiver else {BINDING_STATIC})
        for lane in ("baseline", "instrumented_on"):
            assert len(bundle[lane]) == 2
            for attempt in bundle[lane]:
                launches += 1
                observed = attempt["observation"]
                assert all(attempt['execution']['channels'][name] == [] for name in ('stdout', 'stderr'))
                assert not observed["gaps"] and observed["outcome"]["kind"] == "return"
                outcome = observed["outcome"]["graph"]
                if receiver:
                    check_binding_receiver(observed, case)
                else:
                    zero = {'kind': 'integer', 'type': 'cpp.int', 'value': '0', 'bits': 32, 'signed': True}
                    assert observed["before"] == observed["after"] == {"roots": {BINDING_STATIC: zero}, "nodes": []}
                    assert outcome == {"nodes": [], "roots": {BINDING_STATIC: zero,
                        "result": {"kind": "integer", "type": "cpp.int", "value": "4", "bits": 32, "signed": True}}}
                if lane == "instrumented_on":
                    assert attempt["execution"]["witness"]["functions"] == {case["function"]: 1}
    return launches


def check_binding_receiver(observed: dict, case: dict) -> None:
    """Getters remain uncalled; narrow values, references and return copies are exact."""
    assert case['receiver_fixture']['arguments'] == [10]
    short = case['function'] == BINDING_FUNCTIONS[0]
    outcome = observed['outcome']['graph']
    for graph, expected in ((observed['before'], 10), (outcome, 13), (observed['after'], 13)):
        fields = node(graph, graph['roots']['receiver'])['fields']
        extra = 'field:self_' if short else 'field:\u6570\u636e'
        assert set(fields) == {'location', 'field:value_', extra}
        scalar(graph, fields['field:value_'], expected, short=short)
        scalar(graph, graph['roots']['argument:0'], 3, short=short)
        scalar(graph, graph['roots'][BINDING_STATIC], 0)
        expected_alias = graph['roots']['receiver'] if short else fields['field:value_']
        assert node(graph, fields[extra])['fields']['value'] == expected_alias
    if short:
        assert node(outcome, outcome['roots']['result'])['fields']['value'] == outcome['roots']['receiver']
    else:
        scalar(outcome, outcome['roots']['result'], 13)
        returned = node(outcome, outcome['roots']['result'])
        fields = node(outcome, outcome['roots']['receiver'])['fields']
        assert returned['fields']['location'] != node(outcome, fields['field:value_'])['fields']['location']


def binding_controls(cli: Path, provider: Path, folder: Path, source_text: str = BINDING_SOURCE) -> int:
    """Exercise source names, Unicode macro guards and receiver return semantics."""
    destination = folder / "bindings"
    destination.mkdir()
    source = destination / "application"
    source.mkdir()
    (source / "app.cpp").write_text(source_text)
    policy = destination / "equivalence.toml"
    text = 'schema_version=1\nlanguages=["cpp"]\n[functions]\ninclude=' + json.dumps(BINDING_FUNCTIONS) + '\n'
    for name in BINDING_FUNCTIONS:
        text += '\n[[fixtures]]\nfunction=' + json.dumps(name) + '\ncases=[[3]]\n'
        if name in BINDING_FACTORIES:
            text += 'receiver={factory=' + json.dumps(BINDING_FACTORIES[name]) + ',arguments=[10]}\n'
    policy.write_text(text)
    workspace = Path(command([cli, "plan", "--source", source, "--otelc-root", provider,
                              "--workspace-parent", destination, "--config", policy], destination, "plan"))
    command([cli, "generate", "--workspace", workspace], destination, "generate")
    launches = 0
    for name, suite in (("generated", workspace), ("exported", destination / "exported")):
        if name == "exported":
            command([cli, "export-tests", "--workspace", workspace, "--destination", suite, "--apply"], destination, "export-apply")
        report_dir = destination / (name + "-comparison")
        command([cli, "run", "--workspace", suite, "--report-dir", report_dir], destination, name + "-run")
        launches += check_bindings(report_dir / "report.json", len(BINDING_FUNCTIONS))
        output = command([sys.executable, suite / "tests/test_equivalence.py"], destination, name + "-framework")
        summaries = [json.loads(line) for line in output.splitlines()]
        assert len(summaries) == len(BINDING_FUNCTIONS)
        launches += sum(check_bindings(Path(item["report"]), 1) for item in summaries)
    return launches


def main() -> None:
    """Retain an external actual-provider corpus; this does not qualify shipping builds."""
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--otelc-root", type=Path, required=True)
    parser.add_argument("--report-dir", type=Path, required=True)
    parser.add_argument("--cli", type=Path, required=True)
    args = parser.parse_args()
    provider, cli = args.otelc_root.resolve(strict=True), args.cli.resolve(strict=True)
    folder = args.report_dir.resolve()
    if any(folder.is_relative_to(root) for root in (provider, Path(__file__).resolve().parents[1])):
        parser.error("qualification directory must be new and external")
    folder.mkdir(mode=0o700, exist_ok=False)
    os.environ["OTELEQ_PYTHON"], os.environ["OTELEQ_CLI"] = sys.executable, str(cli)
    workspace = prepare(cli, provider, folder / "cases")
    captures = folder / "comparison"
    command([cli, "run", "--workspace", workspace, "--report-dir", captures], folder, "run", expected=1)
    launches, report = check_report(captures / "report.json", len(METHODS))
    launches += framework(workspace, folder, "generated-framework")
    exported = folder / "exported"
    command([cli, "export-tests", "--workspace", workspace, "--destination", exported], folder, "export-dry-run")
    assert not exported.exists()
    command([cli, "export-tests", "--workspace", workspace, "--destination", exported, "--apply"], folder, "export-apply")
    exported_report = folder / "exported-comparison"
    command([cli, "run", "--workspace", exported, "--report-dir", exported_report], folder, "exported-run", expected=1)
    launches += check_report(exported_report / "report.json", len(METHODS))[0]
    launches += framework(exported, folder, "exported-framework")
    launches += reduction(cli, workspace, folder, report)
    refused_launches, controls = refusals(cli, provider, folder)
    launches += refused_launches
    binding_launches = binding_controls(cli, provider, folder)
    launches += binding_launches
    crlf = folder / "crlf"
    crlf.mkdir()
    crlf_launches = binding_controls(cli, provider, crlf, BINDING_SOURCE.replace("\n", "\r\n"))
    launches += crlf_launches
    counts = verify_launches(folder, launches)
    summary = {"claim": "equivalence over these tests and observations", "artefact_class": "diagnostic",
               "matching_cases": len(METHODS)-len(DIFFERENCES)+2*len(BINDING_FUNCTIONS), "different_cases": len(DIFFERENCES),
               **counts,
               "all_routes": True, "scalar_shrinking_and_replay": True, "source_preserved": True,
               "refusal_controls": controls, "refused_application_launches": refused_launches,
               "binding_cases": len(BINDING_FUNCTIONS), "binding_application_launches": binding_launches,
               "crlf_cases": len(BINDING_FUNCTIONS), "crlf_application_launches": crlf_launches,
               "oteleq_cli_sha256": hashlib.sha256(cli.read_bytes()).hexdigest(),
               "otelc_cli_sha256": hashlib.sha256((provider / "target/debug/quux-otelc").read_bytes()).hexdigest(),
               "qualifier_sha256": hashlib.sha256(Path(__file__).read_bytes()).hexdigest()}
    (folder / "qualification.json").write_text(json.dumps(summary, indent=2) + "\n")
    print(json.dumps(summary), flush=True)


if __name__ == "__main__":
    main()
