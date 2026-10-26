from pathlib import Path
import json,os,subprocess,sys
from urllib.parse import urlsplit
repo=Path('/Users/sclarke/github/oteleq-qualification/work/oteleq-python-origin-admission')
sys.path[:0]=[str(repo/'tests'),str(repo/'adapters/generation'),str(repo/'examples')]
import generation,python_inputs
from qualify_project_tests import command
p=Path(__file__).parent/'origin-effects-promotion-development-01';p.mkdir(mode=0o700)
provider=Path(__file__).parent/'provider-794ccaa-312'
cli=Path(__file__).parent/'runtime-a63b131/target/debug/quux-oteleq'
os.environ.update(OTELEQ_PYTHON=sys.executable,OTELEQ_CLI=str(cli),PYTHONDONTWRITEBYTECODE='1')
source=p/'application';source.mkdir()
CODE='''import os
from pathlib import Path
from urllib.request import Request, urlopen
counter=0
def exercise(value:int)->int:
 global counter
 counter+=value
 root=Path(os.environ["APP_DATA_DIR"])
 data=bytes((value,255))
 (root/"out.bin").write_bytes((root/"seed.bin").read_bytes()+data)
 os.chmod(root/"out.bin",0o600)
 request=Request(os.environ["APP_SERVICE_URL"]+"/observe",data=data,headers={"X-Check":"fixture"},method="POST")
 with urlopen(request) as response:
  if response.status!=201 or response.read()!=b"\\x00\\xff":return -1
 return 7
'''
(source/'app.py').write_text(CODE)
config=p/'equivalence.toml'
config.write_text('''schema_version=1
languages=["python"]
[generation]
seed=123
cases_per_function=3
[adapters.python]
backend="prepared"
profile="python-native-origins-v2"
[functions]
include=["*exercise*"]
[[fixtures]]
function="*exercise*"
domains=[{kind="integer",minimum=0,maximum=7}]
expected_baseline={kind="return_value",value={kind="integer",type="python.int",value="7",signed=true}}
[[effects.filesystem]]
name="data"
environment="APP_DATA_DIR"
path_mode="relative"
files=[{path="seed.bin",hex="00ff",mode=0o600}]
directories=["empty"]
max_bytes=1024
max_entries=32
max_depth=4
[[effects.http]]
name="service"
environment="APP_SERVICE_URL"
headers=["host","x-check"]
responses=[{status=201,hex="00ff"}]
min_requests=1
max_requests=1
max_bytes=2
''')
tools={'python':Path(sys.executable).absolute()};inputs=python_inputs.artefacts(provider,tools)
attempts=set()
def graph(value,counter,*,result=False):
 roots={'arguments':{'ref':0},'global:counter':{'type':'int','value':str(counter)}}
 if result:roots['result']={'type':'int','value':'7'}
 return {'roots':roots,'nodes':[{'type':'builtins.list','items':[{'type':'int','value':str(value)}]}]}
