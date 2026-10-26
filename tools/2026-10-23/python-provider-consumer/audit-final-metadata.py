import hashlib,json,os,pathlib,subprocess,tarfile
base=pathlib.Path(__file__).resolve().parent
runtime='6e3a21f980bf0c5491d847af051b099634310b72'
source=base/'source-6e3a21f'
expected=json.loads((base/'source-6e3a21f-manifest.json').read_text())
if any(hashlib.sha256((source/name).read_bytes()).hexdigest()!=digest for name,digest in expected.items()): raise ValueError('consumer source drift')
interpreters={'312':'/Users/sclarke/github/oteleq-qualification/2026-10-23/python-cli-review-b6dbebb/validation-env-312/bin/python','314':'/Users/sclarke/github/oteleq-qualification/2026-10-23/python-http-review-87ab378/validation-env/bin/python'}
review=base.parent/'python-candidate-review-880c85f/source-880c85f'
providers=[('209b60c','209b60c71a6e74f61313d591f3a82df217fb48aa',base/'provider-209b60c',base/'provider-209b60c.tar',False),('880c85f','880c85f2f16b1ac46cc8214804b872e523c13af9',review,pathlib.Path('/Users/sclarke/github/otelc-qualification/2026-10-23/python-candidate-plan/source-880c85f.tar'),True)]
results=[]
for short,head,root,archive_path,candidate in providers:
    with tarfile.open(archive_path) as archive:
        members=[item for item in archive.getmembers() if item.isfile()]
        changed=[item.name for item in members if hashlib.sha256(archive.extractfile(item).read()).hexdigest()!=hashlib.sha256((root/item.name).read_bytes()).hexdigest()]
    if changed: raise ValueError('provider source drift '+repr(changed))
    for version,python in interpreters.items():
        folder=base/('frozen-6e3a21f-'+short+'-'+version)
        value=json.loads((folder/'report.json').read_text())
        code="import sys;from pathlib import Path;sys.path[:0]=[sys.argv[1],sys.argv[2]];import python_inputs,generation;print(generation.identity(python_inputs.artefacts(Path(sys.argv[3]),{'python':Path(sys.executable).absolute()})))"
        current=subprocess.check_output([python,'-B','-c',code,str(source/'adapters/generation'),str(source/'examples'),str(root)],env={**os.environ,'PYTHONDONTWRITEBYTECODE':'1'},text=True).strip()
        if {item['catalogue_sha256'] for item in value['attempts']}!={current}: raise ValueError('provider/installed scope drift')
        if value['public_python_candidate'] is not candidate: raise ValueError('wrong candidate scope')
        reason=value['source_profile_reason']
        if candidate and 'both baseline and instrumented selected-source origin bindings are unavailable' not in reason: raise ValueError('missing origin guard')
        if not candidate and 'Python has no public implementation or candidate declaration' not in reason: raise ValueError('missing public candidate guard')
        if value['application_body_executed'] or not value['application_source_unchanged']: raise ValueError('application executed/changed')
        refusals=sum(len(item['refused']) for item in value['attempts'])
        if refusals!=8: raise ValueError('missing altered-evidence refusals')
        required={'selected_callables':1,'status':'blocked','run_exit':3,'generated_suite_exit':1,'detached_suite_exit':1,'provider_probes_exported':True}
        if value['cli_refusal']!=required: raise ValueError('blocked CLI proof differs')
        results.append({'provider_revision':head,'provider_source_files_held':len(members),'python':value['interpreter']['version'],'prepared_lanes':2,'altered_evidence_refusals':refusals,'catalogue_sha256':current,'public_python_candidate':candidate,'source_profile_reason':reason,'cli_refusal':required,'report_sha256':hashlib.sha256((folder/'report.json').read_bytes()).hexdigest()})
cli=base/'bin-6e3a21f/quux-oteleq'
record={'runtime_revision':runtime,'consumer_source_files_held':len(expected),'immutable_cli_sha256':hashlib.sha256(cli.read_bytes()).hexdigest(),'contexts':results,'prepared_lanes':8,'altered_evidence_refusals':32,'application_body_executed':False,'source_profile_admitted':False,'project_complete':False,'scope':'Prepared metadata and actual blocked generated/detached suites; no source/health/native recipe/shipping admission.'}
(base/'metadata-6e3a21f-audit.json').write_text(json.dumps(record,indent=2,sort_keys=True)+'\n')
print(json.dumps({'runtime_revision':runtime,'contexts':len(results),'source_files_held':len(expected),'prepared_lanes':8,'refusals':32,'source_profile_admitted':False}))
