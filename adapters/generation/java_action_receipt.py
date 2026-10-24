"""Independent decoded Java action spans, bound to pre-release expectations.

This synchronous diagnostic contract selects one method and its recursion.
It does not replace source/build/probe verification, typed application
observations, final SDK pipeline health or public capability qualification.
"""

from dataclasses import dataclass
import hashlib

import java_telemetry as telemetry
import java_witness as witness
import otelc_capture as capture

ROLE_SCOPE = ("io.quux.otelc.witness", "1")
PREFIX = "otelc.witness."
SCOPE = PREFIX + "scope_id"
ROLE = PREFIX + "role"
PROBE = PREFIX + "probe_id"
MAX_BODIES = 4096
MAX_BYTES = 32 * 1024 * 1024
MAX_SPANS = 65536


@dataclass(frozen=True)
class Action:
    """Retained pre-release harness/arm identities with one observed outcome."""

    action_id: str
    case_id: str
    attempt_id: str
    thread_id: str
    cookie: str
    sequence: str
    scope_id: str
    failed: bool

    def __post_init__(self) -> None:
        for value, width in ((self.action_id, 64), (self.case_id, 64), (self.attempt_id, 64),
                             (self.cookie, 32), (self.scope_id, 32)):
            witness.require(witness.hex_id(value, width), "invalid expected action identity")
        witness.counter(self.thread_id, positive=True)
        witness.counter(self.sequence, positive=True)
        witness.require(type(self.failed) is bool, "missing independently observed outcome kind")


@dataclass(frozen=True)
class Target:
    """Source/compiler-bound Java namespace and method, separate from OTLP names."""

    owner: str
    method: str

    def __post_init__(self) -> None:
        witness.require(all(type(value) is str and value and not any(ord(char) < 32 for char in value)
                            for value in (self.owner, self.method)), "invalid expected target labels")


def _expected(report: dict, identity: witness.Identity, actions: list[Action]) -> dict:
    report = witness.final_report(report, pid=identity.pid, identity=identity)
    witness.require(report["producer"]["error"] is None
                    and report["queue_evidence"] == "derived_after_shutdown",
                    "missing supported final producer/drain checkpoint")
    witness.require(type(actions) is list and 0 < len(actions) <= 64
                    and all(type(action) is Action for action in actions)
                    and len(report["scopes"]) == len(actions), "missing declared final actions")
    for key in ("action_id", "scope_id", "cookie", "sequence"):
        witness.require(len({getattr(action, key) for action in actions}) == len(actions),
                        "duplicate independently expected action")
    scopes = {}
    traces = set()
    for action, scope in zip(actions, report["scopes"]):
        witness.context({**report["producer"], "scope": scope}, identity,
                        thread_id=action.thread_id, cookie=action.cookie, sequence=action.sequence,
                        case_id=action.case_id, attempt_id=action.attempt_id, scope_id=action.scope_id)
        witness.require(scope["producer_complete"] and scope["queue_dropped"] == "0",
                        "action is incomplete or queue evidence is unavailable")
        witness.require(scope["trace_id"] not in traces, "action roots share a trace")
        traces.add(scope["trace_id"])
        scopes[action.scope_id] = scope
    return scopes


def _identities(identity: witness.Identity, scope: dict) -> dict:
    hashes = dict(identity.hashes)
    values = {"runtime_id": identity.runtime_id, "scope_id": scope["scope_id"],
              "context_cookie": scope["cookie"], "case_id": scope["case_id"],
              "attempt_id": scope["attempt_id"]}
    values.update({key: hashes[key] for key in ("build_sha256", "selection_sha256", "policy_sha256", "tooling_sha256")})
    return {PREFIX + key: ("string_value", value) for key, value in values.items()}


