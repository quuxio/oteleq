"""Independent witness checks for the fixed Python resource-close workload."""
from collections.abc import Iterator, Mapping, Sequence
from typing import Any

import otelc_collection


def metric_decoder() -> Any:
    """Use the qualified protobuf dependency only during real resource capture."""
    from opentelemetry.proto.collector.metrics.v1.metrics_service_pb2 import ExportMetricsServiceRequest
    return ExportMetricsServiceRequest


def scoped_metrics(resource: Any, service: str) -> Iterator[Any]:
    """Reject telemetry from a different execution or instrumentation scope."""
    attributes = otelc_collection.attributes(resource.resource)
    if attributes.get("service.name") != service:
        raise ValueError("resource metric service differs from the execution")
    for scope in resource.scope_metrics:
        if scope.scope.name != "quux.otelc":
            raise ValueError("resource metric instrumentation scope differs")
        yield from scope.metrics


def metrics(bodies: Sequence[tuple[str, bytes]], service: str, decoder: Any) -> Iterator[Any]:
    """Read metrics only from the independently identified execution/scope."""
    for path, body in bodies:
        if path != "/v1/metrics":
            continue
        for resource in decoder.FromString(body).resource_metrics:
            yield from scoped_metrics(resource, service)


def metric_points(metric: Any, kind: str, count: int, spec: Mapping[str, Any]) -> None:
    """Reject missing, flagged, non-cumulative or differently scoped points."""
    if metric.WhichOneof("data") != kind:
        raise ValueError("resource metric has an unexpected numeric kind")
    data = getattr(metric, kind)
    if kind == "sum" and (data.aggregation_temporality != 2 or not data.is_monotonic):
        raise ValueError("resource counters must be monotonic and cumulative")
    if not data.data_points:
        raise ValueError("resource metric has no data points")
    required = {} if metric.name.endswith(".failed_releases") else {
        "code.type.name": spec["type"], "otelc.lifetime.boundary": "resource"}
    for point in data.data_points:
        fields = otelc_collection.attributes(point)
        if fields != required or point.flags:
            raise ValueError("resource metric fields or flags differ from the fixture")
        if point.WhichOneof("value") != "as_int" or point.as_int != count:
            raise ValueError("resource metric count differs from the fixture")


def metric_values(bodies: Sequence[tuple[str, bytes]], service: str, spec: Mapping[str, Any], decoder: Any) -> None:
    """Require the fixed workload's actual final cumulative resource metrics."""
    expected = {"otelc.lifetime.admitted": ("sum", spec["count"]),
                "otelc.lifetime.completed": ("sum", spec["count"]),
                "otelc.lifetime.live": ("gauge", 0),
                "otelc.lifetime.failed_releases": ("sum", spec["failed_releases"])}
    seen = set()
    for metric in metrics(bodies, service, decoder):
        if metric.name in expected:
            metric_points(metric, *expected[metric.name], spec)
            seen.add(metric.name)
    if seen != set(expected):
        raise ValueError("missing resource metric observations")


def verify(spans: Sequence[Any], report: Mapping[str, Any], spec: Mapping[str, Any]) -> dict[str, int]:
    """Require successful exactly-once completion after an expected failed close.

    Failed release is an observed application/lifecycle event, not export loss.
    Unexpected failures, pending release frames and genuine losses still fail.
    """
    losses = otelc_collection.verify(spans, report, spec, boundary="resource")
    status = report["lifetimes"]
    expected = {"active_releases": 0, "failed_releases": spec["failed_releases"]}
    if any(type(status.get(key)) is not int or status[key] != count for key, count in expected.items()):
        raise ValueError("missing, pending or unexpected resource release observations")
    return losses
