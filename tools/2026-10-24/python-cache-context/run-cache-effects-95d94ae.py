"""Actual cached filesystem/HTTP/domain/current-source workflows with independent inputs."""
import hashlib,json,os,py_compile,sys
from pathlib import Path
R=Path('/Users/sclarke/github/oteleq-qualification/2026-10-24/python-cache-context')
REPO=Path('/Users/sclarke/github/oteleq-qualification/work/oteleq-python-cache-context')
sys.path[:0]=[str(REPO/'tests'),str(REPO/'adapters/generation'),str(REPO/'examples')]
import generation,python_inputs
import qualify_python_generated_origins as origins
import python_origin_effect_workflows as effects
from python_cache_qualification import CacheInputs
from qualify_project_tests import command
LABEL=sys.argv[1];F=R/('cache-effects-'+LABEL+'-01');F.mkdir(mode=0o700)
CLI=R/'runtime-95d94ae/quux-oteleq';PROVIDER=R/('provider-ce4cf74-'+LABEL)
os.environ.update(OTELEQ_PYTHON=sys.executable,OTELEQ_CLI=str(CLI),PYTHONDONTWRITEBYTECODE='1')
source=F/'application';source.mkdir();target=source/'app.py';target.write_text(effects.SOURCE)
TIME=1_700_000_000_123456789;os.utime(target,ns=(TIME,TIME));py_compile.compile(str(target),doraise=True)
initial=CacheInputs.capture(source,{'app.py':effects.SOURCE.encode()});generation.write(F/'initial-inputs.json',initial.receipt())
catalogue=python_inputs.artefacts(PROVIDER,{'python':Path(sys.executable).absolute()});generation.write(F/'provider-inputs.json',catalogue)
config=F/'equivalence.toml';config.write_text(effects.POLICY.replace('python-native-origins-v2','python-native-cache-origins-v3'))
workspace=Path(command([CLI,'plan','--source',source,'--otelc-root',PROVIDER,'--workspace-parent',F,'--config',config],F,'plan'))
initial.verify_workspace(workspace);command([CLI,'generate','--workspace',workspace],F,'generate')
command([CLI,'run','--workspace',workspace,'--report-dir',F/'comparison'],F,'run');effects.check_report(F/'comparison/report.json')
exported=F/'exported';command([CLI,'export-tests','--workspace',workspace,'--destination',exported,'--apply'],F,'export')
command([CLI,'run','--workspace',exported,'--report-dir',F/'export-comparison'],F,'export-run');effects.check_report(F/'export-comparison/report.json')
initial.verify_originals()
promoted=source/'equivalence-tests';command([CLI,'promote','--workspace',workspace,'--source',source,'--destination',promoted,'--apply'],F,'promote')
stages=[('direct',F/'comparison/report.json',workspace,initial,0,1),('export',F/'export-comparison/report.json',exported,initial,0,1)]
try:
 for index,stage in enumerate(('promoted-unchanged','promoted-changed-body','promoted-added-function')):
  text=effects.stage_source(stage);target.write_text(text);stamp=TIME+index*2_000_000_000;os.utime(target,ns=(stamp,stamp))
  inputs=CacheInputs.capture(source,{'app.py':text.encode()});generation.write(F/(stage+'-inputs.json'),inputs.receipt())
  output=command([sys.executable,'-I','-B',promoted/'test_equivalence.py'],F,stage,0,{'OTELEQ_SOURCE':str(source),'OTELEQ_WORKSPACE_PARENT':str(F)})
  rows=[json.loads(line) for line in output.splitlines()];functions=2 if index==2 else 1
  assert len(rows)==functions*3+1 and rows[0]['project_source']==str(source)
  current=Path(rows[0]['workspace']);inputs.verify_workspace(current);inputs.verify_originals()
  for row in rows[1:]:
   report=Path(row['report']);effects.check_report(report,int(index>0),functions)
   stages.append((stage,report,current,inputs,int(index>0),functions))
finally:
 target.write_text(effects.SOURCE);os.utime(target,ns=(TIME,TIME))
