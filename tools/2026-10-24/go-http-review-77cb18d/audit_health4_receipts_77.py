"""Read original health4/OTLP evidence independently without launching applications."""

from collections import defaultdict
import hashlib
import json
from pathlib import Path
import sys

ROOT = Path(__file__).resolve().parent
ORIGINAL = Path('/Users/sclarke/github/otelc-qualification/2026-10-24/go-source-adapter/http-single-use-retained')
CONSUMER = Path('/Users/sclarke/github/oteleq-qualification/work/oteleq-go-source-provider')
sys.path[:0] = [str(CONSUMER / 'adapters/generation'), str(CONSUMER / 'examples')]
import go_files as files
import go_health as health
import go_provider as provider
from opentelemetry.proto.collector.metrics.v1.metrics_service_pb2 import ExportMetricsServiceRequest
from opentelemetry.proto.collector.trace.v1.trace_service_pb2 import ExportTraceServiceRequest

OUTPUT = ROOT / 'independent-health4-audit-77'
OUTPUT.mkdir(mode=0o700)
held = {}


def observe(path):
    identity, stable, raw = files.file(path, keep=True)
    assert path not in held or held[path] == (identity, stable)
    held[path] = identity, stable
    return raw


def document(path):
    return json.loads(observe(path))


def service(resource):
    names = [item.value.string_value for item in resource.attributes if item.key == 'service.name']
    assert len(names) == 1 and names[0]
    return names[0]


def packets(name):
    directory = ORIGINAL / name
    counts = defaultdict(lambda: {'trace_batches': 0, 'spans': 0, 'metric_batches': 0, 'metric_points': 0,
                                 'http_spans': 0, 'function_spans': 0, 'function_calls': [], 'http_metric_names': set()})
    spans = []
    index = document(directory / 'index.json')
    assert type(index) is list and len(index) <= 4096
    seen = set()
    for item in index:
        assert set(item) == {'bytes', 'file', 'kind', 'sha256'} and item['kind'] in ('traces', 'metrics')
        filename = files.relative(item['file'])
        assert filename not in seen
        seen.add(filename)
        raw = observe(directory / filename)
        assert len(raw) == item['bytes'] and hashlib.sha256(raw).hexdigest() == item['sha256']
        batch_services = set()
        if item['kind'] == 'traces':
            packet = ExportTraceServiceRequest.FromString(raw)
            for resource in packet.resource_spans:
                name = service(resource.resource)
                batch_services.add(name)
                for scope in resource.scope_spans:
                    assert scope.scope.name in ('io.quux.otelc.go', 'go.opentelemetry.io/contrib/instrumentation/net/http/otelhttp')
                    for span in scope.spans:
                        assert len(span.trace_id) == 16 and any(span.trace_id) and len(span.span_id) == 8 and any(span.span_id)
                        assert span.start_time_unix_nano <= span.end_time_unix_nano
                        counts[name]['spans'] += 1
                        counts[name]['http_spans' if scope.scope.name.endswith('/otelhttp') else 'function_spans'] += 1
                        spans.append((name, span))
        else:
            packet = ExportMetricsServiceRequest.FromString(raw)
            for resource in packet.resource_metrics:
                name = service(resource.resource)
                batch_services.add(name)
                for scope in resource.scope_metrics:
                    assert scope.scope.name in ('io.quux.otelc.go', 'go.opentelemetry.io/contrib/instrumentation/net/http/otelhttp')
                    for metric in scope.metrics:
                        kind = metric.WhichOneof('data')
                        assert kind in ('sum', 'gauge', 'histogram', 'exponential_histogram')
                        points = getattr(metric, kind).data_points
                        counts[name]['metric_points'] += len(points)
                        if metric.name == 'otelc.function.calls':
                            assert kind == 'sum'
                            counts[name]['function_calls'].extend(point.as_int for point in points)
                        if scope.scope.name.endswith('/otelhttp'):
                            counts[name]['http_metric_names'].add(metric.name)
        assert len(batch_services) == 1
        for name in batch_services:
            counts[name]['trace_batches' if item['kind'] == 'traces' else 'metric_batches'] += 1
    return counts, spans


