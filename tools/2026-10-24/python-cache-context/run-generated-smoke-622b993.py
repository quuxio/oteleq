"""Initial real generated cache execution, with independent complete literal oracles."""
import hashlib,json,os
from pathlib import Path
import py_compile
import subprocess
import sys

ROOT=Path('/Users/sclarke/github/oteleq-qualification/2026-10-24/python-cache-context')
LABEL=sys.argv[1]
FOLDER=ROOT/('generated-smoke-'+LABEL+'-02');FOLDER.mkdir(mode=0o700)
PROVIDER=ROOT/('provider-ce4cf74-'+LABEL)
CLI=ROOT/'runtime-622b993/quux-oteleq'
SOURCE='counter=0\ndef workload(value:int)->int:\n global counter\n counter+=value\n return value*2+3\n'
source=FOLDER/'application';source.mkdir();target=source/'target.py';target.write_text(SOURCE)
os.utime(target,ns=(1_700_000_000_123456789,1_700_000_000_123456789))
compiled=Path(py_compile.compile(str(target),doraise=True))
original={str(p.relative_to(source)):hashlib.sha256(p.read_bytes()).hexdigest() for p in source.rglob('*') if p.is_file()}
policy=FOLDER/'equivalence.toml';policy.write_text('''schema_version=1
languages=["python"]
[generation]
seed=123
cases_per_function=1
[adapters.python]
backend="prepared"
profile="python-native-cache-origins-v3"
[functions]
include=["*workload*"]
[[fixtures]]
function="*workload*"
domains=[{kind="integer",minimum=7,maximum=7}]
expected_baseline={kind="return_value",value={kind="integer",type="python.int",value="17",signed=true}}
[limits]
case_timeout_ms=30000
''')
environment={**os.environ,'OTELEQ_PYTHON':sys.executable,'PYTHONDONTWRITEBYTECODE':'1'}
def command(name,argv,expected=0):
 result=subprocess.run(list(map(str,argv)),env=environment,capture_output=True,check=False,timeout=240)
 (FOLDER/(name+'.stdout')).write_bytes(result.stdout);(FOLDER/(name+'.stderr')).write_bytes(result.stderr)
 (FOLDER/(name+'.exit')).write_text(str(result.returncode)+'\n')
 assert result.returncode==expected,(name,result.returncode,result.stdout[-1000:],result.stderr[-1000:])
 return result.stdout.decode().strip()
workspace=Path(command('plan',[CLI,'plan','--source',source,'--otelc-root',PROVIDER,'--workspace-parent',FOLDER,'--config',policy]))
plan=json.loads((workspace/'plan.json').read_text());assert len([x for x in plan['inventory'] if x['status']=='ready'])==1 and not any(x['status']=='blocked' for x in plan['inventory'])
command('generate',[CLI,'generate','--workspace',workspace])
command('run',[CLI,'run','--workspace',workspace,'--report-dir',FOLDER/'comparison'])
report=json.loads((FOLDER/'comparison/report.json').read_text());assert report['source_preserved'] and not report['blocked'] and len(report['cases'])==1
case=report['cases'][0];assert case['arguments']==[7] and case['exit_code']==0
folder=FOLDER/'comparison'/case['case']
def graph(counter,result=False):
 roots={'arguments':{'ref':0},'global:counter':{'type':'int','value':str(counter)}}
 if result:roots['result']={'type':'int','value':'17'}
 return {'roots':roots,'nodes':[{'type':'builtins.list','items':[{'type':'int','value':'7'}]}]}
expected={'before':graph(0),'after':graph(7),'outcome':{'kind':'return','value':graph(7,True)}}
identities=[]
for lane in ('baseline','instrumented_on'):
 for repeat in range(2):
  attempt=folder/(lane+'-'+str(repeat));observed=json.loads((attempt/'observation').read_text());assert observed==expected,(str(attempt),observed)
  origins=json.loads((attempt/'python-verified-origins.json').read_text());assert origins['source_origin']=='selected-input-bound'
  assert len(origins['selected'])==1 and all(x['input_binding']=='cache-read' for x in origins['selected'][0]['matches'])
  identities.append({'application_pid':origins['application_pid'],'sdk_pid':origins['sdk_pid']})
assert len({x['application_pid'] for x in identities})==4
assert {str(p.relative_to(source)):hashlib.sha256(p.read_bytes()).hexdigest() for p in source.rglob('*') if p.is_file()}==original
result={'head':'622b9935fea0f11afcaf7b1c678904c7d951ee34','profile':'python-native-cache-origins-v3','actual_application_launches':4,'sdk_processes':2,'literal_full_graph_oracles':True,'both_lane_selected_cache_read_binding':True,'original_source_and_cache_unchanged':True,'cache_sha256':original[str(compiled.relative_to(source))],'identities':identities,'scope':'Initial ordinary timestamp-cache generated case only, not complete generated-cache workflow qualification.'}
(FOLDER/'result.json').write_text(json.dumps(result,indent=2)+'\n');print(json.dumps(result),flush=True)
