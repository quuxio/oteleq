from pathlib import Path
import hashlib,json,os,subprocess
root=Path(__file__).resolve().parent
source=root/'source'
original=Path('/Users/sclarke/github/otelc-qualification/2026-10-23/node-drain-evidence/source-16752e2')
meta=json.loads((root/'source-identity.json').read_text())
def audit():
    for location in (source,original):
        assert all(hashlib.sha256((location/name).read_bytes()).hexdigest()==sha for name,sha in meta['files'].items())
record={'head':meta['head'],'archive_sha256':meta['archive_sha256'],'runs':[]}
for label,python in (('312','/Users/sclarke/github/oteleq-qualification/2026-10-23/python-cli-review-b6dbebb/validation-env-312/bin/python'),('314','/Users/sclarke/github/oteleq-qualification/2026-10-23/python-http-review-87ab378/validation-env/bin/python')):
    audit();command=[python,'-m','unittest','test_node_launch_evidence','-v'];log=root/(label+'.log')
    with log.open('wb') as output:
        result=subprocess.run(command,cwd=source,env={**os.environ,'PYTHONPATH':str(source)+os.pathsep+str(source/'tests'),'PYTHONDONTWRITEBYTECODE':'1'},stdout=output,stderr=subprocess.STDOUT)
    audit();assert result.returncode==0 and 'Ran 8 tests' in log.read_text()
    row={'runtime':label,'command':command,'exit_code':result.returncode,'source_files_preserved':len(meta['files']),'log_sha256':hashlib.sha256(log.read_bytes()).hexdigest()};record['runs'].append(row)
    (root/'tests.json').write_text(json.dumps(record,indent=2)+'\n');print(json.dumps(row),flush=True)