provider.verify_protocols(document(ORIGINAL / 'protocols.json'))
main, spans = packets('receipt-1')
expected_names = {f'go-http-{role}-{collection}{emission}' for role in ('server', 'client') for collection in (0, 1) for emission in (0, 1)}
assert set(main) == expected_names
by_id = {span.span_id: span for _, span in spans}
assert len(by_id) == len(spans) == 64
for name, span in spans:
    if '-server-' in name:
        parent = by_id[span.parent_span_id]
        assert parent.trace_id == span.trace_id and parent.kind == (3 if span.kind == 2 else 2)
    elif span.kind == 3:
        parent = by_id[span.parent_span_id]
        assert parent.trace_id == span.trace_id and parent.name == 'io.quux.otelc.examples/gohttp.workloadRequest'
    else:
        assert span.kind == 1 and not span.parent_span_id

results = []
runtimes = sorted((ORIGINAL / 'execution').glob('test_two_services_all_startup_and_live_states_keep_context_and_collection-*/health.json'))
assert len(runtimes) == 8
for path in runtimes:
    runtime = path.parent
    request = document(runtime / 'go-request.json')
    application = document(runtime / 'go-application-start.json')
    plan = document(runtime / 'go-plan.json')
    completion = document(runtime / 'go-execution.json')
    name = request['policy']['resource']['service_name']
    received = main[name]
    assert received['spans'] == 8 and received['http_spans'] == received['function_spans'] == 4
    assert received['function_calls'] and max(received['function_calls']) == 2
    assert received['http_metric_names'] and all(name.startswith('http.') for name in received['http_metric_names'])
    observe(path)
    raw = health.read(runtime)
    assert raw == completion['sdk_health'] and completion['application_exit_code'] == 0 and completion['failures'] == {}
    result = health.qualify(raw, pid=application['pid'], policy_sha256=provider.policy_digest(request['policy']),
        selection_sha256=plan['selection_sha256'], received={key: received[key] for key in ('trace_batches', 'spans', 'metric_batches', 'metric_points')},
        function_spans=4, observer_completions=0, received_http_spans=4)
    results.append({'service': name, 'pid': application['pid'], 'http': result['http_spans'], 'received': result['received']})

leak_counts, _ = packets('receipt-2')
runtime = ORIGINAL / 'execution/test_unclosed_response_body_is_visible_and_cannot_pass_final_health-2'
request, application, plan, completion = [document(runtime / name) for name in ('go-request.json', 'go-application-start.json', 'go-plan.json', 'go-execution.json')]
observe(runtime / 'health.json')
leak = health.read(runtime)
assert completion['application_exit_code'] == 0 and completion['failures'] and completion['sdk_health'] == leak
assert leak['http_spans'] == {'observed': True, 'closed': True, 'started': '1', 'ended': '0', 'active': '1'}
stats = leak_counts[request['policy']['resource']['service_name']]
try:
    health.qualify(leak, pid=application['pid'], policy_sha256=provider.policy_digest(request['policy']),
        selection_sha256=plan['selection_sha256'], received={key: stats[key] for key in ('trace_batches', 'spans', 'metric_batches', 'metric_points')},
        function_spans=stats['function_spans'], observer_completions=0, received_http_spans=stats['http_spans'])
except ValueError as error:
    assert 'HTTP span completions' in str(error), str(error)
    refusal = str(error)
else:
    raise AssertionError('unread HTTP body incorrectly passed final consumer qualification')
for path, expected in held.items():
    identity, stable, _ = files.file(path)
    assert (identity, stable) == expected
result = {'result': 'passed', 'provider': '77cb18d8e17271c156ce5fa73db9af8a1cb98f8f',
    'healthy_services': results, 'complete_healthy_spans': len(spans), 'unread_body_refusal': refusal,
    'original_evidence_files_held': len(held), 'new_target_applications': 0,
    'consumer_health_sha256': files.identity(CONSUMER / 'adapters/generation/go_health.py')['sha256'],
    'scope': 'Independent health4/raw-receipt compatibility and refusal only. Full consumer build/launch ownership, generated workflow admission and broader context/build profiles remain open.'}
with (OUTPUT / 'result.json').open('x') as stream:
    json.dump(result, stream, indent=2)
    stream.write('\n')
print(json.dumps({key: value for key, value in result.items() if key not in ('healthy_services', 'scope')}), flush=True)
