"""Independent validation for the fixed Python collection lifetime corpus."""
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
        creator = None
        if spec.get("creator") is not None:
            if len(span.links) != 1 or (span.links[0].trace_id, span.links[0].span_id) not in creators:
                raise ValueError("JavaScript collection has no matching source factory creation link")
            creator = creators[(span.links[0].trace_id, span.links[0].span_id)]
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
