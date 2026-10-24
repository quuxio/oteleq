# Generated observer boilerplate is MIT licensed; see GENERATED-LICENSE.txt.
"""Create a private Go worker gate before constructors, observations or calls."""

from pathlib import Path
import json

import go_project

ROOT_ENV = "OTELEQ_GO_CONTROL_ROOT"
TOKEN_ENV = "OTELEQ_GO_CONTROL_TOKEN"
WAIT_ENV = "OTELEQ_GO_CONTROL_WAIT_MS"
HELPER = "rendezvous.go"

SOURCE = Path(__file__).with_name("go_rendezvous.go").read_text()


def enabled(entry: dict) -> bool:
    return entry.get("go_backend") == "source-v1"


def statement(entry: dict) -> str:
    return "__oteleq_gate.AwaitHost();" if enabled(entry) else ""


def imports(entry: dict) -> str:
    """Keep all helper builtins outside the application's lexical package."""
    if not enabled(entry):
        return ""
    module = go_project.module_import(entry["go_context"])
    return "\nimport __oteleq_gate " + json.dumps(module + "/" + go_project.CONTROL_DIRECTORY) + "\n"


def materialise(project: Path, context: dict) -> Path:
    """Create one private package, never add builtin calls to application scope."""
    go_project.module_import(context)
    directory = project / context["module_root"] / go_project.CONTROL_DIRECTORY
    directory.mkdir()
    path = directory / HELPER
    with path.open("x") as output:
        output.write(SOURCE)
    return path
