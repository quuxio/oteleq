"""Discover materialised Go callers independently of SDK build inventories."""

from dataclasses import dataclass
import json
from pathlib import Path
from typing import Callable

from go_build import Intent, Target
import go_files as files
import go_project
from go_provider import data_seal, require, same

DISCOVERY = Path(__file__).with_name("discover.go")
INPUT_FIELDS = ("GoFiles", "CgoFiles", "CFiles", "CXXFiles", "MFiles", "HFiles",
                "FFiles", "SFiles", "SwigFiles", "SwigCXXFiles", "SysoFiles", "EmbedFiles")


@dataclass(frozen=True)
class Caller:
    """Caller-owned declaration, active-input and export-data bindings."""

    original: files.Snapshot
    compiler: str
    target: str
    targets: tuple[Target, ...]
    compiler_inputs: dict
    packages: dict
    reads: dict
    seal: str
    build_tags: tuple[str, ...] = ()

    def state(self) -> dict:
        """Seal nested metadata as well as the immutable declaration objects."""
        return {"original": self.original.sealed_metadata, "compiler": self.compiler, "target": self.target,
                "targets": [vars(target) for target in self.targets],
                "compiler_inputs": self.compiler_inputs, "packages": self.packages,
                "reads": self.reads, "build_tags": self.build_tags}

    def verify(self) -> None:
        """Retained compiler metadata cannot recertify changed source or tools."""
        require(data_seal(self.state()) == self.seal, "Go caller metadata changed")
        self.original.verify()
        for name, expected in self.reads.items():
            observed, facts, _ = files.file(Path(name))
            require(same([observed, list(facts)], expected), "Go caller compiler input changed: " + name)

    def build_intent(self, directory: Path, sdk: files.Snapshot, toolchain: dict,
                     settings: dict, modules: list[dict], context: files.Snapshot) -> Intent:
        """Require the independently discovered denominator in SDK build readers."""
        self.verify()
        require(type(toolchain) is dict and toolchain.get("go") == self.compiler
                and toolchain.get("go_sha256") == self.reads[self.compiler][0]["sha256"],
                "Go build compiler differs from independent caller discovery")
        return Intent(directory, self.original, sdk, self.target, self.targets,
                      toolchain, settings, modules, context, self.compiler_inputs, self.packages, self.build_tags)


def package_target(entry: dict) -> tuple[str, str]:
    """Bind the fixed generated main separately from its source package."""
    context = entry.get("go_context")
    require(type(context) is dict, "Go source caller needs a declared module context")
    module = context["module_root"]
    if module != ".":
        files.relative(module)
    source = files.relative(Path(entry["path"]).relative_to(module).as_posix())
    directory = Path(context["directory"]).relative_to(module).as_posix()
    if directory != ".":
        files.relative(directory)
    if context["package"] != "main":
        directory = go_project.COMMAND_DIRECTORY
    return ("." if directory == "." else "./" + directory), source


def active_inputs(records: list[dict], original: files.Snapshot) -> tuple[dict, dict]:
    """Retain every active module input, including embedded non-source files."""
    inputs, packages = {}, {}
    go_project.package_inputs(records, original.root)
    for record in records:
        directory = Path(record.get("Dir", ""))
        if not directory.is_relative_to(original.root):
            continue
        module = record.get("Module", {})
        require(module.get("Main") is True and module.get("Dir") == str(original.root),
                "Go caller selected another module")
        name = record["ImportPath"]
        require(type(name) is str and name not in packages, "repeated Go caller package")
        packages[name] = {"name": record["Name"], "directory": directory.relative_to(original.root).as_posix()}
        for field in INPUT_FIELDS:
            values = record.get(field, [])
            require(type(values) is list, "invalid Go caller input list")
            for item in values:
                relative = files.relative((directory / files.relative(item)).relative_to(original.root).as_posix())
                require(relative in original.identities, "Go caller read an unfrozen source input")
                inputs[relative] = original.identities[relative]["sha256"]
    require(bool(inputs) and bool(packages), "missing Go caller compiler inputs")
    return inputs, packages


