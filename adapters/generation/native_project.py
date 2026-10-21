"""Freeze explicit native targets from real compilation database commands."""
import json
import hashlib
import os
from pathlib import Path, PurePosixPath
import re
import shlex
import shutil
import tempfile

from otelc_capture import strict_json
import native_frontend

MAX_DATABASE_BYTES = 16 * 1024 * 1024
MAX_COMMANDS = 10000
PATH_OPTIONS = ("-isystem", "-iquote", "-include", "-imacros", "-I")
VALUE_OPTIONS = ("-D", "-U")
DEPENDENCY_OPTIONS = {"-MF", "-MT", "-MQ", "-MJ"}
IGNORED_OPTIONS = {"-MD", "-MMD", "-MP", "-MG"}
SIMPLE_OPTIONS = {"-g", "-g0", "-g1", "-g2", "-g3", "-gline-tables-only", "-pthread", "-pipe",
                  "-fPIC", "-fpic", "-fPIE", "-fpie", "-fno-common", "-fcommon", "-fexceptions",
                  "-fno-exceptions", "-frtti", "-fno-rtti", "-fno-omit-frame-pointer",
                  "-fomit-frame-pointer", "-fno-strict-aliasing", "-fstrict-aliasing"}
EXTENSIONS = {"c": {".c"}, "cpp": {".cc", ".cpp", ".cxx", ".C"}}


def require(condition: bool, reason: str) -> None:
    """A build ambiguity is a blocker rather than an inferred compiler recipe."""
    if not condition:
        raise ValueError("native project: " + reason)


def source_path(value: str, label: str) -> str:
    """Policy paths identify canonical files beneath the selected source root."""
    require(type(value) is str and bool(value), label + " requires a source-relative path")
    path = PurePosixPath(value)
    require(not path.is_absolute() and str(path) == value and ".." not in path.parts
            and "\\" not in value and "\0" not in value, label + " requires a canonical source-relative path")
    return value


def settings(value: dict) -> dict:
    """Declare target membership and link flags; a database has no link recipe."""
    require(type(value) is dict and not set(value) - {"compilation_database", "targets"},
            "adapter accepts compilation_database and targets")
    database = value.get("compilation_database")
    targets = value.get("targets", [])
    if database is None:
        require(targets == [], "targets require a compilation_database")
        return {"compilation_database": None, "targets": []}
    source_path(database, "compilation_database")
    require(type(targets) is list and 1 <= len(targets) <= 32, "declare 1 to 32 native targets")
    result = [target_settings(target) for target in targets]
    require(len({target["name"] for target in result}) == len(result), "target names must be distinct")
    return {"compilation_database": database, "targets": result}


def target_settings(value: dict) -> dict:
    """An explicit ordered unit set disambiguates variants and object link order."""
    require(type(value) is dict and not set(value) - {"name", "units", "link_flags"}, "unsupported target fields")
    name = value.get("name")
    require(type(name) is str and re.fullmatch(r"[A-Za-z_]\w{0,63}", name, re.ASCII) is not None,
            "target name requires an ordinary identifier of at most 64 characters")
    units = value.get("units")
    require(type(units) is list and 1 <= len(units) <= 256, "target requires 1 to 256 ordered units")
    selected = []
    for unit in units:
        require(type(unit) is dict and not set(unit) - {"source", "output"}, "unit accepts source and optional output")
        item = {"source": source_path(unit.get("source"), "unit.source")}
        if "output" in unit:
            item["output"] = source_path(unit["output"], "unit.output")
        selected.append(item)
    require(len({json.dumps(unit, sort_keys=True) for unit in selected}) == len(selected), "target units must be distinct")
    flags = value.get("link_flags", [])
    require(type(flags) is list and len(flags) <= 256 and all(type(flag) is str and
            (flag == "-pthread" or re.fullmatch(r"-l[A-Za-z_]\w*", flag, re.ASCII)) for flag in flags),
            "link_flags currently accept -pthread and named system libraries")
    return {"name": name, "units": selected, "link_flags": flags.copy()}


