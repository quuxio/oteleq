"""Bind source-build3 products to caller-owned Go inputs and a fixed recipe."""

from dataclasses import dataclass
import os
from pathlib import Path

import otelc_capture as capture
import go_files as files
import go_hooks
from go_provider import data_seal, require, same, selection_digest

FIELDS = {"schema_version", "kind", "root", "target", "selection", "inputs", "sdk_inputs",
          "private_inputs", "context_inputs", "inventory", "plain", "instrumented", "modules_before",
          "modules_after", "settings", "toolchain", "commands", "source_complete", "launch_inputs", "source_roster", "runtime_protocols"}
INVENTORY_FIELDS = {"schema_version", "root", "target", "main", "functions", "types", "allocations",
                    "files", "packages", "compiler_inputs"}
SELECTION_FIELDS = {"schema_version", "kind", "main", "functions", "types", "allocations",
                    "releases", "context", "source_complete", "sha256"}
FUNCTION_FIELDS = {"file", "gap", "generic", "line", "name", "package", "parameters", "receiver",
                   "receiver_id", "results", "sha256", "symbol", "variadic"}
SOURCE_SUFFIXES = {".go", ".s", ".S", ".h", ".syso", ".c", ".cc", ".cpp", ".cxx", ".m", ".mm", ".f", ".f90"}
REPLACEMENTS = {"go.opentelemetry.io/otelc/pkg": "pkg",
                "go.opentelemetry.io/otelc/pkg/runtime": "pkg/runtime",
                "go.opentelemetry.io/otelc/instrumentation/runtime": "instrumentation/runtime",
                "go.opentelemetry.io/otelc/instrumentation/go.opentelemetry.io/otel/sdk/trace":
                    "instrumentation/go.opentelemetry.io/otel/sdk/trace"}


@dataclass(frozen=True)
class Target:
    """Selected declaration facts from the consumer's own source inventory."""

    name: str
    file: str
    line: int
    parameters: int
    receiver_id: str = ""


@dataclass(frozen=True)
class Intent:
    """All expected roots, selectors and compiler facts precede provider build."""

    directory: Path
    original: files.Snapshot
    sdk: files.Snapshot
    target: str
    targets: tuple[Target, ...]
    toolchain: dict
    settings: dict
    modules: list[dict]
    context: files.Snapshot


def caller_state(intent: Intent) -> dict:
    """Keep caller-owned compiler data fixed while producer records are read."""
    return {"directory": str(intent.directory), "target": intent.target,
            "original": intent.original.sealed_metadata, "sdk": intent.sdk.sealed_metadata,
            "context": intent.context.sealed_metadata, "targets": [vars(target) for target in intent.targets],
            "toolchain": intent.toolchain, "settings": intent.settings, "modules": intent.modules}


def retained_state(receipt: dict, identity: dict, private: files.Snapshot, sdk: files.Snapshot,
                   context: files.Snapshot, inventory: dict, evidence: dict) -> dict:
    """Bind accepted records as values as well as checking their original files."""
    return {"receipt": receipt, "identity": identity, "inventory": inventory, "evidence": evidence,
            "private": private.sealed_metadata, "sdk": sdk.sealed_metadata, "context": context.sealed_metadata}


@dataclass(frozen=True)
class Build:
    """Checked retained products and independent snapshots for every later use."""

    intent: Intent
    receipt: dict
    identity: dict
    private: files.Snapshot
    sdk: files.Snapshot
    context: files.Snapshot
    inventory: dict
    evidence: dict[str, tuple]
    caller_seal: str
    metadata_seal: str

    def verify(self) -> None:
        """Preserve all original facts and actual private products after execution."""
        require(data_seal(caller_state(self.intent)) == self.caller_seal
                and data_seal(retained_state(self.receipt, self.identity, self.private, self.sdk,
                                             self.context, self.inventory, self.evidence)) == self.metadata_seal,
                "accepted Go build metadata changed")
        for snapshot in (self.intent.original, self.intent.sdk, self.intent.context, self.private, self.sdk, self.context):
            snapshot.verify()
        go_hooks.verify(self.intent.original, self.private, self.receipt["selection"], self.inventory,
                        self.intent.settings["Module"]["Path"])
        require(same(files.identity(self.intent.directory / "build.json"), self.identity), "Go build receipt changed")
        for name in ("plain", "instrumented"):
            require(same(files.identity(self.intent.directory / name), self.receipt[name]), "Go binary changed")
        require(same(files.identity(self.intent.directory / "inspection/inventory.json"), self.receipt["inventory"]),
                "Go compiler inventory changed")
        verify_tools(self.receipt["toolchain"], self.intent.toolchain)
        for name, expected in self.evidence.items():
            observed, stable, _ = files.file(self.intent.directory / name)
            require(same(observed, expected[0]) and stable == expected[1], "Go compiler evidence changed: " + name)


