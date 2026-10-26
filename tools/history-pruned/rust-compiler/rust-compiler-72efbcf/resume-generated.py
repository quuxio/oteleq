import hashlib,json,os,sys
from pathlib import Path
repo=Path('/Users/sclarke/github/oteleq-qualification/work/oteleq-rust-compiler')
sys.path.insert(0,str(repo/'tests'));sys.path.insert(0,str(repo/'adapters/generation'))
import qualify_rust_build as qb
from qualify_generation import command
import generation as g
p=Path(__file__).resolve().parent
f=p/'generated';cli=p/'quux-oteleq';workspace=next(f.glob('oteleq-run-*/plan.json')).parent
os.environ.update(OTELEQ_CLI=str(cli),OTELEQ_PYTHON=sys.executable,OTELEQ_EXECUTABLE=str(cli))
data=json.loads((workspace/'plan.json').read_text());cases=json.loads((workspace/'tests/corpus.json').read_text())
assert len(cases)==4
assert g.manifest(Path(data['source']))==data['source_manifest']
assert g.manifest(workspace/'snapshot')==data['source_manifest']
assert g.generator_identity()==data['generator_sha256']
accepted=[]
for case in cases:
 entry=next(x for x in data['inventory'] if x['id']==case['function_id'])
 old=f/'comparison'/case['id']
 if (old/'typed-bundle.json').exists() and (old/'comparison.json').exists():
  assert json.loads((old/'corpus.json').read_text())==case
  original=json.loads((old/'comparison.json').read_text())
  result=json.loads(command([cli,'compare-observations',old/'typed-bundle.json'],f,'revalidate-'+case['id']))
  assert result==original
  command([cli,'compare-workload',old/'bundle.json'],f,'raw-revalidate-'+case['id'])
  summary={'case':case['id'],'function':entry['otelc_function'],'arguments':case['arguments'],'exit_code':0,'comparison':result}
  qb.check_case(summary,old.parent,'compiler',None)
  accepted.append({'case':case['id'],'root':str(old.parent),'origin':'completed before interruption','actual_launches':6})
 else:
  replay=json.loads(command([cli,'replay','--workspace',workspace,'--case',case['id']],f,'recovered-'+case['id']))
  report=Path(replay['report']);r=json.loads(report.read_text());assert r['source_preserved'] and len(r['cases'])==1
  qb.check_case(r['cases'][0],report.parent,'compiler',None)
  accepted.append({'case':case['id'],'root':str(report.parent),'origin':'recovered with per-case replay','actual_launches':6})
 (f/'recovered-initial-index.json').write_text(json.dumps(accepted,indent=2)+'\n')
 print(json.dumps({'completed_initial_case':case['id'],'origin':accepted[-1]['origin']}),flush=True)
additional=qb.compiler_retained_routes(cli,workspace,f)
assert additional==72 and sum(row['actual_launches'] for row in accepted)==24
assert g.manifest(Path(data['source']))==data['source_manifest']
assert g.manifest(workspace/'snapshot')==data['source_manifest']
record={'runtime_commit':'72efbcfbf832d7cc98c1dd4d1188519e504f994c','qualification_commit':'bb0de7bea0c549f58a32513b0e47212e97aa09fd','provider_commit':'aca9d5adc103e40dbda5db2725ff23fa9f998053','cases':4,'matching_cases':4,'accepted_actual_application_launches':96,'source_preserved':True,'routes':['interrupted run completed by per-case replay','generated unittest/replay','exported run','exported unittest/replay'],'initial_case_index':accepted,'partial_before_interruption':'one additional baseline capture has no complete case bundle; retained separately and excluded from accepted launch count','resume_script_sha256':hashlib.sha256(Path(__file__).read_bytes()).hexdigest()}
(f/'qualification.json').write_text(json.dumps(record,indent=2)+'\n');print(json.dumps(record),flush=True)