def selected_targets(inventories: dict, entry: dict, source: str, root: Path, package: dict) -> tuple[Target, ...]:
    """Rebind target and declared factory after diagnostic source insertion."""
    requests = [(source, entry["name"], entry["parameters"], bool(entry.get("receiver_fixture")))]
    fixture = entry.get("receiver_fixture")
    if fixture:
        prefix = entry["go_context"]["module_root"]
        factory_source = Path(fixture["source_path"]).relative_to(prefix).as_posix()
        requests.append((files.relative(factory_source), fixture["factory"], fixture["argument_types"], False))
    targets = []
    for filename, name, parameters, receiver in requests:
        inventory = inventories.get(str(root / filename))
        require(type(inventory) is dict and type(inventory.get("functions")) is list,
                "Go caller declaration file is not active")
        matches = [row for row in inventory["functions"] if row.get("name") == name]
        require(len(matches) == 1, "Go caller declaration is absent or ambiguous")
        row = matches[0]
        require(row.get("parameters") == parameters and row.get("go_variadic") is False
                and row.get("reason") in ("", "instance method requires a receiver fixture")
                and bool(row.get("go_receiver")) == receiver
                and type(row.get("line")) is int and row["line"] > 0,
                "Go caller declaration shape differs from the planned callable")
        receiver_id = ""
        if receiver:
            pointer = "*" if row["go_receiver"].startswith("*") else ""
            receiver_id = pointer + name.rsplit(".", 1)[0]
        targets.append(Target(package["ImportPath"] + "." + name, filename, row["line"], len(parameters), receiver_id))
    require(len({target.name for target in targets}) == len(targets), "repeated Go caller selection")
    return tuple(targets)


def source_package(records: list[dict], entry: dict, root: Path, target: str) -> dict:
    """Require one generated main and the original planned source package."""
    main_directory = root if target == "." else root / target[2:]
    main = [record for record in records if record.get("Dir") == str(main_directory)]
    require(len(main) == 1 and main[0].get("Name") == "main", "Go caller target is not one main package")
    context = entry["go_context"]
    directory = root / Path(context["directory"]).relative_to(context["module_root"])
    matches = [record for record in records if record.get("Dir") == str(directory)]
    require(len(matches) == 1 and matches[0]["ImportPath"] == context["import_path"]
            and matches[0]["Name"] == context["package"], "Go caller source package differs from the plan")
    return matches[0]


def discover(original: files.Snapshot, entry: dict, go: Path, environment: dict, execute: Callable) -> Caller:
    """Use compiler export data without running application initialisers or SDK code."""
    original.verify()
    require(go.is_absolute() and go.resolve(strict=True) == go, "Go caller compiler must be canonical")
    target, source = package_target(entry)
    options = go_project.settings(entry["go_options"])
    env = {**environment, **go_project.environment(options), "GOTOOLCHAIN": "local",
           "GO111MODULE": "on", "GOPACKAGESDRIVER": "off"}
    reads, read_bytes = {}, 0

    def retain(path: Path) -> None:
        nonlocal read_bytes
        require(path.is_absolute() and path.resolve(strict=True) == path,
                "Go caller compiler input must be canonical")
        name = str(path)
        maximum = files.MAX_FILE_BYTES if name in reads else files.MAX_TREE_BYTES - read_bytes
        identity, facts, _ = files.file(path, maximum=maximum)
        observed = [identity, list(facts)]
        if name in reads:
            require(same(reads[name], observed), "Go caller compiler input changed during discovery")
        else:
            reads[name] = observed
            read_bytes += identity["size"]
        require(len(reads) <= files.MAX_FILES, "Go caller compiler read budget exceeded")

    retain(go)
    retain(DISCOVERY)
    result = execute([go, "list", "-deps", "-export", "-compiled", "-json", "-mod=readonly", target],
                     original.root, env, max_output_bytes=files.MAX_METADATA_BYTES)
    go_project.check_result(result, "Go caller package discovery failed")
    records = go_project.documents(result.stdout)
    require(0 < len(records) <= files.MAX_FILES, "invalid Go caller package denominator")
    names = [record.get("ImportPath") for record in records]
    require(all(type(name) is str and name for name in names) and len(set(names)) == len(names),
            "invalid or repeated Go caller import identity")
    inputs, packages = active_inputs(records, original)
    package = source_package(records, entry, original.root, target)
    require(source in inputs and Path(source).name in package.get("GoFiles", []),
            "Go caller selected source is excluded from compilation")
    exports = {record["ImportPath"]: record["Export"] for record in records if record.get("Export")}
    for path in exports.values():
        retain(Path(path))
    request = {"files": [str(Path(package["Dir"]) / name) for name in sorted(package["GoFiles"])],
               "exports": exports, "import_path": package["ImportPath"],
               "go_version": "go" + package["Module"]["GoVersion"]}
    result = execute([go, "run", DISCOVERY, "--", "--package"], DISCOVERY.parent, env,
                     input_data=json.dumps(request).encode(), max_output_bytes=files.MAX_METADATA_BYTES)
    go_project.check_result(result, "Go caller type checking failed")
    targets = selected_targets(json.loads(result.stdout), entry, source, original.root, package)
    tags = go_project.canonical_tags(options["build_tags"])
    caller = Caller(original, str(go), target, targets, inputs, packages, reads, "", tags)
    caller = Caller(original, str(go), target, targets, inputs, packages, reads, data_seal(caller.state()), tags)
    caller.verify()
    return caller
