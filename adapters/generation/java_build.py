"""Retain compiler-owned class origins and bind prepared Java application inputs."""
from collections.abc import Callable
import json
from pathlib import Path
import shutil

from otelc_capture import file_digest, strict_json, tree_paths
import java_classpath
import java_project

FRONTEND = Path(__file__).with_name("OteleqCompile.java")
MAX_METADATA = 16 * 1024 * 1024
COMPILER_METADATA_FILENAME = "java-compiler.json"
COMPILER_IDENTITY_FILENAME = "java-compiler-identity.json"
PREPARED_APPLICATION_FILENAME = "prepared-application.json"


def require(condition: bool, reason: str) -> None:
    """An incomplete build identity cannot qualify an application launch."""
    if not condition:
        raise ValueError("Java build: " + reason)


def digest(path: Path) -> str:
    """Hash regular project products without blocking on special inputs."""
    return file_digest(path)


def files(root: Path) -> dict[str, str]:
    """Refuse links and preserve the complete private project input set."""
    result = {}
    for path in sorted(tree_paths(root)):
        require(not path.is_symlink(), "symlink in the private build: " + str(path))
        if path.is_file():
            result[path.relative_to(root).as_posix()] = digest(path)
    return result


def contained(name: str, root: Path) -> Path:
    """Metadata may identify files in the selected roots, never another executable."""
    require(type(name) is str, "missing compiler file origin")
    path = Path(name)
    require(path.is_absolute() and path == path.resolve() and path.is_relative_to(root),
            "compiler file origin escapes its private root")
    require(path.is_file() and not path.is_symlink(), "missing compiler input or output")
    return path


def bindings(metadata: dict, project: Path, classes: Path, original: dict,
             generated: set[Path], provenance: str, *, context: dict | None = None) -> dict:
    """Every class must have one compiler source origin read from frozen bytes."""
    fields = {"schema_version", "success", "java_version", "options", "source_reads_sha256", "outputs"}
    if context is not None:
        fields.add("class_reads_sha256")
    require(type(metadata) is dict and set(metadata) == fields
            and metadata.get("schema_version") == (2 if context is not None else 1)
            and type(metadata.get("schema_version")) is int and metadata.get("success") is True,
            "unsupported or unsuccessful compiler result")
    require(type(metadata["java_version"]) is str and metadata["java_version"]
            and metadata["options"] == java_project.compiler_options(project, classes, context),
            "compiler identity or fixed options changed")
    reads = metadata.get("source_reads_sha256")
    outputs = metadata.get("outputs")
    require(type(reads) is dict and type(outputs) is list and 0 < len(outputs) <= 10000,
            "missing or oversized compiler output inventory")
    sources = {}
    for name, sha in reads.items():
        path = contained(name, project)
        relative = path.relative_to(project).as_posix()
        require(path.suffix == ".java" and original.get(relative) == sha,
                "compiler read different source bytes: " + relative)
        sources[str(path)] = sha
    result, recorded = {}, set()
    for output in outputs:
        name, path, source = output_binding(output, project, classes)
        require(name not in result and path not in recorded, "duplicate compiler output binding")
        require(str(source) in sources, "class origin lacks an actual compiler source read")
        relative = source.relative_to(project).as_posix()
        policy_path = "_oteleq_generated/" + relative if source in generated else relative
        result[name] = {"source": str(source), "policy_path": policy_path,
                        "source_sha256": sources[str(source)], "class_sha256": digest(path),
                        "provenance": provenance}
        recorded.add(path)
    actual = {classes / name for name in files(classes)}
    require(recorded == actual, "unrecorded or missing class products")
    if context is not None:
        java_classpath.class_reads(metadata["class_reads_sha256"], context["entries"])
        require(not any(set(result).intersection(entry["classes"]) for entry in context["entries"]),
                "source products duplicate a declared dependency class")
    return result


def output_binding(output: dict, project: Path, classes: Path) -> tuple[str, Path, Path]:
    """Use javac's binary name and origin; a basename or SourceFile tag is insufficient."""
    require(type(output) is dict and set(output) == {"class", "output", "origins"},
            "invalid compiler output fields")
    name, origins = output["class"], output["origins"]
    require(type(name) is str and name and "/" not in name and "\\" not in name
            and all(part and part not in (".", "..") for part in name.split(".")), "invalid binary class name")
    require(type(origins) is list and len(origins) == 1, "class requires one compiler source origin")
    path = contained(output["output"], classes)
    require(path.relative_to(classes).as_posix() == name.replace(".", "/") + ".class",
            "compiler output does not match its binary identity")
    return name, path, contained(origins[0], project)


def module_image(java: Path) -> Path:
    """Require the selected complete JDK rather than an unbound system launcher."""
    java = java.resolve(strict=True)
    modules = java.parent.parent / "lib/modules"
    require(modules.is_file(), "selected Java executable has no JDK module image; set OTELC_JAVA to a complete JDK bin/java")
    return modules


def compiler_inputs(java: Path, frontend: Path | None = None) -> dict:
    """The host executable, complete JDK module image and frontend define the compiler."""
    java = java.resolve(strict=True)
    return {str(path): digest(path) for path in (java, module_image(java), frontend or FRONTEND)}


