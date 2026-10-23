"""Independent frozen Java action declarations and offline compiler outputs.

The public SDK compiler reads original class bytes without starting the
application. Successful bindings alone do not admit generated execution.
"""

from collections.abc import Callable
from dataclasses import dataclass
import hashlib
import json
from pathlib import Path
import sys

import java_build
import java_launch
import java_profiles
import java_provider
import java_witness as witness
import otelc_capture as capture

ROLES = ("envelope", "rendezvous", "wrapper", "target")
DECLARATION_FIELDS = {"owner", "name", "descriptor"}
BINDING_FIELDS = DECLARATION_FIELDS | {"class_sha256", "method_sha256", "probe_id"}
MAX_BINDINGS = 1024 * 1024
MAX_TEXT = 65535
ROUTE_ORDER = ("kind", "field_owner", "field_name", "field_descriptor", "site_instruction",
               "invoke_owner", "invoke_name", "invoke_descriptor", "reference_kind")
COMPILER = """import json, os, sys
from pathlib import Path
os.umask(0o077)
sys.path.insert(0, sys.argv[1])
from otelc.prepared_java import PreparedApplication
from otelc.witness import compile_bindings
application = PreparedApplication.load(Path(sys.argv[3]))
declarations = json.loads(Path(sys.argv[4]).read_text())
options = {} if sys.argv[2] == "java-sync-action-v2" else {"profile": sys.argv[2]}
result = compile_bindings(application, declarations, Path(sys.argv[5]), **options)
print(json.dumps(result, sort_keys=True))
"""


def _text(value: object) -> bool:
    return (type(value) is str and bool(value) and len(value.encode("utf-8")) <= MAX_TEXT
            and not any(ord(char) < 32 or ord(char) == 127 for char in value))


def _owner(value: object) -> bool:
    return (_text(value) and all(value.split("/"))
            and not any(char in value for char in ".;[\\"))


def _field(text: str, start: int) -> tuple[int, int] | None:
    dimensions = 0
    while start < len(text) and text[start] == "[":
        dimensions += 1;start += 1
    if dimensions > 255 or start == len(text):
        return None
    kind = text[start]
    if kind in "BCDFIJSZ":
        return start + 1, 1 if dimensions or kind not in "JD" else 2
    if kind == "L":
        end = text.find(";", start + 1)
        if end > start + 1 and _owner(text[start + 1:end]):
            return end + 1, 1
    return None


def descriptor_slots(value: object) -> int | None:
    """Count parameters only for a complete bounded JVM method descriptor."""
    if not _text(value) or not value.startswith("("):
        return None
    position, slots = 1, 0
    while position < len(value) and value[position] != ")":
        item = _field(value, position)
        if item is None:
            return None
        position, width = item;slots += width
        if slots > 255:
            return None
    if position >= len(value) - 1:
        return None
    position += 1
    if value[position:] == "V":
        return slots
    result = _field(value, position)
    return slots if result is not None and result[0] == len(value) else None


def descriptor(value: object) -> bool:
    """Recognise bounded ordinary JVM method descriptors, including slot limits."""
    return descriptor_slots(value) is not None


@dataclass(frozen=True)
class HandleRoute:
    """Caller-owned field and dispatch kind, independent of compiler output."""

    field_name: str
    reference_kind: int

    def __post_init__(self) -> None:
        witness.require(_text(self.field_name) and not any(char in self.field_name for char in ".;/[<>")
                        and type(self.reference_kind) is int and self.reference_kind in (5, 6),
                        "invalid expected handle route")

    def metadata(self, expected: dict, bindings: dict) -> dict:
        """Recompute the complete closed route from independently requested roles."""
        wrapper, target = expected["wrapper"], expected["target"]
        signature = (target["descriptor"] if self.reference_kind == 6 else
                     "(L" + target["owner"] + ";" + target["descriptor"][1:])
        slots = descriptor_slots(wrapper["descriptor"])
        witness.require(wrapper["descriptor"] == signature and slots is not None and slots <= 254,
                        "handle invocation descriptor or slot bound differs")
        value = {"kind": "direct_method_handle", "field_owner": wrapper["owner"],
                 "field_name": self.field_name, "field_descriptor": "Ljava/lang/invoke/MethodHandle;",
                 "site_instruction": 0, "invoke_owner": "java/lang/invoke/MethodHandle",
                 "invoke_name": "invokeExact", "invoke_descriptor": signature,
                 "reference_kind": self.reference_kind}
        fields = [witness.HANDLE_PROFILE, *(str(value[key]) for key in ROUTE_ORDER),
                  bindings["wrapper"]["probe_id"], bindings["target"]["probe_id"]]
        value["sha256"] = hashlib.sha256("\n".join(fields).encode()).hexdigest()
        return value


