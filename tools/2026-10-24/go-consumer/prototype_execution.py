"""Develop the public Go execution boundary with real raw OTLP and owned PIDs."""
import copy,hashlib,json,os,subprocess,sys,time
from pathlib import Path
for key in list(os.environ):
 if key.startswith(('OTEL','GH_','GITHUB_','SONAR_','AWS_')):os.environ.pop(key)
BASE=Path(__file__).resolve().parent
SDK=Path('/Users/sclarke/github/oteleq-qualification/2026-10-24/go-benchmark-review-fdd434b/fixed-source-b95780c')
CONSUMER=Path('/Users/sclarke/github/oteleq-qualification/work/oteleq-go-source-provider')
sys.path[:0]=[str(CONSUMER/'adapters/generation'),str(CONSUMER/'examples'),str(SDK)]
import go_health as independent_health
import otelc_capture as capture
from otelc import prepared_go as prepared,control
from otelc.config import Policy
from otelc.prepared_python import stop_group
from opentelemetry.proto.collector.trace.v1.trace_service_pb2 import ExportTraceServiceRequest
from opentelemetry.proto.collector.metrics.v1.metrics_service_pb2 import ExportMetricsServiceRequest
ROOT=BASE/'prototype-execution-01';ROOT.mkdir();APP=ROOT/'application';APP.mkdir()
(APP/'go.mod').write_text('module example.com/oteleqfixture\n\ngo 1.26.0\n')
(APP/'main.go').write_text('package main\nimport("bufio";"encoding/json";"os";"strconv")\nvar total int\nfunc init(){if p:=os.Getenv("OTELEQ_GO_BUILD_SENTINEL");p!=""{os.WriteFile(p,[]byte("unexpected build startup"),0600)}}\nfunc Add(value int)int{total+=value;return total+1}\nfunc main(){scanner:=bufio.NewScanner(os.Stdin);for scanner.Scan(){if scanner.Text()=="quit"{return};n,err:=strconv.Atoi(scanner.Text());if err!=nil{panic(err)};v:=Add(n);json.NewEncoder(os.Stdout).Encode(map[string]int{"value":v,"total":total})}}\n')
POLICY=ROOT/'policy.toml';POLICY.write_text('schema_version=3\nlanguages=["go"]\n[resource]\nservice_name="oteleq-go-consumer-prototype"\n[sources]\ninclude=["**/*.go"]\n[functions]\ninclude=["example.com/oteleqfixture.Add"]\n[export]\ninterval_ms=1000\ntimeout_ms=1000\nshutdown_timeout_ms=10000\n[metrics]\ncollection=true\nemission=true\n[traces]\nenabled=true\nsample_ratio=1.0\n[lifetimes]\nenabled=false\n[context]\ntasks=false\nhttp=false\n')
def facts(path):
 info=path.stat();return (hashlib.sha256(path.read_bytes()).hexdigest(),info.st_ino,info.st_mode,info.st_size,info.st_mtime_ns,info.st_ctime_ns)
