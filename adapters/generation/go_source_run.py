"""Build and prepare owned Go workers through fixed public SDK commands."""

from dataclasses import dataclass
import json
from pathlib import Path
import tomllib

import go_build
import go_caller
import go_context
import go_files as files
import go_launch
import go_prepared
import go_project
from go_provider import data_seal, require, same
import go_source
import otelc_capture as capture
import python_prepared


@dataclass(frozen=True)
class Run:
    """Retain independent caller/build/preparation checks around one owned launch."""

    caller: go_caller.Caller
    prepared: go_prepared.Prepared
    session: go_launch.Session
    sdk_version: str

    def verify(self) -> None:
        """Recheck the exact source, compiler, build and completed process evidence."""
        self.caller.verify()
        self.prepared.verify()
        require(self.session.execution is not None, "Go worker did not publish completed owned execution")
        self.session.execution.verify()


def prepare(workflow, root: Path, project: Path, entry: dict, tools: dict,
            environment: dict, folder: Path, config: Path, lane: str, *, wait_ms: int) -> Run:
    """Freeze expectations before producer builds and never execute returned argv."""
    require(go_source.enabled(entry) and lane in ("baseline", "instrumented_on"), "invalid Go source execution lane")
    require(not entry["go_options"]["build_tags"], "source build4 cannot execute tagged inputs")
    require("sequence_configuration" not in entry, "Go source-v1 schedules require separate integration")
    module = project / entry["go_context"]["module_root"]
    original = files.freeze(module)
    sdk = files.freeze(root / "adapters/go")
    producer = files.freeze(root / "otelc")
    tooling = go_source.toolchain(root, tools)
    timeout = go_project.build_timeout(entry["go_build_timeout_ms"]) / 1000
    count = 0

    def execute(argv, cwd, env=None, *, input_data=None, max_output_bytes=files.MAX_METADATA_BYTES):
        nonlocal count
        destination = folder / "go-tooling" / str(count)
        count += 1
        destination.mkdir(mode=0o700, parents=True)
        workflow.write(destination / "command.json", {"argv": list(map(str, argv)), "cwd": str(cwd),
                                                       "timeout_ms": round(timeout * 1000)})
        if input_data is not None:
            (destination / "stdin").write_bytes(input_data)
        result = workflow.execute(argv, cwd, env or environment, destination, timeout=timeout,
                                  input_data=input_data, max_output_bytes=max_output_bytes)
        require(result.returncode == 0, "Go public build/preparation failed; inspect retained compiler channels")
        return result

    caller = go_caller.discover(original, entry, tools["go"], environment, execute)
    workflow.write(folder / "go-caller.json", {**caller.state(), "seal": caller.seal})
    settings = json.loads(execute([tools["go"], "mod", "edit", "-json"], module).stdout)
    modules = go_project.documents(execute([tools["go"], "list", "-m", "-mod=readonly", "-json", "all"], module).stdout)
    context = go_context.prepare(Path(tooling["bundle"]), folder / "go-context")
    intent = caller.build_intent(folder / "go-build", sdk, tooling, settings, modules, context)
    seal = data_seal(go_build.caller_state(intent))
    policy = tomllib.loads(config.read_text())
    require(policy["functions"]["include"] == [target.name for target in caller.targets],
            "Go source policy differs from independently discovered callables")
    command = go_source.cli(root, tools) + ["--config", config, "go-build", "--root", module,
                                          "--target", caller.target, "--output", intent.directory,
                                          "--go", tools["go"], "--prepared-tools"]
    execute(command, root)
    require(data_seal(go_build.caller_state(intent)) == seal, "Go caller inputs changed during SDK build")
    caller.verify()
    build = go_build.read(intent)
    workflow.write(folder / workflow.BUILD_IDENTITIES, {"profile": "go-source-v1", "build": build.identity,
        "plain": build.receipt["plain"], "instrumented": build.receipt["instrumented"], "caller_seal": caller.seal,
        "selection_sha256": build.receipt["selection"]["sha256"]})
    private_modules = go_project.documents(execute([tools["go"], "list", "-m", "-mod=readonly", "-json", "all"],
                                                   build.private.root).stdout)
    require(same(private_modules, build.receipt["modules_after"]), "Go compiled module graph differs from independent compiler read")
    versions = [row.get("Version") for row in private_modules if row.get("Path") == "go.opentelemetry.io/otel"]
    require(len(versions) == 1 and type(versions[0]) is str and versions[0].startswith("v"),
            "Go compiled SDK version is unavailable")
    sdk_version = versions[0][1:]
    build.verify()
    runtime = folder / "go-runtime"
    command = go_source.cli(root, tools) + ["--config", config, "go", "--build", intent.directory,
                                          "--runtime", runtime, "--prepare-only"]
    if lane == "baseline":
        command.append("--plain")
    response = execute(command, root).stdout
    # Strict decoding belongs to the independent prepared reader as well as the
    # public dispatcher; a response never supplies an executable to this process.
    value = capture.strict_json(response)
    checked = go_prepared.verify(value, go_prepared.Intent(build, runtime, producer, tools["python-host"],
                                  python_prepared.file_identity(tools["python-host"]), policy, lane == "baseline"))
    require(same(checked.intent.policy, policy), "Go prepared policy changed")
    caller.verify()
    return Run(caller, checked, go_launch.Session(checked, wait_ms=wait_ms), sdk_version)
