"""Reproduce the fixed Go call-only helper recipe without importing the SDK."""

import hashlib
import json
from pathlib import Path
import unicodedata
from typing import cast

import go_files as files
from go_provider import require, same

KEYWORDS = set("break default func interface select case defer go map struct chan else goto package switch "
               "const fallthrough if range type continue for import return var".split())


def identifier(value: object) -> bool:
    """Accept Go letters/digits, without allowing metadata to insert source text."""
    if type(value) is not str or not value or value == "_" or value in KEYWORDS:
        return False
    return all(char == "_" or unicodedata.category(char).startswith("L")
               or index > 0 and unicodedata.category(char) == "Nd"
               for index, char in enumerate(value))


def failure(results: object) -> str:
    """Only the compiler profile's literal error predicates can enter a rule."""
    require(type(results) is list and len(results) <= 4096, "invalid Go hook result denominator")
    results = cast(list, results)
    predicates, names = [], set()
    for row in results:
        require(type(row) is dict and set(row) == {"expression", "error", "failure", "pointer"}
                and identifier(row["expression"]) and row["expression"] not in names
                and type(row["error"]) is bool and type(row["pointer"]) is str,
                "invalid Go hook result binding")
        names.add(row["expression"])
        if row["error"]:
            require(row["failure"] in ("true", row["expression"] + " != nil"), "invalid Go hook error predicate")
            predicates.append(row["failure"])
        else:
            require(row["failure"] == "", "non-error Go result has an error predicate")
    return " || ".join(predicates) or "false"


def helper(package: str, prefix: str, digest: str) -> bytes:
    """Keep bootstrap, selection guard and probe bridge byte-for-byte fixed."""
    return (f"package {package}\nimport (\n"
            f' {prefix}probe "io.quux.otelc/go/probe"\n'
            f' {prefix}official "go.opentelemetry.io/otelc/pkg/runtime"\n'
            f' {prefix}owned "io.quux.otelc/go/runtime"\n)\n'
            f"var {prefix}Runtime = func()*{prefix}owned.Runtime {{\n"
            f" value,err:={prefix}owned.FromEnvironment({prefix}official.ContextWithImplicitTelemetry,{prefix}official.DetachSpanFromGLS)\n"
            " if err!=nil{panic(err)}\n"
            f' if value.Config.SelectionSHA256!={json.dumps(digest)}{{panic("Go runtime differs from compiled selection")}}\n'
            " return value\n}()\n"
            f"func {prefix}Track[T any](value *T,id int)*T{{\n"
            f" {prefix}probe.Track({prefix}Runtime.Probes,value,id);return value\n}}\n"
            f"func {prefix}Release[T any](value *T,success bool){{{prefix}probe.Release({prefix}Runtime.Probes,value,success)}}\n").encode()


def package_bindings(inventory: dict, module: str) -> dict:
    """Bind every generated package to its declared source directory."""
    packages = inventory["packages"]
    require(type(packages) is dict and bool(packages) and len(packages) <= files.MAX_FILES,
            "missing Go hook package bindings")
    for name, fact in packages.items():
        require(type(name) is str and type(fact) is dict and set(fact) == {"name", "directory"}
                and identifier(fact["name"]), "invalid Go hook package binding")
        directory = fact["directory"]
        if directory != ".":
            files.relative(directory)
        require(name == module + ("/" + directory if directory != "." else ""),
                "Go hook package differs from its source directory")
    return packages


def callable_binding(row: dict, packages: dict) -> tuple[dict, str]:
    """Validate callable spelling and storage before emitting source text."""
    require(type(row["package"]) is str and row["package"] in packages and identifier(row["symbol"]),
            "invalid Go hook callable binding")
    fact = packages[row["package"]]
    require(Path(row["file"]).parent.as_posix() == fact["directory"], "Go hook callable differs from package directory")
    receiver = row["receiver_id"]
    require(type(receiver) is str and (not receiver or identifier(receiver.removeprefix("*"))),
            "invalid Go hook receiver")
    expected_name = row["package"] + "." + (receiver.removeprefix("*") + "." if receiver else "") + row["symbol"]
    require(row["name"] == expected_name, "Go hook callable name differs from symbol/receiver")
    return fact, receiver


