from pathlib import Path
import hashlib,json,os,subprocess,sys
repo=Path('/Users/sclarke/github/oteleq-qualification/work/oteleq-python-origin-admission')
sys.path[:0]=[str(repo/'tests'),str(repo/'adapters/generation'),str(repo/'examples')]
from python_sequence_fixture import COMPACT_SOURCE,raw_observation
from qualify_project_tests import command
import generation,python_inputs
p=Path(__file__).parent/'generated-smoke-01'
p.mkdir(mode=0o700)
source=p/'application'; package=source/'src/pkg'; package.mkdir(parents=True)
(package/'__init__.py').write_text('')
(package/'state.py').write_text(COMPACT_SOURCE)
before=generation.manifest(source)
provider=Path(__file__).parent/'provider-794ccaa-312'
tools={'python':Path(sys.executable).absolute()}
inputs=python_inputs.artefacts(provider,tools)
cli=Path(__file__).parent/'generated-development-target/debug/quux-oteleq'
os.environ.update(OTELEQ_PYTHON=sys.executable,OTELEQ_CLI=str(cli),PYTHONDONTWRITEBYTECODE='1')
config=p/'equivalence.toml'
config.write_text('''schema_version=1
languages=["python"]
[adapters.python]
backend="prepared"
profile="python-native-origins-v2"
import_roots=["src"]
[functions]
include=["src.pkg.state.Counter.identity"]
[[fixtures]]
function="src.pkg.state.Counter.identity"
cases=[[7]]
receiver={factory="Counter",arguments=[10]}
sequence=[{action="call",arguments="case"},{action="call",arguments=[2]}]
''')
workspace=Path(command([cli,'plan','--source',source,'--otelc-root',provider,'--workspace-parent',p,'--config',config],p,'plan'))
data=generation.read(workspace/'plan.json')
print([(e['otelc_function'],e['status'],e['reason']) for e in data['inventory'] if e['status']!='excluded'],flush=True)
assert len([e for e in data['inventory'] if e['status']=='ready'])==1
command([cli,'generate','--workspace',workspace],p,'generate')
command([cli,'run','--workspace',workspace,'--report-dir',p/'comparison'],p,'run')
report=generation.read(p/'comparison/report.json')
assert len(report['cases'])==1 and not report['blocked'] and report['source_preserved']
case=report['cases'][0]
for lane in ('baseline','instrumented_on'):
 for repeat in range(2):
  folder=p/'comparison'/case['case']/(lane+'-'+str(repeat))
  assert generation.read(folder/'observation')==raw_observation('identity',7,lane=='instrumented_on',steps=2,compact=True)
  bound=generation.read(folder/'python-verified-origins.json')
  assert len(bound['selected'])==2
  if lane=='instrumented_on':
   receipt=generation.read(folder/'python-verified-telemetry.json')
   assert receipt['functions']=={'src.pkg.state.Counter.identity':2,'src.pkg.state.Counter.__init__':1}
assert generation.manifest(source)==before and python_inputs.artefacts(provider,tools)==inputs
result={'state':'passed','applications':4,'sdk_processes':2,'complete_graphs_checked':4,'source_preserved':True,'inputs_preserved':True,'workspace':str(workspace),'cli_sha256':hashlib.sha256(cli.read_bytes()).hexdigest()}
generation.write(p/'result.json',result)
print(json.dumps(result),flush=True)