def contained(value: str, directory: Path, root: Path, *, exists: bool = False) -> Path:
    """Only private copies of project inputs may replace compiler path arguments."""
    require(type(value) is str and bool(value) and "\0" not in value, "invalid compiler path")
    path = Path(value)
    path = (directory / path).resolve() if not path.is_absolute() else path.resolve()
    require(path.is_relative_to(root), "compiler path escapes the source root: " + value)
    if exists:
        require(path.exists(), "missing compiler input: " + value)
    return path


def argv(record: dict) -> list[str]:
    """Read argv directly where supplied; command strings are never executed."""
    require(type(record) is dict and not set(record) - {"directory", "file", "arguments", "command", "output"},
            "unsupported compilation database fields")
    arguments = record.get("arguments")
    if arguments is None:
        command = record.get("command")
        require(type(command) is str and len(command) <= 1024 * 1024, "missing or oversized compile command")
        try:
            arguments = shlex.split(command, posix=True)
        except ValueError as error:
            raise ValueError("native project: invalid compile command quoting") from error
    require(type(arguments) is list and 1 <= len(arguments) <= 4096 and
            all(type(item) is str and 0 < len(item) <= 8192 and "\0" not in item for item in arguments),
            "compile arguments require bounded nonempty strings")
    require(not any(item.startswith("@") for item in arguments), "response files need an explicit input recipe")
    return arguments.copy()


def option_value(arguments: list[str], position: int, option: str) -> tuple[str, int]:
    """Preserve split and joined compiler spellings without treating values as flags."""
    argument = arguments[position]
    if argument != option:
        return argument[len(option):], position + 1
    require(position + 1 < len(arguments), option + " requires a value")
    return arguments[position + 1], position + 2


def compiler_identity(argument: str, compiler: Path) -> None:
    """The database must already use the selected qualified compiler."""
    found = shutil.which(argument)
    require(found is not None and Path(found).resolve() == compiler.resolve(),
            "database compiler differs from the selected qualified compiler")


def argument(arguments: list[str], position: int, directory: Path, root: Path) -> tuple[str, list, int]:
    """Classify one option without mistaking an unknown switch for an output path."""
    value = arguments[position]
    if value == "-c":
        return "compile", [], position + 1
    if value == "-o":
        output, next_position = option_value(arguments, position, "-o")
        return "output", [contained(output, directory, root).relative_to(root).as_posix()], next_position
    if value in IGNORED_OPTIONS:
        return "flags", [], position + 1
    option = next((item for item in DEPENDENCY_OPTIONS if value.startswith(item)), None)
    if option:
        _, next_position = option_value(arguments, position, option)
        return "flags", [], next_position
    return semantic_argument(arguments, position, directory, root)


def semantic_argument(arguments: list[str], position: int, directory: Path, root: Path) -> tuple[str, list, int]:
    """Canonicalise local paths while retaining ordered defines and compiler semantics."""
    value = arguments[position]
    # Long driver options overlap, for example -include and -include-pch.
    # Their path values must be separate; only -I has a joined spelling here.
    option = next((item for item in PATH_OPTIONS if value == item
                   or (item == '-I' and value.startswith('-I') and value != '-I-')), None)
    if option:
        path, next_position = option_value(arguments, position, option)
        path = contained(path, directory, root, exists=True)
        return "flags", [option, os.path.relpath(path, directory)], next_position
    option = next((item for item in VALUE_OPTIONS if value.startswith(item)), None)
    if option:
        data, next_position = option_value(arguments, position, option)
        return "flags", [option, data], next_position
    if simple_flag(value):
        return "flags", [value], position + 1
    require(not value.startswith(("-", "@")), "unsupported project compiler flag: " + value)
    return "source", [contained(value, directory, root, exists=True)], position + 1


def flags(arguments: list[str], source: Path, directory: Path, root: Path) -> tuple[list[str], str]:
    """Remove action/output bookkeeping while preserving qualified semantic flags."""
    collected = {"flags": [], "source": [], "output": []}
    position, compilations = 1, 0
    while position < len(arguments):
        kind, values, position = argument(arguments, position, directory, root)
        if kind == "compile":
            compilations += 1
        else:
            collected[kind].extend(values)
    sources, outputs = collected["source"], collected["output"]
    require(compilations == 1 and sources == [source], "database entry must compile its one declared source")
    require(len(outputs) <= 1, "ambiguous compiler output")
    output = outputs[0] if outputs else (directory / source.with_suffix(".o").name).relative_to(root).as_posix()
    return collected["flags"], output


