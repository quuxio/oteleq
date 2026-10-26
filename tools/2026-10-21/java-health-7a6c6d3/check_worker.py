"""Check complete expected receiver values and raw OTLP for the prepared worker."""
import base64
import hashlib
import json
from pathlib import Path
import re

from google.protobuf.json_format import MessageToDict
from opentelemetry.proto.collector.metrics.v1.metrics_service_pb2 import ExportMetricsServiceRequest
from opentelemetry.proto.collector.trace.v1.trace_service_pb2 import ExportTraceServiceRequest

ROOT=Path(__file__).resolve().parent


def integer(value):
    return {'kind':'integer','type':'java.int','value':str(value),'bits':32,'signed':True}


def graph(value,total,*,result=False):
    roots={'receiver':{'kind':'reference','node_id':'n0'},'argument:0':integer(3),'static:App.total':integer(total)}
    if result: roots['result']=integer(13)
    return {'roots':roots,'nodes':[{'id':'n0','type':'java.object:App','fields':{'value':integer(value)}}]}


def attributes(rows):
    result={}
    for row in rows:
        assert row['key'] not in result and len(row['value'])==1
        result[row['key']]=next(iter(row['value'].values()))
    return result


def verify_file(record):
    path=Path(record['path']); info=path.stat()
    assert hashlib.sha256(path.read_bytes()).hexdigest()==record['sha256'],str(path)
    for key,actual in (('size',info.st_size),('inode',info.st_ino),('device',info.st_dev),('mtime_ns',info.st_mtime_ns)):
        assert record[key]==actual,(path,key)


