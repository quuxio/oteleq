"""Independently recheck retained Node source journals and compiler artifacts."""

import hashlib
import json
from pathlib import Path
import re

import node_source as provider
import otelc_capture as capture

KINDS = {"source", "compiler_config", "absent_config", "package_context", "absent_package", "startup",
         "module_requested", "compilation", "compiled", "instrumented", "loaded",
         "module_reentered", "execution_started"}
EMISSIONS = {"compiled", "instrumented", "loaded"}
MAX_ARTIFACT = 32 * 1024 * 1024


def content(path: Path) -> bytes:
    """Only bounded regular files can be retained input evidence."""
    provider.require(path.is_file() and not path.is_symlink() and path.stat().st_size <= MAX_ARTIFACT,
                     "missing, linked or oversized retained artifact")
    return path.read_bytes()


def artifact(record: dict, runtime: Path, prefix: str) -> bytes:
    """A digest can address only this runtime's fixed artifact namespace."""
    provider.require(type(record) is dict and type(record.get("sha256")) is str
                     and re.fullmatch("[a-f0-9]{64}", record["sha256"]) is not None
                     and type(record.get("size")) is int and 0 <= record["size"] <= MAX_ARTIFACT,
                     "invalid retained artifact identity")
    path = runtime / (prefix + "-module-" + record["sha256"] + ".txt")
    provider.require(record.get("file") == str(path), "retained artifact escapes its runtime namespace")
    raw = content(path)
    provider.require(len(raw) == record["size"] and hashlib.sha256(raw).hexdigest() == record["sha256"],
                     "retained artifact bytes changed after SDK verification")
    return raw


def emission(record: dict, sources: set[tuple[str, str]], runtime: Path, prefix: str) -> None:
    """Every emitted byte sequence still belongs to a preceding original source read."""
    provider.require(type(record.get("path")) is str and type(record.get("source_sha256")) is str
                     and (record["path"], record["source_sha256"]) in sources,
                     "retained emission has no preceding source identity")
    artifact({"file": record.get("output_file"), "sha256": record.get("sha256"), "size": record.get("size")}, runtime, prefix)
    fields = {"map_file", "map_sha256", "map_size"}
    if fields & set(record):
        provider.require(fields <= set(record), "incomplete retained emission map")
        artifact({"file": record["map_file"], "sha256": record["map_sha256"], "size": record["map_size"]}, runtime, prefix)


def compiler_files(compiler: dict, runtime: Path, prefix: str, backend: str) -> dict[str, bytes]:
    """Keep compiler consumption and emission artifacts distinct, with closed roles."""
    files = compiler.get("files")
    roles = {"input", "options", "output", "map"} | ({"preparation_map"} if backend == "native" else set())
    provider.require(type(files) is dict and set(files) == roles, "incomplete retained compiler artifacts")
    for record in files.values():
        provider.require(type(record) is dict and set(record) in ({"file", "sha256", "size"}, {"file", "sha256", "size", "path"})
                         and ("path" not in record or type(record["path"]) is str and Path(record["path"]).is_absolute()),
                         "unknown retained compiler artifact fields")
    return {role: artifact(record, runtime, prefix) for role, record in files.items()}


def compiler_identity(compiler: dict, value: dict, manifest: dict, source: Path) -> None:
    """Recorded compiler metadata can identify the pinned tool, never choose a command."""
    backend = value["compiler"]
    fields = {"backend", "version", "compiler_path", "cwd", "transformer_profile", "files", "argv" if backend == "native" else "method"}
    provider.require(type(compiler) is dict and set(compiler) == fields and compiler["backend"] == backend
                     and compiler["cwd"] == value["project"], "retained compiler profile differs")
    root = Path(value["provider"])
    if backend == "api":
        executable = root / "node_modules/typescript-api/lib/typescript.js"
        provider.require(compiler["method"] == "transpileModule" and compiler["version"] == "6.0.3",
                         "unqualified retained API compiler operation")
    else:
        runtime = manifest["runtime"]
        provider.require(runtime.get("platform") in ("darwin", "linux", "win32") and runtime.get("architecture") in ("arm64", "x64"),
                         "unqualified retained native compiler platform")
        executable = root / "node_modules/@typescript" / ("typescript-" + runtime["platform"] + "-" + runtime["architecture"]) / "lib/tsc"
        provider.require(compiler["version"] == "7.0.2", "unqualified retained native compiler version")
        expected = [str(executable.resolve(strict=True)), "--project", compiler["files"]["options"].get("path")]
        provider.require(compiler["argv"] == expected and type(expected[-1]) is str,
                         "retained native compiler command differs from fixed recipe")
    provider.require(compiler["compiler_path"] == str(executable.resolve(strict=True)), "retained compiler tool identity differs")
    profile = "none" if value["plain"] or str(source) != value["entry"] else "original-identities-v1"
    provider.require(compiler["transformer_profile"] == profile, "retained compiler transform selection differs")