def selected_route(profile: str, route: HandleRoute | None) -> HandleRoute | None:
    """Freeze explicit routing intent without inferring it from producer fields."""
    if witness.profile_version(profile) == 3:
        if type(route) is not HandleRoute:
            raise ValueError("Java action witness: handle profile requires its independent route")
        return HandleRoute(route.field_name, route.reference_kind)
    witness.require(route is None, "v2 cannot accept a handle route")
    return None


def declarations(value: object) -> dict:
    """Freeze exactly four distinct caller-owned declarations, without coercion."""
    witness.require(type(value) is dict and set(value) == set(ROLES), "missing explicit action declarations")
    for role in ROLES:
        item = value[role]
        witness.require(type(item) is dict and set(item) == DECLARATION_FIELDS
                        and _owner(item["owner"]) and _text(item["name"])
                        and not any(char in item["name"] for char in ".;/[<>")
                        and descriptor(item["descriptor"]), "invalid action declaration: " + role)
    witness.require(value["rendezvous"]["descriptor"] == "()V"
                    and len({tuple(value[role][key] for key in ("owner", "name", "descriptor"))
                             for role in ROLES}) == 4, "action roles must be distinct with a ()V rendezvous")
    raw = json.dumps(value, sort_keys=True).encode()
    witness.require(len(raw) <= MAX_BINDINGS, "action declarations exceed their byte budget")
    return capture.strict_json(raw)


def verify(value: object, expected: dict, application: dict, classes: Path, *,
           profile: str = witness.PROFILE, route: HandleRoute | None = None) -> dict:
    """Bind every compiler probe to independent declarations and class products."""
    expected = declarations(expected)
    route = selected_route(profile, route)
    witness.require(type(application) is dict and type(application.get("bindings")) is dict,
                    "missing compiler-owned application bindings")
    value = witness.closed_fields(value, {"schema_version", "kind", "profile", "bindings"}
                                  | ({"route"} if route is not None else set()), "unsupported action binding fields")
    witness.require(type(value["schema_version"]) is int and value["schema_version"] == witness.profile_version(profile)
                    and value["kind"] == "otelc.java-witness-bindings" and value["profile"] == profile,
                    "unsupported action binding document")
    bindings = value["bindings"]
    witness.require(type(bindings) is dict and set(bindings) == set(ROLES), "missing compiled action roles")
    for role in ROLES:
        item = witness.closed_fields(bindings[role], BINDING_FIELDS, "unsupported compiled role fields")
        declaration = expected[role]
        witness.require(all(type(item[key]) is str for key in BINDING_FIELDS)
                        and all(item[key] == requested for key, requested in declaration.items()),
                        "compiler changed an action declaration")
        owner = declaration["owner"].replace("/", ".")
        witness.require(owner in application["bindings"], "action owner has no compiler source binding")
        original = application["bindings"][owner]
        actual = classes / (declaration["owner"] + ".class")
        witness.require(type(original) is dict and witness.hex_id(original.get("class_sha256"), 64)
                        and witness.hex_id(item["class_sha256"], 64)
                        and item["class_sha256"] == original["class_sha256"] == java_build.digest(actual)
                        and witness.hex_id(item["method_sha256"], 64), "action class or method identity differs")
        fields = [profile, role, *(declaration[key] for key in ("owner", "name", "descriptor")),
                  item["class_sha256"], item["method_sha256"]]
        witness.require(item["probe_id"] == hashlib.sha256("\n".join(fields).encode()).hexdigest(),
                        "action compiler probe differs")
    if route is not None:
        requested = route.metadata(expected, bindings)
        actual = witness.closed_fields(value["route"], set(requested), "unsupported compiled route fields")
        witness.require(all(type(actual[key]) is type(item) and actual[key] == item for key, item in requested.items()),
                        "compiler changed the independently expected handle route")
    return value


