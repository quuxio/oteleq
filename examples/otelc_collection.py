"""Independent validation of declared call trees and lifetime boundaries."""
from collections.abc import Mapping, Sequence
from subprocess import CompletedProcess
from typing import Any


def expected_channels(result: CompletedProcess[bytes], channels: Mapping[str, str]) -> None:
    """Check fixture outputs independently of agreement between the lanes."""
    if any(getattr(result, name) != expected.encode() for name, expected in channels.items()):
        raise ValueError("application channels do not match independent fixture expectations")


def lifetime_status(report: Mapping[str, Any], count: int) -> dict[str, int]:
    """Require all selected instances to complete without losses or live state."""
    status = report.get("lifetimes")
    if not isinstance(status, dict):
        raise ValueError("missing collection lifetime report")
    expected = {"admitted": count, "completed": count, "current_live": 0,
                "censored": 0, "tracked_instances": 0, "active_constructors": 0,
                "failed_initialisations": 0}
    if any(type(status.get(key)) is not int or status[key] != value for key, value in expected.items()):
        raise ValueError("missing, censored or incomplete collection lifetime counters")
    losses = status.get("losses")
    if (not isinstance(losses, dict)
            or any(not isinstance(key, str) or not key.strip() or type(value) is not int or value != 0
                   for key, value in losses.items())):
        raise ValueError("missing or lossy collection lifetime diagnostics")
    return {"lifetimes." + key: value for key, value in losses.items()}


def attributes(span: Any) -> dict[str, str]:
    """Reject ambiguous metadata while reading the decoded protobuf span."""
    values = {}
    for attribute in span.attributes:
        if not attribute.key or attribute.key in values:
            raise ValueError("duplicate or unnamed lifetime attribute")
        values[attribute.key] = attribute.value.string_value
    return values


def lifetime_span(span: Any, spec: Mapping[str, Any], creator: Any, instances: set[str], *, boundary: str = "collection") -> None:
    """Validate one collection root and its link to the actual creation call."""
    if (span.parent_span_id or span.kind != 1 or span.dropped_links_count
            or span.dropped_attributes_count or len(span.links) != int(creator is not None)):
        raise ValueError("collection lifetime must be a complete linked standalone root")
    if creator is not None:
        link = span.links[0]
        if (link.dropped_attributes_count
                or (link.trace_id, link.span_id) != (creator.trace_id, creator.span_id)):
            raise ValueError("collection lifetime creation link does not match creator")
    values = attributes(span)
    instance = values.get("otelc.lifetime.instance", "")
    if (values.get("code.type.name") != spec["type"]
            or values.get("otelc.lifetime.boundary") != boundary
            or not instance or not instance.isascii() or not instance.isdecimal()
            or len(instance) > 20 or instance[0] == "0" or instance in instances):
        raise ValueError("wrong collection type, boundary or instance identity")
    instances.add(instance)


def verify(spans: Sequence[Any], report: Mapping[str, Any], spec: Mapping[str, Any], *, boundary: str = "collection") -> dict[str, int]:
    """Span IDs/parents, service and scope have already passed the shared decoder."""
    creators = [span for span in spans if span.name == spec["creator"]]
    lifetimes = [span for span in spans if span.name == spec["span"]]
    if len(creators) != 1 or len(lifetimes) != spec["count"]:
        raise ValueError("missing creator or collection lifetime spans")
    creator = creators[0]
    instances = set()
    for span in lifetimes:
        lifetime_span(span, spec, creator, instances, boundary=boundary)
    functions = report.get("functions")
    expected = {spec["creator"]: {"count": 1, "unwinds": 0}}
    if (functions != expected or any(type(functions[spec["creator"]].get(key)) is not int
                                     for key in ("count", "unwinds"))):
        raise ValueError("collection creator runtime observations differ")
    return lifetime_status(report, spec["count"])


def sequence_functions(spans: Sequence[Any], target: str, calls: int, creator: str | None) -> None:
    """Check named invocation roots, allowing recursion within each real call tree."""
    roots = [span.name for span in spans if not span.parent_span_id and span.name in (target, creator)]
    if roots.count(target) != calls or creator is not None and roots.count(creator) != 1:
        raise ValueError("sequence method/factory invocation roots differ from declared actions")
    if creator is None:
        return
    parents = {(span.trace_id, span.span_id): span for span in spans}
    for span in spans:
        if span.name != target:
            continue
        parent = span
        while parent.parent_span_id:
            parent = parents[(parent.trace_id, parent.parent_span_id)]
            if parent.name == creator:
                raise ValueError("receiver construction invoked the selected sequence method")


