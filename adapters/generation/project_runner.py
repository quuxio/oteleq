# Generated oteleq boilerplate. MIT licence: see GENERATED-LICENSE.txt.
"""Discover current application cases in a fresh external private workspace."""
import hashlib
import importlib.util
import json
import os
from pathlib import Path
import stat
import subprocess
import sys
import tempfile
import unittest

ROOT = Path(__file__).resolve().parent
MAX_FILE = 8 * 1024 * 1024


def file_hash(path: Path) -> str:
    """Reject special descriptors before hashing selected executable or data."""
    descriptor = os.open(path, os.O_RDONLY | os.O_NONBLOCK)
    with os.fdopen(descriptor, "rb") as stream:
        metadata = os.fstat(stream.fileno())
        if not stat.S_ISREG(metadata.st_mode) or metadata.st_size > 256 * 1024 * 1024:
            raise ValueError("suite input is not a bounded regular file: " + str(path))
        return hashlib.file_digest(stream, "sha256").hexdigest()


def pairs(items: list) -> dict:
    """Do not let duplicate metadata keys replace reviewed values."""
    result = {}
    for key, value in items:
        if key in result:
            raise ValueError("duplicate suite metadata key: " + key)
        result[key] = value
    return result


def read(path: Path, max_bytes: int = MAX_FILE) -> dict:
    if path.is_symlink() or not path.is_file() or path.stat().st_size > max_bytes:
        raise ValueError("suite metadata is not a bounded regular file")
    return json.loads(path.read_text(), object_pairs_hook=pairs)


def validate_metadata(data: dict) -> None:
    """Keep malformed saved values out of path and subprocess operations."""
    strings = {"source", "otelc_root", "cli", "python", "cli_sha256", "generator_sha256",
               "configuration_sha256", "promotion_source_sha256"}
    mappings = {"tools", "artefacts", "files_sha256"}
    expected = strings | mappings | {"schema_version", "kind", "source_relative"}
    if type(data) is not dict or set(data) != expected:
        raise ValueError("invalid current-source suite metadata fields")
    if type(data["schema_version"]) is not int or data["schema_version"] != 1 or data["kind"] != "oteleq-current-source-tests":
        raise ValueError("invalid current-source suite metadata version")
    if any(type(data[key]) is not str for key in strings) or any(type(data[key]) is not dict for key in mappings):
        raise ValueError("invalid current-source suite metadata values")
    if data["source_relative"] is not None and type(data["source_relative"]) is not str:
        raise ValueError("invalid relative application source")


def verified_project() -> dict:
    """Refuse edits before any new plan or application execution."""
    expected = {".oteleq-owned.json", "project.json", "project-policy.toml", "test_equivalence.py", "README.txt", "GENERATED-LICENSE.txt"}
    entries = list(ROOT.iterdir())
    if {path.name for path in entries} != expected or any(path.is_symlink() or not path.is_file() for path in entries):
        raise ValueError("owned project suite has missing or extra files; use PYTHONDONTWRITEBYTECODE=1 for discovery")
    data, marker = read(ROOT / "project.json"), read(ROOT / ".oteleq-owned.json")
    validate_metadata(data)
    identity = hashlib.sha256(json.dumps(data, sort_keys=True).encode()).hexdigest()
    if (type(marker) is not dict or type(marker.get("schema_version")) is not int or marker["schema_version"] != 1
            or marker.get("kind") != "oteleq-current-source-tests" or marker.get("project_sha256") != identity):
        raise ValueError("project suite metadata identity changed")
    actual = {name: file_hash(ROOT / name) for name in expected - {"project.json", ".oteleq-owned.json"}}
    if actual != data.get("files_sha256"):
        raise ValueError("project suite content changed")
    return data


def source_path(data: dict) -> Path:
    """An external suite requires an explicit current checkout on each run."""
    selected = os.environ.get("OTELEQ_SOURCE")
    if not selected and data["source_relative"] is None:
        raise ValueError("set OTELEQ_SOURCE to the current application for an external suite")
    source = Path(selected).resolve(strict=True) if selected else (ROOT / data["source_relative"]).resolve(strict=True)
    if not source.is_dir():
        raise ValueError("current application is not a directory")
    return source


def command(arguments: list, folder: Path, name: str) -> str:
    """Keep preparation receipts; failures become a visible framework test."""
    result = subprocess.run(list(map(str, arguments)), stdin=subprocess.DEVNULL,
                            capture_output=True, check=False)
    (folder / (name + ".stdout")).write_bytes(result.stdout)
    (folder / (name + ".stderr")).write_bytes(result.stderr)
    if result.returncode or len(result.stdout) + len(result.stderr) > 4 * 1024 * 1024:
        raise ValueError("project " + name + " failed; inspect retained receipts at " + str(folder))
    return result.stdout.decode().strip()


def prepare(data: dict) -> Path:
    """Freeze this checkout and require the reviewed tool/provider context."""
    source = source_path(data)
    cli = Path(os.environ.get("OTELEQ_CLI", data["cli"])).resolve(strict=True)
    if file_hash(cli) != data["cli_sha256"]:
        raise ValueError("CLI identity changed; create a new reviewed project suite")
    parent = Path(os.environ.get("OTELEQ_WORKSPACE_PARENT", tempfile.gettempdir())).resolve(strict=True)
    if parent.is_relative_to(source) or parent.is_relative_to(Path(data["otelc_root"]).resolve(strict=True)):
        raise ValueError("project run parent must be outside the application and provider")
    folder = Path(tempfile.mkdtemp(prefix="oteleq-project-", dir=parent))
    os.environ.setdefault("OTELEQ_PYTHON", data["python"])
    os.environ["PYTHONDONTWRITEBYTECODE"] = "1"
    workspace = Path(command([cli, "plan", "--source", source, "--otelc-root", data["otelc_root"],
                              "--config", ROOT / "project-policy.toml", "--workspace-parent", folder], folder, "plan"))
    plan = read(workspace / "plan.json", 256 * 1024 * 1024)
    for key in ("cli_sha256", "generator_sha256", "configuration_sha256", "artefacts"):
        if plan[key] != data[key]:
            raise ValueError("tool/provider/language context changed; create a new reviewed suite; evidence at " + str(folder))
    command([cli, "generate", "--workspace", workspace], folder, "generate")
    print(json.dumps({"project_source": str(source), "workspace": str(workspace),
                      "claim": "equivalence over these tests and observations"}), flush=True)
    return workspace


class PreparationFailure(unittest.TestCase):
    """An invalid plan must never become successful empty discovery."""

    def __init__(self, message: str):
        super().__init__("test_preparation")
        self.message = message

    def test_preparation(self):
        self.fail(self.message)


def load_tests(loader, tests, pattern):
    """Expose every freshly generated case and selected blocker to unittest."""
    try:
        workspace = prepare(verified_project())
        sys.dont_write_bytecode = True
        name = "oteleq_current_" + workspace.name.replace("-", "_")
        spec = importlib.util.spec_from_file_location(name, workspace / "tests/test_equivalence.py")
        module = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(module)
        suite = loader.loadTestsFromModule(module)
        if suite.countTestCases() == 0:
            raise ValueError("generated current-source suite contains no tests")
        return suite
    except (ValueError, OSError, KeyError, ImportError) as error:
        return unittest.TestSuite([PreparationFailure(str(error))])


if __name__ == "__main__":
    unittest.main()