def simple_flag(argument: str) -> bool:
    """Unknown flags need qualification rather than silently changing the build."""
    return (argument in SIMPLE_OPTIONS or re.fullmatch(r"-O[0123sgz]", argument) is not None
            or re.fullmatch(r"-std=(?:gnu\+\+|c\+\+)(?:17|20|23)|-std=(?:gnu|c)(?:11|17|23)", argument) is not None
            or re.fullmatch(r"-W(?:all|extra|error|pedantic|no-[A-Za-z][A-Za-z\d-]*)", argument, re.ASCII) is not None)


def unit(record: dict, root: Path, language: str, compiler: Path) -> dict:
    """Bind one actual compile variant to a movable private source directory."""
    arguments = argv(record)
    compiler_identity(arguments[0], compiler)
    directory_value = record.get("directory")
    require(type(directory_value) is str and Path(directory_value).is_absolute(),
            "database directory must be absolute to avoid an ambiguous working directory")
    directory = contained(directory_value, root, root, exists=True)
    require(directory.is_dir(), "compiler working directory is not a directory")
    source = contained(record.get("file"), directory, root, exists=True)
    require(source.is_file() and source.suffix in EXTENSIONS[language], "target unit has a different source language")
    selected, output = flags(arguments, source, directory, root)
    if "output" in record:
        require(contained(record["output"], directory, root).relative_to(root).as_posix() == output,
                "database output disagrees with compiler arguments")
    return {"source": source.relative_to(root).as_posix(), "directory": directory.relative_to(root).as_posix(),
            "flags": selected, "output": output, "compiler": str(compiler), "language": language}


def load(root: Path, options: dict, language: str, compiler: Path) -> list[dict]:
    """Resolve each declared target without selecting an arbitrary file variant."""
    require(language in EXTENSIONS, "native target language must be c or cpp")
    root = root.resolve()
    path = root / options["compilation_database"]
    require(path.is_file() and not path.is_symlink() and path.stat().st_size <= MAX_DATABASE_BYTES,
            "compilation database must be a bounded regular file")
    document = strict_json(path.read_text())
    require(type(document) is list and 1 <= len(document) <= MAX_COMMANDS, "invalid compilation database command count")
    requested = {item["source"] for target in options["targets"] for item in target["units"]}
    units = [unit(record, root, language, compiler) for record in selected_records(document, root, requested)]
    targets = []
    for target in options["targets"]:
        selected = []
        for requested in target["units"]:
            matches = [item for item in units if item["source"] == requested["source"]
                       and ("output" not in requested or item["output"] == requested["output"])]
            require(len(matches) == 1, "unit needs one unique database variant: " + requested["source"])
            selected.append(matches[0])
        require(len({item["output"] for item in selected}) == len(selected), "target objects have conflicting outputs")
        targets.append({"name": target["name"], "units": selected, "link_flags": target["link_flags"]})
    return targets


def selected_records(records: list[dict], root: Path, requested: set[str]) -> list[dict]:
    """Other database languages/targets remain outside this explicit target recipe."""
    selected = []
    for record in records:
        require(type(record) is dict, "compilation database entry must be an object")
        directory, source = record.get("directory"), record.get("file")
        require(type(directory) is str and Path(directory).is_absolute() and type(source) is str,
                "database entries require an absolute directory and a source file")
        path = (Path(directory) / source).resolve()
        if path.is_relative_to(root) and path.relative_to(root).as_posix() in requested:
            selected.append(record)
    return selected


def compile_arguments(unit: dict, project: Path, compiler: Path, source: Path, output: Path) -> list:
    """Both lanes reuse the frozen ordered flags in the same private directory."""
    require(source.resolve().is_relative_to(project.resolve()) and output.resolve().is_relative_to(project.resolve()),
            "private compile paths escape the workspace")
    compiler_identity(str(compiler), Path(unit["compiler"]))
    return [compiler, *unit["flags"], "-c", source, "-o", output]


