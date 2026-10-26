import hashlib,json,os,pathlib,subprocess,tarfile
base=pathlib.Path(__file__).resolve().parent
original=pathlib.Path('/Users/sclarke/github/otelc-qualification/2026-10-23/python-candidate-plan/source-880c85f')
metadata=json.loads(original.with_suffix('.json').read_text())
archive=original.with_suffix('.tar')
if hashlib.sha256(archive.read_bytes()).hexdigest()!=metadata['archive_sha256']: raise ValueError('archive differs')
source=base/'source-880c85f'; source.mkdir()
with tarfile.open(archive) as stream: stream.extractall(source,filter='data')
def audit(root):
    changed=[name for name,digest in metadata['files'].items() if hashlib.sha256((root/name).read_bytes()).hexdigest()!=digest]
    if changed: raise ValueError('source drift '+repr(changed))
    return len(metadata['files'])
record={'head':metadata['head'],'base':metadata['base'],'original_sources_before':audit(original),'independent_sources_before':audit(source),'runs':[]}
names=['test_cli.CliTests.test_inspection_reports_current_and_future_adapters','test_cli.CliTests.test_python_candidacy_does_not_advertise_implementation','test_cli.CliTests.test_not_implemented_is_an_execution_error','test_python_provider_protocol','test_python_prepared.PreparedPythonTests.test_public_function_spans_and_metrics_bind_native_code_records']
for label,python in [('312','/Users/sclarke/github/oteleq-qualification/2026-10-23/python-cli-review-b6dbebb/validation-env-312/bin/python'),('314','/Users/sclarke/github/oteleq-qualification/2026-10-23/python-http-review-87ab378/validation-env/bin/python')]:
    command=[python,'-m','unittest','-v',*names]
    with (base/('focused-'+label+'.log')).open('wb') as output:
        result=subprocess.run(command,cwd=source,env={**os.environ,'PYTHONPATH':str(source)+os.pathsep+str(source/'tests'),'PYTHONDONTWRITEBYTECODE':'1'},stdout=output,stderr=subprocess.STDOUT)
    record['runs'].append({'label':label,'command':command,'exit':result.returncode})
record.update(original_sources_after=audit(original),independent_sources_after=audit(source))
(base/'tests.json').write_text(json.dumps(record,indent=2)+'\n')
print(json.dumps(record))
raise SystemExit(any(item['exit'] for item in record['runs']))
