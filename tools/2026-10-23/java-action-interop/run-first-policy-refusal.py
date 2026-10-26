"""Actual fixed v2 JVM/private-harness/decoded-receipt interoperability.

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

ROOT = Path(__file__).resolve().parent
CONSUMER = Path('/Users/sclarke/github/oteleq-qualification/2026-10-23/java-action-receipt/source-ff21555')
SDK = Path('/Users/sclarke/github/oteleq-qualification/2026-10-23/java-action-review-6e027c4/source-6e027c4')
sys.path[:0] = [str(CONSUMER / 'adapters/generation'), str(CONSUMER / 'examples'), str(SDK)]
import generation
import java_action
import java_action_receipt
import java_build
import java_health
import java_launch
import java_provider
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
  private static int wrapper(ActionFixture receiver,int seed){return receiver.target(seed);}
  private static int envelope(ActionFixture receiver,int seed) throws java.io.IOException {
    rendezvous();return wrapper(receiver,seed);
  }
  private static void rendezvous() throws java.io.IOException {
    OteleqRendezvous.awaitRelease(ACTIONS[position++]);
  }
  private String state(){return "{\"value\":"+value+",\"total\":"+total+",\"getters\":"+getters+",\"position\":"+position+"}";}
  public static void main(String[] ignored) throws Exception {
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


sdk_meta = json.loads(Path('/Users/sclarke/github/otelc-qualification/2026-10-23/java-action-v2/source-6e027c4.json').read_text())
consumer_meta = json.loads(CONSUMER.with_suffix('.json').read_text())
source_audit(SDK,sdk_meta);source_audit(CONSUMER,consumer_meta)
products = java_provider.artefacts(SDK, TOOLS)
products[java_provider.HELPER] = capture.file_digest(SDK / java_provider.HELPER)
project = ROOT / 'project';project.mkdir()
(project/'ActionFixture.java').write_text(SOURCE)
shutil.copyfile(java_action.HELPER, project/java_action.HELPER.name)
folder = ROOT / 'build';folder.mkdir()
environment = {**os.environ,'PYTHONDONTWRITEBYTECODE':'1','JAVA_HOME':'/opt/homebrew/opt/openjdk@21'}
java_build.build(project, [project/'ActionFixture.java', project/java_action.HELPER.name], 'ActionFixture',
                 TOOLS['java'], folder/'scratch/classes', folder, environment, generation.execute)
application_file = folder / java_launch.APPLICATION_FILE
application = prepared_java.PreparedApplication.load(application_file)
declarations = {role:{'owner':'ActionFixture','name':role,'descriptor':'()V' if role=='rendezvous'
    else '(I)I' if role=='target' else '(LActionFixture;I)I'} for role in witness.ROLES}
bindings = ROOT/'bindings.json'
document = witness.compile_bindings(application,declarations,bindings)
assert document['schema_version']==2 and document['profile']==java_witness.PROFILE
assert set(document['bindings'])==set(declarations)
for role, declared in declarations.items():
    actual=document['bindings'][role]
    assert all(actual[key]==value for key,value in declared.items())
    assert actual['class_sha256']==capture.file_digest(folder/'scratch/classes/ActionFixture.class')
    probe='\n'.join((java_witness.PROFILE,role,actual['owner'],actual['name'],actual['descriptor'],actual['class_sha256'],actual['method_sha256']))
    assert hashlib.sha256(probe.encode()).hexdigest()==actual['probe_id']


class Session:
    def __init__(self,harness,runtime,expected,plain,attempt):
        self.harness,self.runtime,self.expected,self.plain,self.attempt=harness,runtime,expected,plain,attempt
        self.identity,self.pending=None,None
        self.ready_records,self.armed,self.completed,self.controls=[],[],[],[]

    def query(self,operation,*arguments,deadline):
        value=java_witness.request(self.runtime/'witness.sock',operation,*arguments,deadline=deadline)
        self.controls.append({'operation':operation,'arguments':arguments,'reply':value})
        return value

    def poll(self,process,deadline):
        if self.pending is not None:
            value=self.query('end',self.identity.runtime_id,self.pending['scope_id'],deadline=deadline)
            self.identity.check(value)
            if value['error'] in ('root_active','incomplete'):return
            assert value['error'] is None and value['scope']['producer_complete']
            self.completed.append(value);self.pending=None
        ready=self.harness.poll(process,deadline)
        if ready is None:return
        self.ready_records.append(ready)
        if self.plain or self.harness.position==4:
            self.harness.release(deadline);return
        status=self.query('status',deadline=deadline)
        if self.identity is None:self.identity=java_witness.Identity.bind(status,self.expected,pid=process.pid)
        current=java_witness.context(status,self.identity,thread_id=ready['thread_id'],cookie=status['scope']['cookie'],sequence=status['scope']['sequence'])
        assert current['phase']=='ready'
        args=(self.identity.runtime_id,current['cookie'],current['sequence'],CASE,self.attempt,
              self.expected['build_sha256'],self.expected['selection_sha256'],self.expected['tooling_sha256'],
              self.expected['wrapper_probe_id'],self.expected['policy_sha256'],ready['thread_id'])
        if self.harness.position==0:
            wrong=self.query('arm',*args[:-1],str(int(ready['thread_id'])+1),deadline=deadline)
            assert wrong['error']=='arm_identity_mismatch' and wrong['scope']['phase']=='ready' and wrong['scope']['scope_id'] is None
        armed=self.query('arm',*args,deadline=deadline)
        bound=java_witness.context(armed,self.identity,thread_id=ready['thread_id'],cookie=current['cookie'],sequence=current['sequence'],case_id=CASE,attempt_id=self.attempt)
        assert bound['phase']=='armed' and bound['scope_id'] is not None
        self.armed.append({'ready':ready,'scope':bound})
        self.pending=bound
        self.harness.release(deadline)

    def finish(self,process):
        self.harness.finish(process)
        assert self.pending is None and (self.plain or len(self.completed)==4)


lanes=[]
for plain in (True,False):
    lane=ROOT/('plain' if plain else 'instrumented');lane.mkdir()
    short=Path(tempfile.mkdtemp(prefix='oeqj-',dir='/tmp')).resolve()
    try:
        runtime=short/'runtime';runtime.mkdir(mode=0o700)
        attempt=uuid.uuid4().hex+uuid.uuid4().hex
        harness=java_action.Harness(short/'harness',CASE,attempt,ACTIONS)
        try:
            service='oteleq-action-interop-'+('plain' if plain else 'sdk')
            with capture.receiver(max_requests=4096,max_bytes=32*1024*1024,response_path=lane/'responses.json') as (endpoint,bodies,errors):
                entry={'path':'ActionFixture.java','otelc_function':'ActionFixture.target(int)'}
                data=java_provider.configuration(entry,endpoint,service)
                policy=Policy.parse(data)
                launch=prepared_java.prepare(application,policy,runtime,plain=plain,diagnostic_profile=True,
                    **({} if plain else {'witness_bindings':bindings}))
                java_launch.verify_identity(launch.identity,json.loads(application_file.read_text()),[folder/'scratch/classes'],runtime,data,plain,False)
                java_launch.verify_application(launch.identity['application'],json.loads(application_file.read_text()),application_file,folder/'scratch/classes')
                expected_argv=java_launch.expected_argv(SDK,TOOLS['java'].resolve(),folder/'scratch/classes','ActionFixture',runtime,data,'ActionFixture','target',plain)
                expected={}
                if not plain:
                    expected_argv.insert(1,'-Dotelc.witness.plan='+str(runtime/'witness.properties'))
                    metadata=capture.strict_json((runtime/'witness.json').read_bytes())
                    assert metadata['schema_version']==2 and metadata['profile']==java_witness.PROFILE and metadata['bindings']==document['bindings']
                    assert metadata['bindings_sha256']==capture.file_digest(bindings)
                    expected={key:metadata[key] for key in ('build_sha256','selection_sha256','policy_sha256','tooling_sha256')}
                    expected.update({role+'_probe_id':document['bindings'][role]['probe_id'] for role in declarations})
                    assert expected['build_sha256']==java_provider.digest(launch.identity['application'])
                    assert expected['policy_sha256']==java_provider.digest(data) and expected['selection_sha256']==launch.identity['selection_sha256']
                    assert expected['tooling_sha256']==java_provider.digest(launch.identity['tooling'][:-2])
                assert list(launch.argv)==expected_argv
                retain(lane/'launch.json',launch.identity)
                session=Session(harness,runtime,expected,plain,attempt)
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
            summary={'plain':plain,'pid':process['pid'],'observations':rows,'otlp_bodies':len(bodies)}
            if plain:
                assert not bodies and not (runtime/'health.json').exists() and not (runtime/'witness-health.json').exists()
            else:
                final=java_witness.read_final(runtime,pid=process['pid'],identity=session.identity)
                actions=[java_action_receipt.Action(ACTIONS[index],CASE,attempt,item['ready']['thread_id'],item['scope']['cookie'],item['scope']['sequence'],item['scope']['scope_id'],rows[index]['outcome']['kind']=='error') for index,item in enumerate(session.armed)]
                received=java_action_receipt.qualify(final,session.identity,actions,java_action_receipt.Target('ActionFixture','target'),bodies,service=service,decoder=ExportTraceServiceRequest.FromString)
                assert [item['target_entries'] for item in received['actions']]==[1,3,1,2]
                recorded={java_telemetry.CALLS:[],java_telemetry.DURATION:[]};points=0
                for path,body in bodies:
                    if path=='/v1/metrics':points+=java_telemetry.metrics(ExportMetricsServiceRequest.FromString(body),service,'target',recorded)
                assert all(values and sorted(values)[-1][1]==7 for values in recorded.values())
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
assert java_provider.artefacts(SDK,TOOLS)=={key:value for key,value in products.items() if key!=java_provider.HELPER}
assert capture.file_digest(SDK/java_provider.HELPER)==products[java_provider.HELPER]
record={'consumer_head':consumer_meta['head'],'producer_head':sdk_meta['head'],
        'consumer_sources_preserved':source_audit(CONSUMER,consumer_meta),'producer_sources_preserved':source_audit(SDK,sdk_meta),
        'lanes':lanes,'scope':'fixed interoperability only; generated provider and shipping admission remain unavailable',
        'unobserved':['Throwable inherited/native internals','JDK harness transport state']}
retain(ROOT/'proof.json',record)
print(json.dumps({'consumer_head':record['consumer_head'],'producer_head':record['producer_head'],
    'actual_jvm_pids':[lane['pid'] for lane in lanes],'scopes':len(lanes[1]['received']['actions']),
    'proof_sha256':capture.file_digest(ROOT/'proof.json')}))