def serial_call_trees(spans: Sequence[Any], target: str, calls: int) -> None:
    """Require complete synchronous trees with an unambiguous serial root order."""
    if type(calls) is not int or not 1 <= calls <= 32 or type(target) is not str or not target.strip():
        raise ValueError("serial sequence requires 1 to 32 named calls")
    nodes = {(span.trace_id, span.span_id): span for span in spans}
    roots = [span for span in spans if not span.parent_span_id]
    if len(nodes) != len(spans) or len(roots) != calls or any(span.name != target for span in spans):
        raise ValueError("serial sequence has foreign, duplicate or missing call trees")
    for span in spans:
        start, end = span.start_time_unix_nano, span.end_time_unix_nano
        if type(start) is not int or type(end) is not int or start <= 0 or end < start:
            raise ValueError("serial sequence has invalid call intervals")
    for span in spans:
        start, end = span.start_time_unix_nano, span.end_time_unix_nano
        if span.parent_span_id:
            parent = nodes.get((span.trace_id, span.parent_span_id))
            if parent is None or not parent.start_time_unix_nano <= start <= end <= parent.end_time_unix_nano:
                raise ValueError("serial sequence child is outside its selected parent")
    ordered = sorted(roots, key=lambda span: span.start_time_unix_nano)
    for before, after in zip(ordered, ordered[1:]):
        if (after.start_time_unix_nano <= before.start_time_unix_nano
                or after.start_time_unix_nano < before.end_time_unix_nano):
            raise ValueError("serial sequence call roots overlap or have ambiguous order")
    completed = set()
    for span in spans:
        path, current = set(), span
        while (key := (current.trace_id, current.span_id)) not in completed:
            if key in path:
                raise ValueError("serial sequence has a cyclic parent tree")
            path.add(key)
            if not current.parent_span_id:
                break
            current = nodes[(current.trace_id, current.parent_span_id)]
        completed.update(path)


def linked_creator(span: Any, creators: Mapping[tuple[bytes, bytes], Any], required: bool) -> Any:
    """Resolve the one actual source-factory link before checking the lifetime root."""
    if not required:
        return None
    if len(span.links) != 1 or (span.links[0].trace_id, span.links[0].span_id) not in creators:
        raise ValueError("JavaScript collection has no matching source factory creation link")
    return creators[(span.links[0].trace_id, span.links[0].span_id)]


def javascript(spans: Sequence[Any], report: Mapping[str, Any], spec: Mapping[str, Any]) -> tuple[dict[str, int], int]:
    """Validate actual JS collection roots; unavailable requested completion is a gap."""
    status = report.get("lifetimes")
    fields = ("admitted", "completed", "current_live", "censored", "tracked_instances", "tracked_constructors", "failed_initialisations")
    if (not isinstance(status, dict) or any(type(status.get(key)) is not int or status[key] < 0 for key in fields)
            or status["admitted"] != status["completed"] + status["current_live"]):
        raise ValueError("invalid JavaScript lifetime accounting")
    losses = status.get("losses")
    if not isinstance(losses, dict) or any(not isinstance(key, str) or not key.strip() or type(value) is not int or value < 0 for key, value in losses.items()):
        raise ValueError("invalid JavaScript lifetime losses")
    observed = [span for span in spans if span.name == spec["span"]]
    creators = {(span.trace_id, span.span_id): span for span in spans if span.name == spec.get("creator")}
    instances = set()
    for span in observed:
        creator = linked_creator(span, creators, spec.get("creator") is not None)
        lifetime_span(span, spec, creator, instances)
    result = {"lifetimes." + key: value for key, value in losses.items()}
    expected = {"admitted": spec["count"], "completed": spec["count"], "current_live": 0, "censored": 0,
                "tracked_instances": 0, "tracked_constructors": 0, "failed_initialisations": 0}
    for name, count in expected.items():
        if status[name] != count:
            result["lifetimes.requested." + name] = 1
    if len(observed) != spec["count"] or len(observed) != status["completed"]:
        result["lifetimes.requested.spans"] = 1
    return result, len(observed)


def _serial_require(condition: bool, reason: str) -> None:
    """Reject incomplete or ambiguous serial trace trees."""
    if not condition:
        raise ValueError(reason)


def serial_trees(spans: list) -> list[list]:
    """Complete nonoverlapping serial trees supply counts, not invocation cookies."""
    # The capture module also imports this module for fixed workload checks.
    import otelc_capture as capture

    nodes = {capture.span_identity(span): span for span in spans}
    _serial_require(len(nodes) == len(spans), "duplicate serial call span")
    capture.trace_roots({key: (span.trace_id, span.parent_span_id) if span.parent_span_id else None
                         for key, span in nodes.items()})
    roots = sorted((key for key, span in nodes.items() if not span.parent_span_id),
                   key=lambda key: (nodes[key].start_time_unix_nano, nodes[key].end_time_unix_nano))
    _serial_require(all(nodes[left].end_time_unix_nano <= nodes[right].start_time_unix_nano
                         and (nodes[left].start_time_unix_nano, nodes[left].end_time_unix_nano)
                         != (nodes[right].start_time_unix_nano, nodes[right].end_time_unix_nano)
                         for left, right in zip(roots, roots[1:])), "serial call root order is ambiguous or overlapping")
    grouped = {root: [] for root in roots}
    for key, span in nodes.items():
        root = key
        while nodes[root].parent_span_id:
            root = (nodes[root].trace_id, nodes[root].parent_span_id)
        parent = nodes[root]
        _serial_require(parent.start_time_unix_nano <= span.start_time_unix_nano <= span.end_time_unix_nano <= parent.end_time_unix_nano,
                         "serial call child span escapes its call tree")
        grouped[root].append(span)
    return [grouped[root] for root in roots]
