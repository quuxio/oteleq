"""Check complete public Go sequences and a restored intermediate difference."""
from datetime import datetime, timezone
import hashlib
import json
import os
from pathlib import Path
import subprocess
import sys
import time

ROOT = Path(__file__).resolve().parent
INDEX = json.loads((ROOT / 'source-3029064.json').read_text())
CONSUMER = Path(INDEX['source'])
SDK = Path('/Users/sclarke/github/oteleq-qualification/2026-10-24/go-reuse-review-d2ec6bf/source')
SDK_INDEX = json.loads((SDK.parent / 'inputs-before.json').read_text())
CLI = ROOT / 'target/debug/quux-oteleq'
PYTHON = Path('/Users/sclarke/github/oteleq-qualification/2026-10-24/python-live-metrics/env-312/bin/python')
GO = Path('/Users/sclarke/go/pkg/mod/golang.org/toolchain@v0.0.1-go1.27.3.darwin-arm64/bin/go')
DESTINATION = ROOT / 'public-01'
DESTINATION.mkdir()
APPLICATION = DESTINATION / 'application'
(APPLICATION / 'counter').mkdir(parents=True)
(APPLICATION / 'go.mod').write_text('module example.test/ordered\n\ngo 1.26.0\n')
(APPLICATION / 'counter/api.go').write_text('''package counter
import "runtime/debug"
type Counter struct {value int;calls int;self *Counter}
var shared *Counter
var total int
var gateCalls int
func len(text string)int{gateCalls++;count:=0;for range []byte(text){count++};return count}
func New(seed int)*Counter{value:=&Counter{value:seed};value.self=value;shared=value;return value}
func instrumented()bool{info,ok:=debug.ReadBuildInfo();if !ok{return false};for _,dep:=range info.Deps{if dep.Path=="io.quux.otelc/go"{return true}};return false}
func (value *Counter) Step(amount int)int{value.calls++;value.value+=amount;total+=amount;if amount<0{panic("known")};return value.value}
func (value *Counter) Transient(amount int)int{value.calls++;value.value+=amount;total+=amount;if instrumented(){if value.calls==1{value.value++};if value.calls==3{value.value--}};return 7}
func (value *Counter) String()string{panic("APPLICATION_FORMATTER")}
func (value *Counter) MarshalJSON()([]byte,error){panic("APPLICATION_FORMATTER")}
''')
POLICY = DESTINATION / 'policy.toml'
text = '''schema_version=1
languages=["go"]
[adapters.go]
backend="source-v1"
module_roots=["."]
build_timeout_ms=900000
[limits]
baseline_repeats=2
instrumented_repeats=2
case_timeout_ms=30000
[functions]
include=["*.Counter.Step","*.Counter.Transient"]
'''
for method in ('Step','Transient'):
    text += '\n[[fixtures]]\nfunction="*.Counter.' + method + '"\ncases=[[3]]\nreceiver={factory="New",arguments=[10]}\n'
    if method == 'Transient': text += 'domains=[{kind="integer",minimum=0,maximum=3}]\n'
    expected = ',expected_baseline={kind="error",category="panic",type="go.string"}' if method == 'Step' else ''
    text += 'sequence=[{action="call",arguments="case"},{action="call",arguments=[-2]' + expected + '},{action="call",arguments=[4]}]\n'
POLICY.write_text(text)
ENVIRONMENT = dict(os.environ, OTELEQ_PYTHON=str(PYTHON), OTELC_PYTHON=str(PYTHON), OTELC_GO=str(GO),
                   OTELEQ_CLI=str(CLI), PYTHONDONTWRITEBYTECODE='1', PATH=str(GO.parent) + os.pathsep + os.environ['PATH'])


def write(path,value): path.write_text(json.dumps(value,indent=2)+'\n')


def facts(path):
    value=path.stat()
    return {'sha256':hashlib.sha256(path.read_bytes()).hexdigest(),'facts':[value.st_dev,value.st_ino,value.st_mode,value.st_uid,value.st_gid,value.st_size,value.st_mtime_ns,value.st_ctime_ns]}


