"""Actual-provider development check of three disabled Node startup states."""
import hashlib,json,os
from pathlib import Path
import subprocess,sys

root=Path(__file__).parent
cli=root/'quux-oteleq-88ca22d'
provider=Path('/Users/sclarke/github/otelc-qualification/2026-10-22/node-provider-0f05020/provider')
verifier=Path('/Users/sclarke/github/oteleq-qualification/2026-10-23/node-metric-controls/source-a295b0e/tests')
sys.path.insert(0,str(verifier))
from qualify_generation import command
import node_controls_oracle as oracle
from opentelemetry.proto.collector.metrics.v1.metrics_service_pb2 import ExportMetricsServiceRequest
from opentelemetry.proto.collector.trace.v1.trace_service_pb2 import ExportTraceServiceRequest

folder=root/'startup-smoke-88ca-node24'
folder.mkdir()
application=folder/'application';application.mkdir()
methods={'collectionOff':1,'emissionOff':2,'bothOff':3}
states=[{'collection':True,'emission':True},{'collection':False,'emission':True},{'collection':True,'emission':False},{'collection':False,'emission':False}]
source='class Counter{static total=0;static delta=0;constructor(start){this.value=start;this.self=this;}\n'
for method in methods:
    source+=method+'(value){this.value+=value;Counter.total+=value;process.stdout.write(Buffer.from([0,255,10]));process.stderr.write(Buffer.from([1,255,10]));return 42;}\n'
source+='}\n'
filename=application/'startup.cjs';filename.write_text(source)
policy='schema_version=1\nlanguages=["javascript"]\n[functions]\ninclude='+json.dumps(['startup.Counter.'+name for name in methods])+'\n[adapters.node]\nbackend="source-v1"\n[limits]\ncase_timeout_ms=60000\n'
for method,offset in methods.items():
    flags=states[offset:]+states[:offset]
    policy+='\n[[fixtures]]\nfunction='+json.dumps('startup.Counter.'+method)+'\ncases=[[7]]\nreceiver={factory="Counter",arguments=[10]}\nsequence=[\n'
    for index,state in enumerate(flags):
        policy+='{action="call",arguments='+('"case"' if index==0 else json.dumps([index+1]))+',metrics={collection='+str(state['collection']).lower()+',emission='+str(state['emission']).lower()+'}},\n'
    policy+=']\n'
config=folder/'equivalence.toml';config.write_text(policy)
os.environ.update(OTELEQ_PYTHON=sys.executable,OTELEQ_CLI=str(cli))
workspace=Path(command([cli,'plan','--source',application,'--otelc-root',provider,'--workspace-parent',folder,'--config',config],folder,'plan'))
command([cli,'generate','--workspace',workspace],folder,'generate')
command([cli,'run','--workspace',workspace,'--report-dir',folder/'comparison'],folder,'run')
report=json.loads((folder/'comparison/report.json').read_bytes())
assert report['exit_code']==0 and not report['blocked'] and report['source_preserved'] and len(report['cases'])==3
identities=set()
for case in report['cases']:
    method=case['function'].rsplit('.',1)[-1]
    expected_states=states[methods[method]:]+states[:methods[method]]
    assert case['exit_code']==0
    for lane in ('baseline','instrumented_on'):
        for repeat in range(2):
            attempt=folder/'comparison'/case['case']/(lane+'-'+str(repeat))
            oracle.check(json.loads((attempt/'observation').read_bytes()),method,7,lane=='instrumented_on')
            assert (attempt/'stdout').read_bytes()==bytes.fromhex('00ff0a')*4
            assert (attempt/'stderr').read_bytes()==bytes.fromhex('01ff0a')*4
            controls=json.loads((attempt/'node-controls.json').read_bytes())
            assert [step['requested'] for step in controls['steps']]==expected_states
            app=json.loads((attempt/'node-source-application.json').read_bytes())
            assert app['pid']==controls['pid']
            identities.add(app['pid'])
            if lane=='baseline':
                assert controls['sdk_pid'] is None
                continue
            initial=controls['steps'][0]['before']['history'][0]['status']
            assert all(initial[key] is value for key,value in expected_states[0].items())
            assert initial['function_completions']==0
            sdk=json.loads((attempt/'node-runtime/node-status.json').read_bytes())
            assert sdk['phase']=='closed' and sdk['function_completions']==4 and sdk['pid']==app['pid'] and sdk['sdk_pid']==controls['sdk_pid']
            bodies=json.loads((attempt/'http-capture.json').read_bytes())
            assert not bodies['errors']
            spans=[];latest={}
            for row in bodies['bodies']:
                raw=(attempt/row['file']).read_bytes()
                if row['path']=='/v1/traces':
                    message=ExportTraceServiceRequest.FromString(raw)
                    spans.extend(s for resource in message.resource_spans for scope in resource.scope_spans for s in scope.spans)
                elif row['path']=='/v1/metrics':
                    message=ExportMetricsServiceRequest.FromString(raw)
                    for resource in message.resource_metrics:
                        for scope in resource.scope_metrics:
                            if scope.scope.name!='io.quux.otelc.functions':continue
                            for metric in scope.metrics:
                                points=metric.histogram.data_points if metric.name.endswith('duration') else metric.sum.data_points
                                for point in points:
                                    if metric.name not in latest or point.time_unix_nano>latest[metric.name][0]:
                                        latest[metric.name]=(point.time_unix_nano,point.count if metric.name.endswith('duration') else point.as_int)
            assert len(spans)==4 and all(s.name==case['function'] and not s.parent_span_id for s in spans)
            assert {name:value[1] for name,value in latest.items()}=={'otelc.function.calls':2,'otelc.function.duration':2}
assert len(identities)==12 and filename.read_text()==source
record={'runtime_commit':'88ca22d0853ea173c1f5974933333caaf1f3ba42','cli_sha256':hashlib.sha256(cli.read_bytes()).hexdigest(),'actual_applications':12,'cases':3,'initial_states':['collection-off','emission-off','both-off'],'source_preserved':True,'baseline_and_instrumented_repeats':2,'independent_complete_graph_and_binary_oracle':True,'actual_trace_and_collected_metrics_checked':True,'scope':'Development actual-provider smoke on Node24 JavaScript synchronous receiver methods only; not retained-route, TypeScript, Node26 or overall startup admission.'}
(folder/'SMOKE.json').write_text(json.dumps(record,indent=2)+'\n')
print(json.dumps(record),flush=True)
