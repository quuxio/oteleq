"""Freeze actual Clang dependency identities from the matched scanner's JSON."""
import hashlib
import json
import os
from pathlib import Path

from otelc_capture import strict_json

MAX_BYTES = 16 * 1024 * 1024
MAX_FILES = 10000
MAX_ARGUMENTS = 4096
MAX_ARGUMENT_BYTES = 8192


def require(condition: bool, reason: str) -> None:
    """Malformed or incomplete dependency evidence cannot bind a build recipe."""
    if not condition:
        raise ValueError("native dependencies: " + reason)


def dependency_paths(raw: bytes, source: Path, compiler: Path) -> list[str]:
    """Only one ordinary translation unit and no opaque modules are admitted."""
    require(len(raw) <= MAX_BYTES, "dependency output exceeds its budget")
    data = strict_json(raw)
    require(type(data) is dict and set(data) == {"modules", "translation-units"} and data["modules"] == [],
            "modules need a separate dependency recipe")
    units = data["translation-units"]
    require(type(units) is list and len(units) == 1 and type(units[0]) is dict and set(units[0]) == {"commands"},
            "expected one selected translation unit")
    commands = units[0]["commands"]
    require(type(commands) is list and len(commands) == 1 and type(commands[0]) is dict,
            "expected one selected compiler command")
    command = commands[0]
    required = {"clang-context-hash", "clang-module-deps", "command-line", "file-deps", "input-file"}
    require(required <= set(command) and not set(command) - required - {"executable"}, "unsupported scanner command fields")
    require(type(command["input-file"]) is str and Path(command["input-file"]).resolve() == source.resolve(),
            "scanner input differs from the selected source")
    require(command["clang-module-deps"] == [] and type(command["clang-context-hash"]) is str
            and 0 < len(command["clang-context-hash"]) <= 256, "missing context or unexpected module dependencies")
    arguments = command['command-line']
    require(type(arguments) is list and 1 <= len(arguments) <= MAX_ARGUMENTS
            and all(type(item) is str and 0 < len(item) <= MAX_ARGUMENT_BYTES and '\0' not in item
                    for item in arguments),
            "missing scanner frontend arguments")
    if "executable" in command:
        require(type(command["executable"]) is str and Path(command["executable"]).resolve() == compiler.resolve(),
                "scanner selected a different compiler")
    paths = command["file-deps"]
    require(type(paths) is list and 1 <= len(paths) <= MAX_FILES and
            all(type(item) is str and 0 < len(item) <= 8192 and "\0" not in item for item in paths),
            "invalid dependency path set")
    # Repeated includes are legitimate, notably X-macro .def/.inc files and
    # assert headers. Keep the raw scanner output; hash each file identity once.
    return list(dict.fromkeys(paths))


def file_records(names: list[str], project: Path, directory: Path) -> dict:
    """Preserve logical path bindings as well as the bytes at their actual targets."""
    records = {}
    for name in names:
        logical = Path(os.path.abspath(directory / name))
        path = logical.resolve(strict=True)
        require(path.is_file(), "dependency is not a regular file")
        with path.open("rb") as stream:
            sha = hashlib.file_digest(stream, "sha256").hexdigest()
        records[str(logical.absolute())] = {"resolved": str(path), "sha256": sha,
            "source_relative": path.relative_to(project.resolve()).as_posix()
            if path.is_relative_to(project.resolve()) else None}
    return records


def inspect(unit: dict, project: Path, compiler: Path, scanner: Path, evidence: Path, execute) -> dict:
    """Scan without compilation, application execution or writes in application source."""
    require(scanner.resolve().parent == compiler.resolve().parent and scanner.is_file(),
            "scanner must be beside the selected qualified compiler")
    require(not evidence.resolve().is_relative_to(project.resolve()), "dependency evidence must be outside source")
    evidence.mkdir(parents=True, exist_ok=False)
    directory, source = project / unit["directory"], project / unit["source"]
    database = evidence / "compilation-database.json"
    database.write_text(json.dumps([{"directory": str(directory), "file": str(source),
        "arguments": [str(compiler), *unit["flags"], "-c", str(source), "-o", str(evidence / "unused.o")]}]) + "\n")
    result = execute([scanner, "-compilation-database=" + str(database), "-format=experimental-full",
                      "-mode=preprocess", "-j", "1"], directory)
    require(result.returncode == 0, "compiler dependency scan failed: " + result.stderr.decode(errors="replace")[-2000:])
    (evidence / "dependencies.json").write_bytes(result.stdout)
    records = file_records(dependency_paths(result.stdout, source, compiler), project, directory)
    require(str(source.resolve()) in {item["resolved"] for item in records.values()},
            "compiler omitted the selected translation unit")
    require(not (evidence / "unused.o").exists(), "dependency scan unexpectedly compiled an object")
    return records
