"""Derive helper namespace relocation from actual application and template classes."""
from collections.abc import Callable
import json
from pathlib import Path

import java_classpath as classpath
import java_provider as provider
import otelc_capture as capture

PACKAGES = ("io.quux.otelc.methods.", "io.quux.otelc.lifecycle.",
            "io.quux.otelc.witness.probe.", "io.quux.otelc.http.")
PROOF = "helper-proof"


def packages(root: Path, paths: list[Path], context: dict) -> dict:
    """No filename or producer claim can declare a collision or choose its namespace."""
    entries = classpath.jar_members(root / provider.EXTENSION)
    active = [name for name in PACKAGES if any(entry.startswith(name.replace(".", "/")) for entry in entries)]
    names = set()
    for path in paths:
        if path.is_dir():
            names.update(classpath.inspect(path)["classes"])
    for entry in context["entries"]:
        names.update(entry["classes"])
    if not any(name.startswith(tuple(active)) for name in names):
        return {}
    names.update(name[:-6].replace("/", ".") for name in entries)
    sha = capture.file_digest(root / provider.EXTENSION)
    sequence = 0
    prefix = "io.quux.otelc.generated.h" + sha[:16] + "x"
    while any(name.startswith(prefix + str(sequence) + ".") for name in names):
        sequence += 1
    return {name: prefix + str(sequence) + "." + name.split(".")[-2] + "." for name in active}


def properties(mapping: dict) -> str:
    """These derived ASCII package names need no application-controlled escaping."""
    return "".join(key + "=" + value + "\n" for key, value in sorted(mapping.items()))


def prepare(root: Path, paths: list[Path], context: dict, java: Path, folder: Path,
            environment: dict, execute: Callable) -> None:
    """Reproduce the selected pinned helper transformation before SDK preparation."""
    mapping = packages(root, paths, context)
    proof = folder / PROOF
    proof.mkdir()
    record = {"packages": mapping, "template_sha256": capture.file_digest(root / provider.EXTENSION),
              "tool_sha256": capture.file_digest(root / provider.HELPER)}
    if mapping:
        plan = proof / "helpers.properties"
        plan.write_text(properties(mapping))
        result = execute([java, "-cp", root / provider.HELPER, "io.quux.otelc.tools.HelperRelocator",
                          root / provider.EXTENSION, proof / "helpers-extension.jar", plan],
                         proof, environment, proof / "build")
        provider.require(result.returncode == 0, "independent helper relocation failed")
        record["generated_sha256"] = capture.file_digest(proof / "helpers-extension.jar")
    (proof / "binding.json").write_text(json.dumps(record, indent=2) + "\n")


def verify(root: Path, paths: list[Path], context: dict, folder: Path, runtime: Path) -> tuple[Path, set[Path]]:
    """Require exact independently derived helper bytes, properties and descriptor."""
    mapping = packages(root, paths, context)
    proof = folder / PROOF
    record = capture.strict_json((proof / "binding.json").read_bytes())
    expected = {"packages": mapping, "template_sha256": capture.file_digest(root / provider.EXTENSION),
                "tool_sha256": capture.file_digest(root / provider.HELPER)}
    if not mapping:
        provider.require(record == expected and not any((runtime / name).exists() for name in
                         ("helpers-extension.jar", "helpers.properties", "helpers.json")),
                         "unexpected helper relocation")
        return root / provider.EXTENSION, set()
    generated = proof / "helpers-extension.jar"
    expected["generated_sha256"] = capture.file_digest(generated)
    provider.require(record == expected and (proof / "helpers.properties").read_text() == properties(mapping),
                     "independent helper proof changed")
    extension = runtime / "helpers-extension.jar"
    provider.require(capture.file_digest(extension) == expected["generated_sha256"]
                     and (runtime / "helpers.properties").read_text() == properties(mapping),
                     "private helper bytes or mapping differ")
    descriptor = {"schema_version": 1, "kind": "otelc.java-helper-map", **expected}
    provider.require(capture.strict_json((runtime / "helpers.json").read_bytes()) == descriptor,
                     "private helper descriptor differs")
    return extension, {runtime / name for name in ("helpers-extension.jar", "helpers.properties", "helpers.json")}
