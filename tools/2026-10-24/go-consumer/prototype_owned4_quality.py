"""Run the real generated Go gate, independent ownership readers and raw OTLP."""
import copy,hashlib,json,os,subprocess,sys,time
from pathlib import Path
BASE=Path(__file__).resolve().parent
SOURCE=Path('/Users/sclarke/github/oteleq-qualification/work/oteleq-go-source-provider')
SDK=BASE.parent/'go-parent-review-7223328/source'
ROOT=BASE/'owned4-quality-01';ROOT.mkdir(mode=0o700)
sys.path[:0]=[str(SOURCE/'adapters/generation'),str(SOURCE/'examples')]
import generation as gen
import go_build,go_context,go_files,go_health,go_launch,go_prepared,go_provider,harness,python_prepared
import otelc_capture as capture
from opentelemetry.proto.collector.trace.v1.trace_service_pb2 import ExportTraceServiceRequest
from opentelemetry.proto.collector.metrics.v1.metrics_service_pb2 import ExportMetricsServiceRequest

def write(path,value):
 with path.open('x') as out:out.write(json.dumps(value,indent=2)+'\n')
def fact(path):return go_files.file(path)[:2]
index=json.loads((BASE.parent/'go-parent-review-7223328/source-index.json').read_text())
sdkfacts={name:fact(SDK/name) for name in index['files']}
assert all(value[0]['sha256']==index['files'][name] for name,value in sdkfacts.items())
names=subprocess.check_output(['git','ls-files','--cached','--others','--exclude-standard'],cwd=SOURCE,text=True).splitlines()
consumer={name:hashlib.sha256((SOURCE/name).read_bytes()).hexdigest() for name in names}
write(ROOT/'consumer-development-source.json',{'base':'e763ab5dc9708da209d8435f167cc3d349745ad5','dirty_development_source':True,'files':consumer})
go='/Users/sclarke/go/pkg/mod/golang.org/toolchain@v0.0.1-go1.27.3.darwin-arm64/bin/go'
env={k:v for k,v in os.environ.items() if not k.startswith(('OTEL','GH_','GITHUB_','SONAR_','AWS_'))}
env.update(PATH=str(Path(go).parent)+os.pathsep+env.get('PATH',''),GOTOOLCHAIN='local',GOWORK='off',GOFLAGS='',GOENV='off',PYTHONDONTWRITEBYTECODE='1',OTELC_PYTHON=sys.executable,
 GOPATH=str(BASE.parent/'go-http2-review-33d74f2/go-path'),GOMODCACHE=str(BASE.parent/'go-source-review-67b1b0d/source/build/go-module-cache'),GOCACHE=str(BASE.parent/'go-http-review-b58d798/go-cache'))

def command(label,argv,cwd):
 write(ROOT/(label+'-command.json'),{'argv':argv,'cwd':str(cwd)})
 result=subprocess.run(argv,cwd=cwd,env=env,capture_output=True,timeout=180)
 (ROOT/(label+'.stdout')).write_bytes(result.stdout);(ROOT/(label+'.stderr')).write_bytes(result.stderr)
 assert result.returncode==0,(label,result.stderr.decode(errors='replace')[-3000:])
 return result.stdout

project=ROOT/'project';project.mkdir()
(project/'go.mod').write_text('module example.com/oteleqowned\n\ngo 1.26.0\n')
(project/'main.go').write_text('package main\nvar Total int\nfunc Add(value int)int{Total+=value;return Total+1}\nfunc main(){}\n')
meta=json.loads(command('discover-original',[go,'run',str(SOURCE/'adapters/generation/discover.go'),'--',str(project/'main.go')],SOURCE/'adapters/generation'))
row=next(row for row in meta['functions'] if row['name']=='Add')
entry={**row,'language':'go','path':'main.go','package_end':meta['package_end'],'globals':meta['globals'],
 'file_functions':meta['functions'],'go_main_renames':meta['main_renames'],'go_package':meta['package'],'go_backend':'source-v1'}
