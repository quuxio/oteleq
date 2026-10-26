"""Independently recheck the completed single-call corpus without application runs."""
import hashlib,json,os,subprocess,sys
from pathlib import Path
ROOT=Path(__file__).parent;SOURCE=ROOT/'source-70cbdbc';FOLDER=ROOT/'compatibility-70cbdbc';CLI=ROOT/'quux-oteleq-70cbdbc'
sys.path.insert(0,str(SOURCE/'tests'))
import qualify_cpp_receivers as q
summary=json.loads((FOLDER/'qualification.json').read_text())
assert summary['unique_application_launches']==331 and summary['raw_attempt_folders']==335
assert summary['refusal_controls']==13 and summary['refused_application_launches']==7
refusals={'missing-factory':3,'uninitialised':3,'opaque':3,'local-static':3,'macro-storage':3,'thread-local':3,'template-storage':3,'virtual':3,'collision':3,'budget':4,'constructor-failure':4,'custom-error':4,'initial-state':2}
reports=sorted(FOLDER.rglob('report.json'));assert len(reports)==63
comparisons=observations=0;controls=set()
for path in reports:
 report=json.loads(path.read_text());assert report['source_preserved']
 control=next((name for name in refusals if path.is_relative_to(FOLDER/('refusal-'+name))),None)
 if control is not None:
  controls.add(control);expected=refusals[control]
  if expected==3:assert report['blocked'] and not report['cases']
  else:
   assert not report['blocked'] and len(report['cases'])==1 and report['cases'][0]['exit_code']==expected
   attempts=[p for p in path.parent.rglob('command.json') if p.parent.name.startswith(('baseline-','instrumented_on-'))]
   assert len(attempts)==(4 if expected==2 else 1)
   assert all(b'APP_CALLBACK' not in p.read_bytes() for p in path.parent.rglob('stdout'))
   if expected==2:
    case=report['cases'][0];bundle=json.loads((path.parent/case['case']/'typed-bundle.json').read_text())['cases'][0]
    for lane in ('baseline','instrumented_on'):
     assert len(bundle[lane])==2
     for attempt in bundle[lane]:
      active=int(lane=='instrumented_on');observed=attempt['observation'];argument=case['arguments'][0]
      q.check_state(observed['before'],10+active,0,argument)
      q.check_state(observed['after'],10+active+argument,0,argument)
      q.check_state(observed['outcome']['graph'],10+active+argument,0,argument)
      assert observed['outcome']['kind']=='error' and observed['outcome']['category']=='exception'
      assert observed['outcome']['graph']['roots']['error']=={'kind':'bytes','type':'cpp.exception.std::runtime_error','hex':b'expected'.hex()}
      observations+=1
 else:
  assert not report['blocked'] and report['cases']
  functions={case['function'] for case in report['cases']}
  if functions <= {q.function(name) for name in q.METHODS}:observations+=q.check_report(path,len(report['cases']))[0]
  else:
   assert functions <= set(q.BINDING_FUNCTIONS)
   observations+=q.check_bindings(path,len(report['cases']))
 for case in report['cases']:
  if 'comparison' not in case:continue
  result=subprocess.run([str(CLI),'compare-observations',str(path.parent/case['case']/'typed-bundle.json')],capture_output=True,check=False,timeout=30)
  assert result.returncode==case['exit_code'] and json.loads(result.stdout)==case['comparison']
  comparisons+=1
assert controls==set(refusals) and comparisons==83 and observations==332
counts=q.verify_launches(FOLDER,331)
for path in FOLDER.rglob('plan.json'):
 plan=json.loads(path.read_text())
 for name,sha in plan['source_manifest'].items():
  assert hashlib.sha256((Path(plan['source'])/name).read_bytes()).hexdigest()==sha,name
seal=json.loads((ROOT/'source-70cbdbc.json').read_text());assert all(hashlib.sha256((SOURCE/name).read_bytes()).hexdigest()==sha for name,sha in seal['files'].items())
manifest={}
for path in sorted(FOLDER.rglob('*')):
 if path.is_symlink():manifest[str(path.relative_to(FOLDER))]={'symlink':os.readlink(path)}
 elif path.is_file():
  with path.open('rb') as stream:manifest[str(path.relative_to(FOLDER))]=hashlib.file_digest(stream,'sha256').hexdigest()
raw=json.dumps(manifest,sort_keys=True,indent=2)+'\n';(ROOT/'compatibility-70cbdbc-raw-manifest.json').write_text(raw)
record={'claim':'equivalence over these tests and observations','executed_runtime':seal['commit'],'cli_sha256':hashlib.sha256(CLI.read_bytes()).hexdigest(),'reports':len(reports),'comparisons_recomputed':comparisons,'typed_observations_checked':observations,'refusal_controls':len(controls),**counts,'source_files_preserved':len(seal['files']),'retained_records':len(manifest),'raw_manifest_sha256':hashlib.sha256(raw.encode()).hexdigest(),'new_application_launches':0,'scope':'Exact single-call331-application diagnostic compatibility corpus executed70cbdbc; later runtime identities remain separate.'}
(ROOT/'compatibility-70cbdbc-audit.json').write_text(json.dumps(record,indent=2)+'\n');print(json.dumps(record))
