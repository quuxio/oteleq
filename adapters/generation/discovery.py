"""Source inventories via compiler/runtime ASTs. No regex callable discovery."""
import ast
import json
from pathlib import Path
import sys

import cpp_models
from otelc_capture import native_flags

NATIVE_METADATA_BYTES = 64 * 1024 * 1024

LANGUAGES = {".c": "c", ".h": "c", ".cc": "cpp", ".cpp": "cpp", ".cxx": "cpp", ".hpp": "cpp", ".hh": "cpp", ".hxx": "cpp", ".rs": "rust",
             ".py": "python", ".java": "java", ".js": "javascript", ".mjs": "javascript",
             ".cjs": "javascript", ".jsx": "javascript", ".ts": "typescript", ".mts": "typescript", ".cts": "typescript", ".tsx": "typescript", ".go": "go"}
IGNORED = {".git", "target", "node_modules", ".venv", "__pycache__", "build", "dist"}
ANONYMOUS = "<anonymous>"


def contains_yield(node):
    pending = list(node.body)
    while pending:
        child = pending.pop()
        if isinstance(child, (ast.Yield, ast.YieldFrom)):
            return True
        if not isinstance(child, (ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef, ast.Lambda)):
            pending.extend(ast.iter_child_nodes(child))
    return False


def ordinary_python_method(node, kinds, parameters):
    """Receiver fixtures cover ordinary positional synchronous class functions."""
    args = node.args
    return (kinds == ("class",) and bool(parameters) and not node.decorator_list
            and not args.vararg and not args.kwarg and not args.kwonlyargs
            and not isinstance(node, ast.AsyncFunctionDef) and not contains_yield(node))


def python_function(node, scope, kinds=(), class_roots=()):
    args = node.args
    annotations = [ast.unparse(p.annotation) if p.annotation else "dynamic"
                   for p in (*args.posonlyargs, *args.args)]
    reason = ""
    if scope or node.decorator_list or args.vararg or args.kwarg or args.kwonlyargs:
        reason = "method, nested, decorated or variadic callable needs a fixture"
    if isinstance(node, ast.AsyncFunctionDef) or contains_yield(node):
        reason = "async or generator callable needs a scheduler fixture"
    result = {"name": ".".join((*scope, node.name)), "line": node.lineno, "column": node.col_offset,
            "parameters": annotations, "output": ast.unparse(node.returns) if node.returns else "dynamic", "reason": reason}
    ordinary = ordinary_python_method(node, kinds, annotations)
    if ordinary and node.name == "__init__":
        result["python_constructor_parameters"] = annotations[1:]
    elif ordinary and not node.name.startswith("__"):
        result.update(parameters=annotations[1:], python_receiver_class=scope[0],
                      python_class_roots=list(class_roots),
                      reason="instance method requires a receiver fixture")
    return result


def assignment_targets(node):
    if isinstance(node, ast.Assign):
        return list(node.targets)
    if isinstance(node, (ast.AnnAssign, ast.For, ast.AsyncFor)):
        return [node.target]
    return []


def python_globals(tree):
    globals_ = {}
    pending = list(tree.body)
    while pending:
        node = pending.pop(0)
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef, ast.Lambda)):
            continue
        for target in assignment_targets(node):
            name = target.id if isinstance(target, ast.Name) else "<destructured>"
            globals_[name] = {"name": name, "type": "dynamic"}
        pending.extend(ast.iter_child_nodes(node))
    return list(globals_.values())


def python_inventory(source):
    tree = ast.parse(source)
    functions = []

    def visit(node, scope=(), kinds=(), class_roots=()):
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
            functions.append(python_function(node, scope, kinds, class_roots))
            scope = (*scope, node.name)
            kinds = (*kinds, "function")
        elif isinstance(node, ast.ClassDef):
            class_roots = python_globals(node)
            scope = (*scope, node.name)
            kinds = (*kinds, "class")
        elif isinstance(node, ast.Lambda):
            functions.append({"name": ".".join((*scope, "<lambda>")), "line": node.lineno, "column": node.col_offset,
                              "parameters": [], "output": "unknown", "reason": "lambda needs a capture fixture"})
        for child in ast.iter_child_nodes(node):
            visit(child, scope, kinds, class_roots)
    visit(tree)
    return {"functions": functions, "globals": python_globals(tree), "parser": "Python ast " + sys.version.split()[0]}


def native_origin(location, path):
    if location.get("includedFrom") or "offset" not in location:
        return False
    return not location.get("file") or Path(location["file"]).resolve() == path.resolve()


