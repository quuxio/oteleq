"""Real bounded Java metric protobufs for checkpoint receipt regressions."""

from opentelemetry.proto.collector.metrics.v1.metrics_service_pb2 import ExportMetricsServiceRequest
import java_telemetry as telemetry


def metric_body(count: int, *, service: str = 'case', method: str = 'identity') -> bytes:
    message = ExportMetricsServiceRequest()
    resource = message.resource_metrics.add()
    for key, value in (('service.name', service), ('otelc.language', 'java')):
        resource.resource.attributes.add(key=key).value.string_value = value
    scope = resource.scope_metrics.add()
    scope.scope.name, scope.scope.version = telemetry.METHOD_SCOPE
    calls = scope.metrics.add(name=telemetry.CALLS, unit='{call}')
    calls.sum.aggregation_temporality = 2;calls.sum.is_monotonic = True
    point = calls.sum.data_points.add(start_time_unix_nano=1000000000, time_unix_nano=2000000000, as_int=count)
    point.attributes.add(key='function').value.string_value = method
    duration = scope.metrics.add(name=telemetry.DURATION, unit='s')
    duration.histogram.aggregation_temporality = 2
    point = duration.histogram.data_points.add(start_time_unix_nano=1000000000, time_unix_nano=2000000000,
        count=count, sum=1e-7 * count, explicit_bounds=telemetry.BUCKETS,
        bucket_counts=[count] + [0] * len(telemetry.BUCKETS))
    point.attributes.add(key='function').value.string_value = method
    return message.SerializeToString()