def inputs():
    tools=json.loads((SDK/'build/go-upstream/toolchain.json').read_text())
    return {'source':{name:facts(CONSUMER/name) for name in INDEX['files']},
            'sdk':{name:facts(SDK/name) for name in SDK_INDEX['files']},
            'application':{name:facts(APPLICATION/name) for name in ('go.mod','counter/api.go')},
            'tools':{str(path):facts(path) for path in [SDK/'build/go-upstream/toolchain.json',*[Path(tools[name]) for name in ('go','weaver','bundle')]]},'cli':facts(CLI)}


before=inputs()
assert all(before['source'][name]['sha256']==value for name,value in INDEX['files'].items())
write(DESTINATION/'inputs-before.json',before)
state={'head':INDEX['head'],'sdk_head':SDK_INDEX['head'],'status':'running','commands':[],
       'started':datetime.now(timezone.utc).isoformat(),'scope':'Two diagnostic Go call-only receiver cases with legal shadowed len; helper isolation and durable frontend retention only, live controls and full project remain separate.'}


def execute(name,arguments,expected=0):
    argv=list(map(str,[CLI,*arguments]))
    write(DESTINATION/(name+'-command.json'),argv)
    state['phase']=name;write(DESTINATION/'status.json',state)
    started=time.monotonic()
    with (DESTINATION/(name+'.stdout')).open('xb') as stdout,(DESTINATION/(name+'.stderr')).open('xb') as stderr:
        result=subprocess.run(argv,cwd=CONSUMER,env=ENVIRONMENT,stdout=stdout,stderr=stderr,timeout=1800)
    state['commands'].append({'phase':name,'exit_code':result.returncode,'seconds':round(time.monotonic()-started,3)})
    write(DESTINATION/'status.json',state)
    assert result.returncode==expected,state['commands'][-1]
    return (DESTINATION/(name+'.stdout')).read_text().strip()


def node(graph,reference):
    assert reference['kind']=='reference'
    return next(value['fields'] for value in graph['nodes'] if value['id']==reference['node_id'])


def number(graph,reference): return int(node(graph,reference)['value']['value'])


def caller_inputs(folder):
    record=json.loads((folder/'go-caller.json').read_text())
    frontend=folder/'go-frontend/discover.go'
    assert str(frontend) in record['reads']
    assert not any('/oteleq-adapter-' in name for name in record['reads'])
    assert hashlib.sha256(frontend.read_bytes()).hexdigest()==INDEX['files']['adapters/generation/discover.go']
    for name,(identity,expected) in record['reads'].items():
        path=Path(name);value=path.stat()
        actual=[value.st_dev,value.st_ino,value.st_mode,value.st_uid,value.st_gid,value.st_size,value.st_mtime_ns,value.st_ctime_ns,value.st_nlink]
        assert actual==expected,name
        assert identity['path']==identity['resolved_path']==str(path.resolve())
        assert identity['sha256']==hashlib.sha256(path.read_bytes()).hexdigest() and identity['size']==value.st_size
    return len(record['reads'])


