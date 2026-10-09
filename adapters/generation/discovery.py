"""Source inventories via compiler/runtime ASTs. No regex callable discovery."""
import ast
import json
from pathlib import Path
import sys

LANGUAGES = {".c": "c", ".h": "c", ".cc": "cpp", ".cpp": "cpp", ".cxx": "cpp", ".hpp": "cpp", ".hh": "cpp", ".hxx": "cpp", ".rs": "rust",
             ".py": "python", ".java": "java", ".js": "javascript", ".mjs": "javascript",
             ".cjs": "javascript", ".jsx": "javascript", ".ts": "typescript", ".mts": "typescript", ".cts": "typescript", ".tsx": "typescript", ".go": "go"}
IGNORED = {".git", "target", "node_modules", ".venv", "__pycache__", "build", "dist"}


def python_inventory(source):
    tree = ast.parse(source)
    functions, globals_ = [], []

    def visit(node, scope=()):
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
            args = node.args
            annotations = [ast.unparse(p.annotation) if p.annotation else "dynamic"
                           for p in (*args.posonlyargs, *args.args)]
            reason = ""
            if scope or node.decorator_list or args.vararg or args.kwarg or args.kwonlyargs:
                reason = "method, nested, decorated or variadic callable needs a fixture"
            pending = list(node.body)
            yielded = False
            while pending:
                child = pending.pop()
                yielded |= isinstance(child, (ast.Yield, ast.YieldFrom))
                if not isinstance(child, (ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef, ast.Lambda)):
                    pending.extend(ast.iter_child_nodes(child))
            if isinstance(node, ast.AsyncFunctionDef) or yielded:
                reason = "async or generator callable needs a scheduler fixture"
            functions.append({"name": ".".join((*scope, node.name)), "line": node.lineno, "column": node.col_offset,
                              "parameters": annotations, "output": ast.unparse(node.returns) if node.returns else "dynamic", "reason": reason})
            scope = (*scope, node.name)
        elif isinstance(node, ast.ClassDef):
            scope = (*scope, node.name)
        elif isinstance(node, ast.Lambda):
            functions.append({"name": ".".join((*scope, "<lambda>")), "line": node.lineno, "column": node.col_offset,
                              "parameters": [], "output": "unknown", "reason": "lambda needs a capture fixture"})
        for child in ast.iter_child_nodes(node):
            visit(child, scope)
    visit(tree)
    pending = list(tree.body)
    while pending:
        node = pending.pop(0)
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef, ast.Lambda)):
            continue
        targets = node.targets if isinstance(node, ast.Assign) else [node.target] if isinstance(node, ast.AnnAssign) else []
        if isinstance(node, (ast.For, ast.AsyncFor)):
            targets.append(node.target)
        for target in targets:
            if isinstance(target, ast.Name):
                globals_.append({"name": target.id, "type": "dynamic"})
            else:
                globals_.append({"name": "<destructured>", "type": "unknown"})
        pending.extend(ast.iter_child_nodes(node))
    globals_ = list({g["name"]: g for g in globals_}.values())
    return {"functions": functions, "globals": globals_, "parser": "Python ast " + sys.version.split()[0]}


def native_inventory(document, path):
    functions, globals_ = [], []

    def visit(node, scope=(), inside=False):
        kind, name = node.get("kind"), node.get("name", "<anonymous>")
        location = node.get("loc", {})
        original = not location.get("includedFrom") and ("offset" in location)
        if location.get("file") and Path(location["file"]).resolve() != path.resolve():
            original = False
        if kind in ("NamespaceDecl", "CXXRecordDecl") and name != "<anonymous>":
            scope = (*scope, name)
        if kind == "FunctionTemplateDecl":
            inside = True
        if kind in ("FunctionDecl", "CXXMethodDecl", "CXXConstructorDecl", "CXXDestructorDecl", "LambdaExpr") and original:
            params = [n["type"]["qualType"] for n in node.get("inner", []) if n["kind"] == "ParmVarDecl"]
            body = any(n["kind"] == "CompoundStmt" for n in node.get("inner", []))
            reason = "" if kind == "FunctionDecl" and body and not inside else "method, lambda or external callable needs a fixture"
            if node.get("variadic"):
                reason = "variadic callable needs an argument fixture"
            functions.append({"name": "::".join((*scope, name)), "line": location.get("line", 1),
                              "column": location.get("col", 1), "declaration_only": kind == "FunctionDecl" and not body,
                              "parameters": params, "output": node.get("type", {}).get("qualType", "unknown").split(" (")[0],
                              "reason": reason, "symbol": node.get("mangledName", name)})
            inside = True
        if kind == "VarDecl" and original and not inside:
            globals_.append({"name": "::".join((*scope, name)), "type": node.get("type", {}).get("qualType", "unknown")})
        for child in node.get("inner", []):
            visit(child, scope, inside)
    visit(document)
    return {"functions": functions, "globals": globals_, "parser": "Clang AST JSON"}


def discover(path, language, root, tools, execute):
    here = Path(__file__).parent
    if language == "python":
        return python_inventory(path.read_text())
    if language == "rust":
        command = [sys.executable]  # Replaced with the pinned CLI syntax parser, never target code.
        import os
        command = [os.environ["OTELEQ_EXECUTABLE"], "inventory-rust", path]
    elif language in ("c", "cpp"):
        compiler = tools["clang++" if language == "cpp" else "clang"]
        command = [compiler, "-Xclang", "-ast-dump=json", "-fsyntax-only", path]
    elif language in ("javascript", "typescript"):
        command = [tools[language], here / "discover.mjs", root, path]
    elif language == "go":
        command = [tools[language], "run", here / "discover.go", "--", path]
    else:
        command = [tools[language], here / "Discover.java", path]
    result = execute(command, path.parent)
    if result.returncode:
        raise ValueError("inventory tool failed: " + result.stderr.decode(errors="replace")[-2000:])
    data = json.loads(result.stdout)
    return native_inventory(data, path) if language in ("c", "cpp") else data
