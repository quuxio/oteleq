"""Independent fixed sources and full graph oracles for domain generation."""
import json
from pathlib import Path
import struct

from node_project_oracle import number, object_node
from qualify_returns import LANGUAGES, scalar

DOMAINS = {
    "integer": {"kind": "integer", "minimum": 7, "maximum": 9},
    "boolean": {"kind": "boolean"},
    "float": {"kind": "float", "minimum": 0.1, "maximum": 0.3},
    "string": {"kind": "string", "minimum_length": 0, "maximum_length": 2, "alphabet": "a\u03bb"},
    "probe": {"kind": "integer", "minimum": 0, "maximum": 32},
}
STRING_LANGUAGES = {"python", "java", "javascript", "typescript", "go"}


def kinds(language: str) -> list[str]:
    result = ["integer", "boolean", "float"]
    if language in STRING_LANGUAGES:
        result.append("string")
    if language == "python":
        result.append("probe")
    return result


def source(language: str) -> tuple[str, str]:
    """Identity targets expose the complete actual argument as their result."""
    if language in ("c", "cpp"):
        boolean = "_Bool" if language == "c" else "bool"
        return "app." + language, ("int domain_integer(int value){return value;}\n"
            + boolean + " domain_boolean(" + boolean + " value){return value;}\n"
            + "float domain_float(float value){return value;}\n")
    if language == "rust":
        return "app.rs", ("fn domain_integer(value:i32)->i32{value}\n"
            "fn domain_boolean(value:bool)->bool{value}\nfn domain_float(value:f32)->f32{value}\n")
    if language == "go":
        return "app.go", ("package main\nfunc domain_integer(value int)int{return value}\n"
            "func domain_boolean(value bool)bool{return value}\n"
            "func domain_float(value float32)float32{return value}\n"
            "func domain_string(value string)string{return value}\n")
    if language == "java":
        return "App.java", ("class App {\nstatic int domain_integer(int value){return value;}\n"
            "static boolean domain_boolean(boolean value){return value;}\n"
            "static float domain_float(float value){return value;}\n"
            "static String domain_string(String value){return value;}\n}\n")
    if language == "python":
        active = '"quux.otelc" in (sys.monitoring.get_tool(0),sys.monitoring.get_tool(1),sys.monitoring.get_tool(2),sys.monitoring.get_tool(3),sys.monitoring.get_tool(4),sys.monitoring.get_tool(5))'
        return "app.py", ("import sys\ndef domain_integer(value:int)->int:return value\n"
            "def domain_boolean(value:bool)->bool:return value\n"
            "def domain_float(value:float)->float:return value\n"
            "def domain_string(value:str)->str:return value\n"
            "def domain_probe(value:int)->int:return int(value>=7 and (" + active + "))\n")
    annotation = {"integer": "number", "boolean": "boolean", "float": "number", "string": "string"}
    text = ""
    for kind in kinds(language):
        suffix = ":" + annotation[kind] if language == "typescript" else ""
        text += "function domain_" + kind + "(value" + suffix + ")" + suffix + "{return value;}\n"
    return "app." + ("ts" if language == "typescript" else "js"), text


def arguments(language: str, kind: str) -> list:
    """Literal expected pools never invoke the sampler under qualification."""
    if kind == "integer":
        return [7, 9, 8]
    if kind == "boolean":
        return [False, True]
    if kind == "string":
        return ["", "aa", "\u03bb\u03bb"]
    if kind == "probe":
        return [0, 32, 16]
    if language in ("c", "cpp", "rust", "go", "java"):
        return [struct.unpack(">f", bytes.fromhex(bits))[0] for bits in ("3dcccccd", "3e999999", "3e4ccccc")]
    return [0.1, 0.3, 0.2]


