"""Independent fixed sources and complete numeric-precondition boundary oracles."""
import json
from pathlib import Path
import struct

from node_project_oracle import number, object_node, reference
from qualify_java_receivers import integer as java_integer
from qualify_returns import LANGUAGES, scalar

LESS = {"left": 0, "operator": "<", "right": 1}
INTEGER = {"kind": "integer", "minimum": 7, "maximum": 9}
FLOAT = {"kind": "float", "minimum": 0.1, "maximum": 0.3}
PROBE = {"kind": "integer", "minimum": 0, "maximum": 32}
SEQUENCES = {"java", "javascript", "typescript"}
NAMES = {"integer": "numeric_span", "float": "numeric_float", "probe": "numeric_probe", "sequence": "Meter.numeric_step"}
CASES = 54


def float_pool(language: str) -> list[float]:
    """Literal bits are independent of the domain sampler and target encoders."""
    if language in ("c", "cpp", "rust", "java", "go"):
        return [struct.unpack(">f", bytes.fromhex(bits))[0] for bits in ("3dcccccd", "3e999999", "3e4ccccc")]
    return [0.1, 0.3, 0.2]


def kinds(language: str) -> list[str]:
    return ["integer", "float"] + (["probe"] if language == "python" else []) + (["sequence"] if language in SEQUENCES else [])


def pairs(language: str, kind: str) -> list[list]:
    if kind == "probe":
        return [[0, 32], [0, 16], [16, 32]]
    if kind == "integer":
        return [[7, 9], [7, 8], [8, 9]]
    low, high, middle = float_pool(language)
    return [[low, high]] if kind == "sequence" else [[low, high], [low, middle], [middle, high]]


def integer_source(language: str) -> str:
    """A guarded injective result identifies both integer arguments in this domain."""
    invalid = "start<7||start>9||end<7||end>9||start>=end"
    if language == "rust":
        return "fn numeric_span(start:i32,end:i32)->i32{if " + invalid + "{-1}else{start*100+end}}\n"
    if language == "python":
        return "def numeric_span(start:int,end:int)->int:return start*100+end if 7<=start<end<=9 else -1\n"
    prefix = {"c": "int numeric_span(int start,int end)", "cpp": "int numeric_span(int start,int end)",
              "java": "static int numeric_span(int start,int end)", "go": "func numeric_span(start int,end int)int",
              "javascript": "function numeric_span(start,end)", "typescript": "function numeric_span(start:number,end:number):number"}[language]
    conditional = "if " + invalid + "{return -1};" if language == "go" else "if(" + invalid + ")return -1;"
    return prefix + "{" + conditional + "return start*100+end;}\n"


def floating_source(language: str) -> str:
    """Only the three independently fixed bit pairs can return a positive code."""
    if language in ("c", "cpp"):
        declarations = "const float low=0x1.99999ap-4f,high=0x1.333332p-2f,middle=0x1.999998p-3f;"
        prefix = "int numeric_float(float start,float end){"
    elif language == "rust":
        declarations = "let low=f32::from_bits(0x3dcccccd);let high=f32::from_bits(0x3e999999);let middle=f32::from_bits(0x3e4ccccc);"
        return "fn numeric_float(start:f32,end:f32)->i32{" + declarations + "if start==low&&end==high{1}else if start==low&&end==middle{2}else if start==middle&&end==high{3}else{-1}}\n"
    elif language == "go":
        declarations = "low:=math.Float32frombits(0x3dcccccd);high:=math.Float32frombits(0x3e999999);middle:=math.Float32frombits(0x3e4ccccc);"
        return "func numeric_float(start float32,end float32)int{" + declarations + "if start==low&&end==high{return 1};if start==low&&end==middle{return 2};if start==middle&&end==high{return 3};return -1}\n"
    elif language == "python":
        return "def numeric_float(start:float,end:float)->int:\n if start==0.1 and end==0.3:return 1\n if start==0.1 and end==0.2:return 2\n if start==0.2 and end==0.3:return 3\n return -1\n"
    elif language == "java":
        declarations = "float low=Float.intBitsToFloat(0x3dcccccd),high=Float.intBitsToFloat(0x3e999999),middle=Float.intBitsToFloat(0x3e4ccccc);"
        prefix = "static int numeric_float(float start,float end){"
    else:
        declarations = "const low=0.1,high=0.3,middle=0.2;"
        prefix = "function numeric_float(start:number,end:number):number{" if language == "typescript" else "function numeric_float(start,end){"
    return prefix + declarations + "if(start==low&&end==high)return 1;if(start==low&&end==middle)return 2;if(start==middle&&end==high)return 3;return -1;}\n"


