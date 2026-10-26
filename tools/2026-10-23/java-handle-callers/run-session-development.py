"""Actual fixed schema-3 private-handle/ordinary-harness/decoded-receipt interoperability.

This is qualification work, not generated-provider or shipping admission.
"""

import hashlib
import json
import os
from pathlib import Path
import shutil
import sys
import tempfile
import time
import uuid

ROOT = Path(__file__).resolve().parent / sys.argv[1]
ROOT.mkdir()
CONSUMER = Path('/Users/sclarke/github/oteleq-qualification/2026-10-23/java-handle-callers/source-dcf5ff4')
SDK = Path(sys.argv[2]).resolve(strict=True)
sys.path[:0] = [str(CONSUMER / 'adapters/generation'), str(CONSUMER / 'examples'), str(SDK), '/Users/sclarke/github/oteleq-qualification/work/oteleq-java-action-session/adapters/generation']
import generation
import java_action
import java_action_session
import java_action_bindings
import java_handle_callers
import java_action_receipt
import java_build
import java_health
import java_launch
import java_provider
import java_profiles
import java_telemetry
import java_witness
import otelc_capture as capture
from otelc import prepared_java, witness
from otelc.config import Policy
from opentelemetry.proto.collector.metrics.v1.metrics_service_pb2 import ExportMetricsServiceRequest
from opentelemetry.proto.collector.trace.v1.trace_service_pb2 import ExportTraceServiceRequest

SOURCE = r'''
public final class ActionFixture {
  private int value=10;
  private static int total, getters, position;
  private static final Problem FAILURE=new Problem();
  private static final String[] ACTIONS=System.getenv("OTELEQ_FIXTURE_ACTIONS").split(",");
  private static final class Problem extends RuntimeException {
    public String getMessage(){getters++;return "changed";}
    public String toString(){getters++;return "changed";}
    public synchronized Throwable getCause(){getters++;return this;}
  }
  private int target(int seed){
    if(seed<0)throw FAILURE;
    total+=seed;value+=seed;
    return seed==0?value:target(seed-1)+seed;
  }
  private static final java.lang.invoke.MethodHandle HANDLE=handle();
  private static java.lang.invoke.MethodHandle handle(){
    try{return java.lang.invoke.MethodHandles.lookup().findVirtual(ActionFixture.class,"target",
        java.lang.invoke.MethodType.methodType(int.class,int.class));}
    catch(ReflectiveOperationException failure){throw new AssertionError("fixture handle setup failed");}
  }
  private static int wrapper(ActionFixture receiver,int seed) throws Throwable {
    return (int)HANDLE.invokeExact(receiver,seed);
  }
  private static int envelope(ActionFixture receiver,int seed) throws Throwable {
    rendezvous();return wrapper(receiver,seed);
  }
  private static void rendezvous() throws java.io.IOException {
    OteleqRendezvous.awaitRelease(ACTIONS[position++]);
  }
  private String state(){return "{\"value\":"+value+",\"total\":"+total+",\"getters\":"+getters+",\"position\":"+position+"}";}
  public static void main(String[] ignored) throws Throwable {
    System.out.write(new byte[]{0,(byte)255,10});
    ActionFixture receiver=new ActionFixture();
    java.nio.file.Path output=java.nio.file.Path.of(System.getenv("OTELEQ_FIXTURE_OBSERVATION"));
    int[] seeds={0,2,-1,1};
    for(int seed:seeds){
      String before=receiver.state(),outcome;
      try{int value=envelope(receiver,seed);outcome="{\"kind\":\"return\",\"value\":"+value+"}";}
      catch(Problem failure){outcome="{\"kind\":\"error\",\"type\":\""+failure.getClass().getName()+"\",\"same\":"+(failure==FAILURE)+"}";}
      String row="{\"seed\":"+seed+",\"before\":"+before+",\"outcome\":"+outcome+",\"after\":"+receiver.state()+"}\n";
      java.nio.file.Files.writeString(output,row,java.nio.file.StandardOpenOption.CREATE,java.nio.file.StandardOpenOption.APPEND);
    }
    OteleqRendezvous.awaitRelease(ACTIONS[4]);
    System.err.write(new byte[]{1,(byte)254,10});
  }
}
'''
members, declarations, intended_route = java_handle_callers.members(
    'ActionFixture', 'ActionFixture', 'target', ['int'], 'int', caller_owner='ActionFixture', instance=True)
