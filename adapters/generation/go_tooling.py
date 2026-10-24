"""Independently bind the private Go weaver to its pinned source and real tools."""

import base64
from dataclasses import dataclass
import hashlib
import json
import os
from pathlib import Path
from collections.abc import Callable

import go_context
import go_files as files
from go_provider import data_seal, require, same
import otelc_capture as capture

DIRECTORY = "build/go-upstream-scope"
MANIFEST = "scope-source.json"
BASE_FIELDS = {"schema_version", "module", "version", "module_sum", "module_go_sum", "go", "go_sha256",
               "go_version", "platform", "weaver", "weaver_sha256", "bundle", "bundle_sha256", "build_metadata"}
SCOPE_FIELDS = {"patch_profile", "source_manifest_sha256", "version_output"}
MODULE = "go.opentelemetry.io/otelc"
VERSION = "v1.0.1"
PRIVATE_VERSION = VERSION + "+quux.scope.1"
MODULE_SUM = "h1:HSgkn7kGhHe4kjtv+ex0ZFRbC66sc+c5KcEHgDXuwxE="
MODULE_GO_SUM = "h1:fOCi1cByxU0s3sOwXPp5/gAnxsPl5KsTM9elgtBIESE="
PATCH_PROFILE = "raw-empty-globals-v1"
PATCH_FILE = "tool/internal/instrument/apply_func.go"
PATCH_BEFORE = "16810f7c3718137c906e76a9e364d2e346172f959e0f8873c3180a3a7898e820"
PATCH_AFTER = "d7f7e85feb4608e2c8168753f01b822e16491b43fb72420074129f183adf1422"


def module_hash(catalogue: object, *, prefix: str = "") -> str:
    """Compute Go's Hash1 from checked file digests, without executing metadata."""
    require(type(catalogue) is dict and 0 < len(catalogue) <= files.MAX_FILES
            and all(type(name) is str for name in catalogue),
            "invalid Go weaver source catalogue")
    digest = hashlib.sha256()
    for name, value in sorted(catalogue.items()):
        files.relative(name)
        require("\n" not in name and "\r" not in name and ".git" not in Path(name).parts
                and type(value) is str and len(value) == 64 and all(char in "0123456789abcdef" for char in value),
                "invalid Go weaver source name or digest")
        digest.update((value + "  " + prefix + name + "\n").encode("utf-8"))
    return "h1:" + base64.b64encode(digest.digest()).decode("ascii")


def source_snapshot(root: Path) -> files.Snapshot:
    """VCS inputs cannot hide inside a module snapshot's normal Git exclusion."""
    value = files.freeze(root)
    require(not any(".git" in path.relative_to(root).parts for path in capture.tree_paths(root)),
            "unexpected VCS input in private Go weaver source")
    return value


def source_manifest(value: object, source: files.Snapshot) -> None:
    """Authenticate all original module bytes and the one exact patched file."""
    pins = {"schema_version": 1, "kind": "otelc.go-weaver-source", "profile": PATCH_PROFILE,
            "base_module": MODULE, "base_version": VERSION, "module_sum": MODULE_SUM,
            "module_go_sum": MODULE_GO_SUM, "version": PRIVATE_VERSION,
            "patch": {"file": PATCH_FILE, "before_sha256": PATCH_BEFORE, "after_sha256": PATCH_AFTER}}
    require(type(value) is dict and set(value) == set(pins) | {"base_files", "files"}
            and same({name: value[name] for name in pins}, pins), "unsupported Go weaver source manifest")
    base = value["base_files"]
    require(type(base) is dict and base.get(PATCH_FILE) == PATCH_BEFORE and "go.mod" in base,
            "missing original Go weaver source identities")
    require(module_hash(base, prefix=MODULE + "@" + VERSION + "/") == MODULE_SUM
            and module_hash({"go.mod": base["go.mod"]}) == MODULE_GO_SUM,
            "Go weaver source catalogue differs from the pinned upstream module")
    expected = base | {PATCH_FILE: PATCH_AFTER}
    require(same(value["files"], expected)
            and {name: item["sha256"] for name, item in source.identities.items()} == expected,
            "Go weaver source differs from the single reviewed backport")


@dataclass(frozen=True)
class Binding:
    """Caller-held tools, complete source and fixed metadata-query observations."""

    directory: Path
    tools: dict
    source: files.Snapshot
    reads: dict
    queries: list[dict]
    seal: str

    def state(self) -> dict:
        return {"directory": str(self.directory), "tools": self.tools, "source": self.source.sealed_metadata,
                "reads": self.reads, "queries": self.queries}

    def verify(self) -> None:
        """Rehashed repairs and altered nested dictionaries cannot replace accepted inputs."""
        require(data_seal(self.state()) == self.seal, "accepted Go weaver tooling metadata changed")
        require(source_snapshot(self.source.root) == self.source, "accepted Go weaver source changed")
        for name, expected in self.reads.items():
            identity, facts, _ = files.file(Path(name))
            require(same([identity, list(facts)], expected), "accepted Go weaver input changed: " + name)
        if self.queries:
            checked_queries(self)


