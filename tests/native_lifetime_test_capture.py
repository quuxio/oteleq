"""Adapt copied real captures to explicit literal boundary schemas for tests.

This helper supplies test input, imports no oracle/SDK renderer and starts no
applications. Only the completed C/C++ source captures are actual observations.
"""

import hashlib
import json
from pathlib import Path
import shutil

from opentelemetry.proto.collector.metrics.v1.metrics_service_pb2 import ExportMetricsServiceRequest
from opentelemetry.proto.collector.trace.v1.trace_service_pb2 import ExportTraceServiceRequest

FIXTURES = Path(__file__).with_name('fixtures')


def write(folder: Path, name: str, value: object) -> None:
    """Write a primitive record only inside the caller's temporary capture."""
    (folder / name).write_text(json.dumps(value, allow_nan=False))


def capture(folder: Path, language: str, mode: str) -> tuple[dict, dict]:
    """Copy an actual completed capture, then declare any adapted boundary input."""
    assert language in ('c', 'cpp') and mode in ('completed', 'zero', 'censored', 'unwind', 'throwing-destructor', 'target-error')
    assert mode not in ('unwind', 'throwing-destructor', 'target-error') or language == 'cpp'
    original = FIXTURES / ('native-lifetime-' + language + '-capture')
    shutil.copytree(original, folder)
    manifest = json.loads((original / 'capture.json').read_text())
    for name, expected in manifest['files'].items():
        assert hashlib.sha256((original / name).read_bytes()).hexdigest() == expected
    report = original / 'report.json' if language == 'cpp' else FIXTURES / 'native-lifetime-workflow-c-report.json'
    bundle = original / 'typed-bundle.json' if language == 'cpp' else FIXTURES / 'native-lifetime-workflow-c-typed-bundle.json'
    entry, = [row for row in json.loads(report.read_text())['inventory'] if row['status'] == 'ready']
    witness = json.loads(bundle.read_text())['cases'][0]['instrumented_on'][0]['execution']['witness']
    if mode == 'completed': return entry, witness
    complete = mode != 'censored'
    release = 'destructor_entry' if language == 'cpp' else 'free_entry'
    end = 'shutdown_censored' if mode == 'censored' else release
    observation = {'type_usr': 'c:@S@Item', 'name': 'Item', 'creation_path': [0],
                   'release_path': [0] if complete else None, 'complete': complete,
                   'exception_exit': mode == 'throwing-destructor' if language == 'cpp' and complete else None}
    trace = ExportTraceServiceRequest.FromString((folder / 'otlp-1.protobuf').read_bytes())
    scope = trace.resource_spans[0].scope_spans[0]
    if mode == 'target-error':
        function, = [span for span in scope.spans if span.name == entry['otelc_runtime_function']]
        function.status.code = 2
        function.attributes.add(key='error.type').value.string_value = 'exception'
    lifetime, = [span for span in scope.spans if span.name == 'Item lifetime']
    root, = [span for span in scope.spans if span.name == entry['otelc_runtime_function']]
    if mode == 'censored': lifetime.end_time_unix_nano = root.end_time_unix_nano + 1000000
    duration = lifetime.end_time_unix_nano - lifetime.start_time_unix_nano
    labels = [('type', 'Item'), ('boundary', end), ('otelc.lifetime.complete', complete),
              ('otelc.lifetime.instance', '1')]
    if language == 'cpp' and complete: labels.append(('otelc.destructor.exception_exit', mode == 'throwing-destructor'))
    del lifetime.attributes[:]
    for name, value in labels:
        attribute = lifetime.attributes.add(key=name)
        if type(value) is bool: attribute.value.bool_value = value
        else: attribute.value.string_value = value
    if mode == 'zero':
        kept = [span for span in scope.spans if span.name != 'Item lifetime']
        del scope.spans[:]; scope.spans.extend(kept)
    (folder / 'otlp-1.protobuf').write_bytes(trace.SerializeToString())
    points = 0
    for name in ('otlp-0.protobuf', 'otlp-2.protobuf'):
        message = ExportMetricsServiceRequest.FromString((folder / name).read_bytes())
        values = message.resource_metrics[0].scope_metrics[0].metrics
        if mode == 'target-error':
            calls = next(value for value in values if value.name == 'otelc.function.calls')
            error = values.add(name='otelc.function.errors', unit='{error}')
            error.sum.is_monotonic = True
            error.sum.aggregation_temporality = 2
            point = error.sum.data_points.add()
            point.CopyFrom(calls.sum.data_points[0])
            point.as_int = 1
            point.attributes.add(key='error.type').value.string_value = 'exception'
        if mode == 'zero':
            kept = [value for value in values if not value.name.startswith('otelc.lifetime.')]
            del values[:]; values.extend(kept)
        for value in values:
            if mode == 'censored' and value.name == 'otelc.lifetime.completed': value.name = 'otelc.lifetime.incomplete'
            data = getattr(value, value.WhichOneof('data'))
            points += len(data.data_points)
            if not value.name.startswith('otelc.lifetime.'): continue
            boundary = end if value.name.endswith(('.incomplete', '.duration')) else release
            for point in data.data_points:
                next(a for a in point.attributes if a.key == 'boundary').value.string_value = boundary
                if mode == 'censored' and value.name.endswith('.duration') and point.count:
                    measured = float(duration) / 1000000000
                    point.sum = point.min = point.max = measured
                    buckets = [0] * (len(point.explicit_bounds) + 1)
                    bucket = next((i for i, bound in enumerate(point.explicit_bounds) if measured <= bound), len(buckets) - 1)
                    buckets[bucket] = 1
                    del point.bucket_counts[:]; point.bucket_counts.extend(buckets)
        (folder / name).write_bytes(message.SerializeToString())
    for name in ('expected-lifetimes-before-build.json', 'expected-lifetimes.json'):
        value = json.loads((folder / name).read_text())
        value['observations'] = [] if mode == 'zero' else [observation]
        write(folder, name, value)
    final = json.loads((folder / 'native-runtime/app/health.json').read_text())
    accounting = final['object_accounting' if language == 'cpp' else 'resource_accounting']
    accounting.update(types='0' if mode == 'zero' else '1', admitted='0' if mode == 'zero' else '1',
                      completed='0' if mode in ('zero', 'censored') else '1', censored='1' if mode == 'censored' else '0')
    spans = 1 if mode == 'zero' else 2
    final['span_accounting'].update(sampled_started=str(spans), sampled_ended=str(spans))
    final['trace_exports'].update(units_started=str(spans), units_succeeded=str(spans))
    final['metric_exports'].update(units_started=str(points), units_succeeded=str(points))
    write(folder, 'native-runtime/app/health.json', final)
    digest = hashlib.sha256()
    for row in json.loads((folder / 'http-capture.json').read_text())['bodies']:
        body = (folder / row['file']).read_bytes(); route = row['path']
        digest.update(len(route).to_bytes(8, 'big') + route.encode() + len(body).to_bytes(8, 'big') + body)
    verified = json.loads((folder / 'native-verified-lifetimes.json').read_text())
    rows = [] if mode == 'zero' else [{**verified['lifetimes'][0], **observation, 'boundary': end, 'duration_ns': duration}]
    verified.update(spans=spans, lifetimes=rows, metric_points=points, health=final, raw_otlp_sha256=digest.hexdigest())
    write(folder, 'native-verified-lifetimes.json', verified)
    witness['raw_otlp_sha256'] = digest.hexdigest()
    return entry, witness
