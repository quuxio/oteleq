import hashlib, json, os, pathlib, subprocess, tarfile
base=pathlib.Path(__file__).resolve().parent
sdk=base/'provider-209b60c'
source=base/'source-e83300b'
with tarfile.open(base/'provider-209b60c.tar') as archive:
    members=[item for item in archive.getmembers() if item.isfile()]
    changed=[item.name for item in members if hashlib.sha256(archive.extractfile(item).read()).hexdigest()!=hashlib.sha256((sdk/item.name).read_bytes()).hexdigest()]
if changed: raise ValueError('provider source changed: '+repr(changed))
interpreters={
'312':'/Users/sclarke/github/oteleq-qualification/2026-10-23/python-cli-review-b6dbebb/validation-env-312/bin/python',
'314':'/Users/sclarke/github/oteleq-qualification/2026-10-23/python-http-review-87ab378/validation-env/bin/python'}
results=[]
for version,python in interpreters.items():
    report=base/('frozen-e83300b-'+version)
    value=json.loads((report/'report.json').read_text())
    code="import json,sys;from pathlib import Path;sys.path[:0]=[sys.argv[1],sys.argv[2]];import python_inputs,generation;print(generation.identity(python_inputs.artefacts(Path(sys.argv[3]),{'python':Path(sys.executable).absolute()})))"
    current=subprocess.check_output([python,'-B','-c',code,str(source/'adapters/generation'),str(source/'examples'),str(sdk)],env={**os.environ,'PYTHONDONTWRITEBYTECODE':'1'},text=True).strip()
    if {item['catalogue_sha256'] for item in value['attempts']}!={current}: raise ValueError('installed/provider scope changed '+version)
    refusals=sum(len(item['refused']) for item in value['attempts'])
    if refusals!=8 or value['application_body_executed'] or not value['application_source_unchanged']: raise ValueError('incomplete actual metadata evidence')
    cli=value['cli_refusal']
    if cli!={'selected_callables':1,'status':'blocked','run_exit':3,'generated_suite_exit':1,'detached_suite_exit':1,'provider_probes_exported':True}: raise ValueError('CLI refusal scope changed')
    results.append({'python':value['interpreter']['version'],'lanes':2,'alteration_refusals':refusals,'catalogue_sha256':current,'public_python_candidate':value['public_python_candidate'],'cli_refusal':cli,'report_sha256':hashlib.sha256((report/'report.json').read_bytes()).hexdigest()})
cli=base/'bin-e83300b/quux-oteleq'
record={'runtime_revision':'e83300bc9c09846641064de7ede3539588a6a552','provider_revision':'209b60c71a6e74f61313d591f3a82df217fb48aa','provider_source_files':len(members),'provider_source_changed':changed,'immutable_cli_sha256':hashlib.sha256(cli.read_bytes()).hexdigest(),'interpreters':results,'prepared_lanes':4,'actual_evidence_refusals':16,'application_body_executed':False,'source_profile_admitted':False,'project_complete':False,'scope':'Prepared metadata and blocked generated/detached suites only.'}
(base/'metadata-e83300b-audit.json').write_text(json.dumps(record,indent=2,sort_keys=True)+'\n')
print(json.dumps(record))