harness.materialise(project,entry,[21])
meta=json.loads(command('discover-worker',[go,'run',str(SOURCE/'adapters/generation/discover.go'),'--',str(project/'main.go')],SOURCE/'adapters/generation'))
line=next(row['line'] for row in meta['functions'] if row['name']=='Add')
original=go_files.freeze(project)
settings=json.loads(command('settings',[go,'mod','edit','-json'],project))
raw=command('modules',[go,'list','-m','-mod=readonly','-json','all'],project).decode().strip();modules=[]
while raw:
 value,end=json.JSONDecoder().raw_decode(raw);modules.append(value);raw=raw[end:].lstrip()
policy={'schema_version':3,'languages':['go'],'resource':{'service_name':'oteleq-go-owned4'},
 'export':{'endpoint':'http://127.0.0.1:1','interval_ms':1000,'timeout_ms':1000,'shutdown_timeout_ms':10000},
 'sources':{'include':['**/*.go'],'exclude':[]},'functions':{'include':['example.com/oteleqowned.Add'],'exclude':[]},
 'metrics':{'collection':True,'emission':True,'histogram_boundaries_seconds':[1e-6,1e-5,1e-4,.001,.01,.1,1.]},
 'traces':{'enabled':True,'sample_ratio':1.0},'context':{'tasks':False,'http':False},
 'lifetimes':{'enabled':False,'include':[],'exclude':[],'max_live':4096,'release_methods':['close']},
 'benchmark':{'iterations':10000,'samples':15,'warmup':5}}

def policy_file(path,data):
 lines=['schema_version=3','languages=["go"]']
 for key,value in data.items():
  if type(value) is not dict:continue
  lines.append('['+key+']')
  lines.extend(name+'='+json.dumps(item) for name,item in value.items())
 path.write_text('\n'.join(lines)+'\n')