def source(language: str) -> tuple[str, str]:
    body = integer_source(language) + floating_source(language)
    if language == "java":
        return "App.java", "class App{\n" + body + "}\nclass Meter{private int total;private Meter(int start){total=start;}int numeric_step(float start,float end){total+=App.numeric_float(start,end);return total;}}\n"
    if language == "go":
        return "app.go", 'package main\nimport "math"\n' + body
    if language == "python":
        active = '"quux.otelc" in (sys.monitoring.get_tool(0),sys.monitoring.get_tool(1),sys.monitoring.get_tool(2),sys.monitoring.get_tool(3),sys.monitoring.get_tool(4),sys.monitoring.get_tool(5))'
        return "app.py", "import sys\n" + body + "def numeric_probe(start:int,end:int)->int:return int(end>=7 and (" + active + "))\n"
    if language in ("javascript", "typescript"):
        annotation = ":number" if language == "typescript" else ""
        field = "total:number;" if annotation else ""
        body += "class Meter{" + field + "constructor(start" + annotation + "){this.total=start;}numeric_step(start" + annotation + ",end" + annotation + ")" + annotation + "{this.total+=numeric_float(start,end);return this.total;}}\n"
        return "app." + ("mts" if annotation else "mjs"), body
    return "app." + ("rs" if language == "rust" else language), body


def kind_of(entry: dict) -> str:
    matches = [kind for kind, name in NAMES.items() if name in entry["name"]]
    assert len(matches) == 1
    return matches[0]


def argument(language: str, value, *, floating: bool) -> dict:
    if not floating:
        return scalar(language, int(value))
    width = ">f" if language == "java" else ">d"
    label = {"java": "java.float", "python": "python.float64"}.get(language, language + ".float64")
    return {"kind": "float", "type": label, "bits": struct.pack(width, value).hex()}


def plain_graph(language: str, kind: str, arguments: list, result=None) -> dict:
    graph = {"roots": {}, "nodes": []}
    if language == "python":
        graph = {"roots": {"arguments": reference("n0")}, "nodes": [{"id": "n0", "type": "python.builtins.list",
                 "fields": {"item:" + str(index): argument(language, value, floating=kind == "float")
                            for index, value in enumerate(arguments)}}]}
    if language in ("javascript", "typescript"):
        graph = {"roots": {"arguments": reference("n0")}, "nodes": [object_node(language, "n0", "ecmascript.array.prototype:Array",
                 {"0": number(language, arguments[0]), "1": number(language, arguments[1]), "length": number(language, 2)}, array=True)]}
    if result is not None:
        graph["roots"]["result"] = scalar(language, result)
    return graph


def local_reference(graph: dict, name: str) -> dict:
    value = graph["roots"][name]
    assert set(value) == {"kind", "node_id"} and value["kind"] == "reference" and value["node_id"]
    return value


