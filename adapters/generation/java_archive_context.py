"""Freeze effective Java dependency classes and verify fresh runtime resolutions."""
from collections.abc import Callable
from pathlib import Path

import java_archives as archives
import java_classpath as classpath
import java_profiles as profiles
import otelc_capture as capture

PROFILE = "source-classpath-archives-v1"
PROBE = "archive-probe"


def enabled(options: dict) -> bool:
    """Only an explicit consumer profile admits versioned archive layouts."""
    return options.get("profile") == profiles.ARCHIVES


def configured(context: dict | None) -> bool:
    return context is not None and context.get("profile") == PROFILE


def fields(entry: dict, active: bool) -> tuple[str, ...]:
    """Schema-1 catalogues keep their original exact record shape."""
    return classpath.RECORD_FIELDS + (("members", "multi_release") if active and entry["kind"] == "jar" else ())


def inspect(path: Path, *, expected: dict | None = None, feature: int | None = None) -> dict:
    """Check physical inputs; selection is attested separately by the actual JDK."""
    if path.is_dir():
        return classpath.inspect(path)
    raw = archives.catalogues([path])[str(path)]
    result = {"kind": "jar", "files": {"": raw["sha256"]}, "directories": [], "members": raw["members"],
              "classes": expected["classes"] if expected else {},
              "multi_release": expected["multi_release"] if expected else False}
    if expected is not None:
        value = {"schema_version": 1, "profile": archives.PROFILE, "jdk_feature": feature,
                 "archives": [{"classpath_index": 0, "path": str(path), "sha256": raw["sha256"],
                               "multi_release": result["multi_release"], "classes": result["classes"]}]}
        archives.validate(value, [path], {str(path): raw})
    return result


def jdk(java: Path, frontend: Path) -> dict:
    """Only known selected-JDK files may define the portable runtime identity."""
    result = archives.inputs(java, frontend)
    del result[str(frontend)]
    return result


def bind(context: dict, root: Path, java: Path, environment: dict, execute: Callable) -> None:
    """Resolve frozen private copies once; retain the literal probe as provenance."""
    empty = root / "empty-classes"
    empty.mkdir()
    paths = [empty, *(root / entry["owned"] for entry in context["entries"])]
    record = archives.inspect(paths, java, root / PROBE, environment, execute)
    context.update(schema_version=2, profile=PROFILE,
                   archive_feature=record["resolution"]["jdk_feature"],
                   archive_jdk=jdk(java, root / PROBE / archives.FRONTEND.name))
    for selected in record["resolution"]["archives"]:
        entry = context["entries"][selected["classpath_index"] - 1]
        entry.update(classes=selected["classes"], multi_release=selected["multi_release"])
    names = set()
    for entry in context["entries"]:
        classpath.require(not names.intersection(entry["classes"]), "duplicate class definitions in declared classpath")
        names.update(entry["classes"])


def verify_jdk(context: dict, root: Path, java: Path) -> None:
    """Exports retain the original probe bytes while guarding the actual selected JDK."""
    frontend = root / PROBE / archives.FRONTEND.name
    classpath.require(capture.file_digest(frontend) == capture.file_digest(archives.FRONTEND)
                      and jdk(java, frontend) == context["archive_jdk"], "archive frontend or selected JDK changed")
    record = capture.strict_json((root / PROBE / "resolution.json").read_bytes())
    classpath.require(record["resolution"]["jdk_feature"] == context["archive_feature"],
                      "frozen archive JDK feature differs")


def expected_resolution(paths: list[Path], context: dict) -> dict:
    """Rebind only known private paths; keep every selected member identity intact."""
    rows = []
    for index, entry in enumerate(context["entries"], 1):
        if entry["kind"] == "jar":
            rows.append({"classpath_index": index, "path": str(paths[index]), "sha256": entry["files"][""],
                         "multi_release": entry["multi_release"], "classes": entry["classes"]})
    return {"schema_version": 1, "profile": archives.PROFILE,
            "jdk_feature": context["archive_feature"], "archives": rows}


def prepare_attempt(paths: list[Path], context: dict, java: Path, folder: Path,
                    environment: dict, execute: Callable) -> None:
    """A fresh JDK result must agree with the frozen dependency catalogue before launch."""
    record = archives.inspect(paths, java, folder / PROBE, environment, execute)
    archives.require(record["resolution"] == expected_resolution(paths, context),
                     "private dependency selection differs from the frozen catalogue")


def verify_attempt(claim: object, paths: list[Path], context: dict, java: Path, folder: Path) -> None:
    """Reject forged producer and cached catalogue claims against the original fresh probe."""
    record = capture.strict_json((folder / PROBE / "resolution.json").read_bytes())
    archives.verify(claim, record, paths, java=java, folder=folder / PROBE)
    archives.require(record["resolution"] == expected_resolution(paths, context),
                     "private dependency selection differs from the frozen catalogue")
