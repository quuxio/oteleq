import hashlib,json,os,pathlib,re,subprocess,tarfile
base=pathlib.Path(__file__).resolve().parent
original=pathlib.Path('/Users/sclarke/github/otelc-qualification/2026-10-23/python-native-encoder/source-3bfc45f')
metadata=json.loads(original.with_suffix('.json').read_text())
archive=original.with_suffix('.tar')
if hashlib.sha256(archive.read_bytes()).hexdigest()!=metadata['archive_sha256']: raise ValueError('archive differs')
source=base/'source-3bfc45f'; source.mkdir()
with tarfile.open(archive) as stream: stream.extractall(source,filter='data')
def audit(root):
    changed=[name for name,digest in metadata['files'].items() if hashlib.sha256((root/name).read_bytes()).hexdigest()!=digest]
    if changed: raise ValueError('source drift '+repr(changed))
    return len(metadata['files'])
record={'head':metadata['head'],'base':metadata['base'],'original_sources_before':audit(original),'independent_sources_before':audit(source),'runs':[]}
for label,python in [('312','/Users/sclarke/github/oteleq-qualification/2026-10-23/python-cli-review-b6dbebb/validation-env-312/bin/python'),('314','/Users/sclarke/github/oteleq-qualification/2026-10-23/python-http-review-87ab378/validation-env/bin/python')]:
    command=[python,'-m','unittest','-v','test_python_native_encoder','test_native_encoder_build','test_python_input_build']
    path=base/('focused-'+label+'.log')
    with path.open('wb') as output:
        result=subprocess.run(command,cwd=source,env={**os.environ,'PYTHONPATH':str(source)+os.pathsep+str(source/'tests'),'PYTHONDONTWRITEBYTECODE':'1'},stdout=output,stderr=subprocess.STDOUT)
    count=re.search(r'Ran (\d+) tests?',path.read_text())
    record['runs'].append({'label':label,'command':command,'exit':result.returncode,'tests':int(count[1]) if count else None})
record.update(original_sources_after=audit(original),independent_sources_after=audit(source))
(base/'tests.json').write_text(json.dumps(record,indent=2)+'\n')
print(json.dumps(record))
raise SystemExit(any(item['exit'] for item in record['runs']))
