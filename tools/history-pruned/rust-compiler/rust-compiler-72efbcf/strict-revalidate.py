import hashlib,json,sys
from pathlib import Path
repo=Path('/Users/sclarke/github/oteleq-qualification/work/oteleq-rust-compiler');sys.path.insert(0,str(repo/'tests'))
import qualify_rust_build as q
p=Path(__file__).resolve().parent;f=p/'generated';workspace=next(f.glob('oteleq-run-*/plan.json')).parent
plan=json.loads((workspace/'plan.json').read_text());corpus=json.loads((workspace/'tests/corpus.json').read_text());accepted=[]
for row in json.loads((f/'recovered-initial-index.json').read_text()):
 case=next(x for x in corpus if x['id']==row['case']);entry=next(x for x in plan['inventory'] if x['id']==case['function_id']);root=Path(row['root'])
 summary={'case':case['id'],'function':entry['otelc_function'],'arguments':case['arguments'],'exit_code':0,'comparison':json.loads((root/case['id']/'comparison.json').read_text())}
 q.check_case(summary,root,'compiler',None);accepted.append(root/case['id'])
for name in ('framework.stdout','export-framework.stdout'):
 for line in (f/name).read_text().splitlines():
  report=Path(json.loads(line)['report']);d=json.loads(report.read_text());assert d['source_preserved'] and len(d['cases'])==1
  q.check_case(d['cases'][0],report.parent,'compiler',None);accepted.append(report.parent/d['cases'][0]['case'])
d=json.loads((f/'export-comparison/report.json').read_text());assert d['source_preserved'] and len(d['cases'])==4
for case in d['cases']:q.check_case(case,f/'export-comparison','compiler',None);accepted.append(f/'export-comparison'/case['case'])
assert len(accepted)==16
commands={q.capture.file_digest(path) for root in accepted for path in root.glob('*/command.json')};assert len(commands)==96
r={'accepted_case_executions':16,'accepted_application_launches':96,'unique_command_identities':len(commands),'literal_oracle':'exact complete state/outcome records, rejecting prefixes/suffixes','all_oracles_pass':True,'qualifier_sha256':hashlib.sha256(Path(q.__file__).read_bytes()).hexdigest(),'revalidation_script_sha256':hashlib.sha256(Path(__file__).read_bytes()).hexdigest(),'source_runtime_commit':'72efbcfbf832d7cc98c1dd4d1188519e504f994c','application_reruns':0}
(p/'strict-revalidation.json').write_text(json.dumps(r,indent=2)+'\n');print(json.dumps(r))