def check_receiver_graph(graph: dict, language: str, arguments: list, total: int, *, returned=False) -> None:
    """Use observed local labels only; every type, root and field is independent."""
    receiver = local_reference(graph, "receiver")
    identity = receiver["node_id"]
    if language == "java":
        roots = {"receiver": receiver, **{"argument:" + str(index): argument(language, value, floating=True)
                                        for index, value in enumerate(arguments)}}
        nodes = [{"id": identity, "type": "java.object:Meter", "fields": {"total": java_integer(total)}}]
    else:
        array = local_reference(graph, "arguments")
        assert array["node_id"] != identity
        roots = {"arguments": array, "receiver": receiver}
        nodes = [object_node(language, array["node_id"], "ecmascript.array.prototype:Array",
                             {"0": number(language, arguments[0]), "1": number(language, arguments[1]), "length": number(language, 2)}, array=True),
                 object_node(language, identity, "ecmascript.object.prototype:declared:" + language + ".app.Meter", {"total": number(language, total)})]
    if returned:
        roots["result"] = java_integer(total) if language == "java" else number(language, total)
    assert set(graph) == {"roots", "nodes"} and graph["roots"] == roots
    assert len(graph["nodes"]) == len(nodes)
    assert {node["id"]: node for node in graph["nodes"]} == {node["id"]: node for node in nodes}


def check_sequence(observed: dict, language: str, arguments: list) -> None:
    low, _, middle = float_pool(language)
    expected = [([low, middle], 10, 12), (arguments, 12, 13)]
    assert len(observed["steps"]) == 2
    for index, (step, (values, before, after)) in enumerate(zip(observed["steps"], expected)):
        assert step["id"] == "step-" + str(index) and step["action"] == "call" and not step["gaps"]
        check_receiver_graph(step["before"], language, values, before)
        check_receiver_graph(step["after"], language, values, after)
        assert step["outcome"]["kind"] == "return"
        check_receiver_graph(step["outcome"]["graph"], language, values, after, returned=True)
    assert observed["before"] == observed["steps"][0]["before"]
    assert observed["after"] == observed["steps"][-1]["after"] and observed["outcome"] == observed["steps"][-1]["outcome"]


def expected_result(language: str, kind: str, arguments: list, lane: str) -> int:
    if kind == "probe":
        return int(arguments[1] >= 7 and lane == "instrumented_on")
    if kind == "integer":
        return int(arguments[0] * 100 + arguments[1])
    return pairs(language, kind).index(arguments) + 1


def check_attempt(folder: Path, attempt: dict, entry: dict, kind: str, arguments: list, lane: str) -> None:
    observed, execution, language = attempt["observation"], attempt["execution"], entry["language"]
    assert observed["fixture"] == {"status": "ready"} and not observed["gaps"]
    if kind == "sequence":
        check_sequence(observed, language, arguments)
    else:
        result = expected_result(language, kind, arguments, lane)
        assert observed["before"] == observed["after"] == plain_graph(language, kind, arguments)
        assert observed["outcome"] == {"kind": "return", "graph": plain_graph(language, kind, arguments, result)}
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


def check_report(path: Path, count: int, override: list | None = None) -> set[str]:
    assert override is None or count == 1
    report = json.loads(path.read_text())
    assert report["source_preserved"] and not report["blocked"] and len(report["cases"]) == count
    entries = {entry["otelc_function"]: entry for entry in report["inventory"]}
    attempts = set()
    for case in report["cases"]:
        entry = entries[case["function"]]
        kind, language = kind_of(entry), entry["language"]
        assert entry["input_preconditions"] == [LESS]
        index = int(case["case"].rsplit("-", 1)[1])
        expected = pairs(language, kind)[index] if override is None else override
        assert case["case"].rsplit("-", 1)[0] == entry["id"] and case["arguments"] == expected
        assert expected[0] < expected[1]
        assert case["exit_code"] == int(kind == "probe" and expected[1] >= 7)
        parent = path.parent / case["case"]
        bundle = json.loads((parent / "typed-bundle.json").read_text())["cases"][0]
        assert bundle["contract"]["expected_baseline"] == {"kind": "return"}
        for lane in ("baseline", "instrumented_on"):
            assert len(bundle[lane]) == 2
            for number_, attempt in enumerate(bundle[lane]):
                folder = parent / (lane + "-" + str(number_))
                check_attempt(folder, attempt, entry, kind, expected, lane)
                attempts.add(str(folder.resolve()))
    assert len(attempts) == count * 4
    assert report["exit_code"] == max(case["exit_code"] for case in report["cases"])
    return attempts
