import datetime,json,os,sys
from pathlib import Path
repo=Path('/Users/sclarke/github/oteleq-qualification/work/oteleq-rust-compiler');sys.path.insert(0,str(repo/'tests'))
import qualify_rust_build as q
from qualify_generation import command
p=Path(__file__).resolve().parent;f=p/'legacy';f.mkdir();cli=p/'quux-oteleq'
root=Path('/Users/sclarke/github/oteleq-qualification/2026-10-20/pause-for-reboot/otelc-integrated-provider-0419a51-frozen')
assert not (root/'target/debug/otelc-rust-compiler.json').exists()
state={'name':'legacy','pid':os.getpid(),'state':'running','started_at':datetime.datetime.now(datetime.timezone.utc).isoformat()}
(p/'legacy-state.json').write_text(json.dumps(state,indent=2)+'\n')
os.environ.update(OTELEQ_PYTHON=sys.executable,OTELEQ_CLI=str(cli))
source,policy,_=q.fixture(f,'compiler')
w=Path(command([cli,'plan','--source',source,'--otelc-root',root,'--workspace-parent',f,'--config',policy],f,'plan'))
command([cli,'generate','--workspace',w],f,'generate')
command([cli,'run','--workspace',w,'--report-dir',f/'comparison'],f,'run')
r=json.loads((f/'comparison/report.json').read_text());assert r['source_preserved'] and len(r['cases'])==4
for case in r['cases']:
 q.check_case(case,f/'comparison','compiler',None)
 for m in (f/'comparison'/case['case']).glob('instrumented_on-*/scratch/rust-bundle/build.json'):assert json.loads(m.read_text())['schema_version']==1
record={'runtime_commit':'ed09f136b090c50e062ff2ff678194c959be6c1a','provider_commit':'0419a51af9aa5b86cabcc21690eda48b987b80d1','build_schema':1,'cases':4,'actual_application_launches':24,'source_preserved':True}
(f/'qualification.json').write_text(json.dumps(record,indent=2)+'\n')
state.update(state='completed',exit_code=0,completed_at=datetime.datetime.now(datetime.timezone.utc).isoformat());(p/'legacy-state.json').write_text(json.dumps(state,indent=2)+'\n');print(json.dumps(record),flush=True)