start = SOURCE.index('  private static final java.lang.invoke.MethodHandle HANDLE=handle();')
end = SOURCE.index('  private String state()', start)
SOURCE = SOURCE[:start] + members + SOURCE[end:]
SOURCE = SOURCE.replace('private static int total, getters, position;', 'private static int total, getters;')
SOURCE = SOURCE.replace('envelope(receiver,seed)', 'oteleqEnvelope(receiver,seed)')
SOURCE = SOURCE.replace('+position+', '+OTELEQ_ACTION_POSITION+')
CASE = hashlib.sha256(SOURCE.encode()).hexdigest()
ACTIONS = [hashlib.sha256(('action-' + str(index)).encode()).hexdigest() for index in range(5)]
TOOLS = {'java': Path('/opt/homebrew/opt/openjdk@21/bin/java'), 'javac': Path('/opt/homebrew/opt/openjdk@21/bin/javac')}
os.environ.update(OTELC_JAVA=str(TOOLS['java']), OTELC_JAVAC=str(TOOLS['javac']))
ORACLE = []
for index, (seed, before_value, before_total, after_value, after_total, returned) in enumerate(
    ((0,10,0,10,0,10), (2,10,0,13,3,16), (-1,13,3,13,3,None), (1,13,3,14,4,15))):
    state = lambda value,total,position: {'value':value,'total':total,'getters':0,'position':position}
    ORACLE.append({'seed':seed,'before':state(before_value,before_total,index),
        'outcome':{'kind':'return','value':returned} if returned is not None else {'kind':'error','type':'ActionFixture$Problem','same':True},
        'after':state(after_value,after_total,index+1)})


def retain(path, value):
    path.write_text(json.dumps(value, indent=2) + '\n')


def source_audit(root, metadata):
    assert all(hashlib.sha256((root/name).read_bytes()).hexdigest()==sha for name,sha in metadata['files'].items())
    return len(metadata['files'])


sdk_meta = json.loads(Path(sys.argv[3]).read_text())
consumer_meta = json.loads(CONSUMER.with_suffix('.json').read_text())
source_audit(SDK,sdk_meta);source_audit(CONSUMER,consumer_meta)
products = java_provider.artefacts(SDK, TOOLS, java_profiles.SAFE)
products[java_provider.HELPER] = capture.file_digest(SDK / java_provider.HELPER)
retain(ROOT/'inputs.json',{'consumer_head':consumer_meta['head'],'producer_head':sdk_meta['head'],
    'sdk_products':products,'runner_sha256':capture.file_digest(Path(__file__))})
project = ROOT / 'project';project.mkdir()
(project/'ActionFixture.java').write_text(SOURCE)
(project/java_action.HELPER.name).write_text(java_handle_callers.helper_source(''))
folder = ROOT / 'build';folder.mkdir()
environment = {**os.environ,'PYTHONDONTWRITEBYTECODE':'1','JAVA_HOME':'/opt/homebrew/opt/openjdk@21'}
java_build.build(project, [project/'ActionFixture.java', project/java_action.HELPER.name], 'ActionFixture',
                 TOOLS['java'], folder/'scratch/classes', folder, environment, generation.execute)
application_file = folder / java_launch.APPLICATION_FILE
application = prepared_java.PreparedApplication.load(application_file)
bindings_folder = ROOT/'bindings'
document = java_action_bindings.compile(SDK, project, folder, bindings_folder, TOOLS, declarations,
    environment, generation.execute, profile=java_witness.HANDLE_PROFILE, route=intended_route)
bindings = bindings_folder/'bindings.json'
assert document['schema_version']==3 and document['profile']==java_witness.HANDLE_PROFILE
assert set(document['bindings'])==set(declarations)
for role, declared in declarations.items():
    actual=document['bindings'][role]
    assert all(actual[key]==value for key,value in declared.items())
    assert actual['class_sha256']==capture.file_digest(folder/'scratch/classes/ActionFixture.class')
    probe='\n'.join((java_witness.HANDLE_PROFILE,role,actual['owner'],actual['name'],actual['descriptor'],actual['class_sha256'],actual['method_sha256']))
    assert hashlib.sha256(probe.encode()).hexdigest()==actual['probe_id']
route={'kind':'direct_method_handle','field_owner':'ActionFixture','field_name':'OTELEQ_HANDLE',
    'field_descriptor':'Ljava/lang/invoke/MethodHandle;','site_instruction':0,
    'invoke_owner':'java/lang/invoke/MethodHandle','invoke_name':'invokeExact',
    'invoke_descriptor':'(LActionFixture;I)I','reference_kind':5}
