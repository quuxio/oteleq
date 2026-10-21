"""Retain compiler-owned class origins and bind prepared Java application inputs."""
from collections.abc import Callable
import hashlib
import json
from pathlib import Path
import shutil

from otelc_capture import strict_json

FRONTEND = Path(__file__).with_name("OteleqCompile.java")
MAX_METADATA = 16 * 1024 * 1024


def require(condition: bool, reason: str) -> None:
    """An incomplete build identity cannot qualify an application launch."""
    if not condition:
        raise ValueError("Java build: " + reason)


def digest(path: Path) -> str:
    """Hash stable, bounded project products without invoking application code."""
    value = hashlib.sha256()
    with path.open("rb") as stream:
        for block in iter(lambda: stream.read(1024 * 1024), b""):
            value.update(block)
    return value.hexdigest()


def files(root: Path) -> dict[str, str]:
    """Refuse links and preserve the complete private project input set."""
    result = {}
    for path in sorted(root.rglob("*")):
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
             generated: set[Path], provenance: str) -> dict:
    """Every class must have one compiler source origin read from frozen bytes."""
    require(type(metadata) is dict and set(metadata) == {"schema_version", "success", "java_version", "options", "source_reads_sha256", "outputs"}
            and metadata.get("schema_version") == 1
            and type(metadata.get("schema_version")) is int and metadata.get("success") is True,
            "unsupported or unsuccessful compiler result")
    require(type(metadata["java_version"]) is str and metadata["java_version"]
            and metadata["options"] == ["-encoding", "UTF-8", "-proc:none", "-implicit:class",
                                       "-classpath", str(project), "-d", str(classes)],
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
          classes: Path, folder: Path, environment: dict, execute: Callable) -> dict:
    """Compile private source, retain origins, and emit the public prepared manifest."""
    project = project.resolve(strict=True)
    folder = folder.resolve()
    classes = classes.resolve()
    require(classes.is_relative_to(folder) and not classes.is_relative_to(project) and not classes.exists(),
            "class output must be new and outside the private source")
    require(not folder.is_relative_to(project), "build records must be outside the private source")
    original = files(project)
    sources = [contained(str(path.resolve()), project) for path in sources]
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
    command = [java, "-cp", isolated, frontend, project, classes, *sources]
    result = execute(command, project, environment, folder / "build", max_output_bytes=MAX_METADATA)
    require(not result.returncode, "compilation failed; inspect build/stderr")
    metadata = strict_json(result.stdout)
    require(files(project) == original and compiler_inputs(java, frontend) == tool_inputs,
            "private source or compiler changed during compilation")
    (folder / "java-compiler.json").write_text(json.dumps(metadata, indent=2) + "\n")
    compiler = {"driver": "JDK JavaCompiler file manager", "inputs_sha256": tool_inputs,
                "argv": list(map(str, command)), "compiler_metadata_sha256": digest(folder / "java-compiler.json")}
    (folder / "java-compiler-identity.json").write_text(json.dumps(compiler, indent=2) + "\n")
    provenance = "oteleq.jdk-file-manager-v1:" + digest(folder / "java-compiler-identity.json")
    bound = bindings(metadata, project, classes, original, set(sources[1:]), provenance)
    require(main in bound, "generated main has no compiler binding")
    application = {"schema_version": 1, "main_class": main, "classpath": [str(classes)], "bindings": bound}
    (folder / "prepared-application.json").write_text(json.dumps(application, indent=2) + "\n")
    record = {"schema_version": 1, "source_sha256": original, "classes_sha256": files(classes),
              "main_class": main, "compiler_metadata_sha256": digest(folder / "java-compiler.json"),
              "compiler_identity_sha256": digest(folder / "java-compiler-identity.json"),
              "prepared_application_sha256": digest(folder / "prepared-application.json")}
    (folder / "build-identities.json").write_text(json.dumps(record, indent=2) + "\n")
    return application


def verify(project: Path, classes: Path, folder: Path) -> None:
    """Recheck the actual source, products, compiler and retained build records."""
    record = strict_json((folder / "build-identities.json").read_bytes())
    require(record.get("schema_version") == 1 and type(record.get("schema_version")) is int,
            "unsupported build identity")
    require(files(project) == record["source_sha256"] and files(classes) == record["classes_sha256"],
            "application source or class products changed")
    for name, key in (("java-compiler.json", "compiler_metadata_sha256"),
                      ("java-compiler-identity.json", "compiler_identity_sha256"),
                      ("prepared-application.json", "prepared_application_sha256")):
        require(digest(folder / name) == record[key], "retained compiler evidence changed: " + name)
    compiler = strict_json((folder / "java-compiler-identity.json").read_bytes())
    require(all(Path(name).is_file() and digest(Path(name)) == sha
                for name, sha in compiler["inputs_sha256"].items()), "selected compiler changed")
