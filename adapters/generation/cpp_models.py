"""Freeze C++ source declarations and passive storage from Clang's checked AST."""
import re
import sys
from pathlib import Path


BUILTINS = {"bool", "char", "signed char", "unsigned char", "short", "unsigned short", "int", "unsigned int",
            "long", "unsigned long", "long long", "unsigned long long", "float", "double", "void"}
ARRAY = re.compile(r"([^\[\]]+)\[(\d+)\]((?:\[\d+\])*)$", re.ASCII)
FUNCTION_KINDS = {"FunctionDecl", "CXXMethodDecl", "CXXConstructorDecl", "CXXDestructorDecl"}


def bind_symbols(inventory: dict, demangler: Path, directory: Path, execute) -> None:
    """Use the selected LLVM tool's actual ABI names, including cv/ref qualifiers."""
    functions = inventory["cpp_functions"]
    symbols = sorted({item["symbol"] for item in functions if item["symbol"]})
    if not symbols:
        return
    if any(any(char.isspace() for char in symbol) for symbol in symbols):
        raise ValueError("C++ symbol contains invalid framing")
    # AST linkage names carry Mach-O's prefix; LLVM IR names do not. cxxfilt's
    # strip option leaves unmangled C names unchanged, so normalise before it.
    ir_symbols = [symbol.removeprefix("_") if sys.platform == "darwin" else symbol for symbol in symbols]
    result = execute([demangler, "--no-strip-underscore"], directory, input_data=("\n".join(ir_symbols) + "\n").encode())
    names = result.stdout.decode("utf-8", errors="strict").splitlines()
    unmangled = {item["symbol"] for item in functions if (item["symbol"].removeprefix("_") if sys.platform == "darwin" else item["symbol"]) == item["name"].rsplit("::", 1)[-1]}
    unresolved = any(original not in unmangled and symbol.startswith("_Z") and name == symbol
                     for original, symbol, name in zip(symbols, ir_symbols, names))
    if result.returncode or len(names) != len(symbols) or unresolved or any(not name or len(name) > 4096 for name in names):
        raise ValueError("C++ compiler symbol resolution failed")
    identities = dict(zip(symbols, names))
    for item in functions:
        if item["symbol"] in identities:
            item["compiler_identity"] = identities[item["symbol"]]


def physical(location: dict, path: Path) -> bool:
    """Macro and foreign declarations cannot supply private source edit ranges."""
    return ("offset" in location and not location.get("includedFrom")
            and not location.get("spellingLoc") and not location.get("expansionLoc")
            and (not location.get("file") or Path(location["file"]).resolve() == path.resolve()))


def signature(node: dict) -> dict:
    """Keep checked spellings separately from their underlying scalar domains."""
    parameters = [item["type"] for item in node.get("inner", []) if item["kind"] == "ParmVarDecl"]
    function = node.get("type", {}).get("qualType", "unknown")
    output, separator, tail = function.partition("(")
    depth, qualifiers = 1, ""
    for index, char in enumerate(tail):
        depth += (char == "(") - (char == ")")
        if depth == 0:
            qualifiers = tail[index+1:].strip()
            break
    return {"parameters": [item.get("desugaredQualType", item["qualType"]) for item in parameters],
            "parameter_spellings": [item["qualType"] for item in parameters],
            "output": output.strip() if separator else "unknown", "function_type": function,
            "qualifiers": qualifiers,
            "variadic": bool(node.get("variadic"))}


def constructor(node: dict) -> dict:
    """A missing field initialiser remains visible, including delegated construction."""
    initialisers = [item for item in node.get("inner", []) if item["kind"] == "CXXCtorInitializer"]
    return {**signature(node), "symbol": node.get("mangledName", ""),
            "implicit": bool(node.get("isImplicit")), "deleted": bool(node.get("explicitlyDeleted")),
            "initialised_fields": [item["anyInit"]["name"] for item in initialisers if item.get("anyInit")],
            "delegated": any("delegatingInit" in item for item in initialisers),
            "has_body": any(item["kind"] == "CompoundStmt" for item in node.get("inner", []))}


def record(node: dict, name: str, path: Path) -> dict:
    """Retain ordered fields, access, statics and the exact physical closing brace."""
    access = "private" if node.get("tagUsed") == "class" else "public"
    fields, statics, constructors = [], [], []
    for item in node.get("inner", []):
        kind = item["kind"]
        if kind == "AccessSpecDecl":
            access = item["access"]
        elif kind in ("FieldDecl", "VarDecl"):
            type_ = item.get("type", {})
            member = {"name": item.get("name", ""), "type": type_.get("qualType", "unknown"),
                      "canonical": type_.get("desugaredQualType", type_.get("qualType", "unknown")),
                      "access": access, "in_class_initialiser": bool(item.get("hasInClassInitializer")),
                      "bitfield": bool(item.get("isBitfield")), "mutable": bool(item.get("mutable")),
                      "physical": physical(item.get("loc", {}), path)}
            (fields if kind == "FieldDecl" else statics).append(member)
        elif kind == "CXXConstructorDecl":
            constructors.append(constructor(item))
    end = node.get("range", {}).get("end", {})
    return {"kind": "record", "name": name, "tag": node.get("tagUsed"), "fields": fields,
            "statics": statics, "constructors": constructors,
            "bases": [item.get("type", {}).get("qualType", "unknown") for item in node.get("bases", [])],
            "polymorphic": bool(node.get("definitionData", {}).get("isPolymorphic")),
            "aggregate": bool(node.get("definitionData", {}).get("isAggregate")),
            "trivially_copyable": bool(node.get("definitionData", {}).get("isTriviallyCopyable")),
            "physical": physical(node.get("loc", {}), path) and physical(end, path),
            "body_end": end.get("offset", -1), "source_offset": node.get("loc", {}).get("offset", -1)}