def _scoped_span(span, instrumentation: tuple, values: dict, scope: dict,
                 identity: witness.Identity, target: Target) -> tuple[str, str | None]:
    witness.require(span.trace_id.hex() == scope["trace_id"] and span.kind == 1
                    and span.status.code in (0, 2)
                    and not span.links
                    and span.dropped_attributes_count == span.dropped_events_count == span.dropped_links_count == 0,
                    "invalid scoped trace, kind, status or dropped observations")
    expected = _identities(identity, scope)
    witness.require(all(values.get(key) == value for key, value in expected.items()),
                    "decoded span has a different action/runtime/build identity")
    for event in span.events:
        witness.require(event.dropped_attributes_count == 0, "scoped event lost attributes")
        telemetry.attributes(event.attributes)
    role = values.get(ROLE)
    if role is None:
        witness.require(instrumentation == telemetry.METHOD_SCOPE and PROBE not in values
                        and values.get("code.namespace") == ("string_value", target.owner)
                        and values.get("code.function") == ("string_value", target.method)
                        and span.name == target.owner.rsplit(".", 1)[-1] + "." + target.method,
                        "unbound selected-method descendant")
        return span.span_id.hex(), None
    witness.require(role in (("string_value", "wrapper"), ("string_value", "target"),
                            ("string_value", "recursive_target")), "unknown action role")
    name = role[1]
    probe = "wrapper" if name == "wrapper" else "target"
    witness.require(instrumentation == ROLE_SCOPE and span.name == "otelc.action." + probe
                    and values.get(PROBE) == ("string_value", dict(identity.hashes)[probe + "_probe_id"]),
                    "role span lacks the exact compiler probe")
    return span.span_id.hex(), name


def _tree(scope: dict, rows: dict, action: Action) -> dict:
    started, ended, exported = witness.span_sets(scope)
    witness.require(set(rows) == started == ended == exported,
                    "actual decoded receipt differs from producer span accounting")
    root, target = scope["root_span_id"], scope["target_span_id"]
    nodes, children = {}, {key: [] for key in rows}
    roles = {"wrapper": [], "target": [], "recursive_target": [], None: []}
    for key, (span, role) in rows.items():
        parent = span.parent_span_id.hex() if span.parent_span_id else None
        nodes[(span.trace_id, span.span_id)] = (span.trace_id, span.parent_span_id) if parent else None
        roles[role].append(key)
        if parent is not None:
            witness.require(parent in rows, "scoped descendant has a missing parent")
            children[parent].append(key)
            owner = rows[parent][0]
            witness.require(owner.start_time_unix_nano <= span.start_time_unix_nano
                            <= span.end_time_unix_nano <= owner.end_time_unix_nano,
                            "scoped child lies outside its parent interval: "
                            f"trace={span.trace_id.hex()} child={key} parent={parent} "
                            f"start_delta_ns={span.start_time_unix_nano - owner.start_time_unix_nano} "
                            f"end_delta_ns={span.end_time_unix_nano - owner.end_time_unix_nano}")
    witness.require(capture.trace_roots(nodes) == 1 and roles["wrapper"] == [root]
                    and roles["target"] == [target] and not rows[root][0].parent_span_id
                    and children[root] == [target], "action lacks its sole wrapper/target root")
    targets = roles["target"] + roles["recursive_target"]
    witness.require(len(targets) == witness.counter(scope["target_entries"], positive=True)
                    and len(roles[None]) == len(targets), "target invocation count differs from decoded probes/methods")
    for key in targets:
        witness.require(len(children[key]) == 1 and rows[children[key][0]][1] is None,
                        "target probe lacks its sole selected-method child")
        witness.require(rows[key][0].status.code == rows[children[key][0]][0].status.code,
                        "method/probe exception status differs")
    for key in roles[None]:
        witness.require(all(rows[child][1] == "recursive_target" for child in children[key]),
                        "unexpected selected-method descendant")
        intervals = sorted((rows[child][0].start_time_unix_nano,
                            rows[child][0].end_time_unix_nano) for child in children[key])
        witness.require(all(left[1] <= right[0] for left, right in zip(intervals, intervals[1:])),
                        "synchronous siblings overlap")
    expected_status = 2 if action.failed else 0
    witness.require(rows[root][0].status.code == rows[target][0].status.code == expected_status,
                    "role exits differ from independently observed application outcome")
    return {"action_id": action.action_id, "scope_id": action.scope_id,
            "thread_id": action.thread_id, "trace_id": scope["trace_id"],
            "spans": len(rows), "target_entries": len(targets),
            "selected_method_spans": len(roles[None]),
            "error_spans": sum(span.status.code == 2 for span, _ in rows.values()),
            "flush_failures": scope["flush_failures"], "export_failures": scope["export_failures"]}