def binding(directory: Path, tools: dict, source: files.Snapshot, reads: dict, queries: list[dict]) -> Binding:
    """Seal the caller's complete source, tool and metadata-query observations."""
    value = Binding(directory, tools, source, reads, queries, "")
    return Binding(directory, tools, source, reads, queries, data_seal(value.state()))


def read(directory: Path, compiler: Path) -> Binding:
    """Inspect caller-selected files only; this does not admit an application build."""
    require(directory.is_absolute() and directory.resolve(strict=True) == directory and directory.is_dir()
            and compiler.is_absolute() and compiler.resolve(strict=True) == compiler,
            "Go weaver tooling paths must be caller-selected and canonical")
    reads = {}

    def observe(path: Path, *, content: bool = False) -> tuple[dict, bytes]:
        identity, facts, raw = files.file(path, files.MAX_METADATA_BYTES if content else files.MAX_FILE_BYTES,
                                          keep=content)
        reads[str(path)] = [identity, list(facts)]
        return identity, raw

    _, raw = observe(directory / "toolchain.json", content=True)
    tools = capture.strict_json(raw)
    pins = {"schema_version": 2, "module": MODULE, "version": VERSION, "module_sum": MODULE_SUM,
            "module_go_sum": MODULE_GO_SUM, "go_version": "go1.27.3", "patch_profile": PATCH_PROFILE,
            "version_output": "otelc version " + PRIVATE_VERSION, "bundle_sha256": go_context.BUNDLE_SHA256}
    require(type(tools) is dict and set(tools) == BASE_FIELDS | SCOPE_FIELDS
            and same({name: tools[name] for name in pins}, pins)
            and tools["go"] == str(compiler) and tools["weaver"] == str(directory / "bin/otelc")
            and type(tools["build_metadata"]) is str and type(tools["platform"]) is dict
            and set(tools["platform"]) == {"GOOS", "GOARCH"}
            and all(type(item) is str and bool(item) for item in tools["platform"].values()),
            "unsupported scope-safe Go toolchain manifest")
    for name in ("go", "weaver", "bundle"):
        require(type(tools[name]) is str, "invalid Go weaver input path")
        path = Path(tools[name])
        observed, _ = observe(path)
        require(observed["sha256"] == tools[name + "_sha256"], "Go weaver tool bytes differ: " + name)
    require(os.access(compiler, os.X_OK) and os.access(directory / "bin/otelc", os.X_OK),
            "Go compiler or private weaver is not executable")
    identity, raw = observe(directory / MANIFEST, content=True)
    require(identity["sha256"] == tools["source_manifest_sha256"], "Go weaver source manifest changed")
    source = source_snapshot(directory / "source")
    source_manifest(capture.strict_json(raw), source)
    result = binding(directory, tools, source, reads, [])
    result.verify()
    return result


def checked_queries(value: Binding) -> None:
    """The compiler and fixed weaver must report the installed native/private profile."""
    go, weaver = value.tools["go"], str(value.directory / "bin/otelc")
    commands = [[go, "env", "-json", "GOROOT", "GOVERSION", "GOOS", "GOARCH", "GOHOSTOS", "GOHOSTARCH"],
                [go, "version", "-m", weaver], [weaver, "version"]]
    require(type(value.queries) is list and len(value.queries) == 3, "missing Go weaver metadata queries")
    for row, command in zip(value.queries, commands):
        require(type(row) is dict and set(row) == {"command", "stdout"} and same(row["command"], command)
                and type(row["stdout"]) is str, "Go weaver metadata query recipe changed")
    environment = capture.strict_json(value.queries[0]["stdout"])
    platform = value.tools["platform"]
    expected = {"GOROOT": str(Path(go).parent.parent), "GOVERSION": "go1.27.3",
                **platform, "GOHOSTOS": platform["GOOS"], "GOHOSTARCH": platform["GOARCH"]}
    metadata = value.queries[1]["stdout"]
    require(same(environment, expected) and metadata == value.tools["build_metadata"]
            and "\tmod\t" + MODULE + "\t(devel)\t" in metadata
            and "\tpath\t" + MODULE + "/tool/cmd/otelc\n" in metadata
            and value.queries[2]["stdout"].strip() == "otelc version " + PRIVATE_VERSION,
            "Go compiler/private weaver metadata differs from the selected installation")


def prepare(directory: Path, compiler: Path, execute: Callable) -> Binding:
    """Capture three fixed read-only tool queries before any application build."""
    value = read(directory, compiler)
    go, weaver = str(compiler), str(directory / "bin/otelc")
    commands = [[go, "env", "-json", "GOROOT", "GOVERSION", "GOOS", "GOARCH", "GOHOSTOS", "GOHOSTARCH"],
                [go, "version", "-m", weaver], [weaver, "version"]]
    queries = []
    for command in commands:
        result = execute(command, directory, max_output_bytes=1024 * 1024)
        require(result.returncode == 0 and not result.stderr and len(result.stdout) <= 1024 * 1024,
                "Go weaver read-only metadata query failed")
        queries.append({"command": command, "stdout": result.stdout.decode("utf-8")})
    result = binding(directory, value.tools, value.source, value.reads, queries)
    result.verify()
    return result
