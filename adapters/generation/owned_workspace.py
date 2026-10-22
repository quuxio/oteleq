"""Validate retained tool output before separating it from application inputs."""
from pathlib import Path

import discovery
import project_tests
from otelc_capture import walk_tree

MARKER = ".oteleq-owned.json"
OWNERSHIP_ERROR = "workspace is not an owned oteleq directory"


def verify_layout(workflow, workspace: Path) -> None:
    """Reserved run/cache output remains owned; unexpected root entries do not."""
    allowed = {MARKER, workflow.PLAN_FILE, "snapshot", "tests", workflow.GENERATED_MANIFEST,
               workflow.README_FILE, "runs", "go-cache", workflow.native_profile.DIRECTORY,
               workflow.java_project.DIRECTORY, workflow.java_provider.DIRECTORY}
    if workspace.is_symlink() or not workspace.is_dir():
        raise ValueError(OWNERSHIP_ERROR)
    if any(path.name not in allowed or path.is_symlink() for path in workspace.iterdir()):
        raise ValueError("workspace contains unowned files; retain and inspect it")
    for name in ("snapshot", "runs", "go-cache"):
        path = workspace / name
        if path.exists() and not path.is_dir():
            raise ValueError("workspace contains an invalid owned directory: " + name)


def verify_contexts(workflow, workspace: Path, data: dict) -> None:
    """Check private native and Java context seals without external toolchains."""
    native = workspace / workflow.native_profile.DIRECTORY
    if native.exists() and (not data.get("native_projects") or
            workflow.native_profile.context_manifest(workflow, workspace) != data.get("native_context_manifest")):
        raise ValueError("native context was edited or is unowned; retain and inspect it")
    if data.get("native_projects") and not native.is_dir():
        raise ValueError("native context is missing; retain and inspect it")
    workflow.java_project.verify_owned(workspace, data)
    workflow.java_provider.verify_probes(workflow, workspace, data)


def verify_suite(workflow, workspace: Path) -> None:
    """Every generated test or helper must still match its frozen manifest."""
    tests, seal = workspace / "tests", workspace / workflow.GENERATED_MANIFEST
    if tests.exists() and not seal.is_file():
        raise ValueError("generated suite is unsealed; retain and inspect it")
    if seal.exists() and (not tests.is_dir() or workflow.manifest(tests) != workflow.read(seal)):
        raise ValueError("generated suite was edited; retain and inspect it")


def verify(workflow, workspace: Path) -> tuple[dict, dict]:
    """Inspect owned content without original sources, external tools or deletion."""
    marker_path = workspace / MARKER
    if workspace.is_symlink() or marker_path.is_symlink():
        raise ValueError(OWNERSHIP_ERROR)
    if workspace.is_dir() and marker_path.is_file():
        candidate = workflow.read(marker_path)
        if type(candidate) is dict and candidate.get("kind") == project_tests.KIND:
            return project_tests.verify(workflow, workspace)
    verify_layout(workflow, workspace)
    marker = workflow.read(workspace / MARKER)
    if (type(marker) is not dict or type(marker.get("schema_version")) is not int
            or marker["schema_version"] != workflow.VERSION
            or (marker.get("id") is not None and type(marker["id"]) is not str)):
        raise ValueError(OWNERSHIP_ERROR)
    if not (workspace / workflow.PLAN_FILE).is_file():
        raise ValueError("workspace plan is unsealed; retain and inspect it")
    data = workflow.read(workspace / workflow.PLAN_FILE)
    if (type(data) is not dict or type(data.get("schema_version")) is not int
            or data["schema_version"] != workflow.VERSION
            or marker.get("plan_sha256") != workflow.identity(data)):
        raise ValueError("plan identity changed; retain and inspect it")
    if (not (workspace / "snapshot").is_dir()
            or workflow.manifest(workspace / "snapshot") != data["source_manifest"]):
        raise ValueError("snapshot was edited; retain and inspect it")
    verify_contexts(workflow, workspace, data)
    verify_suite(workflow, workspace)
    return marker, data


def require_application_input(source: Path, name: str) -> None:
    """An explicit build input cannot select an owned diagnostic snapshot or helper."""
    path = source / name
    for parent in (path, *path.parents):
        if not parent.is_relative_to(source):
            break
        marker = parent / MARKER
        if marker.exists() or marker.is_symlink():
            raise ValueError("explicit application input is inside a retained oteleq workspace: " + name)


def exclusions(workflow, source: Path, source_roots=()) -> list[dict]:
    """List verified output roots; a marker alone never hides application source."""
    result = {}
    roots = dict.fromkeys([source, *(source / name for name in source_roots)])
    for root in roots:
        require_application_input(source, root.relative_to(source).as_posix())
        for directory, names, files in walk_tree(root):
            path = Path(directory)
            relative = path.relative_to(source).as_posix()
            if MARKER in names or MARKER in files:
                try:
                    marker, data = verify(workflow, path)
                except (ValueError, OSError, KeyError, TypeError) as error:
                    raise ValueError(f"invalid retained oteleq workspace {relative}: {error}") from error
                result[relative] = exclusion_record(workflow, relative, marker, data)
                names[:] = []
            else:
                names[:] = sorted(name for name in names if name not in discovery.IGNORED)
    return [result[name] for name in sorted(result)]


def exclusion_record(workflow, relative: str, marker: dict, data: dict) -> dict:
    """Describe either verified output kind without adding branches to the walk."""
    reason = ("verified current-source oteleq suite" if marker.get("kind") == project_tests.KIND
              else "verified retained oteleq workspace")
    return {"path": relative, "workspace_id": marker.get("id"),
            "plan_sha256": workflow.identity(data), "reason": reason}
