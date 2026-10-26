"""Four actual processes with an independently fixed two-call C++ state oracle."""
import hashlib,json,os,sys
from pathlib import Path
ROOT=Path(__file__).parent
SOURCE=ROOT/'source-bfa7d0b'
sys.path.insert(0,str(SOURCE/'tests'))
from qualify_cpp_receivers import SOURCE as APPLICATION,check_state,node
from qualify_generation import command
PROVIDER_MANIFEST=Path('/Users/sclarke/github/otelc-qualification/2026-10-20/integrated-provider/d6d03b7/manifest.json')
PROVIDER=PROVIDER_MANIFEST.parent/'provider'
CLI=ROOT/'quux-oteleq-bfa7d0b'
FOLDER=ROOT/'smoke-bfa7d0b';FOLDER.mkdir()
def digest(path):return hashlib.sha256(path.read_bytes()).hexdigest()
def verify_provider():
 manifest=json.loads(PROVIDER_MANIFEST.read_text());count=0
 for group in ('source_sha256','products_sha256','dependencies'):
  for name,record in manifest[group].items():
   path=PROVIDER/name
   if isinstance(record,str):assert digest(path)==record,name
   elif 'sha256' in record:assert digest(path)==record['sha256'],name
   else:assert path.is_symlink() and os.readlink(path)==record['symlink'] and str(path.resolve())==record['resolved'],name
   count+=1
 for key in ('clang','clang++','python'):
  tool=manifest['tools'][key];assert digest(Path(tool['resolved']))==tool['sha256'],key
 return {'provider_commit':manifest['source_commit'],'records':count,'selected_tools':3,'manifest_sha256':digest(PROVIDER_MANIFEST)}
before=verify_provider();(FOLDER/'provider-before.json').write_text(json.dumps(before,indent=2)+'\n')
app=FOLDER/'application';app.mkdir();(app/'app.cpp').write_text(APPLICATION)
policy=FOLDER/'equivalence.toml'
policy.write_text('''schema_version=1
languages=["cpp"]
[functions]
include=["sample::Counter::identity(short)"]
[[fixtures]]
function="sample::Counter::identity(short)"
cases=[[7]]
receiver={factory="sample::Counter",arguments=[10]}
sequence=[{action="call",arguments="case"},{action="call",arguments=[2]}]
''')
inputs={str(p):digest(p) for p in (Path(__file__),app/'app.cpp',policy,CLI)}
(FOLDER/'inputs.json').write_text(json.dumps(inputs,indent=2)+'\n')
os.environ.update(OTELEQ_PYTHON=sys.executable,OTELEQ_CLI=str(CLI),PYTHONDONTWRITEBYTECODE='1',OTELC_CLANG='/opt/homebrew/opt/llvm@22/bin/clang',OTELC_CLANGXX='/opt/homebrew/opt/llvm@22/bin/clang++')
os.environ['PATH']='/opt/homebrew/opt/llvm@22/bin:'+os.environ['PATH']
workspace=Path(command([CLI,'plan','--source',app,'--otelc-root',PROVIDER,'--workspace-parent',FOLDER,'--config',policy],FOLDER,'plan'))
command([CLI,'generate','--workspace',workspace],FOLDER,'generate')
report_dir=FOLDER/'comparison'
command([CLI,'run','--workspace',workspace,'--report-dir',report_dir],FOLDER,'run')
report=json.loads((report_dir/'report.json').read_text());assert report['source_preserved'] and not report['blocked'] and len(report['cases'])==1
case=report['cases'][0];assert case['exit_code']==0 and case['arguments']==[7]
bundle=json.loads((report_dir/case['case']/'typed-bundle.json').read_text())['cases'][0]
launches=0
for lane in ('baseline','instrumented_on'):
 assert len(bundle[lane])==2
 for attempt in bundle[lane]:
  launches+=1;observation=attempt['observation'];assert observation['gaps']==[] and len(observation['steps'])==2
  for index,step in enumerate(observation['steps']):
   assert step['id']=='step-'+str(index) and step['action']=='call' and step['gaps']==[]
   argument=(7,2)[index];before_value=(10,17)[index];after_value=(17,19)[index];before_total=(0,7)[index];after_total=(7,9)[index]
   check_state(step['before'],before_value,before_total,argument)
   check_state(step['after'],after_value,after_total,argument)
   assert step['outcome']['kind']=='return'
   graph=step['outcome']['graph'];check_state(graph,after_value,after_total,argument)
   assert node(graph,graph['roots']['result'])['fields']['value']==graph['roots']['receiver']
  assert observation['before']==observation['steps'][0]['before'] and observation['after']==observation['steps'][-1]['after'] and observation['outcome']==observation['steps'][-1]['outcome']
  assert all(attempt['execution']['channels'][key]==[] for key in ('stdout','stderr'))
  if lane=='instrumented_on':assert attempt['execution']['witness']['functions']=={case['function']:2}
after=verify_provider();assert before==after
assert all(digest(Path(path))==expected for path,expected in inputs.items())
result={'claim':'equivalence over these tests and observations','scope':'single method, two ordered calls; diagnostic smoke only','actual_application_launches':launches,'provider':after,'cli_sha256':digest(CLI),'result':'pass'}
(FOLDER/'result.json').write_text(json.dumps(result,indent=2)+'\n');print(json.dumps(result))