def qualify(report: dict, identity: witness.Identity, actions: list[Action], target: Target,
            bodies: list, *, service: str, decoder) -> dict:
    """Match decoded OTLP to retained identities and observed outcome kinds."""
    witness.require(type(target) is Target and type(service) is str and bool(service),
                    "missing independent target/service identity")
    scopes = _expected(report, identity, actions)
    witness.require(type(bodies) is list and 0 < len(bodies) <= MAX_BODIES,
                    "missing or excessive raw receiver bodies")
    by_scope, seen = {key: {} for key in scopes}, set()
    traces = {scope["trace_id"] for scope in scopes.values()}
    raw, total, trace_batches, metric_batches = hashlib.sha256(), 0, 0, 0
    for record in bodies:
        witness.require(type(record) in (tuple, list) and len(record) == 2,
                        "unsupported raw receiver record shape")
        path, body = record
        witness.require(type(path) is str and path in ("/v1/traces", "/v1/metrics")
                        and type(body) is bytes, "unsupported raw receiver record")
        total += len(body)
        witness.require(total <= MAX_BYTES, "raw receiver byte budget exceeded")
        route = path.encode("ascii")
        raw.update(len(route).to_bytes(8, "big") + route + len(body).to_bytes(8, "big") + body)
        if path == "/v1/metrics":
            metric_batches += 1
            continue
        trace_batches += 1
        message = telemetry.decode(decoder, body)
        for resource in message.resource_spans:
            telemetry.resource(resource.resource, service)
            witness.require(resource.resource.dropped_attributes_count == 0, "OTLP resource lost attributes")
            for group in resource.scope_spans:
                witness.require(group.scope.dropped_attributes_count == 0, "OTLP scope lost attributes")
                telemetry.attributes(group.scope.attributes)
                instrumentation = group.scope.name, group.scope.version
                for span in group.spans:
                    key = capture.span_identity(span)
                    witness.require(key not in seen and len(seen) < MAX_SPANS,
                                    "duplicate or excessive decoded spans")
                    seen.add(key)
                    values = telemetry.attributes(span.attributes)
                    scope_id = values.get(SCOPE)
                    if scope_id is None:
                        witness.require(span.trace_id.hex() not in traces,
                                        "action trace contains an unattributed span")
                        continue
                    witness.require(scope_id[0] == "string_value" and scope_id[1] in scopes,
                                    "decoded span claims an unknown action scope")
                    current = scopes[scope_id[1]]
                    span_id, role = _scoped_span(span, instrumentation, values, current, identity, target)
                    by_scope[scope_id[1]][span_id] = span, role
    observed = [_tree(scopes[action.scope_id], by_scope[action.scope_id], action) for action in actions]
    roots = [by_scope[action.scope_id][scopes[action.scope_id]["root_span_id"]][0] for action in actions]
    witness.require(all(left.end_time_unix_nano <= right.start_time_unix_nano
                        for left, right in zip(roots, roots[1:])), "serial action intervals overlap or reverse")
    scoped = sum(item["spans"] for item in observed)
    description = (identity.profile + " with decoded OTLP traces" if identity.profile == witness.HANDLE_PROFILE
                   else "Java action-v2 with decoded OTLP traces")
    return {"decoder": description, "pid": identity.pid,
            "runtime_id": identity.runtime_id, "actions": observed,
            "trace_batches": trace_batches, "metric_batches": metric_batches,
            "spans": len(seen), "scoped_spans": scoped, "unscoped_spans": len(seen) - scoped,
            "raw_receipt_sha256": raw.hexdigest()}
