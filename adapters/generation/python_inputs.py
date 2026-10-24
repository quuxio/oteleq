"""Freeze rebuilt Python tooling and the selected installed SDK input scope."""

import hashlib
import os
from pathlib import Path
import stat
import sys
import sysconfig

import otelc_capture as capture

MAX_FILES = 100000
MAX_BYTES = 4 * 1024 ** 3
REQUIRED = {"otelc/prepared_python.py", "otelc/python_recipe.py",
            "otelc/python_supervisor.py", "otelc/python_launch_files.py",
            "otelc/python_health.py", "otelc/cli_bootstrap.py"}
NATIVE_SOURCES = {"CodeCapture.c", "EntryCapture.c", "ImportCapture.c",
                  "InputJournal.c", "InputJournal.h", "NativeMain.c"}


def require(condition: bool, reason: str) -> None:
    """An incomplete installed scope must remain a visible provider failure."""
    if not condition:
        raise ValueError("Python prepared inputs: " + reason)


def dependency_roots(python: Path) -> list[Path]:
    """Derive wheel paths without processing .pth files or importing SDK code."""
    require(python == Path(sys.executable).absolute(),
            "selected interpreter must retain the current host/venv spelling")
    prefix = python.parent.parent
    paths = (sysconfig.get_paths(scheme="venv", vars={"base": str(prefix), "platbase": str(prefix)})
             if (prefix / "pyvenv.cfg").is_file() else sysconfig.get_paths())
    return list(dict.fromkeys(Path(paths[key]) for key in ("purelib", "platlib")))


def walk_error(error: OSError) -> None:
    """Unreadable directories cannot become an empty successful inventory."""
    raise error


def builder_inputs(root: Path) -> list[Path]:
    """Freeze the fixed builder and its optional maintained encoder dependency.

    This inventories input bytes only. Presence of the helper does not select
    an execution profile or establish native/source-origin qualification.
    """
    helpers = (root / "ci/native_encoder.py", root / "ci/native_origin_chain.py")
    return [root / "ci/build_python_inputs.py", *[path for path in helpers if path.exists() or path.is_symlink()]]


def files(root: Path, *, suffixes: set[str] | None = None) -> list[Path]:
    """Bytecode caches are outside the declared scope; linked trees are refused."""
    require(root.is_dir() and not root.is_symlink(), "missing or linked directory: " + str(root))
    result = []
    for directory, names, leaves in os.walk(root, onerror=walk_error):
        for name in names:
            require(not (Path(directory) / name).is_symlink(), "linked input directory")
        names[:] = sorted(name for name in names if name != "__pycache__")
        for name in sorted(leaves):
            path = Path(directory) / name
            if path.suffix in (".pyc", ".pyo") or suffixes is not None and path.suffix not in suffixes:
                continue
            result.append(path)
            require(len(result) <= MAX_FILES, "input file count exceeds the declared budget")
    return result


def catalogue(paths: list[tuple[str, Path, Path]]) -> dict[str, str]:
    """Retain bytes and literal internal file links, within fixed total bounds."""
    require(len(paths) <= MAX_FILES, "input file count exceeds the declared budget")
    result, total = {}, 0
    for name, path, root in paths:
        metadata = path.lstat()
        require(stat.S_ISREG(metadata.st_mode) or stat.S_ISLNK(metadata.st_mode),
                "non-regular input: " + name)
        if stat.S_ISLNK(metadata.st_mode):
            require(path.resolve(strict=True).is_relative_to(root.resolve(strict=True)),
                    "input file link escapes its declared root: " + name)
            result["link-target:" + name] = hashlib.sha256(os.fsencode(os.readlink(path))).hexdigest()
        resolved = path.stat()
        require(stat.S_ISREG(resolved.st_mode), "input link must name a regular file: " + name)
        total += resolved.st_size
        require(total <= MAX_BYTES, "input bytes exceed the declared budget")
        result[name] = capture.file_digest(path)
    return result


def artefacts(root: Path, tools: dict[str, Path]) -> dict[str, str]:
    """Hash maintained sources, prebuilt native tools and actual installed bytes.

    This scope excludes interpreter/OS libraries and general application import
    closure. It records .pth as data; isolated SDK startup must not execute it.
    """
    require(root.is_dir() and not root.is_symlink(), "provider root must be a real directory")
    python = tools["python"]
    roots = dependency_roots(python)
    selected = [root / name for name in ("bin/quux-otelc", "requirements.txt", "requirements-dev.txt")]
    selected += builder_inputs(root)
    selected += files(root / "otelc", suffixes={".py"})
    selected += files(root / "native/python", suffixes={".c", ".h"})
    products = files(root / "build/tools/python-inputs")
    selected += products
    names = {path.relative_to(root).as_posix() for path in selected}
    require(REQUIRED <= names, "incomplete public prepared Python API")
    require({"native/python/" + name for name in NATIVE_SOURCES} <= names, "incomplete native Python observer sources")
    product_names = {path.name for path in products}
    require({"otelc-python-inputs", "build.json"} <= product_names
            and any(name in product_names for name in ("libotelc_python_inputs.so", "libotelc_python_inputs.dylib")),
            "missing prebuilt native observer products")
    paths = [(path.relative_to(root).as_posix(), path, root) for path in selected]
    for installed in roots:
        paths.extend(("installed:" + str(installed) + ":" + path.relative_to(installed).as_posix(), path, installed)
                     for path in files(installed))
    result = catalogue(paths)
    for name, tool in tools.items():
        result["tool:" + name] = capture.file_digest(tool)
        if tool.is_symlink():
            result["tool-link:" + name] = hashlib.sha256(os.fsencode(os.readlink(tool))).hexdigest()
    return result
