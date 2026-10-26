"""Independent source and regression check for benchmark final-drain ordering."""
import hashlib,json,os,subprocess,tarfile
from pathlib import Path
root=Path(__file__).parent/'python-http-failure-review-fa71ec2';root.mkdir()
owner=Path('/Users/sclarke/github/otelc-qualification/2026-10-23/python-http-failure-diagnostics/source-fa71ec2');meta=json.loads(owner.with_suffix('.json').read_text());archive=owner.with_suffix('.tar')
assert meta['head']=='fa71ec2b02622a7dade56158a123fdaed6eafc43'
assert hashlib.sha256(archive.read_bytes()).hexdigest()==meta['archive_sha256']==hashlib.sha256(subprocess.check_output(['git','archive','--format=tar',meta['head']],cwd='/Users/sclarke/github/otelc')).hexdigest()
source=root/'source';source.mkdir()
with tarfile.open(archive) as stream:stream.extractall(source,filter='data')
record={'head':meta['head'],'base':meta['base'],'archive_sha256':meta['archive_sha256'],'source_files':len(meta['files']),'runs':[]}
for label,python in {'312':'/Users/sclarke/github/oteleq-qualification/2026-10-23/python-cli-review-b6dbebb/validation-env-312/bin/python','314':'/Users/sclarke/github/oteleq-qualification/2026-10-23/python-http-review-87ab378/validation-env/bin/python'}.items():
    log=root/('python-'+label+'.log');command=[python,'-m','unittest','test_python_http_components','test_python_http_context','-v']
    with log.open('wb') as stream:result=subprocess.run(command,cwd=source,env={**os.environ,'PYTHONDONTWRITEBYTECODE':'1','PYTHONPATH':str(source)+os.pathsep+str(source/'tests')},stdout=stream,stderr=subprocess.STDOUT,timeout=150)
    assert all(hashlib.sha256((folder/name).read_bytes()).hexdigest()==sha for folder in (owner,source) for name,sha in meta['files'].items())
    row={'runtime':label,'exit_code':result.returncode,'command':command,'log_sha256':hashlib.sha256(log.read_bytes()).hexdigest()};record['runs'].append(row);(root/'tests.json').write_text(json.dumps(record,indent=2)+'\n');print(json.dumps(row),flush=True)
    if result.returncode:raise SystemExit(result.returncode)