route['sha256']=hashlib.sha256('\n'.join([java_witness.HANDLE_PROFILE,
    *(str(route[key]) for key in ('kind','field_owner','field_name','field_descriptor','site_instruction',
      'invoke_owner','invoke_name','invoke_descriptor','reference_kind')),
    document['bindings']['wrapper']['probe_id'],document['bindings']['target']['probe_id']]).encode()).hexdigest()
assert set(document)=={'schema_version','kind','profile','bindings','route'} and document['route']==route


lanes=[]
for repeat,plain in ((1,True),(1,False),(2,True),(2,False)):
    lane=ROOT/(('plain' if plain else 'instrumented')+'-'+str(repeat));lane.mkdir()
    short=Path(tempfile.mkdtemp(prefix='oeqj-',dir='/tmp')).resolve()
    try:
        runtime=short/'runtime';runtime.mkdir(mode=0o700)
        attempt=uuid.uuid4().hex+uuid.uuid4().hex
        harness=java_action.Harness(short/'harness',CASE,attempt,ACTIONS)
        try:
            service='oteleq-action-interop-'+('plain' if plain else 'sdk')+'-'+str(repeat)
            with capture.receiver(max_requests=4096,max_bytes=32*1024*1024,response_path=lane/'responses.json') as (endpoint,bodies,errors):
                entry={'path':'ActionFixture.java','otelc_function':'ActionFixture.target(int)'}
                data=java_provider.configuration(entry,endpoint,service)
                data['context']={'tasks':False,'http':False}
                policy=Policy.parse(data)
                assert policy.data==data
                launch=prepared_java.prepare(application,policy,runtime,plain=plain,diagnostic_profile=True,
                    **({} if plain else {'witness_bindings':bindings,'witness_profile':witness.HANDLE_PROFILE}))
                java_launch.verify_identity(launch.identity,json.loads(application_file.read_text()),[folder/'scratch/classes'],runtime,data,plain,False)
                java_launch.verify_application(launch.identity['application'],json.loads(application_file.read_text()),application_file,folder/'scratch/classes')
                expected_argv=java_launch.expected_argv(SDK,TOOLS['java'].resolve(),folder/'scratch/classes','ActionFixture',runtime,data,'ActionFixture','target',plain,java_profiles.SAFE)
                expected={}
                if not plain:
                    # The explicit action SDK additionally fixes disabled context
                    # instrumentation. Existing stock/safe recipes remain exact.
                    values=java_launch.agent_values(data,'ActionFixture','target',java_profiles.SAFE)
                    values.update({key:'false' for key in (
                        'otel.instrumentation.executors.enabled',
                        'otel.instrumentation.java-http-client.enabled',
                        'otel.instrumentation.java-http-server.enabled',
                        'otel.instrumentation.otelc-http-headers.enabled')})
                    first=expected_argv.index('-Dotel.exporter.otlp.endpoint='+endpoint)
                    expected_argv[first:expected_argv.index('-cp')]=[
                        '-D'+key+'='+value for key,value in sorted(values.items())]
                    expected_argv.insert(1,'-Dotelc.witness.plan='+str(runtime/'witness.properties'))
                    metadata=capture.strict_json((runtime/'witness.json').read_bytes())
                    assert metadata['schema_version']==3 and metadata['profile']==java_witness.HANDLE_PROFILE and metadata['bindings']==document['bindings']
                    assert metadata['bindings_sha256']==capture.file_digest(bindings) and metadata['route']==route
                    expected={key:metadata[key] for key in ('build_sha256','selection_sha256','policy_sha256','tooling_sha256')}
                    expected.update({role+'_probe_id':document['bindings'][role]['probe_id'] for role in declarations})
                    expected['route_binding_sha256']=route['sha256']
                    assert expected['build_sha256']==java_provider.digest(launch.identity['application'])
                    assert expected['policy_sha256']==java_provider.digest(data) and expected['selection_sha256']==launch.identity['selection_sha256']
                    assert expected['tooling_sha256']==java_provider.digest(launch.identity['tooling'][:-2])
                retain(lane/'expected-argv.json',expected_argv)
                retain(lane/'policy.json',data)
                assert list(launch.argv)==expected_argv
                retain(lane/'launch.json',launch.identity)
                session=java_action_session.Session(harness,runtime,expected,plain=plain)
                try:
                    result=generation.execute(launch.argv,project,{**environment,**harness.environment(),
                        'OTELEQ_FIXTURE_ACTIONS':','.join(ACTIONS),'OTELEQ_FIXTURE_OBSERVATION':str(lane/'observations.jsonl')},
                        lane/'process',timeout=30,record_process=True,interaction=session)
                finally:
                    retain(lane/'controls.json',session.controls)
                    retain(lane/'harness.json',harness.records)
                assert result.returncode==0 and result.stdout==b'\x00\xff\n' and result.stderr==b'\x01\xfe\n'
                assert not errors
            rows=[capture.strict_json(line) for line in (lane/'observations.jsonl').read_bytes().splitlines()]
            assert rows==ORACLE
            launch.verify_inputs()
            process=capture.strict_json((lane/'process/process.json').read_bytes())
            retain(lane/'controls.json',session.controls);retain(lane/'harness.json',harness.records)
            raw=lane/'otlp';raw.mkdir()
            for index,(path,body) in enumerate(bodies):(raw/f'{index:04d}.bin').write_bytes(body)
            retain(raw/'index.json',[{'route':path,'file':f'{index:04d}.bin','sha256':hashlib.sha256(body).hexdigest()} for index,(path,body) in enumerate(bodies)])
            summary={'repeat':repeat,'plain':plain,'pid':process['pid'],'observations':rows,'otlp_bodies':len(bodies)}
            if plain:
                assert not bodies and not (runtime/'health.json').exists() and not (runtime/'witness-health.json').exists()
            else:
                final=java_witness.read_final(runtime,pid=process['pid'],identity=session.identity)
                actions=session.receipt_actions([row['outcome']['kind']=='error' for row in rows])
                received=java_action_receipt.qualify(final,session.identity,actions,java_action_receipt.Target('ActionFixture','target'),bodies,service=service,decoder=ExportTraceServiceRequest.FromString)
                assert [item['target_entries'] for item in received['actions']]==[1,3,1,2]
                recorded={java_telemetry.CALLS:[],java_telemetry.DURATION:[]};points=0
                for path,body in bodies:
                    if path=='/v1/metrics':points+=java_telemetry.metrics(ExportMetricsServiceRequest.FromString(body),service,'target',recorded)
                for values in recorded.values():
                    ordered=[value for _,value in sorted(values)]
                    assert ordered and ordered[-1]==7 and ordered==sorted(ordered)
                    assert all(0<=value<=7 for value in ordered)
                health=java_health.qualify(java_health.read(runtime),pid=process['pid'],policy_sha256=expected['policy_sha256'],selection_sha256=expected['selection_sha256'],trace_batches=received['trace_batches'],spans=received['spans'],metric_batches=received['metric_batches'],metric_points=points)
                retain(lane/'verified-action-receipt.json',received);retain(lane/'verified-health.json',health)
                summary['received']=received
            java_launch.archive(runtime,lane)
            retain(lane/'summary.json',summary);lanes.append(summary)
        finally:harness.close()
    except BaseException as failure:
        retain(lane/'failure.json',{'type':type(failure).__name__,'message':str(failure),
            'runtime':str(short),'retained_for_diagnosis':True})
        raise
    else:shutil.rmtree(short)
assert java_provider.artefacts(SDK,TOOLS,java_profiles.SAFE)=={key:value for key,value in products.items() if key!=java_provider.HELPER}
assert capture.file_digest(SDK/java_provider.HELPER)==products[java_provider.HELPER]
record={'session_component_sha256':capture.file_digest(Path(java_action_session.__file__)),
        'consumer_head':consumer_meta['head'],'producer_head':sdk_meta['head'],
        'consumer_sources_preserved':source_audit(CONSUMER,consumer_meta),'producer_sources_preserved':source_audit(SDK,sdk_meta),
        'lanes':lanes,'scope':'emitted typed caller, independent compiler bridge and actual runtime interoperability; development host session; generated pipeline and shipping admission remain unavailable',
        'unobserved':['Throwable inherited/native internals','JDK harness transport state']}
retain(ROOT/'proof.json',record)
print(json.dumps({'consumer_head':record['consumer_head'],'producer_head':record['producer_head'],
    'actual_jvm_pids':[lane['pid'] for lane in lanes],
    'scopes':sum(len(lane['received']['actions']) for lane in lanes if not lane['plain']),
    'proof_sha256':capture.file_digest(ROOT/'proof.json')}))