def compiler_input(compiler: dict, raw: dict[str, bytes], source: dict, backend: str) -> None:
    """Retained compiler input must still refer to this original source text."""
    if backend == "api":
        provider.require(compiler["files"]["input"].get("path") == source["path"]
                         and hashlib.sha256(raw["input"]).hexdigest() == source["text_sha256"],
                         "retained API compiler input differs from source")
        return
    preparation = capture.strict_json(raw["preparation_map"])
    original = compiler["files"]["input"].get("path")
    provider.require(type(original) is str and Path(original).is_absolute(), "missing native compiler input path")
    provider.require(type(preparation) is dict and preparation.get("sources") == [source["path"]]
                     and preparation.get("file") == Path(original).name
                     and type(preparation.get("sourcesContent")) is list and len(preparation["sourcesContent"]) == 1
                     and type(preparation["sourcesContent"][0]) is str
                     and hashlib.sha256(preparation["sourcesContent"][0].encode()).hexdigest() == source["text_sha256"],
                     "retained native preparation map lost original source text")


def native_options(options: dict, compiler: dict, source: Path, commonjs: bool) -> None:
    """Native emission has one private input and fixed non-project build flags."""
    files = compiler["files"]
    provider.require(type(files["input"].get("path")) is str, "missing native compiler input path")
    original = Path(files["input"]["path"])
    directory = original.parent
    name = source.with_suffix(".cts").name if commonjs and source.suffix == ".ts" else source.name
    provider.require(directory.name.startswith("otelc-native-typescript-") and original.name == name
                     and files["options"]["path"] == str(directory / "tsconfig.json")
                     and options.get("files") == [str(original)], "retained native compiler input recipe differs")
    fixed = {"rootDir": str(directory), "outDir": str(directory / "emitted"), "noEmitOnError": False,
             "noCheck": True, "noResolve": True, "incremental": False, "composite": False, "types": [],
             "moduleResolution": "node16" if commonjs else "bundler", "module": "node16" if commonjs else "preserve"}
    settings = options["compilerOptions"]
    provider.require(json.dumps({key: settings.get(key) for key in fixed}, sort_keys=True) == json.dumps(fixed, sort_keys=True),
                     "retained native compiler build flags differ")
    extension = {".cts": ".cjs", ".mts": ".mjs"}.get(original.suffix, ".js")
    output = directory / "emitted" / original.with_suffix(extension).name
    provider.require(files["output"].get("path") == str(output) and files["map"].get("path") == str(output) + ".map",
                     "retained native compiler output recipe differs")


def compiler_options(compiler: dict, compiled: dict, request: dict, value: dict) -> None:
    """Rehashed raw options must still describe the fixed plain or selected recipe."""
    prefix = "node-plain" if value["plain"] else "node"
    options = capture.strict_json(artifact(compiler["files"]["options"], Path(value["runtime"]), prefix))
    provider.require(type(options) is dict and compiled.get("format") in ("commonjs", "module"), "invalid retained compiler options")
    commonjs = compiled["format"] == "commonjs"
    settings = options.get("compilerOptions") if value["compiler"] == "native" else options
    fixed = {"sourceMap": True, "inlineSourceMap": False, "inlineSources": True, "removeComments": False,
             "declaration": False, "declarationMap": False, "emitDeclarationOnly": False, "noEmit": False,
             "allowImportingTsExtensions": False, "rewriteRelativeImportExtensions": False,
             "verbatimModuleSyntax": not commonjs, "isolatedModules": True}
    provider.require(type(settings) is dict and json.dumps({key: settings.get(key) for key in fixed}, sort_keys=True) == json.dumps(fixed, sort_keys=True),
                     "retained compiler emission flags differ")
    if value["compiler"] == "native":
        native_options(options, compiler, Path(request["path"]), commonjs)
    else:
        provider.require(type(settings.get("module")) is int and settings["module"] == (1 if commonjs else 200),
                         "retained API module format differs")


def module_request(record: dict, project: Path) -> None:
    """Module origins remain inside the independently materialised source tree."""
    provider.require(type(record.get("path")) is str and type(record.get("logical_source")) is str,
                     "missing retained module origin")
    path = Path(record["path"])
    provider.require(path.is_absolute() and path.is_relative_to(project)
                     and record["logical_source"] == path.relative_to(project).as_posix()
                     and record.get("url") == path.as_uri() and record.get("module_type") in ("javascript", "typescript"),
                     "retained module URL or source origin differs")


