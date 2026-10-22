"""Independent selected-JDK archive evidence for the new Java launch contract."""
from collections.abc import Callable
import json
import os
from pathlib import Path
import shutil
import zipfile

import java_classpath as classpath
import otelc_capture as capture

PROFILE = "java-runtime-archives-v1"
FRONTEND = Path(__file__).with_name("OteleqArchives.java")
JAVA_OPTIONS = {"JAVA_TOOL_OPTIONS", "JDK_JAVA_OPTIONS", "_JAVA_OPTIONS"}
MAX_METADATA = 16 * 1024 * 1024


def require(condition: bool, reason: str) -> None:
    if not condition:
        raise ValueError("Java runtime archives: " + reason)


def inputs(java: Path, frontend: Path) -> dict[str, str]:
    """Bind the actual JDK and diagnostic resolver, independent of SDK metadata."""
    java = java.resolve(strict=True)
    modules = java.parent.parent / "lib/modules"
    require(all(path.is_file() and not path.is_symlink() for path in (java, modules, frontend)),
            "missing or linked JDK/resolver input")
    return {str(path): capture.file_digest(path) for path in (java, modules, frontend)}


def catalogues(paths: list[Path]) -> dict[str, dict]:
    """Retain raw class members separately from effective runtime classes."""
    require(0 < len(paths) <= 256 and len(paths) == len(set(paths)), "invalid ordered classpath")
    result, total = {}, 0
    for path in paths:
        require(path.is_absolute() and path.resolve(strict=True) == path and not path.is_symlink()
                and os.pathsep not in str(path) and "*" not in str(path), "unsafe classpath location")
        if not path.is_dir():
            total += path.stat().st_size
            require(total <= classpath.MAX_TOTAL_BYTES, "combined archives exceed their byte budget")
            before = classpath.digest(path)
            members = classpath.jar_members(path)
            require(classpath.digest(path) == before, "archive changed during inventory")
            result[str(path)] = {"sha256": before, "members": members}
    return result


def validate(value: object, paths: list[Path], raw: dict[str, dict]) -> None:
    """Require the closed profile and exact physical members in every selected JAR."""
    if not isinstance(value, dict):
        raise ValueError("Java runtime archives: unsupported resolution record")
    require(type(value) is dict and set(value) == {"schema_version", "profile", "jdk_feature", "archives"}
            and type(value["schema_version"]) is int and value["schema_version"] == 1
            and value["profile"] == PROFILE and type(value["jdk_feature"]) is int
            and value["jdk_feature"] >= 9 and type(value["archives"]) is list,
            "unsupported resolution record")
    expected = [(index, path) for index, path in enumerate(paths) if str(path) in raw]
    require(len(value["archives"]) == len(expected), "missing or extra archive")
    defined = set()
    for path in paths:
        if path.is_dir():
            names = set(classpath.inspect(path)["classes"])
            require(not defined.intersection(names), "duplicate class definitions")
            defined.update(names)
    for archive, (index, path) in zip(value["archives"], expected):
        require(type(archive) is dict and set(archive) == {"classpath_index", "path", "sha256", "multi_release", "classes"}
                and type(archive["classpath_index"]) is int and archive["classpath_index"] == index
                and archive["path"] == str(path) and archive["sha256"] == raw[str(path)]["sha256"]
                and type(archive["multi_release"]) is bool and type(archive["classes"]) is dict
                and len(archive["classes"]) <= classpath.MAX_FILES, "archive identity differs")
        require(not defined.intersection(archive["classes"]), "duplicate class definitions")
        defined.update(archive["classes"])
        for name, member in archive["classes"].items():
            require(type(name) is str and type(member) is dict and set(member) == {"entry", "sha256"}
                    and type(member["entry"]) is str, "invalid selected class member")
            logical = name.replace(".", "/") + ".class"
            require(classpath.binary_name(logical) == name and "\\" not in logical
                    and member["entry"] in raw[str(path)]["members"]
                    and member["sha256"] == raw[str(path)]["members"][member["entry"]],
                    "selected class bytes differ")
            actual = member["entry"]
            require(actual == logical or actual.startswith("META-INF/versions/")
                    and actual.split("/", 3)[-1] == logical, "selected member has another binary name")


def inspect(paths: list[Path], java: Path, folder: Path, environment: dict,
            execute: Callable) -> dict:
    """Resolve with JarFile only; the isolated probe cannot initialise application code."""
    require(not JAVA_OPTIONS.intersection(environment), "ambient JVM options are unsupported")
    raw = catalogues(paths)
    require(folder.is_absolute() and folder.resolve() == folder and not folder.exists()
            and all(not folder.is_relative_to(path) for path in paths),
            "resolver output must be new and outside classpath inputs")
    folder.mkdir(parents=True)
    isolated = folder / "empty-classpath"
    isolated.mkdir()
    frontend = folder / FRONTEND.name
    shutil.copyfile(FRONTEND, frontend)
    expected = inputs(java, frontend)
    command = [java, "-Xshare:off", "-cp", isolated, frontend, *paths]
    result = execute(command, folder, environment, folder / "probe", max_output_bytes=MAX_METADATA)
    require(result.returncode == 0, "selected JDK resolution failed; inspect probe/stderr")
    value = capture.strict_json(result.stdout)
    require(inputs(java, frontend) == expected and catalogues(paths) == raw,
            "selected resolver, JDK or archives changed")
    validate(value, paths, raw)
    record = {"resolution": value, "raw_archives": raw, "inputs_sha256": expected,
              "argv": list(map(str, command))}
    (folder / "resolution.json").write_text(json.dumps(record, indent=2) + "\n")
    return record


def verify(claim: object, record: dict, paths: list[Path], *, java: Path, folder: Path) -> None:
    """A producer claim must match independent member identities, even for equal bytes."""
    raw = catalogues(paths)
    expected = [java, "-Xshare:off", "-cp", folder / "empty-classpath", folder / FRONTEND.name, *paths]
    require(set(record) == {"resolution", "raw_archives", "inputs_sha256", "argv"}
            and raw == record["raw_archives"] and record["inputs_sha256"] == inputs(java, folder / FRONTEND.name)
            and record["argv"] == list(map(str, expected)),
            "retained resolution inputs changed")
    require(capture.strict_json((folder / "probe/stdout").read_bytes()) == record["resolution"],
            "retained selected-JDK result changed")
    validate(claim, paths, raw)
    require(claim == record["resolution"], "producer resolution differs from the selected JDK")


def materialise(record: dict, paths: list[Path], destination: Path, *, java: Path, folder: Path) -> list[Path]:
    """Copy exact selected bytes for metadata inspection, never for application launch."""
    verify(record["resolution"], record, paths, java=java, folder=folder)
    require(destination.is_absolute() and destination.resolve() == destination and not destination.exists()
            and all(not destination.is_relative_to(path) for path in paths),
            "metadata view must be new and outside classpath inputs")
    destination.mkdir(parents=True)
    result = list(paths)
    for archive in record["resolution"]["archives"]:
        target = destination / str(archive["classpath_index"]).zfill(4)
        target.mkdir()
        with zipfile.ZipFile(archive["path"]) as source:
            for name, member in archive["classes"].items():
                path = target / (name.replace(".", "/") + ".class")
                path.parent.mkdir(parents=True, exist_ok=True)
                path.write_bytes(source.read(member["entry"]))
                require(classpath.digest(path) == member["sha256"], "selected metadata bytes changed")
        result[archive["classpath_index"]] = target
    verify(record["resolution"], record, paths, java=java, folder=folder)
    return result
