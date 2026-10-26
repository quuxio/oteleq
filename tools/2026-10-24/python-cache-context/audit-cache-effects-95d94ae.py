"""Audit retained effects/promotion runs and finish prelaunch refusal controls, no new apps."""
import hashlib,json,os,subprocess,sys
from pathlib import Path
R=Path('/Users/sclarke/github/oteleq-qualification/2026-10-24/python-cache-context');REPO=Path('/Users/sclarke/github/oteleq-qualification/work/oteleq-python-cache-context')
sys.path[:0]=[str(REPO/'tests'),str(REPO/'adapters/generation'),str(REPO/'examples')]
import generation,python_inputs,python_provider
import qualify_python_generated_origins as origins
import python_origin_effect_workflows as effects
from python_cache_qualification import CacheInputs
from qualify_python_caches import scalar
from qualify_project_tests import command
LABEL=sys.argv[1];F=R/('cache-effects-'+LABEL+'-01');CLI=R/'runtime-95d94ae/quux-oteleq';PROVIDER=R/('provider-ce4cf74-'+LABEL)
os.environ.update(OTELEQ_PYTHON=sys.executable,OTELEQ_CLI=str(CLI),PYTHONDONTWRITEBYTECODE='1')
assert F.is_dir();source=F/'application';target=source/'app.py';TIME=1_700_000_000_123456789
catalogue=generation.read(F/'provider-inputs.json');assert python_inputs.artefacts(PROVIDER,{'python':Path(sys.executable).absolute()})==catalogue
initial=CacheInputs.capture(source,{'app.py':effects.SOURCE.encode()});assert initial.receipt()==generation.read(F/'initial-inputs.json')
workspace=Path((F/'plan.stdout').read_text().strip());exported=F/'exported'
for name in ('plan','generate','run','export','export-run','promote','promoted-unchanged','promoted-changed-body','promoted-added-function'):
 assert (F/(name+'.exit')).read_text()=='0\n',name
stages=[('direct',F/'comparison/report.json',workspace,initial,0,1),('export',F/'export-comparison/report.json',exported,initial,0,1)]
for index,stage in enumerate(('promoted-unchanged','promoted-changed-body','promoted-added-function')):
 text=effects.stage_source(stage);receipt=generation.read(F/(stage+'-inputs.json'))
 expected={**initial.source_facts['app.py'],'sha256':hashlib.sha256(text.encode()).hexdigest(),'size':len(text.encode()),'mtime_ns':TIME+index*2_000_000_000}
 assert receipt=={'sources':{'app.py':expected},'caches':initial.cache_facts}
 inputs=CacheInputs(source,{'app.py':text.encode()},initial.caches,receipt['sources'],receipt['caches'])
 rows=[json.loads(line) for line in (F/(stage+'.stdout')).read_text().splitlines()];functions=2 if index==2 else 1
 assert len(rows)==functions*3+1 and rows[0]['project_source']==str(source)
 current=Path(rows[0]['workspace']);assert current.is_relative_to(F)
 for row in rows[1:]:stages.append((stage,Path(row['report']),current,inputs,int(index>0),functions))
def typed_graph(value,counter,result=False):
 roots={'arguments':{'kind':'reference','node_id':'n0'},'global:counter':scalar(counter)}
 if result:roots['result']=scalar(7)
 return {'roots':roots,'nodes':[{'id':'n0','type':'python.builtins.list','fields':{'item:0':scalar(value)}}]}
interpreter=origins.interpreter_probe();identities={};observations=0;comparisons=0;seen_reports=set()
for stage,report,ws,inputs,shift,functions in stages:
 assert report not in seen_reports;seen_reports.add(report);assert report.is_relative_to(F)
 inputs.verify_workspace(ws);data=generation.read(report);assert data['workspace']==str(ws)
 effects.check_report(report,shift,functions);entries={e['otelc_function']:e for e in data['inventory']}
 for case in data['cases']:
  bundlepath=report.parent/case['case']/'typed-bundle.json';bundle=generation.read(bundlepath)['cases'][0]
  compared=subprocess.run([str(CLI),'compare-observations',str(bundlepath)],capture_output=True,check=False,timeout=30)
  assert compared.returncode==0 and python_provider.same(generation.capture.strict_json(compared.stdout),case['comparison'])
  assert case['comparison']['verdict']=='equivalent_observed';comparisons+=1
  value,=case['arguments'];contract=bundle['contract']
  expected={'case_id':case['case'],'function_id':case['function'],'observation_schema_version':1,'fixture_sha256':contract['fixture_sha256'],'fixture':{'status':'ready'},'gaps':[],'before':typed_graph(value,0),'after':typed_graph(value,value+shift),'outcome':{'kind':'return','graph':typed_graph(value,value+shift,True)}}
  for lane in ('baseline','instrumented_on'):
   for repeat in range(2):
    attempt=report.parent/case['case']/(lane+'-'+str(repeat));observations+=1
    assert python_provider.same(bundle[lane][repeat]['observation'],expected)
    value2=generation.read(attempt/'python-verified-origins.json');binding='source-compiler' if shift else 'cache-read'
    assert len(value2['selected'])==1 and all(m['input_binding']==binding for m in value2['selected'][0]['matches'])
    actual=origins.recheck_attempt(attempt,entries[case['function']],PROVIDER,catalogue,interpreter,selection_builder=inputs.scalar_selection,cache_builder=inputs.frozen_caches)
    identities[actual['runtime']]=actual
assert observations==len(identities)==72 and comparisons==18
assert len({d['application_pid'] for d in identities.values()})==72
assert len({d['sdk_pid'] for d in identities.values() if not d['plain']})==36
actual_starts={str(p):hashlib.sha256(p.read_bytes()).hexdigest() for p in F.rglob('python-application-start.json')}
assert set(actual_starts)=={str(Path(runtime)/'python-application-start.json') for runtime in identities}
initial.verify_originals();case=generation.read(F/'comparison/report.json')['cases'][0]['case']
cached=next(iter(initial.caches));cache_path=source/cached;original_cache=cache_path.read_bytes();cache_stat=cache_path.stat();snapshot=workspace/'snapshot/app.py';snapshot_stat=snapshot.stat();refusals=[]
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
  assert {str(p):hashlib.sha256(p.read_bytes()).hexdigest() for p in F.rglob('python-application-start.json')}==actual_starts
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
result={'runtime_head':'95d94aed4fa7e1319392cd8013003cefbcc76888','qualification_driver':'external audit preserving first wrong-verdict audit failure','actual_application_launches':72,'sdk_processes':36,'complete_raw_effect_and_typed_observations':72,'reports':len(seen_reports),'recomputed_comparisons':18,'prelaunch_input_mutation_refusals':len(refusals),'new_applications_in_this_audit':0,'all_actual_start_records_accounted':True,'current_source_unchanged_changed_added_function':True,'original_source_cache_bytes_and_recorded_facts_restored':True,'scope':'Actual domains/filesystem/HTTP/direct/export/current-source cached/fallback workflows with retained raw transport, complete literal raw+typed/effect oracles and deliberate input mutations; not shipping/full-project completion.'}
generation.write(F/'retained-audit.json',result);print(json.dumps(result),flush=True)
