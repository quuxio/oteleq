"""Bind ordinary source C++ receiver factories and private diagnostic access."""
from collections.abc import Callable
import re

import cpp_models


HELPER_NAMESPACE = "__oteleq_cpp"


def require(condition: bool, reason: str) -> None:
    """Unsupported storage/construction remains a named fixture gap."""
    if not condition:
        raise ValueError("C++ receiver fixture: " + reason)


def record_shape(record: dict) -> None:
    """No unions, inherited/native layouts, macro fields or bit-field address tricks."""
    require(record["physical"] and record["tag"] in ("class", "struct") and not record["bases"]
            and not record["polymorphic"], "requires an ordinary physical source class without bases or virtual storage")
    fields = record["fields"]
    require(len(fields) <= 256 and all(field["name"].isidentifier() and field["physical"]
            and not field["bitfield"] for field in fields), "source fields need complete addressable declarations")


def type_graph(types: list[str], records: dict) -> dict:
    """Only passive, bounded source storage enters the initial native registry."""
    selected, pending = {}, list(types)
    while pending:
        name = pending.pop()
        if name in selected or name == "void":
            continue
        require(type(name) is str and 0 < len(name) <= 1024 and len(selected) < 512,
                "type observation budget exceeded")
        require("volatile" not in name.split(), "volatile storage needs a separate observation contract")
        if name.startswith("const "):
            selected[name] = {"kind": "qualified", "element": name[6:]}
            pending.append(name[6:])
        elif name in cpp_models.BUILTINS:
            kind = "boolean" if name == "bool" else "float" if name in ("float", "double") else "integer"
            selected[name] = {"kind": kind}
        elif name.endswith((" *", " &")):
            element = name[:-2]
            selected[name] = {"kind": "pointer" if name.endswith(" *") else "reference", "element": element}
            require(element != "void", "void pointers need an explicit buffer view")
            pending.append(element)
        elif cpp_models.ARRAY.fullmatch(name):
            array = cpp_models.ARRAY.fullmatch(name)
            require(0 < int(array[2]) <= 4096, "array storage exceeds its bound")
            element = array[1] + array[3]
            selected[name] = {"kind": "array", "element": element, "length": int(array[2])}
            pending.append(element)
        else:
            require(name in records, "opaque or foreign storage: " + name)
            record = records[name]
            record_shape(record)
            selected[name] = {"kind": "record", "fields": record["fields"]}
            pending.extend(field["canonical"] for field in record["fields"])
    return selected


def complete_constructor(record: dict, constructor: dict) -> None:
    """Own scalar slots must be initialised before the observer can read them."""
    require(not constructor["deleted"] and not constructor["delegated"] and constructor["has_body"],
            "requires an ordinary complete source constructor")
    initialised = set(constructor["initialised_fields"])
    missing = [field["name"] for field in record["fields"]
               if not field["in_class_initialiser"] and field["name"] not in initialised]
    require(not missing, "constructor leaves unobserved initialisation for: " + ", ".join(missing))


def bind(entry: dict, discovered: dict, declaration: dict, concrete: Callable) -> dict:
    """Freeze existing constructor/factory inputs and exact source-owned storage."""
    method = entry.get("cpp_function", {})
    require(method.get("kind") == "CXXMethodDecl" and method.get("has_body") and not method.get("static")
            and not method.get("nested") and not method.get("deleted") and not method.get("variadic"),
            "requires an ordinary source instance method")
    owner, records = method["owner"], discovered["cpp_records"]
    require(owner in records, "receiver source definition is unavailable")
    record = records[owner]
    record_shape(record)
    constructor = declaration["factory"] in (owner, owner.rsplit("::", 1)[-1])
    if constructor:
        candidates = [item for item in record["constructors"] if not item["implicit"] and not item["deleted"]]
        require(len(candidates) == 1, "constructor requires one unique existing source declaration")
        factory = candidates[0]
        complete_constructor(record, factory)
        factory_name = owner
    else:
        candidates = [item for item in discovered["cpp_functions"] if item["name"] == declaration["factory"]
                      and (item["kind"] == "FunctionDecl" or item["kind"] == "CXXMethodDecl" and item["static"] and item["owner"] == owner)
                      and item["has_body"] and not item["nested"]]
        require(len(candidates) == 1, "factory requires one unique ordinary source function")
        factory = candidates[0]
        require(factory["output"] == owner and not factory["variadic"], "factory must return the exact source class by value")
        factory_name = factory["name"]
        for item in record["constructors"]:
            if not item["implicit"]:
                complete_constructor(record, item)
    parameters = {"language": "cpp", "parameters": factory["parameters"]}
    arguments = concrete(parameters, declaration["arguments"])
    roots = [owner, method["output"], *method["parameters"]]
    # Every declared package/static root remains required. The graph contract
    # binds private static fields through their owning source access helper.
    globals_ = []
    for item in entry["globals"]:
        require(not item.get("inaccessible"), "function-local static storage needs a separate access fixture")
        name = item["name"]
        parent, _, leaf = name.rpartition("::")
        static = next((field for field in records.get(parent, {}).get("statics", []) if field["name"] == leaf), None)
        type_ = static["canonical"] if static else discovered["cpp_globals"][name]
        globals_.append({"name": name, "type": type_, "owner": parent if static else ""})
        roots.append(type_)
    selected = type_graph(roots, records)
    observed_records = {name: records[name] for name, model in selected.items() if model["kind"] == "record"}
    for item in globals_:
        if item["owner"]:
            observed_records[item["owner"]] = records[item["owner"]]
            record_shape(records[item["owner"]])
    return {"owner": owner, "method": method, "types": selected, "records": observed_records,
            "globals": globals_, "factory": {"kind": "constructor" if constructor else "function", "name": factory_name,
            "parameters": factory["parameters"], "arguments": arguments, "arguments_requested": declaration["arguments"]},
            "memory_precondition": "factory/target storage and pointer pointees must be live and initialised; arbitrary C++ memory validity is not inferred"}


def private_source(source: str, records: dict) -> str:
    """Add friend access in the private copy without changing fields or layout."""
    raw = source.encode()
    require(HELPER_NAMESPACE not in source, "reserved helper name collides with application source")
    for name, record in sorted(records.items(), key=lambda item: item[1]["body_end"], reverse=True):
        offset = record["body_end"]
        require(record["physical"] and raw[offset:offset+1] == b"}", "class source range differs")
        friend = ("\nfriend struct ::" + HELPER_NAMESPACE + "::access<::" + name + ">;\n").encode()
        raw = raw[:offset] + friend + raw[offset:]
    return raw.decode()


def sanitise_identifiers(contract: dict) -> str:
    """Application macros must not replace a generated access with a callback."""
    identifiers = {"int", "short", "long", "unsigned", "signed", "char", "float", "double", "bool", "const",
                   "template", "class", "struct", "static", "return", "auto", "void", "typename", "decltype"}
    names = [*contract["records"], contract["factory"]["name"], contract["method"]["name"]]
    names.extend(field["name"] for item in contract["records"].values() for field in [*item["fields"], *item["statics"]])
    for name in names:
        identifiers.update(re.findall(r"[A-Za-z_][A-Za-z0-9_]*", name))
    return "\n".join("#undef " + name for name in sorted(identifiers)) + "\n"