policy_file(ROOT/'build-policy.toml',policy)
descriptor=json.loads(command('protocols',[str(SDK/'bin/quux-otelc'),'go-protocols'],SDK))
go_provider.verify_protocols(descriptor)
tools,_=go_files.read(SDK/'build/go-upstream/toolchain.json')
sdkinput=go_files.freeze(SDK/'adapters/go');context=go_context.prepare(Path(tools['bundle']),ROOT/'expected-context')
write(ROOT/'context-before-build.json',{'bundle':go_files.identity(Path(tools['bundle'])),'expected_files':context.identities,'file_facts':context.facts,'no_task_profile':True,'source':'independent consumer recipe; no SDK renderer'})
command('build',[str(SDK/'bin/quux-otelc'),'--config',str(ROOT/'build-policy.toml'),'go-build','--root',str(project),'--output',str(ROOT/'bundle'),'--go',go],SDK)
built=go_build.read(go_build.Intent(ROOT/'bundle',original,sdkinput,'.',(go_build.Target('example.com/oteleqowned.Add','main.go',line,1),),tools,settings,modules,context))
producer=go_files.freeze(SDK/'otelc');python=Path(sys.executable).absolute()
expected=b'abi:{"pointer_bits":64}\nbefore\nTotal:int:0\nreturn:int:22\nafter\nTotal:int:21\n'
results=[]
for plain in (True,False):
 lane=ROOT/('baseline' if plain else 'instrumented');lane.mkdir(mode=0o700)
 with capture.receiver(max_requests=128,allow_chunked=True) as (endpoint,bodies,errors):
  data=copy.deepcopy(policy);data['export']['endpoint']=endpoint
  configuration=lane/'policy.toml';policy_file(configuration,data)
  runtime=lane/'runtime'
  response=json.loads(command(lane.name+'-prepare',[str(SDK/'bin/quux-otelc'),'--config',str(configuration),'go','--build',str(ROOT/'bundle'),'--runtime',str(runtime),*(['--plain'] if plain else []),'--prepare-only'],SDK))
  intent=go_prepared.Intent(built,runtime,producer,python,python_prepared.file_identity(python),data,plain)
  checked=go_prepared.verify(response,intent)
  session=go_launch.Session(checked,wait_ms=30000)
  observation=lane/'observation.txt'
  application_env={**env,**session.environment(),'OTELEQ_OBSERVATION':str(observation)}
  result=gen.execute(go_prepared.command(intent),SDK,application_env,lane,timeout=30,max_output_bytes=262144,record_process=True,interaction=session)
  assert result.returncode==0 and result.stdout==result.stderr==b''
  assert observation.read_bytes()==expected,observation.read_bytes()
  session.execution.verify()
 assert not errors,errors
 capture.retain_http(lane,bodies,errors)
 received={'trace_batches':0,'spans':0,'metric_batches':0,'metric_points':0};spans=[];calls=[];duration=[]
 for path,body in bodies:
  if path=='/v1/traces':
   received['trace_batches']+=1
   packet=ExportTraceServiceRequest.FromString(body)
   for resource in packet.resource_spans:
    for scope in resource.scope_spans:
     assert scope.scope.name=='io.quux.otelc.go';spans.extend(scope.spans)
  else:
   assert path=='/v1/metrics';received['metric_batches']+=1
   packet=ExportMetricsServiceRequest.FromString(body)
   for resource in packet.resource_metrics:
    for scope in resource.scope_metrics:
     assert scope.scope.name=='io.quux.otelc.go'
     for metric in scope.metrics:
      points=getattr(metric,metric.WhichOneof('data')).data_points;received['metric_points']+=len(points)
      if metric.name in ('otelc.function.calls','otelc.function.duration','otelc.function.errors'):
       for point in points:
        attrs={item.key:item.value.string_value for item in point.attributes}
        assert attrs=={'function':'example.com/oteleqowned.Add'}
        if metric.name=='otelc.function.calls':calls.append(point.as_int)
        elif metric.name=='otelc.function.duration':duration.append(point.count)
        else:assert point.as_int==0
 received['spans']=len(spans)
 if plain:
  assert not bodies and session.execution.value['sdk_pid'] is None
  health=None
 else:
  assert len(spans)==1 and spans[0].name=='example.com/oteleqowned.Add' and not spans[0].parent_span_id
  assert len(spans[0].trace_id)==16 and any(spans[0].trace_id) and len(spans[0].span_id)==8 and any(spans[0].span_id)
  assert calls and duration and all(value==1 for value in calls+duration)
  health=go_health.qualify(session.execution.health,pid=session.started.owner.application_pid,
   policy_sha256=go_provider.policy_digest(data),selection_sha256=built.receipt['selection']['sha256'],
   received=received,function_spans=1,observer_completions=0,received_http_spans=0)
 receipt={'plain':plain,'supervisor_pid':session.started.owner.pid,'application_pid':session.started.owner.application_pid,
  'sdk_pid':session.execution.value['sdk_pid'],'kernel':session.kernel_observations,'received':received,'health':health,
  'complete_literal_observation':True,'independent_execution_reader':True,'pre_call_release_owned':True}
 write(lane/'independent-receipt.json',receipt);results.append(receipt)
built.verify();producer.verify()
assert all(fact(SDK/name)==value for name,value in sdkfacts.items())
assert all(hashlib.sha256((SOURCE/name).read_bytes()).hexdigest()==digest for name,digest in consumer.items())
write(ROOT/'result.json',{'result':'passed','provider':index['head'],'provider_files_bytes_and_facts_held':len(sdkfacts),
 'consumer_development_source_files_held':len(consumer),'build_schema':4,'context_independently_reconstructed_before_build':True,'expected_context_files':len(context.identities),'actual_target_applications':2,'actual_sdk_processes':1,
 'literal_return':22,'literal_global_before':0,'literal_global_after':21,'lanes':results,
 'scope':'Actual generated scalar worker ready/release and consumer-owned execution against frozen build4 provider. Expected21file context is independently reconstructed before build from pinned upstream bundle and consumer literal extensions. Public generator admission, retained routes, receivers/live controls and broader qualification remain open.'})
print(json.dumps({'result':'passed','actual_target_applications':2,'sdk_processes':1,'provider_files_held':len(sdkfacts),'consumer_files_held':len(consumer),'literal_return':22,'global_before':0,'global_after':21,'raw_spans':results[1]['received']['spans']}))