def native_function(node, scope, inside):
    kind, name = node["kind"], node.get("name", ANONYMOUS)
    location = node.get("loc", {})
    params = [n["type"]["qualType"] for n in node.get("inner", []) if n["kind"] == "ParmVarDecl"]
    body = any(n["kind"] in ("CompoundStmt", "CXXTryStmt") for n in node.get("inner", []))
    reason = "" if kind == "FunctionDecl" and body and not inside else "method, lambda or external callable needs a fixture"
    if node.get("variadic"):
        reason = "variadic callable needs an argument fixture"
    return {"name": "::".join((*scope, name)), "line": location.get("line", 1), "column": location.get("col", 1),
            "declaration_only": kind == "FunctionDecl" and not body, "parameters": params,
            "output": node.get("type", {}).get("qualType", "unknown").split(" (")[0],
            "reason": reason, "symbol": node.get("mangledName", name),
            "source_offset": location.get("offset", -1), "native_kind": kind}


def native_inventory(document, path, *, cpp=False):
    functions, globals_ = [], []
    callable_kinds = {"FunctionDecl", "CXXMethodDecl", "CXXConstructorDecl", "CXXDestructorDecl", "LambdaExpr"}

    def visit(node, scope=(), inside=False):
        kind, name = node.get("kind"), node.get("name", ANONYMOUS)
        original = native_origin(node.get("loc", {}), path)
        if kind in ("NamespaceDecl", "CXXRecordDecl") and name != ANONYMOUS:
            scope = (*scope, name)
        if kind == "FunctionTemplateDecl":
            inside = True
        if kind in callable_kinds:
            if original:
                functions.append(native_function(node, scope, inside))
            inside = True
        if kind == "VarDecl" and original and not inside:
            globals_.append({"name": "::".join((*scope, name)), "type": node.get("type", {}).get("qualType", "unknown")})
        if kind == "VarDecl" and original and inside and (node.get("storageClass") == "static" or node.get("tls")):
            globals_.append({"name": "<static-local:" + "::".join((*scope, name)) + "@" + str(node["loc"]["offset"]) + ">",
                             "type": node.get("type", {}).get("qualType", "unknown"), "inaccessible": True})
        for child in node.get("inner", []):
            visit(child, scope, inside)
    visit(document)
    result = {"functions": functions, "globals": globals_, "parser": "Clang AST JSON"}
    if cpp:
        models = cpp_models.Inventory(document, path).export()
        source = path.read_bytes()
        bindings = {(item["source_offset"], item["kind"], item["symbol"]): item for item in models["cpp_functions"]}
        for function in functions:
            key = (function["source_offset"], function["native_kind"], function["symbol"])
            if key in bindings:
                function["cpp_function"] = bindings[key]
                function["name"] = bindings[key]["name"]
                function["declaration_only"] = not bindings[key]["has_body"]
                function["parameters"] = bindings[key]["parameters"]
                function["output"] = bindings[key]["output"]
                offset = function["source_offset"]
                function["line"] = source.count(b"\n", 0, offset) + 1
                function["column"] = offset - source.rfind(b"\n", 0, offset)
        result.update(models)
        result["globals"] = ([{"name": name, "type": type_} for name, type_ in models["cpp_globals"].items()]
                             + [item for item in globals_ if item.get("inaccessible")])
    return result


def discover(path, language, root, tools, execute):
    here = Path(__file__).parent
    if language == "python":
        return python_inventory(path.read_text())
    if language == "rust":
        import os
        command = [os.environ["OTELEQ_EXECUTABLE"], "inventory-rust", path]
    elif language in ("c", "cpp"):
        compiler = tools["clang++" if language == "cpp" else "clang"]
        command = [compiler, *native_flags(language), "-Xclang", "-ast-dump=json", "-fsyntax-only", path]
    elif language in ("javascript", "typescript"):
        command = [tools[language], here / "discover.mjs", root]
    elif language == "go":
        command = [tools[language], "run", here / "discover.go", "--", path]
    else:
        command = [tools[language], here / "Discover.java", path]
    if language in ("javascript", "typescript"):
        document = json.dumps({"filename": str(path), "source": path.read_text()}).encode()
        result = execute(command, path.parent, input_data=document)
    elif language in ("c", "cpp"):
        result = execute(command, path.parent, max_output_bytes=NATIVE_METADATA_BYTES)
    else:
        result = execute(command, path.parent)
    if result.returncode:
        raise ValueError("inventory tool failed: " + result.stderr.decode(errors="replace")[-2000:])
    data = json.loads(result.stdout)
    inventory = native_inventory(data, path, cpp=language == "cpp") if language in ("c", "cpp") else data
    if language == "cpp" and "cpp-demangler" in tools:
        cpp_models.bind_symbols(inventory, tools["cpp-demangler"], path.parent, execute)
    return inventory