def fields(value: object, expected: set[str], label: str) -> dict:
    require(type(value) is dict and set(value) == expected, "invalid Go build " + label + " fields")
    return value


def validate_intent(intent: Intent) -> None:
    """Reject malformed caller declarations before reading any returned product."""
    output = intent.directory
    require(isinstance(output, Path) and output.is_absolute() and output.resolve(strict=True) == output,
            "Go build directory must be canonical")
    require(all(type(value) is files.Snapshot for value in (intent.original, intent.sdk, intent.context))
            and not any(output.is_relative_to(root) or root.is_relative_to(output)
                        for root in (intent.original.root, intent.sdk.root, intent.context.root)), "Go build output overlaps source")
    require(type(intent.target) is str and (intent.target == "." or intent.target.startswith("./")
            and files.relative(intent.target[2:]) == intent.target[2:]), "Go build requires one fixed main-package target")
    require(type(intent.targets) is tuple and 0 < len(intent.targets) <= files.MAX_FILES
            and all(type(target) is Target for target in intent.targets)
            and all(type(target.name) is str for target in intent.targets)
            and len({target.name for target in intent.targets}) == len(intent.targets), "invalid Go target denominator")
    require("go.mod" in intent.original.identities and type(intent.settings) is dict
            and type(intent.settings.get("Module")) is dict
            and type(intent.settings["Module"].get("Path")) is str, "missing Go module identity")
    for target in intent.targets:
        require(type(target.name) is str and bool(target.name) and "\0" not in target.name
                and type(target.line) is int and target.line > 0 and type(target.parameters) is int
                and target.parameters >= 0 and type(target.receiver_id) is str, "invalid Go selected declaration")
        files.relative(target.file)


def verify_tools(value: object, expected: dict) -> None:
    """Only the caller's pinned paths are read; records never select another tool."""
    require(type(value) is dict and same(value, expected), "Go build selected another toolchain")
    for name in ("go", "weaver", "bundle"):
        path = Path(expected[name])
        require(files.identity(path)["sha256"] == expected[name + "_sha256"], "selected Go tool bytes changed")


def module_graph(value: object) -> dict[str, dict]:
    """A missing, repeated or malformed module cannot establish preservation."""
    require(type(value) is list and bool(value) and len(value) <= files.MAX_FILES, "missing Go module graph")
    result = {}
    for row in value:
        require(type(row) is dict and type(row.get("Path")) is str and bool(row["Path"])
                and row["Path"] not in result, "invalid or repeated Go module")
        result[row["Path"]] = row
    return result


def verify_modules(receipt: dict, intent: Intent, after_settings: dict) -> None:
    """Keep existing module resolutions and language/toolchain/runtime defaults."""
    require(same(receipt["modules_before"], intent.modules) and same(receipt["settings"], intent.settings),
            "Go original module settings or graph differ from caller inputs")
    before, after = module_graph(intent.modules), module_graph(receipt["modules_after"])
    names = ("Version", "Main", "Replace", "Sum", "GoModSum", "GoVersion")
    for name, row in before.items():
        require(name in after and same({key: row.get(key) for key in names},
                                      {key: after[name].get(key) for key in names}),
                "Go instrumentation changed an existing dependency: " + name)
    old_go, new_go = intent.settings.get("Go"), after_settings.get("Go")
    require(type(old_go) is str and type(new_go) is str and old_go.split(".")[:2] == new_go.split(".")[:2]
            and all(same(intent.settings.get(name), after_settings.get(name)) for name in ("Toolchain", "Godebug", "Module")),
            "Go instrumentation changed language, module, toolchain or GODEBUG settings")