def digest(path: Path) -> str:
    """Hash actual file content rather than timestamps or nominal dependency names."""
    with path.open('rb') as stream:
        return hashlib.file_digest(stream, 'sha256').hexdigest()


def prepare(root: Path, options: dict, language: str, compiler: Path, evidence: Path, execute) -> dict:
    """Freeze actual commands, project ASTs, read inputs and existence-only probes."""
    root = root.resolve()
    require(not evidence.resolve().is_relative_to(root), 'build evidence must be outside application source')
    targets = load(root, options, language, compiler)
    frontend = native_frontend.build(compiler, evidence / 'frontend', root, execute)
    database = options['compilation_database']
    local = {database: digest(root / database)}
    units, resolved_targets, external = {}, [], {}
    for target in targets:
        selected = []
        for item in target['units']:
            key = hashlib.sha256(json.dumps(item, sort_keys=True).encode()).hexdigest()
            if key not in units:
                metadata = evidence / 'units' / key
                document = native_frontend.inspect(item, root, frontend, evidence / 'frontend', metadata, execute)
                inputs = native_frontend.input_state(document, item, root)
                merge_inputs(inputs['dependencies'], local, external)
                units[key] = {**item, **inputs, 'metadata_sha256': digest(metadata / 'metadata.json')}
            selected.append(key)
        resolved_targets.append({'name': target['name'], 'units': selected, 'link_flags': target['link_flags']})
    prepared = {'source_root': str(root), 'language': language, 'database': database,
                'compiler': {'path': str(compiler), 'sha256': digest(compiler)}, 'frontend': frontend,
                'targets': resolved_targets, 'units': units, 'local_inputs': local, 'external_inputs': external}
    verify(prepared, evidence, execute)
    return prepared


def merge_inputs(dependencies: dict, local: dict, external: dict) -> None:
    """A shared header cannot acquire different content between target scans."""
    for logical, record in dependencies.items():
        relative = record['source_relative']
        if relative is not None:
            require(relative not in local or local[relative] == record['sha256'],
                    'project input changed between dependency scans: ' + relative)
            local[relative] = record['sha256']
        else:
            require(logical not in external or external[logical] == record,
                    'external input changed between dependency scans: ' + logical)
            external[logical] = record


def verify(prepared: dict, evidence: Path, execute) -> None:
    """Detect changed bytes, path bindings and positive or negative search results."""
    root = Path(prepared['source_root'])
    native_frontend.verify(prepared['frontend'], evidence / 'frontend')
    for key, unit in prepared['units'].items():
        require(digest(evidence / 'units' / key / 'metadata.json') == unit['metadata_sha256'],
                'retained compiler metadata changed: ' + key)
        for logical, record in unit['dependencies'].items():
            path = Path(logical)
            require(path.is_file() and str(path.resolve()) == record['resolved'],
                    'project input path changed: ' + logical)
    for name, expected in prepared['local_inputs'].items():
        path = root / name
        require(path.resolve().is_relative_to(root) and path.is_file() and not path.is_symlink()
                and digest(path) == expected, 'project build input changed: ' + name)
    for name, record in prepared['external_inputs'].items():
        path = Path(name)
        require(str(path.resolve()) == record['resolved'] and path.is_file() and digest(path) == record['sha256'],
                'external build input changed: ' + name)
    record = prepared['compiler']
    require(Path(record['path']).is_file() and digest(Path(record['path'])) == record['sha256'],
            'selected compiler changed')
    checks = Path(tempfile.mkdtemp(prefix='input-check-', dir=evidence))
    for key, unit in prepared['units'].items():
        document = native_frontend.inspect(unit, root, prepared['frontend'], evidence / 'frontend',
                                           checks / key, execute, mode='inputs')
        state = native_frontend.input_state(document, unit, root)
        require(state == {name: unit[name] for name in ('dependencies', 'probes')},
                'compiler inputs or preprocessor search results changed: ' + unit['source'])
