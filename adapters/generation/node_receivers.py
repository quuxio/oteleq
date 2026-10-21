"""Declare and materialise private JavaScript/TypeScript class receiver callers."""
import json
from pathlib import Path
import posixpath
import node_project


def factory(entry: dict, discovered: dict, name: str) -> tuple[dict, str]:
    """Resolve a source constructor or one ordinary synchronous factory function."""
    constructor = name == entry["node_receiver_class"]
    qualified = name + ".constructor" if constructor else name
    matches = [item for item in discovered["functions"] if item["name"] == qualified]
    if constructor and not matches:
        return {"name": name, "line": 0, "source_function": None, "parameters": []}, "constructor"
    if len(matches) != 1:
        raise ValueError("Node receiver factory requires one unique source declaration")
    source = matches[0]
    if constructor and "node_constructor_parameters" in source:
        return {"name": name, "line": source["line"], "source_function": qualified,
                "parameters": source["node_constructor_parameters"]}, "constructor"
    if not constructor and not source["reason"] and not source.get("async"):
        return {"name": name, "line": source["line"], "source_function": qualified,
                "parameters": source["parameters"]}, "function"
    raise ValueError("Node receiver factory requires a source constructor or ordinary synchronous function")


def driver(entry: dict, arguments: list, source: str, sequence: list | None = None) -> str:
    """Capture class bindings before original static initialisers can change them."""
    owner = entry["node_receiver_class"]
    method = entry["name"].rsplit(".", 1)[-1]
    helper = posixpath.relpath("_oteleq_generated/node_observe.mjs", str(Path(entry["path"]).parent))
    helper = helper if helper.startswith(".") else "./" + helper
    fixture = entry["receiver_fixture"]
    factory_name = fixture["factory"] if fixture["kind"] == "function" else "undefined"
    commonjs = node_project.commonjs(entry)
    observer = ("const __oteleqObserver=require(" + json.dumps(helper) + ");" if commonjs
                else "import * as __oteleqObserver from " + json.dumps(helper) + ";")
    bootstrap = ";" + observer + "let __oteleqClass;const __oteleqFactory=" + factory_name + ";\n"
    if sequence is not None:
        sequence_helper = helper.replace("node_observe.mjs", "node_sequence.mjs")
        bootstrap += ("const __oteleqSequence=require(" + json.dumps(sequence_helper) + ");\n" if commonjs
                      else "import * as __oteleqSequence from " + json.dumps(sequence_helper) + ";\n")
    metadata = {"label": entry["node_class_label"], "owner": owner,
                "methods": entry["node_class_methods"],
                "statics": [item["name"] for item in entry["node_class_roots"]]}
    capture = " static{__oteleqClass=__oteleqObserver.captureClass(this," + json.dumps(metadata) + ");} "
    raw = source.encode()
    insertions = [(entry["binding_capture_offset"], bootstrap), (entry["node_class_capture_offset"], capture)]
    for position, text in sorted(insertions, reverse=True):
        if not 0 <= position <= len(raw):
            raise ValueError("Node receiver capture offset is outside the source")
        raw = raw[:position] + text.encode() + raw[position:]
    globals_ = "".join(json.dumps("global:"+item["name"])+":"+item["name"]+"," for item in entry["globals"])
    valid_binding = owner + "===__oteleqClass.constructor"
    if fixture["kind"] == "function":
        valid_binding += "&&" + factory_name + "===__oteleqFactory"
    invoke = ("__oteleqSequence.runSequence" if sequence is not None else "__oteleqObserver.runReceiver") + "(__oteleqClass,__oteleqCall,__oteleqRoots,()=>" + valid_binding + ")"
    start = "\n;void(async()=>{\n" if commonjs else ""
    finish = "})();\n" if commonjs else ""
    return raw.decode() + start + f'''
const __oteleqArguments={json.dumps(arguments)};
const __oteleqRoots=()=>({{{globals_}arguments:__oteleqArguments}});
const __oteleqCall={{factory:__oteleqFactory,fixture:{json.dumps(fixture)},method:{json.dumps(method)},arguments:__oteleqArguments,asynchronous:{str(bool(entry.get("async"))).lower()},sequence:{json.dumps(sequence)}}};
await {invoke};
''' + finish


def prototype_label(entry: dict) -> str:
    """Only the selected frozen source class can receive a declared prototype tag."""
    return "declared:" + entry["node_class_label"]
