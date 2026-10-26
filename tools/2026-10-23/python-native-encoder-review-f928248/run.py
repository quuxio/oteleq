import hashlib,json,os,pathlib,re,subprocess,tarfile
base=pathlib.Path(__file__).resolve().parent
original=pathlib.Path('/Users/sclarke/github/otelc-qualification/2026-10-23/python-native-encoder/source-f928248')
metadata=json.loads(original.with_suffix('.json').read_text())
archive=original.with_suffix('.tar')
if hashlib.sha256(archive.read_bytes()).hexdigest()!=metadata['archive_sha256']: raise ValueError('archive differs')
source=base/'source-f928248'; source.mkdir()
with tarfile.open(archive) as stream: stream.extractall(source,filter='data')
def audit(root):
    changed=[name for name,digest in metadata['files'].items() if hashlib.sha256((root/name).read_bytes()).hexdigest()!=digest]
    if changed: raise ValueError('source drift '+repr(changed))
    return len(metadata['files'])
record={'head':metadata['head'],'base':metadata['base'],'original_sources_before':audit(original),'independent_sources_before':audit(source),'runs':[]}
names=['test_python_native_encoder','test_native_encoder_build','test_python_input_build','test_cli.CliTests.test_inspection_reports_current_and_future_adapters','test_cli.CliTests.test_python_candidacy_does_not_advertise_implementation','test_cli.CliTests.test_not_implemented_is_an_execution_error','test_python_provider_protocol','test_python_prepared.PreparedPythonTests.test_public_function_spans_and_metrics_bind_native_code_records']
helper=(base.parent/'python-native-encoder-review-3bfc45f/check-default-snapshot.py').read_text().replace("source-3bfc45f","source-f928248")
(base/'check-default-snapshot.py').write_text(helper)
for label,python in [('312','/Users/sclarke/github/oteleq-qualification/2026-10-23/python-cli-review-b6dbebb/validation-env-312/bin/python'),('314','/Users/sclarke/github/oteleq-qualification/2026-10-23/python-http-review-87ab378/validation-env/bin/python')]:
    command=[python,'-m','unittest','-v',*names]
    path=base/('focused-'+label+'.log')
    environment={**os.environ,'PYTHONPATH':str(source)+os.pathsep+str(source/'tests'),'PYTHONDONTWRITEBYTECODE':'1'}
    with path.open('wb') as output: result=subprocess.run(command,cwd=source,env=environment,stdout=output,stderr=subprocess.STDOUT)
    count=re.search(r'Ran (\d+) tests?',path.read_text())
    probe=subprocess.run([python,str(base/'check-default-snapshot.py')],cwd=base,env=environment,capture_output=True,text=True)
    (base/('falsifier-'+label+'.log')).write_text(probe.stdout+probe.stderr)
    outcomes=json.loads(probe.stdout) if probe.returncode==0 else []
    safe=bool(outcomes) and all(row['exit']==0 and row['stdout'].startswith('refused 0 ') and not row['stderr'] for row in outcomes)
    record['runs'].append({'label':label,'command':command,'exit':result.returncode,'tests':int(count[1]) if count else None,'falsifier_exit':probe.returncode,'original_falsifier_refused_without_callbacks':safe,'falsifier_outcomes':outcomes})
record.update(original_sources_after=audit(original),independent_sources_after=audit(source))
(base/'tests.json').write_text(json.dumps(record,indent=2)+'\n')
print(json.dumps(record))
raise SystemExit(any(item['exit'] or not item['original_falsifier_refused_without_callbacks'] for item in record['runs']))
