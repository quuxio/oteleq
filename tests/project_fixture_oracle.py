"""Independent literal graphs for current-source suite qualification."""
import json
from pathlib import Path

from domain_fixture_oracle import typed
from node_project_oracle import number, object_node, reference
from precondition_fixture_oracle import LANGUAGES, LESS, SEQUENCES
from precondition_fixture_oracle import check_sequence, pairs, plain_graph
from qualify_returns import scalar

EMOJI = "\U0001f642"
TEXT_VALUES = (EMOJI, "\x7f")
STAGES = {"initial": (20, 53), "changed": (20, 53), "added": (28, 61), "different": (29, 62)}


def kind_of(entry: dict) -> str:
    """Every accepted function has one independently declared fixture role."""
    names = {"integer": "numeric_span", "float": "numeric_float", "sequence": "Meter.numeric_step",
             "text": "current_text", "added": "current_added", "probe": "current_probe"}
    matches = [kind for kind, name in names.items() if name in entry["name"]]
    assert len(matches) == 1, entry["name"]
    return matches[0]


def arguments_for(language: str, kind: str) -> list[list]:
    if kind in ("integer", "float", "sequence"):
        return pairs(language, kind)
    return [[value] for value in TEXT_VALUES] if kind == "text" else [[]]


def graph(language: str, kind: str, arguments: list, result: int | None = None) -> dict:
    """Compare complete roots, descriptors, values and nodes, including empty arguments."""
    if kind in ("integer", "float"):
        return plain_graph(language, kind, arguments, result)
    value = {"roots": {}, "nodes": []}
    if language == "python":
        value = {"roots": {"arguments": reference("n0")}, "nodes": [{"id": "n0", "type": "python.builtins.list",
            "fields": {"item:0": typed(language, "string", arguments[0])} if kind == "text" else {}}]}
    elif language in ("javascript", "typescript"):
        value = {"roots": {"arguments": reference("n0")}, "nodes": [object_node(language, "n0",
            "ecmascript.array.prototype:Array", {"length": number(language, 0)}, array=True)]}
    if result is not None:
        value["roots"]["result"] = scalar(language, result)
    return value


def expected_result(language: str, kind: str, arguments: list, lane: str, stage: str) -> int:
    if kind == "integer":
        return arguments[0] * 100 + arguments[1] + (0 if stage == "initial" else 1000)
    if kind == "float":
        return pairs(language, kind).index(arguments) + 1
    if kind == "text":
        return 1
    if kind == "added":
        return 5
    assert kind == "probe"
    return int(lane == "instrumented_on")


def check_server_responses(folder: Path, lane: str) -> None:
    """A received body cannot stand in for even a completed server header write."""
    record = json.loads((folder / "http-responses.json").read_text())
    captured = json.loads((folder / "http-capture.json").read_text())
    assert type(record["schema_version"]) is int and record["schema_version"] == 1 and record["clock"] == "monotonic_ns"
    assert record["scope"] == "server response headers; client acknowledgement is not observed"
    assert type(record["unrecorded_events"]) is int and record["unrecorded_events"] == 0 and not captured["errors"]
    assert len(record["events"]) == len(captured["bodies"])
    assert bool(record["events"]) == (lane == "instrumented_on")
    for index, event in enumerate(record["events"]):
        assert type(event["body_index"]) is int and event["body_index"] == index and event["path"] == captured["bodies"][index]["path"]
        assert type(event["status"]) is int and event["status"] == 200 and event["headers_write_failed"] is False
        times = [event[name] for name in ("request_started_ns", "body_received_ns", "response_started_ns",
                                          "headers_written_ns", "handler_finished_ns")]
        assert all(type(value) is int and value > 0 for value in times) and times == sorted(times)