def injection(row: dict, selected: dict, prefix: str, finish: bool, package: dict) -> list[str]:
    """Keep shutdown ordering and selected invocation indices explicit."""
    code = []
    if finish:
        require(package["name"] == "main" and type(row["parameters"]) is int
                and row["parameters"] == 0 and same(row["results"], []),
                "invalid Go main shutdown binding")
        code.append("defer " + prefix + "Runtime.Close()")
    if row["name"] in selected:
        predicate = failure(row["results"])
        code += [f"{prefix}Invocation := {prefix}Runtime.Probes.Start({selected[row['name']]})",
                 "defer func(){" + prefix + "Invocation.End(" + predicate + ")}()"]
    return code


def rule(row: dict, main: str, receiver: str, index: int, code: list[str]) -> str:
    """Serialise checked callable bindings with the fixed injected code."""
    target = "main" if row["package"] == main else row["package"]
    result = f"rule_{index}:\n  target: {json.dumps(target)}\n  where:\n    func: {json.dumps(row['symbol'])}\n"
    if receiver:
        result += "    recv: " + json.dumps(receiver) + "\n"
    return result + "  do:\n    - inject_code:\n        raw: |\n" + "".join("          " + line + "\n" for line in code)


def generated(selection: dict, inventory: dict, module: str) -> dict[str, bytes]:
    """Derive all additions for the explicit synchronous, no-context hook profile."""
    require(same(selection["context"], {"tasks": False, "http": False})
            and all(same(selection[name], []) for name in ("types", "allocations", "releases")),
            "unsupported Go generated hook profile")
    digest = selection["sha256"]
    require(type(digest) is str and len(digest) == 64 and all(char in "0123456789abcdef" for char in digest),
            "invalid Go hook selection digest")
    prefix = "__otelc_" + digest[:12] + "_"
    packages = package_bindings(inventory, module)
    selected = {row["name"]: index for index, row in enumerate(selection["functions"])}
    additions, rules, used, mains = {}, [], set(), 0
    for row in inventory["functions"]:
        finish = row["package"] == inventory["main"] and row["symbol"] == "main" and row["receiver_id"] == ""
        if row["name"] not in selected and not finish:
            continue
        fact, receiver = callable_binding(row, packages)
        code = injection(row, selected, prefix, finish, fact)
        rules.append(rule(row, inventory["main"], receiver, len(rules), code))
        mains += int(finish)
        used.add(row["package"])
    require(mains == 1, "Go hooks require one main shutdown binding")
    for package in sorted(used):
        fact = packages[package]
        path = Path(fact["directory"]) / ("zz_otelc_" + digest[:12] + ".go")
        additions[path.as_posix()] = helper(fact["name"], prefix, digest)
    additions["otelc_rules/doc.go"] = b"package rules\n"
    additions["otelc_rules/otelc.yaml"] = "\n".join(rules).encode()
    imports = [module + "/otelc_rules", "go.opentelemetry.io/otelc/instrumentation/runtime",
               "go.opentelemetry.io/otelc/instrumentation/go.opentelemetry.io/otel/sdk/trace"]
    additions["otel.instrumentation.go"] = ("//go:build tools\n\npackage tools\nimport (\n"
                                           + "".join(" _ " + json.dumps(name) + "\n" for name in imports) + ")\n").encode()
    return additions


def verify(original: files.Snapshot, private: files.Snapshot, selection: dict,
           inventory: dict, module: str) -> None:
    """A rehashed manifest cannot admit changed helpers or additional private code."""
    expected = generated(selection, inventory, module)
    require(not any((original.root / name).exists() or (original.root / name).is_symlink()
                    for name in ("otelc_rules", "otel.instrumentation.go", "otelc.tool.go"))
            and not set(expected) & set(original.identities), "Go generated helpers collide with original inputs")
    prefix = ("__otelc_" + selection["sha256"][:12] + "_").encode()
    for name in inventory["files"]:
        require(prefix not in files.file(original.root / name, keep=True)[2], "Go hook identifier collides with original source")
    require(set(private.identities) == set(original.identities) | set(expected) | {"go.sum"},
            "Go private file denominator differs from generated recipe")
    for name, data in expected.items():
        actual = private.identities[name]
        require(actual["size"] == len(data) and actual["sha256"] == hashlib.sha256(data).hexdigest(),
                "Go generated helper differs from independent recipe: " + name)
