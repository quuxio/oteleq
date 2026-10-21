"""Freeze declared Java source roots and independent ordered dependency inputs."""
import json
import os
from pathlib import Path, PurePosixPath
import shutil

import java_classpath as classpath

DIRECTORY = "java-context"
CONTEXT_FILE = "java-build-context.json"
PROFILE = "source-classpath-v1"
MAX_ENTRIES = 256


def require(condition: bool, reason: str) -> None:
    if not condition:
        raise ValueError("Java project: " + reason)


def path_list(value: object, label: str, *, relative: bool) -> list[str]:
    """Configuration paths are literal inputs, never JVM options or globs."""
    if not isinstance(value, list):
        raise ValueError("Java project: invalid " + label)
    require(len(value) <= MAX_ENTRIES, "invalid " + label)
    result = []
    for name in value:
        require(type(name) is str and 0 < len(name) <= 4096 and not any(ord(char) < 32 for char in name)
                and "*" not in name and os.pathsep not in name, "invalid " + label + " path")
        if relative:
            path = PurePosixPath(name)
            require(not path.is_absolute() and ".." not in path.parts and "\\" not in name,
                    "source roots must stay inside the selected repository")
            name = str(path)
        require(name not in result, "duplicate " + label + " path")
        result.append(name)
    return result


def settings(value: dict) -> dict:
    """An absent context preserves the qualified standalone compiler recipe."""
    if not {"source_roots", "classpath"} & set(value):
        return {}
    roots = path_list(value.get("source_roots", ["."]), "source_roots", relative=True)
    require(bool(roots), "source_roots must not be empty")
    return {"source_roots": roots, "classpath": path_list(value.get("classpath", []), "classpath", relative=False)}


def source_files(source: Path, options: dict, ignored: set[str]) -> list[str]:
    """Explicit roots include generated Java source without admitting build binaries."""
    result = set()
    for relative in options["source_roots"]:
        root = source / relative
        require(root.is_dir() and root.resolve() == root and root.is_relative_to(source), "missing or linked source root")
        for directory, directories, names in os.walk(root):
            parent = Path(directory)
            require(not any((parent / name).is_symlink() for name in directories + names), "symlink in source root")
            directories[:] = sorted(name for name in directories if name not in ignored)
            for name in names:
                if name.endswith(".java"):
                    path = parent / name
                    require(path.is_file(), "Java source is not a regular file")
                    require(name != "module-info.java", "named Java modules need a separate build profile")
                    result.add(path.relative_to(source).as_posix())
    require(bool(result), "source roots contain no Java units")
    return sorted(result)


def source_manifest(source: Path, options: dict, contents: dict, ignored: set[str]) -> dict:
    """Preserve ordinary snapshot exclusions while retaining explicit generated units."""
    result = dict(contents)
    if "source_roots" in options:
        for name in source_files(source, options, ignored):
            result[name] = classpath.digest(source / name)
    return result


def bind_entry(entry: dict, context: dict | None) -> None:
    """Bind Java callables to the declared source-unit set without hiding blockers."""
    if entry["language"] != "java" or context is None or entry["status"] == "excluded":
        return
    if entry["path"] not in context["source_units"]:
        entry.update(status="blocked", reason="selected Java source is outside declared source roots")
    else:
        entry["java_context_profile"] = PROFILE


def snapshot_exclusions(source: Path, options: dict) -> list[str]:
    """Internal declared JARs use the separate dependency budget and frozen copy."""
    result = set()
    for name in options.get("classpath", []):
        path = Path(os.path.abspath(source / name))
        if path.is_relative_to(source) and path.suffix.lower() == ".jar":
            require(path.resolve(strict=True) == path and not path.is_symlink(), "linked internal JAR")
            result.add(path.relative_to(source).as_posix())
    return sorted(result)


def directories(snapshot: Path, options: dict) -> None:
    """Retain declared empty source roots in the private source copy."""
    for name in options.get("source_roots", []):
        (snapshot / name).mkdir(parents=True, exist_ok=True)


def context_manifest(workspace: Path) -> dict:
    """All context files, including otherwise cache-like names, belong to the seal."""
    return classpath.manifest(workspace / DIRECTORY)


def input_locations(source: Path, options: dict) -> list[Path]:
    """Resolve declared inputs before creating any output below a chosen parent."""
    return [(source / name).resolve(strict=True) for name in options.get("classpath", [])]


def original_locations(data: dict) -> list[Path]:
    """Frozen original paths remain protected even when an export is detached."""
    return [Path(entry["source"]) for entry in data.get("java_context", {}).get("entries", [])]


def protect_destination(destination: Path, locations: list[Path]) -> None:
    """Do not write into dependencies or recursively copy a workspace into itself."""
    require(all(not destination.is_relative_to(path) for path in locations),
            "generated outputs must be outside declared dependencies")


