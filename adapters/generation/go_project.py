"""Resolve explicit Go module contexts without running application initialisers."""
import json
from pathlib import Path, PurePosixPath
import re
import string

import go_storage


COMMAND_DIRECTORY = "oteleq_generated_cmd"
OBSERVER_DIRECTORY = "oteleq_generated_observer"
CONTROL_DIRECTORY = "oteleq_generated_control"
BRIDGE = "OteleqGeneratedRun"
ASCII_TAG = frozenset(string.ascii_letters + string.digits + "_.")
SOURCE_BACKENDS = ("source-v1", "source-scope-v1")


def canonical_tags(value: object) -> tuple[str, ...]:
    """Bound literal tag inputs; the selected Go parser owns Unicode grammar."""
    if type(value) not in (tuple, list) or len(value) > 128:
        raise ValueError("Go build tags require at most 128 literal names")
    for name in value:
        if type(name) is not str:
            raise ValueError("Go build tag must be a string")
        try:
            encoded = name.encode("utf-8")
        except UnicodeEncodeError as error:
            raise ValueError("Go build tag must be valid UTF-8") from error
        if not 0 < len(encoded) <= 256 or any(ord(char) < 128 and char not in ASCII_TAG for char in name):
            raise ValueError("Go build tag must be one bounded literal name")
    if len(value) != len(set(value)):
        raise ValueError("Go build tags must be distinct")
    return tuple(sorted(value))


def build_timeout(value: int) -> int:
    """Reject invalid retained budgets before starting any selected Go tool."""
    if type(value) is not int or not 1 <= value <= 900000:
        raise ValueError("Go build_timeout_ms must be an integer from 1 to 900000")
    return value


def settings(value: dict) -> dict:
    """Freeze module roots, shared build tags and the per-command build budget."""
    if not isinstance(value, dict) or set(value) - {"backend", "module_roots", "build_tags", "build_timeout_ms", "build_min_free_bytes"}:
        raise ValueError("adapters.go accepts backend, module_roots, build_tags, build_timeout_ms and build_min_free_bytes")
    backend = value.get("backend", "legacy")
    if type(backend) is not str or backend not in ("legacy", *SOURCE_BACKENDS):
        raise ValueError("adapters.go.backend must be legacy, source-v1 or source-scope-v1")
    timeout = build_timeout(value.get("build_timeout_ms", 180000))
    minimum = go_storage.minimum(value.get("build_min_free_bytes", 0))
    if minimum and backend not in SOURCE_BACKENDS:
        raise ValueError("Go build_min_free_bytes requires a source-v1 or source-scope-v1 backend")
    roots, tags = value.get("module_roots", []), value.get("build_tags", [])
    if not isinstance(roots, list) or any(type(item) is not str for item in roots):
        raise ValueError("Go module_roots must be an array of relative paths")
    for item in roots:
        path = PurePosixPath(item)
        if (not item or path.is_absolute() or str(path) != item or ".." in path.parts
                or "\\" in item or ":" in item):
            raise ValueError("Go module roots require canonical source-relative paths")
    if not isinstance(tags, list) or len(roots) != len(set(roots)):
        raise ValueError("Go module roots and build tags must be valid and distinct")
    selected_tags = canonical_tags(tags)
    if backend in SOURCE_BACKENDS:
        tags = list(selected_tags)
    elif any(not re.fullmatch(r"[A-Za-z0-9_.]+", tag) for tag in tags):
        raise ValueError("legacy Go build tags require ASCII literal names")
    if tags and not roots:
        raise ValueError("Go build_tags require explicit module_roots")
    result = {"module_roots": roots.copy(), "build_tags": tags.copy(), "build_timeout_ms": timeout}
    if "backend" in value:
        result["backend"] = backend
    if "build_min_free_bytes" in value:
        result["build_min_free_bytes"] = minimum
    return result


def environment(options: dict) -> dict[str, str]:
    """Apply the same selected tags during inventory and retained compilation."""
    tags = options["build_tags"]
    return {"GOFLAGS": "-tags=" + ",".join(tags) if tags else "", "GOWORK": "off", "GOENV": "off"}


def module_root(snapshot: Path, source: Path, roots: list[str]) -> Path:
    """Never borrow a module, workspace or local replacement outside the snapshot."""
    directories = [directory for directory in (source.parent, *source.parent.parents) if directory.is_relative_to(snapshot)]
    for directory in directories:
        if (directory / "go.work").exists():
            raise ValueError("Go workspaces need a separate build recipe")
    for directory in directories:
        if (directory / "go.mod").is_file():
            relative = directory.relative_to(snapshot).as_posix()
            if relative not in roots:
                raise ValueError("nearest Go module root is not configured: " + relative)
            return directory
    raise ValueError("Go source requires a configured go.mod inside the source snapshot")


def documents(raw: bytes) -> list[dict]:
    """Decode go list's stream of complete JSON objects."""
    decoder, text, result = json.JSONDecoder(), raw.decode(), []
    position = 0
    while position < len(text):
        if text[position].isspace():
            position += 1
            continue
        value, position = decoder.raw_decode(text, position)
        if not isinstance(value, dict):
            raise ValueError("Go list returned a non-object package")
        result.append(value)
    return result


