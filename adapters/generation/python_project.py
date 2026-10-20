"""Resolve explicit Python source import roots without executing application code."""
import keyword
from pathlib import Path, PurePosixPath


def import_roots(value: object) -> list[str]:
    """Keep import paths distinct, canonical and inside the private source tree."""
    if not isinstance(value, list) or any(type(item) is not str for item in value):
        raise ValueError("adapters.python.import_roots must be an array of relative paths")
    for item in value:
        path = PurePosixPath(item)
        if (not item or path.is_absolute() or str(path) != item or ".." in path.parts
                or "\\" in item or ":" in item):
            raise ValueError("Python import roots require canonical source-relative paths")
    if len(value) != len(set(value)):
        raise ValueError("Python import roots must be distinct")
    return value.copy()


def child_source(directory: Path, name: str) -> Path | None:
    """Follow regular source-package precedence over an identically named module."""
    for candidate in (directory / name / "__init__.py", directory / (name + ".py")):
        if candidate.is_file():
            return candidate
    return None


def module_source(snapshot: Path, roots: list[str], parts: list[str]) -> Path | None:
    """A regular package selected in one root cannot fall through to another root."""
    source = next((candidate for root in roots
                   if (candidate := child_source(snapshot / root, parts[0])) is not None), None)
    for name in parts[1:]:
        if source is None or source.name != "__init__.py":
            return None
        source = child_source(source.parent, name)
    return source


def context(snapshot: Path, path: str, roots: list[str]) -> dict:
    """Bind one selected source to its real import name and regular package chain."""
    target = Path(path)
    matches = [root for root in roots if target.is_relative_to(root)]
    if len(matches) != 1:
        raise ValueError("Python source must match exactly one configured import root")
    relative = target.relative_to(matches[0]).with_suffix("")
    parts = list(relative.parts)
    if parts[-1] == "__init__":
        parts.pop()
    if not parts or any(not part.isidentifier() or keyword.iskeyword(part) for part in parts):
        raise ValueError("Python source requires a valid importable module name")
    resolved = module_source(snapshot, roots, parts)
    if resolved is None or resolved != snapshot / target:
        raise ValueError("Python source is shadowed or requires an unsupported namespace/package import context")
    return {"module": ".".join(parts), "roots": roots.copy()}


def loader(context_: dict) -> str:
    """Recheck actual import resolution before executing the selected module."""
    return f'''sys.path[:0] = [str((Path.cwd() / root).resolve()) for root in {context_["roots"]!r}]
spec = importlib.util.find_spec({context_["module"]!r})
if spec is None or spec.origin is None or Path(spec.origin).resolve() != target.resolve():
    raise RuntimeError("configured Python import resolved to a different source")
module = importlib.import_module({context_["module"]!r})
if Path(vars(module).get("__file__", "")).resolve() != target.resolve():
    raise RuntimeError("imported Python module has a different source")
'''
