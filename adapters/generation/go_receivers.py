"""Bind declared Go factories to compiler-resolved source storage."""
from collections.abc import Callable
from pathlib import PurePosixPath


def require(condition: bool, reason: str) -> None:
    """Keep incomplete source/factory/storage bindings as visible blockers."""
    if not condition:
        raise ValueError("Go receiver fixture: " + reason)


def fields(model: dict, package: str) -> list[str]:
    """Require the complete ordered source struct declaration."""
    require(set(model) == {"kind", "name", "fields"}
            and type(model["name"]) is str and model["name"].isidentifier(), "unbound struct name")
    values = model["fields"]
    require(type(values) is list and len(values) <= 256, "struct field budget exceeded")
    names, children = set(), []
    for field in values:
        require(type(field) is dict and set(field) == {"name", "type", "embedded", "package", "tag_hex"},
                "invalid source field declaration")
        name, tag = field["name"], field["tag_hex"]
        require(type(name) is str and name.isidentifier() and name != "_" and name not in names,
                "missing, duplicate or blank source field")
        require(type(field["embedded"]) is bool and field["package"] in ("", package),
                "field source package or embedding differs")
        require(type(tag) is str and len(tag) <= 8192 and bytes.fromhex(tag).hex() == tag,
                "invalid source field tag")
        names.add(name)
        children.append(field["type"])
    return children


def children(model: dict, package: str) -> list[str]:
    """Only declared passive storage participates in the initial Go codec."""
    kind = model.get("kind")
    if kind in ("boolean", "string"):
        require(set(model) == {"kind"}, "unexpected primitive declaration")
    elif kind == "integer":
        require(set(model) == {"kind", "bits", "signed"}
                and type(model["bits"]) is int and model["bits"] in (8, 16, 32, 64)
                and type(model["signed"]) is bool, "invalid integer storage")
    elif kind == "float":
        require(set(model) == {"kind", "bits"} and type(model["bits"]) is int
                and model["bits"] in (32, 64), "invalid float storage")
    elif kind == "pointer":
        require(set(model) == {"kind", "element"}, "invalid pointer storage")
        return [model["element"]]
    elif kind == "array":
        require(set(model) == {"kind", "element", "length"}
                and type(model["length"]) is int and 0 <= model["length"] <= 4096,
                "array declaration exceeds its bound")
        return [model["element"]]
    elif kind == "struct":
        return fields(model, package)
    else:
        raise ValueError("Go receiver fixture: " + str(model.get("reason", "unsupported storage")))
    return []


def storage(models: dict, roots: list[str], package: str) -> dict:
    """Collect a bounded recursive type graph; unrelated package types stay out."""
    selected, pending = {}, list(roots)
    while pending:
        name = pending.pop()
        require(type(name) is str and 0 < len(name) <= 1024, "invalid declared type identity")
        if name in selected or name == "void":
            continue
        require(name in models and type(models[name]) is dict, "missing compiler-resolved storage: " + name)
        require(len(selected) < 512, "type observation budget exceeded")
        model = models[name]
        nested = children(model, package)
        if model["kind"] == "struct":
            require(name == package + "." + model["name"], "struct source identity differs")
        selected[name] = model
        pending.extend(nested)
    return selected


def bind(entry: dict, discovered: dict, declaration: dict, concrete: Callable) -> None:
    """Freeze a same-package factory and exact receiver/argument/global storage."""
    require("go_context" in entry and entry.get("go_receiver")
            and entry["reason"] in ("", "instance method requires a receiver fixture")
            and not entry.get("go_variadic"), "requires an ordinary semantic source method")
    models, context = discovered["go_types"], entry["go_context"]
    package, receiver = context["import_path"], entry["go_receiver"]
    require(receiver in models, "receiver storage is unavailable")
    owner = models[receiver].get("element") if models[receiver]["kind"] == "pointer" else receiver
    require(owner in models and models[owner]["kind"] == "struct", "requires a named source struct receiver")
    root = "*" + owner
    candidates = [item for item in discovered["go_functions"] if item["name"] == declaration["factory"]]
    require(len(candidates) == 1, "factory requires one unique source function")
    factory = candidates[0]
    require(not factory["reason"] and not factory.get("go_receiver") and not factory.get("go_variadic")
            and factory.get("go_result") == root, "factory must return the exact source struct pointer")
    filename = factory["go_source"]
    require(type(filename) is str and PurePosixPath(filename).name == filename and filename.endswith(".go"),
            "factory source file binding differs")
    parameters, result = entry.get("go_parameters"), entry.get("go_result")
    require(type(parameters) is list and len(parameters) == len(entry["parameters"])
            and type(result) is str, "method signature is incomplete or has multiple results")
    arguments = concrete({"language": "go", "parameters": factory["parameters"]}, declaration["arguments"])
    globals_ = discovered["go_global_types"]
    require(set(globals_) == {item["name"] for item in entry["globals"]}, "package global storage differs")
    roots = {"receiver": root, **{"argument:" + str(i): name for i, name in enumerate(parameters)},
             **{"global:" + name: type_ for name, type_ in globals_.items()}}
    selected = storage(models, [*roots.values(), result, *factory["go_parameters"]], package)
    source = str(PurePosixPath(context["directory"]) / filename)
    entry.update(receiver_class=models[owner]["name"], go_receiver_type=root, go_models=selected,
                 go_root_types=roots, receiver_configuration=declaration,
                 receiver_fixture={"factory": factory["name"], "kind": "function", "line": factory["line"],
                                   "source_function": source.removesuffix(".go").replace("/", ".") + "." + factory["name"],
                                   "source_path": source, "arguments": arguments,
                                   "arguments_requested": declaration["arguments"], "argument_types": factory["parameters"]},
                 reason="")