class Inventory:
    """A checked translation unit supplies nominal scopes; no callable regexes."""

    def __init__(self, document: dict, path: Path) -> None:
        self.path = path
        self.records: dict[str, dict] = {}
        self.aliases: dict[str, str] = {}
        self.contexts: dict[str, tuple[str, ...]] = {}
        self.functions: dict[tuple[int, str, str], dict] = {}
        self.globals: dict[str, dict] = {}
        self.collect(document)

    def collect(self, node: dict, scope: tuple[str, ...] = (), inside: bool = False) -> None:
        """Resolve out-of-line method owners through compiler declaration contexts."""
        kind, name = node.get("kind"), node.get("name", "")
        original = physical(node.get("loc", {}), self.path)
        scope = self.contexts.get(node.get("parentDeclContextId"), scope)
        if kind in ("NamespaceDecl", "CXXRecordDecl") and name and not node.get("isImplicit"):
            scope = (*scope, name)
            self.contexts[node["id"]] = scope
        qualified = "::".join(scope)
        if original and kind == "CXXRecordDecl" and node.get("completeDefinition"):
            self.records[qualified] = record(node, qualified, self.path)
        if original and kind in ("TypeAliasDecl", "TypedefDecl"):
            type_ = node.get("type", {})
            self.aliases["::".join((*scope, name))] = type_.get("desugaredQualType", type_.get("qualType", "unknown"))
        if original and kind == "VarDecl" and not inside and not node.get("tls"):
            type_ = node.get("type", {})
            self.globals["::".join((*scope, name))] = {"scope": "::".join(scope),
                    "type": type_.get("desugaredQualType", type_.get("qualType", "unknown"))}
        if original and kind in FUNCTION_KINDS:
            self.collect_function(node, scope, inside)
        nested = inside or kind in FUNCTION_KINDS or kind in ("FunctionTemplateDecl", "ClassTemplateDecl")
        for child in node.get("inner", []):
            # Local classes need a separate lifetime and construction profile.
            if nested and child.get("kind") in ("CXXRecordDecl", "ClassTemplateDecl"):
                continue
            self.collect(child, scope, nested)

    def collect_function(self, node: dict, scope: tuple[str, ...], inside: bool) -> None:
        """Retain one checked declaration, including distinct implicit overloads."""
        kind = node["kind"]
        key = (node["loc"]["offset"], kind, node.get("mangledName", ""))
        self.functions[key] = {**signature(node), "owner": "::".join(scope) if kind != "FunctionDecl" else "",
                "name": "::".join((*scope, node.get("name", ""))), "kind": kind,
                "static": node.get("storageClass") == "static", "implicit": bool(node.get("isImplicit")),
                "nested": inside,
                "deleted": bool(node.get("explicitlyDeleted")), "symbol": node.get("mangledName", ""),
                "source_offset": node["loc"]["offset"],
                "has_body": any(item["kind"] in ("CompoundStmt", "CXXTryStmt") for item in node.get("inner", []))}
        if kind == "CXXConstructorDecl":
            self.functions[key]["construction"] = constructor(node)

    def resolve(self, text: str, scope: str, seen: frozenset[str] = frozenset()) -> str:
        """Resolve checked scalar aliases and named source records lexically."""
        text = " ".join(text.split())
        if text in BUILTINS:
            return text
        if text.startswith("const "):
            return "const " + self.resolve(text[6:], scope, seen)
        for suffix in (" &&", " &", " *"):
            if text.endswith(suffix):
                return self.resolve(text[:-len(suffix)], scope, seen) + suffix
        array = ARRAY.fullmatch(text)
        if array:
            return self.resolve(array[1], scope, seen) + "[" + array[2] + "]" + array[3]
        namespaces = scope.split("::") if scope else []
        for count in range(len(namespaces), -1, -1):
            name = "::".join([*namespaces[:count], text.removeprefix("::")]) if not text.startswith("::") else text[2:]
            if name in self.records:
                return name
            if name in self.aliases and name not in seen:
                return self.resolve(self.aliases[name], "::".join(name.split("::")[:-1]), seen | {name})
        return text

    def export(self) -> dict:
        """Physical offsets and source type identities stay frozen in the plan."""
        for name, item in self.records.items():
            for declared in item["constructors"]:
                definitions = [function["construction"] for function in self.functions.values()
                               if function["kind"] == "CXXConstructorDecl" and function["symbol"] == declared["symbol"]
                               and function["has_body"]]
                if len(definitions) == 1:
                    declared.update(definitions[0])
                declared["parameters"] = [self.resolve(value, name) for value in declared["parameters"]]
            for field in [*item["fields"], *item["statics"]]:
                field["canonical"] = self.resolve(field["canonical"], name)
        for item in self.functions.values():
            scope = item["owner"] or "::".join(item["name"].split("::")[:-1])
            item["parameters"] = [self.resolve(value, scope) for value in item["parameters"]]
            item["output"] = self.resolve(item["output"], scope)
        globals_ = {name: self.resolve(item["type"], item["scope"]) for name, item in self.globals.items()}
        return {"cpp_records": self.records, "cpp_functions": list(self.functions.values()), "cpp_globals": globals_}