def source_read(record: dict, project: Path) -> None:
    """Recheck complete source reads without following arbitrary journal paths."""
    provider.require(type(record.get("path")) is str and type(record.get("requested_path")) is str,
                     "missing retained source read origin")
    path, requested = Path(record["path"]), Path(record["requested_path"])
    provider.require(path.is_absolute() and path.is_relative_to(project) and requested.is_absolute()
                     and requested.is_relative_to(project) and requested.resolve(strict=True) == path,
                     "retained source read escapes the private project")
    raw = content(path)
    provider.require(type(record.get("size")) is int and record["size"] == len(raw)
                     and record.get("sha256") == hashlib.sha256(raw).hexdigest()
                     and record.get("text_sha256") == hashlib.sha256(raw.decode("utf-8").encode()).hexdigest(),
                     "retained source read changed after SDK verification")


def module_phase(record: dict, requests: dict, phases: dict, project: Path) -> None:
    """A phase belongs to one preceding request and cannot replace another load."""
    load = record.get("load_id")
    provider.require(type(load) is int and load > 0, "invalid retained module load identity")
    kind = record["kind"]
    if kind == "module_requested":
        provider.require(load not in requests, "duplicate retained module request")
        module_request(record, project)
        requests[load], phases[load] = record, {}
        return
    provider.require(load in requests and kind not in phases[load] and record.get("path") == requests[load]["path"],
                     "missing request, duplicate phase or changed retained source origin")
    typed = requests[load]["module_type"] == "typescript"
    if kind == "compilation":
        expected = set()
        provider.require(typed, "compiler phase order differs for JavaScript")
    elif kind == "compiled":
        expected = {"compilation"}
        provider.require(typed, "compiled phase order differs for JavaScript")
    else:
        expected = {"compilation", "compiled"} if typed else set()
    provider.require(set(phases[load]) == expected, "retained compiler phase order differs")
    if kind != "compilation":
        provider.require(all(record.get(key) == requests[load][key] for key in ("url", "logical_source")),
                         "retained module phase changed its original URL")
    phases[load][kind] = record


def complete_modules(requests: dict, phases: dict, sources: dict, value: dict) -> None:
    """Every requested load has its own complete selected or plain emission."""
    provider.require(set(sources) <= {record["path"] for record in requests.values()}, "retained source has no module request")
    for load, request in requests.items():
        final = "instrumented" if not value["plain"] and request["path"] == value["entry"] else "loaded"
        provider.require(final in phases[load], "retained module load did not complete")
        if request["module_type"] == "typescript":
            provider.require({"compilation", "compiled"} <= set(phases[load]), "retained TypeScript compiler phase is missing")
            compiler_options(phases[load]["compilation"]["compiler"], phases[load]["compiled"], request, value)


def verify(records: list, value: dict, manifest: dict) -> None:
    """Recheck raw journal continuity and all retained compiler/emission bytes."""
    runtime, project = Path(value["runtime"]), Path(value["project"])
    prefix = "node-plain" if value["plain"] else "node"
    journal = runtime / (prefix + "-sources.jsonl")
    if value["plain"] and value["language"] == "javascript":
        provider.require(not journal.exists() and not journal.is_symlink(), "plain JavaScript has an unrequested source journal")
        return
    raw = content(journal)
    provider.require(raw.endswith(b"\n"), "retained source journal is truncated")
    actual = [capture.strict_json(line) for line in raw.splitlines()]
    provider.require(json.dumps(actual, sort_keys=True) == json.dumps(records, sort_keys=True),
                     "verified source records differ from the actual read journal")
    sources, requests, phases = {}, {}, {}
    for record in records:
        provider.require(type(record) is dict and type(record.get("kind")) is str and record["kind"] in KINDS, "unknown retained source record")
        kind = record["kind"]
        if kind == "source":
            source_read(record, project)
            sources[record["path"]] = record
        if kind in EMISSIONS:
            emission(record, {(path, item["sha256"]) for path, item in sources.items()}, runtime, prefix)
        if kind == "compilation":
            provider.require(type(record.get("path")) is str and record["path"] in sources,
                             "compiler phase has no preceding original source")
            compiler = record.get("compiler")
            provider.require(type(compiler) is dict, "missing retained compiler record")
            data = compiler_files(compiler, runtime, prefix, value["compiler"])
            compiler_identity(compiler, value, manifest, Path(record["path"]))
            compiler_input(compiler, data, sources[record["path"]], value["compiler"])
        if kind in EMISSIONS | {"module_requested", "compilation"}:
            module_phase(record, requests, phases, project)
    complete_modules(requests, phases, sources, value)