def prepare(source: Path, workspace: Path, options: dict, ignored: set[str]) -> dict | None:
    """Copy existing dependencies without running a build manager in the repository."""
    if "source_roots" not in options:
        return None
    origins = input_locations(source, options)
    protect_destination(workspace, origins)
    require(not any(path.is_relative_to(workspace) for path in origins), "dependency is inside the owned workspace")
    root = workspace / DIRECTORY
    root.mkdir(mode=0o700)
    (root / "classpath").mkdir()
    units = source_files(source, options, ignored)
    entries, names, locations, total = [], set(), set(), 0
    for index, declared in enumerate(options["classpath"]):
        requested = Path(os.path.abspath(source / declared))
        origin = requested.resolve(strict=True)
        require(origin not in locations, "duplicate resolved classpath location")
        locations.add(origin)
        record = classpath.inspect(origin)
        total += sum((origin / name).stat().st_size for name in record["files"]) if record["kind"] == "directory" else origin.stat().st_size
        require(total <= classpath.MAX_TOTAL_BYTES, "combined classpath exceeds its byte budget")
        require(not names.intersection(record["classes"]), "duplicate class definitions in declared classpath")
        names.update(record["classes"])
        owned = "classpath/" + str(index).zfill(4) + (".jar" if record["kind"] == "jar" else "")
        target = root / owned
        if record["kind"] == "jar":
            shutil.copy2(origin, target)
        else:
            shutil.copytree(origin, target)
        require(classpath.inspect(origin) == record and classpath.inspect(target) == record, "dependency changed while freezing")
        entries.append({"requested": str(requested), "source": str(origin), "owned": owned, **record})
    context = {"schema_version": 1, "profile": PROFILE, "source_roots": options["source_roots"],
               "excluded_source_jars": snapshot_exclusions(source, options),
               "source_units": units, "entries": entries}
    raw = json.dumps(context, indent=2) + "\n"
    require(len(raw.encode()) <= 16 * 1024 * 1024, "context metadata exceeds its byte budget")
    (root / "context.json").write_text(raw)
    return context


def verify(workspace: Path, data: dict, *, originals: bool = True) -> None:
    """Original plans guard original inputs; exported plans use their frozen copies."""
    context = data.get("java_context")
    root = workspace / DIRECTORY
    if context is None:
        require(not root.exists(), "unowned Java context")
        require("java" not in data.get("configuration", {}).get("languages", [])
                or "source_roots" not in data["configuration"]["adapters"]["java"], "missing declared Java context")
        return
    require(context_manifest(workspace) == data["java_context_manifest"], "frozen Java context changed")
    require(json.loads((root / "context.json").read_text()) == context, "Java context identity changed")
    options = data["configuration"]["adapters"]["java"]
    require(context["schema_version"] == 1 and context["profile"] == PROFILE
            and context["source_roots"] == options["source_roots"]
            and len(context["entries"]) == len(options["classpath"]), "Java context configuration differs")
    require(source_files(workspace / "snapshot", options, set(data["excluded_directories"])) == context["source_units"],
            "Java source unit set changed")
    for index, entry in enumerate(context["entries"]):
        require(entry["kind"] in ("jar", "directory")
                and entry["owned"] == "classpath/" + str(index).zfill(4) + (".jar" if entry["kind"] == "jar" else ""),
                "invalid owned classpath location")
        expected = {key: entry[key] for key in classpath.RECORD_FIELDS}
        require(classpath.inspect(root / entry["owned"]) == expected, "frozen dependency differs")
        if originals:
            require(Path(entry["requested"]).resolve(strict=True) == Path(entry["source"])
                    and classpath.inspect(Path(entry["source"])) == expected, "original dependency changed")


def materialise(workspace: Path, data: dict, folder: Path, project: Path) -> dict | None:
    """Each attempt receives its own dependency bytes and compiler search paths."""
    context = data.get("java_context")
    if context is None:
        return None
    verify(workspace, data, originals="original_source" not in data)
    root = folder / "java-classpath"
    root.mkdir()
    entries = []
    for entry in context["entries"]:
        original = workspace / DIRECTORY / entry["owned"]
        target = root / Path(entry["owned"]).name
        if entry["kind"] == "jar":
            shutil.copy2(original, target)
        else:
            shutil.copytree(original, target)
        entries.append({"path": str(target), **{key: entry[key] for key in classpath.RECORD_FIELDS}})
    result = {"schema_version": 1, "profile": PROFILE,
              "source_roots": [str(project / name) for name in context["source_roots"]],
              "source_units": [str(project / name) for name in context["source_units"]], "entries": entries}
    (folder / CONTEXT_FILE).write_text(json.dumps(result, indent=2) + "\n")
    verify_attempt(folder, result)
    return result


def verify_attempt(folder: Path, expected: dict) -> None:
    """Neither application code nor retained metadata can replace dependency inputs."""
    require(json.loads((folder / CONTEXT_FILE).read_text()) == expected, "attempt Java context changed")
    for entry in expected["entries"]:
        require(classpath.inspect(Path(entry["path"])) == {key: entry[key] for key in classpath.RECORD_FIELDS},
                "private dependency bytes changed")


def runtime_classpath(classes: Path, context: dict | None) -> list[Path]:
    """The compiled application comes first; metadata cannot choose extra locations."""
    return [classes, *(Path(entry["path"]) for entry in context["entries"])] if context else [classes]


def compiler_options(project: Path, classes: Path, context: dict | None) -> list[str]:
    """Only the host chooses fixed compiler flags and literal private search paths."""
    result = ["-encoding", "UTF-8", "-proc:none", "-implicit:class"]
    if context is None:
        return result + ["-classpath", str(project), "-d", str(classes)]
    roots = os.pathsep.join(context["source_roots"])
    # An empty -classpath means the working directory to javac; use an owned empty directory.
    paths = [entry["path"] for entry in context["entries"]] or [str(classes)]
    return result + ["-sourcepath", roots, "-classpath", os.pathsep.join(paths), "-d", str(classes)]


def classpath_files(classes: Path, context: dict | None) -> set[Path]:
    """Prepared evidence must include every resource byte, not only loaded classes."""
    result = {path for path in classes.rglob("*") if path.is_file()}
    for entry in context["entries"] if context else []:
        path = Path(entry["path"])
        result.update({path} if entry["kind"] == "jar" else {path / name for name in entry["files"]})
    return result