def audit(report):
    data=json.loads(report.read_text())
    assert data['source_preserved'] and not data['blocked'] and len(data['cases'])==2
    applications=[];sdk=0
    for case in data['cases']:
        method=case['function'].rsplit('.',1)[-1]
        assert method in ('Step','Transient') and case['exit_code']==int(method=='Transient')
        bundle=json.loads((report.parent/case['case']/'typed-bundle.json').read_text())['cases'][0]
        for lane in ('baseline','instrumented_on'):
            assert len(bundle[lane])==2
            for repeat,attempt in enumerate(bundle[lane]):
                folder=report.parent/case['case']/(lane+'-'+str(repeat))
                caller_inputs(folder)
                observed=attempt['observation'];assert not observed['gaps'] and len(observed['steps'])==3
                for index,(step,amount,prior,after,total_before,total_after) in enumerate(zip(observed['steps'],(3,-2,4),(10,13,11),(13,11,15),(0,3,1),(3,1,5))):
                    assert step['id']=='step-'+str(index) and step['action']=='call' and step['gaps']==[]
                    extra=method=='Transient' and lane=='instrumented_on'
                    for boundary,value,total,calls in (('before',prior+int(extra and index>0),total_before,index),('after',after+int(extra and index<2),total_after,index+1)):
                        graph=step[boundary];roots=graph['roots']
                        assert set(roots)=={'receiver','argument:0','global:shared','global:total','global:gateCalls'}
                        assert roots['argument:0']=={'kind':'integer','type':'go.int','bits':64,'signed':True,'value':str(amount)}
                        fields=node(graph,node(graph,roots['receiver'])['value'])
                        assert set(fields)=={'value','calls','self'}
                        assert number(graph,fields['value'])==value and number(graph,fields['calls'])==calls
                        assert node(graph,fields['self'])['value']==roots['receiver']
                        assert node(graph,roots['global:shared'])['value']==roots['receiver']
                        assert number(graph,roots['global:total'])==total
                        assert number(graph,roots['global:gateCalls'])==0
                    outcome=step['outcome']
                    if method=='Step' and index==1:
                        assert outcome['kind']=='error' and outcome['category']=='panic'
                        assert outcome['graph']['roots']['error']=={'kind':'string','type':'go.string','encoding':'raw_bytes','value':'6b6e6f776e'}
                    else:
                        assert outcome['kind']=='return'
                        assert outcome['graph']['roots']['result']=={'kind':'integer','type':'go.int','bits':64,'signed':True,'value':str(7 if method=='Transient' else after)}
                assert observed['before']==observed['steps'][0]['before'] and observed['after']==observed['steps'][-1]['after']
                assert observed['outcome']==observed['steps'][-1]['outcome']
                assert (folder/'stdout').read_bytes()==(folder/'stderr').read_bytes()==b''
                start=json.loads((folder/'go-runtime/oteleq-go-start.json').read_text())
                owner=start['owner']
                assert start['kernel']['application']=={'pid':owner['application_pid'],'parent_pid':owner['pid'],'process_group':owner['pid']}
                app=json.loads((folder/'go-runtime/go-application-start.json').read_text())
                applications.append(app['launch_id'])
                if lane=='baseline':assert attempt['execution']['witness'] is None
                else:
                    sdk+=1
                    receipt=json.loads((folder/'go-verified-telemetry.json').read_text())
                    assert receipt['sdk_pid']==owner['application_pid'] and receipt['spans']==4
                    assert receipt['functions']=={'example.test/ordered/counter.Counter.'+method:3,'example.test/ordered/counter.New':1}
                    assert not any(receipt['losses'].values()) and receipt['pending']==0
                    assert receipt['health']['metric_exported_points'] is None
        if method=='Transient':
            assert bundle['baseline'][0]['observation']['after']==bundle['instrumented_on'][0]['observation']['after']
            assert bundle['baseline'][0]['observation']['outcome']==bundle['instrumented_on'][0]['observation']['outcome']
    assert len(applications)==len(set(applications))==8 and sdk==4
    return {'actual_applications':8,'actual_sdk_processes':4,'complete_intermediate_observations':24,'matching_methods':1,'restored_intermediate_difference':1,'zero_application_builtin_callbacks_at_graph_boundaries':48,'durable_frontends_after_cli_cleanup':8,'all_caller_read_bytes_and_file_facts_rechecked_after_cli_cleanup':True}


try:
    workspace=Path(execute('plan',['plan','--source',APPLICATION,'--otelc-root',SDK,'--config',POLICY,'--workspace-parent',DESTINATION]))
    state['workspace']=str(workspace)
    plan=json.loads((workspace/'plan.json').read_text())
    assert len([entry for entry in plan['inventory'] if entry['status']=='ready'])==2 and not any(entry['status']=='blocked' for entry in plan['inventory'])
    execute('generate',['generate','--workspace',workspace])
    execute('run',['run','--workspace',workspace,'--report-dir',DESTINATION/'comparison'],expected=1)
    state['audit']=audit(DESTINATION/'comparison/report.json')
    state['status']='passed'
except Exception as error:
    state.update(status='failed',error=repr(error))
finally:
    after=inputs();write(DESTINATION/'inputs-after.json',after)
    state['preservation']={name:before[name]==after[name] for name in before}
    if not all(state['preservation'].values()):state['status']='failed'
    state['finished']=datetime.now(timezone.utc).isoformat();write(DESTINATION/'status.json',state)
    print(json.dumps(state,indent=2),flush=True)
    raise SystemExit(0 if state['status']=='passed' else 1)
