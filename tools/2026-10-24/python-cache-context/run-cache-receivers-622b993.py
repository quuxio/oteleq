"""Generated cached receiver corpus using maintained independent graph oracles."""
import hashlib,json,os,py_compile,sys
from pathlib import Path
R=Path('/Users/sclarke/github/oteleq-qualification/2026-10-24/python-cache-context')
REPO=Path('/Users/sclarke/github/oteleq-qualification/work/oteleq-python-cache-context')
sys.path[:0]=[str(REPO/'tests'),str(REPO/'adapters/generation'),str(REPO/'examples')]
import generation,python_provider,python_inputs
import qualify_python_generated_origins as origins
import qualify_python_sequences as legacy
import sequence_qualification as shared
from python_sequence_fixture import SOURCE,METHODS,FUNCTIONS,function
from qualify_project_tests import command
LABEL=sys.argv[1];F=R/('cache-receivers-'+LABEL+'-01');F.mkdir(mode=0o700)
CLI=R/'runtime-622b993/quux-oteleq';PROVIDER=R/('provider-ce4cf74-'+LABEL)
os.environ.update(OTELEQ_PYTHON=sys.executable,OTELEQ_CLI=str(CLI),PYTHONDONTWRITEBYTECODE='1')
catalogue=python_inputs.artefacts(PROVIDER,{'python':Path(sys.executable).absolute()});generation.write(F/'provider-inputs.json',catalogue)
CASES=F/'cases';CASES.mkdir();source=CASES/'application';package=source/'src/pkg';package.mkdir(parents=True)
(package/'__init__.py').write_text('');(package/'state.py').write_text(SOURCE)
def facts():
 return {str(p.relative_to(source)):{'sha256':hashlib.sha256(p.read_bytes()).hexdigest(),'mtime_ns':p.stat().st_mtime_ns,'mode':p.stat().st_mode,'inode':p.stat().st_ino} for p in source.rglob('*') if p.is_file()}
for path in sorted(source.rglob('*.py')):
 os.utime(path,ns=(1_700_000_000_123456789,1_700_000_000_123456789));py_compile.compile(str(path),doraise=True)
before=facts();generation.write(F/'original-inputs.json',before)
text='schema_version=1\nlanguages=["python"]\n[adapters.python]\nimport_roots=["src"]\nbackend="prepared"\nprofile="python-native-cache-origins-v3"\n[functions]\ninclude='+json.dumps(list(FUNCTIONS))+'\n'
for method in METHODS:
 text+='\n[[fixtures]]\nfunction='+json.dumps(function(method))+'\ncases=[[7]]\nreceiver={factory='+json.dumps('make_counter' if method=='secret' else 'Counter')+',arguments=[10]}\n'
 error=',expected_baseline={kind="error",category="exception",type="python.builtins.ValueError"}' if method=='fail' else ''
 text+='sequence=[{action="call",arguments="case"'+error+'},{action="call",arguments=[2]}]\n'
 if method=='transient':text+='domains=[{kind="integer",minimum=0,maximum=7}]\n'
config=CASES/'equivalence.toml';config.write_text(text)
workspace=shared.plan_generate(CLI,PROVIDER,CASES,source,config,set(FUNCTIONS))
shared.exercise_routes(CLI,F,workspace,METHODS,FUNCTIONS,origins.check_report,legacy.controls,origins.framework)
assert facts()==before
reports=sorted(F.rglob('report.json'));observations,comparisons=shared.compare_reports(F,reports,CLI,origins.check_report,())
identities={};retained_records=0
for report in reports:
 data=generation.read(report)
 for case in data['cases']:
  for lane in ('baseline','instrumented_on'):
   for repeat in range(2):
    folder=report.parent/case['case']/(lane+'-'+str(repeat));d=generation.read(folder/'python-verified-origins.json');assert d['source_origin']=='selected-input-bound'
    assert len(d['selected'])==2 and all(m['input_binding']=='cache-read' for s in d['selected'] for m in s['matches'])
    runtime=str(Path(generation.read(folder/'command.json')[-1]).parent/'python-runtime');identities[runtime]={'application_pid':d['application_pid'],'sdk_pid':d['sdk_pid']};retained_records+=1
assert python_inputs.artefacts(PROVIDER,{'python':Path(sys.executable).absolute()})==catalogue
assert len({d['application_pid'] for d in identities.values()})==len(identities)
result={'head':'622b9935fea0f11afcaf7b1c678904c7d951ee34','actual_application_launches':len(identities),'sdk_processes':sum(d['sdk_pid'] is not None for d in identities.values()),'complete_raw_and_typed_observations':observations,'retained_attempt_records':retained_records,'recomputed_comparisons':comparisons,'original_source_cache_facts_preserved':True,'generated_replay_framework_detached_reduced_routes':True,'all_selected_target_and_creator_cache_bound':True,'scope':'Actual workflow and independent complete graph oracle experiment; independent raw native transport re-audit still required.'}
generation.write(F/'result.json',result);print(json.dumps(result),flush=True)
