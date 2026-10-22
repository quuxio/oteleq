"""Keep the actual Node application and its independent SDK in one owned run."""

import json
import os
from pathlib import Path
import subprocess
import stat
import sys
import time
from typing import Any

import node_source
from otelc_capture import strict_json

FIELDS = {"schema_version", "provider", "project", "entry", "runtime", "policy", "node",
          "language", "compiler", "plain", "gc_fixture", "timeout_ms"}


def request(path: Path) -> dict[str, Any]:
    """A fixed request describes source intent, never an arbitrary command vector."""
    node_source.require(path.is_file() and not path.is_symlink() and path.stat().st_size <= 1024 * 1024,
                        "missing, linked or oversized supervisor request")
    value = strict_json(path.read_bytes())
    node_source.require(type(value) is dict and set(value) == FIELDS
                        and type(value["schema_version"]) is int and value["schema_version"] == 1,
                        "invalid supervisor request fields")
    for key in ("provider", "project", "entry", "runtime", "policy", "node"):
        node_source.require(type(value[key]) is str and Path(value[key]).is_absolute(),
                            "supervisor paths must be explicit and absolute")
    node_source.require(type(value["language"]) is str and value["language"] in node_source.LANGUAGES
                        and type(value["compiler"]) is str and value["compiler"] in ("native", "api")
                        and type(value["plain"]) is bool and type(value["gc_fixture"]) is bool
                        and type(value["timeout_ms"]) is int and 1 <= value["timeout_ms"] <= 3600000,
                        "invalid source execution controls")
    project, runtime = Path(value["project"]), Path(value["runtime"])
    node_source.require(project.resolve(strict=True) == Path.cwd().resolve()
                        and Path(value["entry"]).resolve(strict=True).is_relative_to(project.resolve())
                        and runtime.parent.resolve() == path.parent.resolve()
                        and not runtime.exists() and not runtime.is_symlink(),
                        "supervisor source/runtime boundaries differ")
    node_source.require(not runtime.resolve().is_relative_to(Path(value["provider"]).resolve())
                        and not runtime.resolve().is_relative_to(project.resolve()),
                        "runtime must be outside application and provider")
    return value


def write(path: Path, value: Any) -> None:
    """Publish consumer-owned receipts without replacing existing evidence."""
    descriptor = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
    with os.fdopen(descriptor, "w") as stream:
        json.dump(value, stream, sort_keys=True)
        stream.write("\n")


def expected_argv(value: dict[str, Any]) -> list[str]:
    """Independently fix executable, source-map, GC and bootstrap arguments."""
    result = [value["node"], "--enable-source-maps"]
    if value["gc_fixture"]:
        result.append("--expose-gc")
    if not (value["plain"] and value["language"] == "javascript"):
        prefix = "node-plain" if value["plain"] else "node"
        result += ["--require", str(Path(value["runtime"]) / (prefix + "-bootstrap.cjs"))]
    return result + [value["entry"]]


def wait_sdk_exit(report: dict, application_pid: int, deadline: float) -> None:
    """A final report and actual SDK termination both precede group cleanup."""
    sdk = report.get("sdk_pid")
    node_source.require(type(sdk) is int and sdk > 1 and sdk != application_pid,
                        "independent SDK PID is unavailable")
    while True:
        try:
            group = os.getpgid(sdk)
        except ProcessLookupError:
            return
        node_source.require(group == os.getpgrp(), "SDK process escaped its owned run group")
        if time.monotonic() >= deadline:
            raise TimeoutError("independent SDK process did not exit within the case budget")
        time.sleep(.01)


def remaining(deadline: float) -> float:
    """Preparation and final drain share the original case wall-time budget."""
    value = deadline - time.monotonic()
    if value <= 0:
        raise TimeoutError("Node source case budget exhausted")
    return value


def close_transport(runtime: Path, folder: Path, sdk_pid: int) -> None:
    """Remove the inactive event endpoint only after the actual SDK has exited."""
    filename = runtime / "node-events.fifo"
    metadata = filename.lstat()
    node_source.require(stat.S_ISFIFO(metadata.st_mode) and metadata.st_uid == os.getuid()
                        and stat.S_IMODE(metadata.st_mode) == 0o600,
                        "source event endpoint is not the owned private FIFO")
    filename.unlink()
    write(folder / "node-source-transport.json", {"path": str(filename), "kind": "fifo", "mode": 0o600,
          "sdk_pid": sdk_pid, "removed_after_sdk_exit": True})


def run(value: dict[str, Any], folder: Path) -> int:
    """Forward only application channels and retain real parent/SDK evidence."""
    deadline = time.monotonic() + value["timeout_ms"] / 1000
    sys.path.insert(0, value["provider"])
    from otelc.config import Policy
    from otelc import node, node_provenance

    os.environ["OTELC_NODE"] = value["node"]
    node_source.verify_protocols(node.protocols())
    policy = Policy.load(Path(value["policy"]))
    runtime = Path(value["runtime"])
    command = node.command(policy, runtime, value["language"], root=Path(value["project"]),
                           entry=Path(value["entry"]), backend=value["compiler"],
                           plain=value["plain"], gc_fixture=value["gc_fixture"])
    node_source.require(command == expected_argv(value), "public API changed the fixed Node recipe")
    prefix = "node-plain" if value["plain"] else "node"
    manifest = json.loads((runtime / (prefix + "-launch.json")).read_bytes())
    node_source.require(type(manifest.get("schema_version")) is int
                        and manifest["schema_version"] == node_source.PROTOCOLS["source"],
                        "prepared source evidence version differs from the requested protocol")
    write(folder / "node-source-command.json", command)
    remaining(deadline)
    application = subprocess.Popen(command)
    try:
        write(folder / "node-source-application.json",
              {"pid": application.pid, "supervisor_pid": os.getpid(), "group": os.getpgrp()})
        result = application.wait(timeout=remaining(deadline))
    finally:
        if application.poll() is None:
            application.kill()
            application.wait(timeout=5)
    write(folder / "node-source-application-exit.json", {"pid": application.pid, "returncode": result})
    report = None
    if not value["plain"]:
        report = node.wait_report(runtime, timeout=remaining(deadline))
        node_source.require(report.get("pid") == application.pid, "final report belongs to another application PID")
        wait_sdk_exit(report, application.pid, deadline)
    verified = node_provenance.finish(runtime, manifest)
    node_source.require(verified, "public final input verification failed")
    node_source.require(report is None or report.get("phase") == "closed", "independent SDK drain failed")
    if report is not None:
        close_transport(runtime, folder, report["sdk_pid"])
    write(folder / "node-source-completion.json",
          {"application_pid": application.pid, "application_returncode": result,
           "sdk_pid": report["sdk_pid"] if report else None,
           "sdk_exited": True if report else None,
           "phase": report.get("phase") if report else None, "inputs_verified": verified})
    return result


if __name__ == "__main__":
    filename = Path(sys.argv[1])
    raise SystemExit(run(request(filename), filename.parent))