def verify_report(path,shift=0,functions=1):
 report=generation.read(path);assert report['source_preserved'] and not report['blocked']
 assert len(report['cases']) in (1,functions*3)
 for case in report['cases']:
  assert case['exit_code']==0 and case['function'] in ('app.exercise','app.exercise_added')
  value,=case['arguments'];assert type(value) is int and 0<=value<=7
  bundle=generation.read(path.parent/case['case']/'typed-bundle.json')['cases'][0]
  for lane in ('baseline','instrumented_on'):
   assert len(bundle[lane])==2
   for index,observed in enumerate(bundle[lane]):
    folder=path.parent/case['case']/(lane+'-'+str(index));attempts.add(str(folder))
    assert generation.read(folder/'observation')=={'before':graph(value,0),'after':graph(value,value+shift),'outcome':{'kind':'return','value':graph(value,value+shift,result=True)}}
    execution=observed['execution'];assert execution['capture_complete'] and execution['termination']=={'kind':'exit','code':0}
    assert execution['channels']['stdout']==execution['channels']['stderr']==[]
    fs=json.loads(bytes(execution['channels']['filesystem:data']))
    before={bytes.fromhex(e['path_hex']):e for e in fs['before']['entries']};after={bytes.fromhex(e['path_hex']):e for e in fs['after']['entries']}
    assert set(before)=={b'',b'empty',b'seed.bin'} and set(after)=={b'',b'empty',b'seed.bin',b'out.bin'}
    assert before[b'seed.bin']==after[b'seed.bin']=={'path_hex':b'seed.bin'.hex(),'kind':'file','mode':0o600,'hex':'00ff'}
    assert after[b'out.bin']=={'path_hex':b'out.bin'.hex(),'kind':'file','mode':0o600,'hex':bytes((0,255,value,255)).hex()}
    assert fs['before']['complete'] and fs['after']['complete'] and not fs['before']['gaps'] and not fs['after']['gaps']
    http=json.loads(bytes(execution['channels']['http:service']));assert http['complete'] and not http['gaps'] and len(http['requests'])==1
    request=http['requests'][0];assert request['method']=='POST' and request['target_hex']==b'/observe'.hex() and request['version']=='HTTP/1.1'
    assert request['body_hex']==bytes((value,255)).hex() and request['response_index']==0
    assert bytes.fromhex(request['response_hex'])==b'HTTP/1.1 201 Fixture\r\nConnection: close\r\nContent-Length: 2\r\n\r\n\x00\xff'
    binding=generation.read(folder/'http-controls.json')['environment']['APP_SERVICE_URL']
    headers=[bytes.fromhex(line) for line in request['header_lines_hex']];assert len(headers)==2
    assert [h.partition(b':')[2].strip() for h in headers if h.partition(b':')[0].lower()==b'host']==[urlsplit(binding).netloc.encode()]
    assert [h.partition(b':')[2].strip() for h in headers if h.partition(b':')[0].lower()==b'x-check']==[b'fixture']
    origin=generation.read(folder/'python-verified-origins.json');assert len(origin['selected'])==1 and origin['selected'][0]['qualname']==case['function'].split('.',1)[1]
    if lane=='instrumented_on':
     witness=execution['witness'];assert witness['functions']=={case['function']:1} and witness['spans']==1 and witness['pending']==0 and not any(witness['losses'].values())
    else:assert execution['witness'] is None
 return report
workspace=Path(command([cli,'plan','--source',source,'--otelc-root',provider,'--workspace-parent',p,'--config',config],p,'plan'))
plan=generation.read(workspace/'plan.json');assert len([r for r in plan['inventory'] if r['status']=='ready'])==1
command([cli,'generate','--workspace',workspace],p,'generate')
command([cli,'run','--workspace',workspace,'--report-dir',p/'comparison'],p,'run')
verify_report(p/'comparison/report.json')
exported=p/'exported';command([cli,'export-tests','--workspace',workspace,'--destination',exported,'--apply'],p,'export')
command([cli,'run','--workspace',exported,'--report-dir',p/'export-comparison'],p,'export-run');verify_report(p/'export-comparison/report.json')
promoted=source/'equivalence-tests';command([cli,'promote','--workspace',workspace,'--source',source,'--destination',promoted,'--apply'],p,'promote')
def current(name,shift,functions):
 output=command([sys.executable,'-I','-B',promoted/'test_equivalence.py'],p,name,0,{'OTELEQ_SOURCE':str(source),'OTELEQ_WORKSPACE_PARENT':str(p)})
 records=[json.loads(line) for line in output.splitlines()];fresh=Path(records[0]['workspace'])
 assert len(records)==functions*3+1 and len([e for e in generation.read(fresh/'plan.json')['inventory'] if e['status']=='ready'])==functions
 for row in records[1:]:verify_report(Path(row['report']),shift,functions)
current('promoted-unchanged',0,1)
changed=CODE.replace('counter+=value\n','counter+=value+1\n');(source/'app.py').write_text(changed)
current('promoted-changed-body',1,1)
added=changed+'\n'+changed[changed.index('def exercise('):].replace('def exercise(','def exercise_added(',1)
(source/'app.py').write_text(added);current('promoted-added-function',1,2)
assert (source/'app.py').read_text()==added and python_inputs.artefacts(provider,tools)==inputs
result={'state':'passed','distinct_application_attempts':len(attempts),'generated_domain_cases':3,'filesystem_and_http_bindings':'reached both prepared lanes','complete_raw_graph_and_effect_oracles':True,'current_source_stages':['unchanged','changed-body','added-function'],'inputs_preserved':True,'cli_sha256':generation.capture.file_digest(cli)}
generation.write(p/'result.json',result);print(json.dumps(result),flush=True)