def build(project: Path, sources: list[Path], main: str, java: Path,
          classes: Path, folder: Path, environment: dict, execute: Callable, *, context: dict | None = None) -> dict:
    """Compile private source, retain origins, and emit the public prepared manifest."""
    project = project.resolve(strict=True)
    folder = folder.resolve()
    classes = classes.resolve()
    require(classes.is_relative_to(folder) and not classes.is_relative_to(project) and not classes.exists(),
            "class output must be new and outside the private source")
    require(not folder.is_relative_to(project), "build records must be outside the private source")
    original = files(project)
    sources = [contained(str(path.resolve()), project) for path in sources]
    generated = set(sources[1:])
    if context is not None:
        java_project.verify_attempt(folder, context)
        require(str(sources[0]) in context["source_units"], "selected target is outside declared source units")
        sources = [contained(name, project) for name in context["source_units"]] + sources[1:]
    require(sources and len(set(sources)) == len(sources) and all(path.suffix == ".java" for path in sources),
            "explicit Java source units must be distinct")
    classes.mkdir(parents=True)
    isolated = folder / "compiler-classpath"
    isolated.mkdir(parents=True)
    tool = folder / "compiler-tool"
    tool.mkdir()
    frontend = tool / FRONTEND.name
    shutil.copyfile(FRONTEND, frontend)
    tool_inputs = compiler_inputs(java, frontend)
    arguments = [project, classes, *sources]
    if context is not None:
        paths = [entry["path"] for entry in context["entries"]]
        arguments = ["--context-v2", project, classes, str(len(context["source_roots"])),
                     *context["source_roots"], str(len(paths)), *paths, *sources]
    command = [java, "-cp", isolated, frontend, *arguments]
    result = execute(command, project, environment, folder / "build", max_output_bytes=MAX_METADATA)
    require(not result.returncode, "compilation failed; inspect build/stderr")
    metadata = strict_json(result.stdout)
    require(files(project) == original and compiler_inputs(java, frontend) == tool_inputs,
            "private source or compiler changed during compilation")
    (folder / COMPILER_METADATA_FILENAME).write_text(json.dumps(metadata, indent=2) + "\n")
    compiler = {"driver": "JDK JavaCompiler file manager", "inputs_sha256": tool_inputs,
                "argv": list(map(str, command)), "compiler_metadata_sha256": digest(folder / COMPILER_METADATA_FILENAME)}
    (folder / COMPILER_IDENTITY_FILENAME).write_text(json.dumps(compiler, indent=2) + "\n")
    provenance = "oteleq.jdk-file-manager-v1:" + digest(folder / COMPILER_IDENTITY_FILENAME)
    bound = bindings(metadata, project, classes, original, generated, provenance, context=context)
    require(main in bound, "generated main has no compiler binding")
    application = {"schema_version": 1, "main_class": main,
                   "classpath": list(map(str, java_project.runtime_classpath(classes, context))), "bindings": bound}
    (folder / PREPARED_APPLICATION_FILENAME).write_text(json.dumps(application, indent=2) + "\n")
    record = {"schema_version": 1, "source_sha256": original, "classes_sha256": files(classes),
              "main_class": main, "compiler_metadata_sha256": digest(folder / COMPILER_METADATA_FILENAME),
              "compiler_identity_sha256": digest(folder / COMPILER_IDENTITY_FILENAME),
              "prepared_application_sha256": digest(folder / PREPARED_APPLICATION_FILENAME)}
    if context is not None:
        java_project.verify_attempt(folder, context)
        record["java_context_sha256"] = digest(folder / java_project.CONTEXT_FILE)
    (folder / "build-identities.json").write_text(json.dumps(record, indent=2) + "\n")
    return application


def verify(project: Path, classes: Path, folder: Path) -> None:
    """Recheck the actual source, products, compiler and retained build records."""
    record = strict_json((folder / "build-identities.json").read_bytes())
    require(record.get("schema_version") == 1 and type(record.get("schema_version")) is int,
            "unsupported build identity")
    require(files(project) == record["source_sha256"] and files(classes) == record["classes_sha256"],
            "application source or class products changed")
    for name, key in ((COMPILER_METADATA_FILENAME, "compiler_metadata_sha256"),
                      (COMPILER_IDENTITY_FILENAME, "compiler_identity_sha256"),
                      (PREPARED_APPLICATION_FILENAME, "prepared_application_sha256")):
        require(digest(folder / name) == record[key], "retained compiler evidence changed: " + name)
    compiler = strict_json((folder / COMPILER_IDENTITY_FILENAME).read_bytes())
    require(all(Path(name).is_file() and digest(Path(name)) == sha
                for name, sha in compiler["inputs_sha256"].items()), "selected compiler changed")
    if "java_context_sha256" in record:
        path = folder / java_project.CONTEXT_FILE
        require(digest(path) == record["java_context_sha256"], "retained Java context changed")
        java_project.verify_attempt(folder, strict_json(path.read_bytes()))