def typed(language: str, kind: str, value) -> dict:
    """Declare the qualified scalar labels and exact payloads independently."""
    if kind in ("integer", "probe"):
        return scalar(language, int(value))
    if kind == "boolean":
        labels = {"c": "c._Bool", "cpp": "cpp.bool", "rust": "rust.bool", "python": "python.bool",
                  "java": "java.lang.Boolean", "go": "go.bool"}
        return {"kind": "boolean", "type": labels.get(language, language + ".boolean"), "value": value}
    if kind == "float":
        labels = {"c": "c.float", "cpp": "cpp.float", "rust": "rust.f32", "python": "python.float64",
                  "java": "java.float", "go": "go.float32"}
        width = ">d" if language in ("python", "javascript", "typescript") else ">f"
        return {"kind": "float", "type": labels.get(language, language + ".float64"),
                "bits": struct.pack(width, value).hex()}
    encoding = {"python": "codepoints32_be", "go": "raw_bytes"}.get(language, "utf16_be")
    codec = {"codepoints32_be": "utf-32-be", "raw_bytes": "utf-8", "utf16_be": "utf-16-be"}[encoding]
    return {"kind": "string", "type": "java.lang.String" if language == "java" else language + ".string",
            "encoding": encoding, "value": value.encode(codec).hex()}


def graph(language: str, kind: str, value, *, returned=False, lane="baseline") -> dict:
    before = {"roots": {}, "nodes": []}
    if language == "python":
        before = {"roots": {"arguments": {"kind": "reference", "node_id": "n0"}},
                  "nodes": [{"id": "n0", "type": "python.builtins.list",
                             "fields": {"item:0": typed(language, kind, value)}}]}
    if language in ("javascript", "typescript"):
        before = {"roots": {"arguments": {"kind": "reference", "node_id": "n0"}},
                  "nodes": [object_node(language, "n0", "ecmascript.array.prototype:Array",
                             {"0": typed(language, kind, value), "length": number(language, 1)}, array=True)]}
    if returned:
        outcome = int(value >= 7 and lane == "instrumented_on") if kind == "probe" else value
        before["roots"]["result"] = typed(language, kind, outcome)
    return before


def kind_of(entry: dict) -> str:
    matches = [kind for kind in kinds(entry["language"]) if "domain_" + kind in entry["name"]]
    assert len(matches) == 1, entry["name"]
    return matches[0]


def check_attempt(folder: Path, attempt: dict, entry: dict, kind: str, value, lane: str) -> None:
    """Check full values, process completion, raw files and real instrumentation."""
    language = entry["language"]
    observed, execution = attempt["observation"], attempt["execution"]
    assert observed["fixture"] == {"status": "ready"} and not observed["gaps"]
    assert observed["before"] == observed["after"] == graph(language, kind, value)
    assert observed["outcome"] == {"kind": "return", "graph": graph(language, kind, value, returned=True, lane=lane)}
    assert execution["capture_complete"] and execution["termination"] == {"kind": "exit", "code": 0}
    assert execution["channels"] == {"stdout": [], "stderr": []}
    if lane == "instrumented_on":
        witness = execution["witness"]
        assert witness["functions"] == {entry["otelc_function"]: 1}
        assert witness["spans"] == 1 and witness["pending"] == 0 and not any(witness["losses"].values())
    else:
        assert execution["witness"] is None
    assert json.loads((folder / "typed-observation.json").read_text()) == observed
    assert (folder / "stdout").read_bytes() == (folder / "stderr").read_bytes() == b""


def check_report(path: Path, *, count: int, expected_arguments: list | None = None) -> set[str]:
    """Check every complete fixed graph, raw channel and selected-function witness."""
    report = json.loads(path.read_text())
    assert report["source_preserved"] and not report["blocked"] and len(report["cases"]) == count
    inventory = {entry["otelc_function"]: entry for entry in report["inventory"]}
    attempts = set()
    for case in report["cases"]:
        entry = inventory[case["function"]]
        language, kind = entry["language"], kind_of(entry)
        assert case["case"].rsplit("-", 1)[0] == entry["id"]
        index = int(case["case"].rsplit("-", 1)[1])
        value = (arguments(language, kind) if expected_arguments is None else expected_arguments)[index]
        assert case["arguments"] == [value]
        assert case["exit_code"] == int(kind == "probe" and value >= 7)
        parent = path.parent / case["case"]
        bundle = json.loads((parent / "typed-bundle.json").read_text())["cases"][0]
        assert bundle["contract"]["expected_baseline"] == {"kind": "return"}
        for lane in ("baseline", "instrumented_on"):
            assert len(bundle[lane]) == 2
            for index, attempt in enumerate(bundle[lane]):
                folder = parent / (lane + "-" + str(index))
                check_attempt(folder, attempt, entry, kind, value, lane)
                attempts.add(str(folder.resolve()))
    assert len(attempts) == count * 4
    assert report["exit_code"] == max(case["exit_code"] for case in report["cases"])
    return attempts