def write(path,value):path.write_text(json.dumps(value,indent=2)+'\n')
original={p.name:facts(p) for p in APP.iterdir()}
index=json.loads((SDK.parent/'fixed-source-b95780c-index.json').read_text())
assert all(hashlib.sha256((SDK/name).read_bytes()).hexdigest()==sha for name,sha in index['files'].items())
environment=dict(os.environ,OTELC_PYTHON=sys.executable,OTELEQ_GO_BUILD_SENTINEL=str(ROOT/'unexpected-build-start'),GOCACHE='/Users/sclarke/github/oteleq-qualification/2026-10-24/go-source-review-67b1b0d/source/build/go-build-cache',GOMODCACHE='/Users/sclarke/github/oteleq-qualification/2026-10-24/go-source-review-67b1b0d/source/build/go-module-cache',PATH='/Users/sclarke/go/pkg/mod/golang.org/toolchain@v0.0.1-go1.27.3.darwin-arm64/bin:/opt/homebrew/bin:/usr/bin:/bin:/usr/sbin:/sbin')
command=[str(SDK/'bin/quux-otelc'),'--config',str(POLICY),'go-build','--root',str(APP),'--output',str(ROOT/'bundle'),'--go','/Users/sclarke/go/pkg/mod/golang.org/toolchain@v0.0.1-go1.27.3.darwin-arm64/bin/go']
write(ROOT/'build-command.json',{'argv':command,'cwd':str(SDK),'source_provider':index['head']})
with (ROOT/'build.stdout').open('xb') as out,(ROOT/'build.stderr').open('xb') as err:built=subprocess.run(command,cwd=SDK,env=environment,stdout=out,stderr=err,timeout=300)
assert built.returncode==0 and not (ROOT/'unexpected-build-start').exists()
assert {p.name:facts(p) for p in APP.iterdir()}==original
results=[]
for plain in (True,False):
 lane=ROOT/('plain' if plain else 'instrumented');lane.mkdir(mode=0o700);runtime=lane/'runtime'
 with capture.receiver(max_requests=128,allow_chunked=True) as (endpoint,bodies,errors):
  data=copy.deepcopy(Policy.load(POLICY).data);data['export']['endpoint']=endpoint;policy=Policy.parse(data)
  prepared.prepare(policy,runtime,build_directory=ROOT/'bundle',plain=plain)
  argv=prepared.command(runtime)
  expected=[sys.executable,'-I','-S','-B',str(SDK/'otelc/go_supervisor.py'),'--runtime',str(runtime)]
  assert argv==expected
  write(lane/'caller-launch.json',{'argv':argv,'parent_pid':os.getpid(),'plain':plain})
  process=subprocess.Popen(argv,stdin=subprocess.PIPE,stdout=subprocess.PIPE,stderr=subprocess.PIPE,start_new_session=True)
  try:
   deadline=time.monotonic()+20
   while not (runtime/'go-application-start.json').exists():
    assert process.poll() is None and time.monotonic()<deadline
    time.sleep(.005)
   application=json.loads((runtime/'go-application-start.json').read_text());pid=application['pid']
   assert pid!=process.pid and os.getpgid(pid)==process.pid
   assert application['supervisor_pid']==process.pid and application['process_group']==process.pid and application['plain'] is plain
   if not plain:control.wait_ready(runtime/'control.json',pid)
   out,err=process.communicate(b'21\nquit\n',timeout=20)
   assert process.returncode==0 and err==b'' and json.loads(out)=={'value':22,'total':21}
   (lane/'stdout').write_bytes(out);(lane/'stderr').write_bytes(err)
   execution=prepared.execution(runtime,supervisor_pid=process.pid,parent_pid=os.getpid(),returncode=process.returncode)
   assert execution['application_pid']==pid and execution['failures']=={} and execution['inputs_rechecked']
  finally:stop_group(process)
 assert not errors
 capture.retain_http(lane,bodies,errors)
 received={'trace_batches':0,'spans':0,'metric_batches':0,'metric_points':0};spans=[];calls=[];durations=[]
 for path,body in bodies:
  if path=='/v1/traces':
   received['trace_batches']+=1
   message=ExportTraceServiceRequest.FromString(body)
   for resource in message.resource_spans:
    for scope in resource.scope_spans:
     assert scope.scope.name=='io.quux.otelc.go'
     spans.extend(scope.spans)
  else:
   assert path=='/v1/metrics';received['metric_batches']+=1
   message=ExportMetricsServiceRequest.FromString(body)
   for resource in message.resource_metrics:
    for scope in resource.scope_metrics:
     assert scope.scope.name=='io.quux.otelc.go'
     for metric in scope.metrics:
      points=getattr(metric,metric.WhichOneof('data')).data_points
      received['metric_points']+=len(points)
      if metric.name in ('otelc.function.calls','otelc.function.duration','otelc.function.errors'):
       for point in points:
        attributes={item.key:item.value.string_value for item in point.attributes}
        assert attributes=={'function':'example.com/oteleqfixture.Add'}
        if metric.name=='otelc.function.calls':calls.append(point.as_int)
        elif metric.name=='otelc.function.duration':durations.append(point.count)
        else:assert point.as_int==0
 received['spans']=len(spans)
 if plain:
  assert not bodies and execution['sdk_pid'] is None and not (runtime/'health.json').exists()
  health=None
 else:
  assert len(spans)==1 and spans[0].name=='example.com/oteleqfixture.Add' and not spans[0].parent_span_id
  assert len(spans[0].trace_id)==16 and len(spans[0].span_id)==8 and any(spans[0].trace_id) and any(spans[0].span_id)
  assert calls and durations and all(value==1 for value in calls+durations)
  digest=hashlib.sha256(json.dumps(policy.data,sort_keys=True).encode()).hexdigest()
  selection=json.loads((ROOT/'bundle/build.json').read_text())['selection']['sha256']
  health=independent_health.qualify(independent_health.read(runtime),pid=pid,policy_sha256=digest,selection_sha256=selection,received=received,function_spans=1,observer_completions=0)
 write(lane/'independent-receipt.json',{'plain':plain,'supervisor_pid':process.pid,'application_pid':pid,'sdk_pid':execution['sdk_pid'],'received':received,'health':health,'expected_return':22,'expected_global_total':21})
 results.append({'plain':plain,'supervisor_pid':process.pid,'application_pid':pid,'sdk_pid':execution['sdk_pid'],'received':received})
assert {p.name:facts(p) for p in APP.iterdir()}==original
changed=[name for name,sha in index['files'].items() if hashlib.sha256((SDK/name).read_bytes()).hexdigest()!=sha]
assert not changed
write(ROOT/'result.json',{'provider':index['head'],'consumer_component':'b9ab648ef9359bcc4efc670f9c8b60bc213cb4a5','actual_applications':2,'actual_sdk_processes':1,'matched_literal_return_and_global':True,'source_file_facts_held':True,'provider_source_files_held':452,'lanes':results,'scope':'Development public-API fixture and independent health/raw OTLP binding only. Generated worker integration, independently verified build/private transformations and full provider qualification remain pending.'})
print(json.dumps({'actual_applications':2,'sdk_processes':1,'expected_return':22,'expected_global_total':21,'raw_trace_spans':results[1]['received']['spans'],'source_held':True,'scope':'development prototype only'}),flush=True)