def commands(intent: Intent) -> list[dict]:
    """Reconstruct fixed compiler invocations without executing recorded arguments."""
    root, output, go = intent.original.root, intent.directory, intent.toolchain["go"]
    private = output / "private"
    recipes = [([go, "mod", "edit", "-json"], root),
               ([go, "list", "-m", "-mod=readonly", "-json", "all"], root)]
    replacements = {name: output / "context" / suffix for name, suffix in REPLACEMENTS.items()}
    replacements["io.quux.otelc/go"] = output / "sdk"
    recipes += [([go, "mod", "edit", "-replace=" + name + "=" + str(path), "-require=" + name + "@v0.0.0"], private)
                for name, path in replacements.items()]
    recipes += [([go, "mod", "edit", "-require=go.opentelemetry.io/otel/sdk@v1.47.0"], private),
                ([go, "mod", "tidy"], private), ([go, "list", "-m", "-mod=readonly", "-json", "all"], private),
                ([go, "mod", "edit", "-json"], private), ([go, "mod", "verify"], root),
                ([go, "mod", "verify"], private),
                ([go, "build", "-mod=readonly", "-o", str(output / "plain"), intent.target], root),
                ([intent.toolchain["weaver"], "--work-dir", str(output / "weaver-work"), "go", "build",
                  "-mod=readonly", "-o", str(output / "instrumented"), intent.target], private)]
    return [{"argv": argv, "cwd": str(cwd), "exit_code": 0} for argv, cwd in recipes]


def source_inventory(value: object, intent: Intent) -> dict:
    """Every compiler input and selected declaration must bind the frozen source."""
    value = fields(value, INVENTORY_FIELDS, "compiler inventory")
    require(type(value["schema_version"]) is int and value["schema_version"] == 1
            and value["root"] == str(intent.original.root) and value["target"] == intent.target,
            "Go compiler inventory differs from caller root/target")
    main = intent.settings["Module"]["Path"] + ("/" + intent.target[2:] if intent.target != "." else "")
    require(value["main"] == main, "Go compiler main package differs from the caller target")
    for label in ("files", "compiler_inputs"):
        actual = value[label]
        require(type(actual) is dict and bool(actual) and len(actual) <= files.MAX_FILES, "missing Go compiler source inputs")
        for name, digest in actual.items():
            files.relative(name)
            require(name in intent.original.identities and digest == intent.original.identities[name]["sha256"],
                    "Go compiler source differs from frozen original: " + name)
    require(set(value["files"]) <= set(value["compiler_inputs"])
            and type(value["functions"]) is list, "Go declaration source is not a compiler input")
    identities = []
    for row in value["functions"]:
        row = fields(row, FUNCTION_FIELDS, "declaration")
        require(type(row.get("line")) is int and row["line"] > 0 and type(row.get("file")) is str
                and row["file"] in value["files"] and row.get("sha256") == value["files"][row["file"]]
                and type(row.get("name")) is str and type(row.get("symbol")) is str,
                "invalid Go compiler declaration identity")
        identities.append((row["file"], row["line"], row["name"], row["symbol"]))
    require(len(identities) == len(set(identities)), "repeated Go compiler declaration")
    return value


def selected(value: object, intent: Intent, inventory: dict) -> dict:
    """Admit declared scalar/receiver calls; other hook shapes stay unsupported."""
    value = fields(value, SELECTION_FIELDS, "selection")
    require(type(value["schema_version"]) is int and value["schema_version"] == 1
            and value["kind"] == "otelc.go-source-selection" and value["source_complete"] is False
            and value["main"] == inventory["main"] and same(value["context"], {"tasks": False, "http": False})
            and value["types"] == value["allocations"] == value["releases"] == [], "unsupported Go selection/hook profile")
    body = {name: item for name, item in value.items() if name != "sha256"}
    require(value["sha256"] == selection_digest(body), "Go selection digest differs")
    require(type(value["functions"]) is list and len(value["functions"]) == len(intent.targets)
            and bool(intent.targets), "Go selected callable denominator differs")
    rows = {row["name"]: row for row in value["functions"] if type(row) is dict and type(row.get("name")) is str}
    require(len(rows) == len(intent.targets) and set(rows) == {target.name for target in intent.targets},
            "Go selected callable identities differ")
    for target in intent.targets:
        row = rows[target.name]
        require(any(same(row, original) for original in inventory["functions"])
                and row["file"] == target.file and row["line"] == target.line
                and type(row.get("parameters")) is int and row["parameters"] == target.parameters
                and row.get("receiver_id") == target.receiver_id and row.get("generic") is False
                and row.get("variadic") is False and row.get("gap") == "", "Go selected declaration or supported shape differs")
    return value