initial.verify_originals()
interpreter=origins.interpreter_probe();identities={};observations=0;comparisons=0;seen_reports=set()
for stage,report,ws,inputs,shift,functions in stages:
 assert report not in seen_reports;seen_reports.add(report)
 inputs.verify_workspace(ws);data=generation.read(report);assert data['workspace']==str(ws)
 checked,attempts=effects.check_report(report,shift,functions);entries={e['otelc_function']:e for e in data['inventory']}
 for case in data['cases']:
  result=json.loads(command([CLI,'compare-observations',report.parent/case['case']/'typed-bundle.json'],report.parent,'audit-'+case['case']))
  assert result['verdict']=='equivalent';comparisons+=1
  for lane in ('baseline','instrumented_on'):
   for repeat in range(2):
    folder=report.parent/case['case']/(lane+'-'+str(repeat));observations+=1
    value=generation.read(folder/'python-verified-origins.json');expected='source-compiler' if shift else 'cache-read'
    assert len(value['selected'])==1 and all(m['input_binding']==expected for m in value['selected'][0]['matches'])
    actual=origins.recheck_attempt(folder,entries[case['function']],PROVIDER,catalogue,interpreter,selection_builder=inputs.scalar_selection,cache_builder=inputs.frozen_caches)
    identities[actual['runtime']]=actual
assert observations==len(identities)==72 and comparisons==18
assert len({d['application_pid'] for d in identities.values()})==72
assert len({d['sdk_pid'] for d in identities.values() if not d['plain']})==36
# Deliberate fixture mutations must refuse before another application starts.
case=generation.read(F/'comparison/report.json')['cases'][0]['case'];cached=next(iter(initial.caches));cache_path=source/cached
original_cache=cache_path.read_bytes();cache_stat=cache_path.stat();snapshot=workspace/'snapshot/app.py';snapshot_stat=snapshot.stat()
refusals=[]
for fault in ('original-cache-bytes','source-time','cache-mode','stored-cache-bytes','snapshot-time','new-cache'):
 stored=workspace/'python-cache-context/files'/cached;stored_bytes=stored.read_bytes();stored_stat=stored.stat();extra=cache_path.with_name('app.foreign.pyc')
 try:
  if fault=='original-cache-bytes':cache_path.write_bytes(original_cache+b'changed')
  elif fault=='source-time':os.utime(target,ns=(TIME+1,TIME+1))
  elif fault=='cache-mode':cache_path.chmod(0o600 if (cache_stat.st_mode&0o777)!=0o600 else 0o640)
  elif fault=='stored-cache-bytes':stored.write_bytes(stored_bytes+b'changed')
  elif fault=='snapshot-time':os.utime(snapshot,ns=(TIME+1,TIME+1))
  else:extra.write_bytes(b'new associated cache')
  command([CLI,'replay','--workspace',workspace,'--case',case],F,'refuse-'+fault,4)
  stderr=(F/('refuse-'+fault+'.stderr')).read_text();assert 'Python' in stderr and not (F/('refuse-'+fault+'.stdout')).read_bytes()
  refusals.append({'fault':fault,'exit_code':4,'additional_application_launches':0,'stderr':stderr})
 finally:
  if fault=='original-cache-bytes':cache_path.write_bytes(original_cache)
  if fault=='stored-cache-bytes':stored.write_bytes(stored_bytes)
  if extra.exists():extra.unlink()
  os.chmod(cache_path,cache_stat.st_mode&0o7777);os.utime(cache_path,ns=(cache_stat.st_atime_ns,cache_stat.st_mtime_ns))
  os.chmod(stored,stored_stat.st_mode&0o7777);os.utime(stored,ns=(stored_stat.st_atime_ns,stored_stat.st_mtime_ns))
  os.utime(target,ns=(TIME,TIME));os.utime(snapshot,ns=(snapshot_stat.st_atime_ns,snapshot_stat.st_mtime_ns))
 initial.verify_originals();initial.verify_workspace(workspace)
assert python_inputs.artefacts(PROVIDER,{'python':Path(sys.executable).absolute()})==catalogue
generation.write(F/'refusals.json',refusals)
result={'head':'95d94aed4fa7e1319392cd8013003cefbcc76888','qualification_driver':'external95driver with frozen294 shared auditors','actual_application_launches':72,'sdk_processes':36,'complete_raw_effect_and_typed_observations':72,'reports':len(seen_reports),'recomputed_comparisons':18,'prelaunch_input_mutation_refusals':len(refusals),'current_source_unchanged_changed_added_function':True,'original_source_cache_bytes_and_recorded_facts_restored':True,'scope':'Actual cache domains/filesystem/HTTP/direct/export/current-source workflows; input mutations are deliberate negative controls; no shipping/full-project completion claim.'}
generation.write(F/'result.json',result);print(json.dumps(result),flush=True)