def check_attempt(folder: Path, attempt: dict, entry: dict, kind: str, arguments: list,
                  lane: str, stage: str) -> None:
    """Agreement alone cannot hide a wrong caller, codec, return or witness."""
    observed, execution, language = attempt["observation"], attempt["execution"], entry["language"]
    assert observed["fixture"] == {"status": "ready"} and not observed["gaps"]
    if kind == "sequence":
        check_sequence(observed, language, arguments)
    else:
        result = expected_result(language, kind, arguments, lane, stage)
        assert observed["before"] == observed["after"] == graph(language, kind, arguments)
        assert observed["outcome"] == {"kind": "return", "graph": graph(language, kind, arguments, result)}
    assert execution["capture_complete"] and execution["termination"] == {"kind": "exit", "code": 0}
    assert execution["channels"] == {"stdout": [], "stderr": []}
    if lane == "instrumented_on":
        witness, calls = execution["witness"], 2 if kind == "sequence" else 1
        assert witness["functions"] == {entry["otelc_function"]: calls} and witness["spans"] == calls
        assert witness["pending"] == 0 and not any(witness["losses"].values())
    else:
        assert execution["witness"] is None
    assert json.loads((folder / "typed-observation.json").read_text()) == observed
    assert (folder / "stdout").read_bytes() == (folder / "stderr").read_bytes() == b""
    check_server_responses(folder, lane)


def check_report(path: Path, stage: str) -> tuple[str, set[str]]:
    report = json.loads(path.read_text())
    assert report["source_preserved"] and not report["blocked"] and len(report["cases"]) == 1
    case = report["cases"][0]
    entry = next(item for item in report["inventory"] if item["otelc_function"] == case["function"])
    kind, language = kind_of(entry), entry["language"]
    index = int(case["case"].rsplit("-", 1)[1])
    arguments = arguments_for(language, kind)[index]
    assert case["case"].rsplit("-", 1)[0] == entry["id"] and case["arguments"] == arguments
    if kind in ("integer", "float", "sequence"):
        assert entry["input_preconditions"] == [LESS]
    assert case["exit_code"] == report["exit_code"] == int(kind == "probe")
    parent = path.parent / case["case"]
    bundle = json.loads((parent / "typed-bundle.json").read_text())["cases"][0]
    expectation = {"kind": "return_value", "value": scalar("python", 1)} if kind == "text" else {"kind": "return"}
    assert bundle["contract"]["expected_baseline"] == expectation
    attempts = set()
    for lane in ("baseline", "instrumented_on"):
        assert len(bundle[lane]) == 2
        for index, attempt in enumerate(bundle[lane]):
            folder = parent / (lane + "-" + str(index))
            check_attempt(folder, attempt, entry, kind, arguments, lane, stage)
            attempts.add(str(folder.resolve()))
    assert len(attempts) == 4
    return case["case"], attempts


def check_suite(stdout: Path, stage: str, *, preflight: bool = False) -> tuple[Path, set[str]]:
    """Account for each concrete case once across actual unittest replay reports."""
    records = [json.loads(line) for line in stdout.read_text().splitlines()]
    workspace = Path(records[0]["workspace"])
    assert records[0]["claim"] == "equivalence over these tests and observations"
    data = json.loads((workspace / "plan.json").read_text())
    ready = [entry for entry in data["inventory"] if entry["status"] == "ready"]
    assert not any(entry["status"] == "blocked" for entry in data["inventory"])
    functions, count = (4, 5) if preflight else STAGES[stage]
    assert len(ready) == functions and len(records) == count + 1
    expected_kinds = {"sequence", "text"} if preflight else {"integer", "float", "sequence", "text"}
    if stage in ("added", "different"):
        expected_kinds.add("added")
    if stage == "different":
        expected_kinds.add("probe")
    assert {kind_of(entry) for entry in ready} == expected_kinds
    assert {entry["language"] for entry in ready} == (SEQUENCES | {"python"} if preflight else set(LANGUAGES))
    corpus = json.loads((workspace / "tests/corpus.json").read_text())
    assert len(corpus) == count
    expected = {case["id"] for case in corpus}
    cases, attempts = set(), set()
    for record in records[1:]:
        case, observed = check_report(Path(record["report"]), stage)
        assert case not in cases and attempts.isdisjoint(observed)
        cases.add(case)
        attempts |= observed
    assert cases == expected and len(attempts) == count * 4
    return workspace, attempts