def read(intent: Intent) -> Build:
    """Check one completed source-build3 without compiler or application execution."""
    validate_intent(intent)
    original_caller = data_seal(caller_state(intent))
    output = intent.directory
    for snapshot in (intent.original, intent.sdk, intent.context):
        snapshot.verify()
    receipt, identity = files.read(output / "build.json")
    receipt = fields(receipt, FIELDS, "receipt")
    require(type(receipt["schema_version"]) is int and receipt["schema_version"] == 3
            and same(receipt["runtime_protocols"], {"config": 2, "health": 4})
            and receipt["kind"] == "otelc.go-source-build" and receipt["source_complete"] is False
            and receipt["root"] == str(intent.original.root) and receipt["target"] == intent.target,
            "Go build root, target or schema differs")
    require(same(receipt["inputs"], intent.original.identities), "Go original input inventory differs")
    verify_tools(receipt["toolchain"], intent.toolchain)
    require(same(receipt["commands"], commands(intent)), "Go compiler command recipe differs")
    expected_commands = commands(intent)
    # commands.json is an array; read its bounded bytes without object projection.
    _, _, raw_commands = files.file(output / "commands.json", files.MAX_METADATA_BYTES, keep=True)
    require(same(capture.strict_json(raw_commands), expected_commands), "Go retained compiler command log differs")
    evidence = {}
    for name in ["build.json", "commands.json", "plain", "instrumented", "inspection/inventory.json",
                 *[f"command-{index}.{suffix}" for index in range(len(expected_commands)) for suffix in ("stdout", "stderr")]]:
        observed, stable, _ = files.file(output / name)
        evidence[name] = observed, stable
    after_settings, _ = files.read(output / "command-10.stdout")
    verify_modules(receipt, intent, after_settings)
    for name in ("plain", "instrumented"):
        require(os.access(output / name, os.X_OK) and same(files.identity(output / name), receipt[name]),
                "Go binary identity or executable permission differs")
    inventory, observed = files.read(output / "inspection/inventory.json")
    require(same(observed, receipt["inventory"]), "Go compiler inventory file differs")
    inventory = source_inventory(inventory, intent)
    selected(receipt["selection"], intent, inventory)
    launch_names = set(inventory["compiler_inputs"]) | {"go.mod"} | ({"go.sum"} & set(intent.original.identities))
    require(same(receipt["launch_inputs"], {name: intent.original.identities[name] for name in launch_names})
            and receipt["source_roster"] == sorted(name for name in intent.original.identities if Path(name).suffix in SOURCE_SUFFIXES),
            "Go compiled input or source roster differs")
    snapshots = {name: files.freeze(output / name) for name in ("private", "sdk", "context")}
    for name, snapshot in snapshots.items():
        require(bool(snapshot.identities) and same(receipt[name + "_inputs"], snapshot.identities), "Go private build inventory differs: " + name)
    require(files.content(snapshots["sdk"]) == files.content(intent.sdk), "Go private SDK differs from caller-frozen source")
    require(files.content(snapshots["context"]) == files.content(intent.context), "Go context differs from caller-frozen profile")
    for name, original in intent.original.identities.items():
        if name not in ("go.mod", "go.sum"):
            require(name in snapshots["private"].identities
                    and all(snapshots["private"].identities[name][key] == original[key] for key in ("sha256", "size")),
                    "Go private copy changed original program data: " + name)
    go_hooks.verify(intent.original, snapshots["private"], receipt["selection"], inventory, intent.settings["Module"]["Path"])
    state = retained_state(receipt, identity, snapshots["private"], snapshots["sdk"], snapshots["context"], inventory, evidence)
    result = Build(intent, receipt, identity, snapshots["private"], snapshots["sdk"], snapshots["context"],
                   inventory, evidence, original_caller, data_seal(state))
    result.verify()
    return result