def package_inputs(records: list[dict], snapshot: Path) -> None:
    """Keep unsupported source compilation and local dependency escapes visible."""
    for record in records:
        module = record.get("Module", {})
        replacement = module.get("Replace", {})
        if replacement and not replacement.get("Version"):
            if not Path(replacement.get("Dir", "")).is_relative_to(snapshot):
                raise ValueError("local Go replacement must remain inside the source snapshot")
        if Path(record.get("Dir", "")).is_relative_to(snapshot):
            if record.get("CgoFiles") or record.get("SFiles") or record.get("SwigFiles") or record.get("SwigCXXFiles"):
                raise ValueError("project cgo, assembly and SWIG require a separate Go build recipe")


def check_result(result, label: str) -> None:
    """Tool failures retain a useful bounded diagnostic and never create ready cases."""
    if result.returncode:
        raise ValueError(label + ": " + result.stderr.decode(errors="replace")[-2000:])


def load_package(source: Path, snapshot: Path, module: Path, go: Path, execute) -> dict:
    """Use actual package inclusion and compiler export data for semantic inventory."""
    listed = execute([go, "list", "-deps", "-export", "-json", "-mod=readonly", "."], source.parent)
    check_result(listed, "Go package discovery failed")
    records = documents(listed.stdout)
    package_inputs(records, snapshot)
    matches = [record for record in records if record.get("Dir") == str(source.parent)]
    if len(matches) != 1 or not matches[0].get("GoFiles"):
        raise ValueError("Go package has no unique active source file set")
    package = matches[0]
    if Path(package.get("Module", {}).get("Dir", "")) != module:
        raise ValueError("Go list selected a different module root")
    files = [source.parent / name for name in sorted(package["GoFiles"])]
    if any(not path.is_relative_to(snapshot) or path.is_symlink() or not path.is_file() for path in files):
        raise ValueError("Go active package sources must be regular snapshot files")
    request = {"files": [str(path) for path in files],
               "exports": {record["ImportPath"]: record["Export"] for record in records if record.get("Export")},
               "import_path": package["ImportPath"], "go_version": "go" + package["Module"]["GoVersion"]}
    result = execute([go, "run", Path(__file__).with_name("discover.go"), "--", "--package"], Path(__file__).parent,
                     input_data=json.dumps(request).encode())
    check_result(result, "Go package type checking failed")
    inventories = json.loads(result.stdout)
    context = {"module_root": module.relative_to(snapshot).as_posix(),
               "directory": source.parent.relative_to(snapshot).as_posix(),
               "import_path": package["ImportPath"], "package": package["Name"],
               "files": [path.relative_to(snapshot).as_posix() for path in files],
               "shadowed_recovery": any(item["name"] in ("panic", "recover") for inventory in inventories.values()
                                        for item in inventory["functions"]),
               "main_renames": {path.relative_to(snapshot).as_posix(): inventories[str(path)]["main_renames"]
                               for path in files}}
    if any("__oteleq" in path.read_text() or BRIDGE in path.read_text() for path in files):
        raise ValueError("generated Go observer name collides with package source")
    for directory, kind in ((COMMAND_DIRECTORY, "command"), (OBSERVER_DIRECTORY, "observer"),
                            (CONTROL_DIRECTORY, "control")):
        if (module / directory).exists() or (module / directory).is_symlink():
            raise ValueError("generated Go " + kind + " directory collides with source")
    return {"inventories": inventories, "context": context}


def discover(source: Path, snapshot: Path, options: dict, go: Path, execute, cache: dict) -> dict:
    """Cache one semantic result per package; retain excluded build-file callables."""
    key = str(source.parent)
    if key not in cache:
        try:
            module = module_root(snapshot, source, options["module_roots"])
            cache[key] = load_package(source, snapshot, module, go, execute)
        except ValueError as error:
            cache[key] = str(error)
    package = cache[key]
    if isinstance(package, str) or str(source) not in package["inventories"]:
        result = execute([go, "run", Path(__file__).with_name("discover.go"), "--", source], Path(__file__).parent)
        check_result(result, "inactive Go source inventory failed")
        inventory = json.loads(result.stdout)
        for function in inventory["functions"]:
            function["reason"] = package if isinstance(package, str) else "Go source is excluded by the selected host/build tags or is a separate _test.go target"
            function["entrypoint"] = False
        return inventory
    return {**package["inventories"][str(source)], "go_context": package["context"]}


def worker_path(context: dict) -> str:
    """A real main package includes siblings; a library gets an importing main."""
    if context["package"] == "main":
        return context["directory"]
    return str(Path(context["module_root"]) / COMMAND_DIRECTORY / "main.go")


def module_import(context: dict) -> str:
    """Recover the compiler-bound module path from its source package directory."""
    for key in ("module_root", "directory"):
        value = context[key]
        if (type(value) is not str or not value or PurePosixPath(value).is_absolute()
                or str(PurePosixPath(value)) != value or ".." in PurePosixPath(value).parts
                or "\\" in value or ":" in value):
            raise ValueError("Go caller context requires canonical source-relative directories")
    relative = PurePosixPath(context["directory"]).relative_to(context["module_root"]).as_posix()
    suffix = "" if relative == "." else "/" + relative
    name = context["import_path"]
    if type(name) is not str or not name or not name.endswith(suffix):
        raise ValueError("Go source package differs from its module import path")
    result = name.removesuffix(suffix) if suffix else name
    if not result:
        raise ValueError("Go module import path is empty")
    return result


def rename_entrypoint(source: str, positions: list[int]) -> str:
    """Preserve calls/references to the original main, leaving lexical shadows alone."""
    raw = source.encode()
    for position in sorted(positions, reverse=True):
        if raw[position:position + 4] != b"main":
            raise ValueError("Go main source range does not match its resolved binding")
        raw = raw[:position] + b"__oteleq_original_main" + raw[position + 4:]
    return raw.decode()