def check(folder, *, source_root=None):
    source_root = source_root or folder
    expected={'java_receiver_schema_version':1,'before':graph(10,0),'after':graph(13,3),
              'outcome':{'kind':'return','value':graph(13,3,result=True)}}
    for lane in ('baseline','instrumented'):
        assert json.loads((folder/lane/'observation').read_text())==expected
        observed=json.loads((folder/lane/'typed-observation.json').read_text())
        assert observed['before']==expected['before'] and observed['after']==expected['after']
        assert observed['outcome']=={'kind':'return','graph':expected['outcome']['value']}
        assert observed['fixture']=={'status':'ready'} and not observed['gaps']
        launch=json.loads((folder/lane/'launch.json').read_text())
        assert launch['main_class']=='OteleqDriver' and launch['plain'] is (lane=='baseline')
        assert launch['application']['ordered_classpath']==[str(source_root/'scratch/classes')]
        original=Path(json.loads((folder/lane/'runtime-original.json').read_text()))
        assert launch['control_socket']==(None if lane=='baseline' else str(original/'control.sock'))
        application=launch['application']
        files=[application['manifest'],*application['classpath'],*application['sources'],*launch['tooling']]
        for record in files: verify_file(record)
        assert {p.resolve() for p in (source_root/'scratch/classes').rglob('*') if p.is_file()}=={Path(row['path']) for row in application['classpath']}
        log=(folder/lane/'runtime/class-load.log').read_text()
        for name in ('App','OteleqDriver','OteleqGraph'):
            assert re.search(r'\] '+name+r' source: file:'+re.escape(str(source_root/'scratch/classes'))+r'/',log)
        assert not (folder/lane/'application/stdout').read_bytes()
    noise = ('[otel.javaagent 2026-10-21 00:00:00:000 +0000] [main] INFO io.opentelemetry.javaagent.tooling.VersionLogger - opentelemetry-javaagent - version: 2.32.0\nOpenJDK 64-Bit Server VM warning: Sharing is only supported for boot loader classes because bootstrap classpath has been appended\n' if source_root.name=='stderr-v1' else '')
    for lane in ('baseline','instrumented'):
        assert (folder/lane/'application/stderr').read_bytes()==noise.encode()
        launch=json.loads((folder/lane/'launch.json').read_text())
        assert launch['jvm_profile']=='diagnostic-no-cds' and launch['argv'].count('-Xshare:off')==1
        original=Path(json.loads((folder/lane/'runtime-original.json').read_text()))
        assert launch['agent_diagnostics']==(None if lane=='baseline' else str(original/'agent.log'))
    diagnostics=(folder/'instrumented/runtime/agent.log').read_text()
    assert diagnostics.count('opentelemetry-javaagent - version: 2.32.0')==1
    assert diagnostics.count('Helper classes and resources wont be injected if no types are instrumented: {0}')==1
    assert 'OpenJDK 64-Bit Server VM warning' not in diagnostics
    records=json.loads((folder/'http-capture.json').read_text())
    assert not records['errors']
    decoded=[]; spans=[]; points=0; metric_batches=0; trace_batches=0
    def check_snapshot(metrics):
        calls=metrics['otelc.function.calls']['sum']['data_points']
        assert len(calls)==1 and calls[0]['as_int']=='1' and attributes(calls[0]['attributes'])=={'function':'add'}
        duration=metrics['otelc.function.duration']['histogram']['data_points']
        assert len(duration)==1
        point=duration[0]
        assert point['count']=='1' and attributes(point['attributes'])=={'function':'add'}
        assert point['explicit_bounds']==[1e-6,1e-5,.0001,.001,.01,.1,1.0]
        assert len(point['bucket_counts'])==8 and sum(map(int,point['bucket_counts']))==1
        assert 0<=point['min']==point['max']==point['sum']
        processed=metrics['processedSpans']['sum']['data_points']
        assert len(processed)==1 and processed[0]['as_int']=='1' and attributes(processed[0]['attributes'])=={'dropped':False,'processorType':'BatchSpanProcessor'}
        queued=metrics['queueSize']['gauge']['data_points']
        assert len(queued)==1 and queued[0]['as_int']=='0'

    for index,row in enumerate(records['bodies']):
        assert row['file']==f'otlp-{index}.protobuf' and row['path'] in ('/v1/traces','/v1/metrics')
        message=ExportTraceServiceRequest() if row['path']=='/v1/traces' else ExportMetricsServiceRequest()
        message.ParseFromString((folder/row['file']).read_bytes())
        frame=MessageToDict(message,preserving_proto_field_name=True)
        decoded.append({'path':row['path'],'message':frame})
        metrics={}
        for kind in ('resource_spans','resource_metrics'):
            for resource in frame.get(kind,[]):
                attrs=attributes(resource['resource']['attributes'])
                assert attrs['service.name']=='oteleq-prepared-worker' and attrs['otelc.language']=='java' and attrs['telemetry.sdk.version']=='1.66.0'
                for scope in resource.get('scope_spans',[]): spans+=scope.get('spans',[])
                for scope in resource.get('scope_metrics',[]):
                    for metric in scope.get('metrics',[]):
                        assert metric['name'] not in metrics
                        metrics[metric['name']]=metric
                        points+=sum(len(value.get('data_points',[])) for value in metric.values() if isinstance(value,dict))
        if row['path']=='/v1/metrics':
            metric_batches+=1
            required={'processedSpans','queueSize','otelc.function.calls','otelc.function.duration'}
            assert required <= set(metrics) <= required|{'otlp.exporter.seen','otlp.exporter.exported'}
            check_snapshot(metrics)
        else: trace_batches+=1
    assert decoded==json.loads((folder/'decoded-otlp.json').read_text())
    assert len(spans)==1 and spans[0]['name']=='App.add' and not spans[0].get('parent_span_id') and spans[0]['status']=={}
    span=spans[0];attrs=attributes(span['attributes'])
    assert attrs=={'code.namespace':'App','code.function':'add','thread.id':'1','thread.name':'main'}
    for name,size in (('trace_id',16),('span_id',8)):
        value=base64.b64decode(span[name],validate=True);assert len(value)==size and any(value)
    assert 0<int(span['start_time_unix_nano'])<=int(span['end_time_unix_nano'])
    health=json.loads((folder/'instrumented/runtime/health.json').read_text())
    launch=json.loads((folder/'instrumented/launch.json').read_text())
    process=json.loads((folder/'instrumented/application/process.json').read_text())
    assert health['schema_version']==1 and health['kind']=='otelc.runtime-health' and health['scope']=='sdk_pipeline'
    assert health['pid']==process['pid'] and health['phase']=='final' and health['sdk_attached'] is True
    assert process['argv']==launch['argv']
    assert health['policy_sha256']==launch['policy_sha256'] and health['selection_sha256']==launch['selection_sha256']
    selection=json.loads((folder/'instrumented/runtime/selection.json').read_text())
    assert health['selection_sha256']==hashlib.sha256(json.dumps(selection,sort_keys=True).encode()).hexdigest()
    assert health['lifecycle']=={'flush':'succeeded','shutdown':'succeeded'}
    assert health['span_accounting']=={'processors_observed':1,'batch_processors_observed':1,'sampled_started':'1',
        'sampled_ended':'1','sampled_active':'0','queue_pending':'0','queue_dropped':'0','queue_evidence':'derived_after_shutdown'}
    for name,unit,batches,units in (('trace_exports','spans',trace_batches,1),('metric_exports','metric_points',metric_batches,points)):
        assert health[name]=={'exporters_observed':1,'unit':unit,'batches_started':str(batches),'batches_succeeded':str(batches),
            'batches_failed':'0','batches_pending':'0','units_started':str(units),'units_succeeded':str(units),'units_failed':'0'}
    assert health['downstream_receipt']==health['otlp_partial_rejection']=='unavailable'
    assert health==json.loads((folder/'instrumented/checked-health.json').read_text())
    return {'application_processes':2,'verdict':'equivalent_observed','selected_spans':1,'recorded_calls':1,
        'health_pid':process['pid'],'trace_batches':trace_batches,'metric_batches':metric_batches,'metric_points':points,
        'final_flush':'succeeded','final_shutdown':'succeeded','final_queue_pending':0,'final_queue_dropped':0,
        'stderr_bytes_per_lane':len(noise.encode()),'scope':'Fixed generated consumer smoke only; no live controls, repeated generic CLI, lifetime completeness, invocation attribution or shipping claim'}

if __name__=='__main__':
    result=check(ROOT/'clean-v1')
    (ROOT/'checked.json').write_text(json.dumps(result,indent=2)+'\n')
    print(json.dumps(result))