def inputs(root: Path, tools: dict) -> dict:
    """Include the offline helper as well as the fixed safe runtime/tooling scope."""
    value = java_provider.artefacts(root, tools, java_profiles.SAFE)
    helper = root / java_provider.HELPER
    witness.require(helper.is_file() and not helper.is_symlink(), "missing regular offline binding compiler")
    value[java_provider.HELPER] = capture.file_digest(helper)
    value["tool:python"] = capture.file_digest(Path(sys.executable))
    value["tool:jdk-modules"] = capture.file_digest(java_build.module_image(tools["java"]))
    return value


def _audit(root: Path, project: Path, build: Path, classes: Path, tools: dict,
           before: dict, request: Path, request_identity: dict) -> None:
    java_build.verify(project, classes, build)
    witness.require(before == inputs(root, tools) and request_identity == java_launch.identity(request),
                    "offline compiler inputs changed")


def compile(root: Path, project: Path, build: Path, folder: Path, tools: dict,
            expected: dict, environment: dict, execute: Callable, *,
            profile: str = witness.PROFILE, route: HandleRoute | None = None) -> dict:
    """Run the fixed public offline SDK API in a new private external directory."""
    frozen = declarations(expected)
    route = selected_route(profile, route)
    witness.require(folder.is_absolute() and folder.parent == folder.parent.resolve(strict=True)
                    and not folder.is_relative_to(project.resolve(strict=True))
                    and not folder.is_relative_to(root.resolve(strict=True)), "binding outputs must be new and external")
    classes = build / java_launch.CLASSES
    java_build.verify(project, classes, build)
    application = capture.strict_json((build / java_launch.APPLICATION_FILE).read_bytes())
    before = inputs(root, tools)
    folder.mkdir(mode=0o700)
    request, output = folder / "declarations.json", folder / "bindings.json"
    with request.open("x") as stream:
        request.chmod(0o600)
        stream.write(json.dumps(frozen, sort_keys=True) + "\n")
    request_identity = java_launch.identity(request)
    command = [sys.executable, "-I", "-S", "-B", "-c", COMPILER, str(root), profile,
               str(build / java_launch.APPLICATION_FILE), str(request), str(output)]
    tool_environment = java_provider.environment(root, tools, folder, environment)
    tool_environment["OTELC_JAVA"] = str(tools["java"].resolve(strict=True))
    try:
        result = execute(command, root, tool_environment, folder / "compiler",
                         max_output_bytes=MAX_BINDINGS)
    except BaseException as error:
        try:
            _audit(root, project, build, classes, tools, before, request, request_identity)
        except (OSError, ValueError) as audit_error:
            error.add_note("Offline input audit also failed: " + str(audit_error))
        raise
    _audit(root, project, build, classes, tools, before, request, request_identity)
    witness.require(result.returncode == 0, "offline binding compilation failed; inspect compiler/stderr")
    snapshot = witness.private_snapshot(folder, "bindings.json", MAX_BINDINGS)
    value = capture.strict_json(snapshot.raw)
    witness.require(capture.strict_json(result.stdout) == value, "offline compiler response differs from retained bindings")
    verify(value, frozen, application, classes, profile=profile, route=route)
    witness.require(witness.private_snapshot(folder, "bindings.json", MAX_BINDINGS) == snapshot,
                    "offline bindings output changed after validation")
    record = {"schema_version": 1, "profile": profile, "argv": command, "cwd": str(root),
              "sdk_inputs_sha256": before, "declarations": request_identity,
              "application_sha256": capture.file_digest(build / java_launch.APPLICATION_FILE),
              "bindings_sha256": hashlib.sha256(snapshot.raw).hexdigest()}
    if route is not None:
        record["expected_handle"] = {"field_name": route.field_name, "reference_kind": route.reference_kind}
    (folder / "compiler-inputs.json").write_text(json.dumps(record, indent=2) + "\n")
    return value
