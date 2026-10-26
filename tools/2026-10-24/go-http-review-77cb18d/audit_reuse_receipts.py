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

OUTPUT = ROOT / 'independent-reuse-audit'
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



counts, spans = packets('receipt-3')
assert set(counts) == {'go-http-reuse-client','go-http-reuse-server'}
clients=[span for name,span in spans if name=='go-http-reuse-client' and span.kind==3]
servers=[span for name,span in spans if name=='go-http-reuse-server' and span.kind==2]
assert len(clients)==len(servers)==2
assert {(span.trace_id,span.parent_span_id) for span in servers} == {(span.trace_id,span.span_id) for span in clients}
results=[]
for role,ordinal in [('client',2),('server',1)]:
 runtime=ORIGINAL/'execution'/('test_returned_request_context_keeps_each_native_http_operation_visible-'+str(ordinal))
 request,application,plan,completion=[document(runtime/name) for name in ('go-request.json','go-application-start.json','go-plan.json','go-execution.json')]
 observe(runtime/'health.json'); raw=health.read(runtime)
 assert completion['application_exit_code']==0 and completion['failures']=={} and completion['sdk_health']==raw
 name='go-http-reuse-'+role; received=counts[name]
 assert raw['http_spans']=={'observed':True,'closed':True,'started':'2','ended':'2','active':'0'}
 result=health.qualify(raw,pid=application['pid'],policy_sha256=provider.policy_digest(request['policy']),selection_sha256=plan['selection_sha256'],received={key:received[key] for key in ('trace_batches','spans','metric_batches','metric_points')},function_spans=received['function_spans'],observer_completions=0,received_http_spans=2)
 results.append({'service':name,'pid':application['pid'],'received':result['received'],'http':result['http_spans']})
responses=[json.loads(line) for line in observe(ORIGINAL/'application-responses.jsonl').decode().splitlines()]
reuse=[row for row in responses if 'reuse' in str(row)]
assert reuse
for path,expected in held.items():
 identity,stable,_=files.file(path); assert (identity,stable)==expected
result={'result':'passed','services':results,'client_http_spans':2,'server_http_spans':2,'exact_cross_service_parentage':True,'raw_spans':len(spans),'original_evidence_files_held':len(held),'new_target_applications':0,'scope':'Independent retained public reuse receipt, final health and parent joins; source preservation and broader execution/build admission remain separate.'}
with (OUTPUT/'result.json').open('x') as stream:json.dump(result,stream,indent=2)
print(json.dumps({key:value for key,value in result.items() if key!='services'}),flush=True)
