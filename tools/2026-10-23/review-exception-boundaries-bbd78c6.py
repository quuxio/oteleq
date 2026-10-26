"""Independently review exception-boundary extractions without changing fixtures."""
import hashlib,json,os,re,subprocess,tarfile
from pathlib import Path
root=Path(__file__).parent/'python-exception-boundaries-review-bbd78c6';root.mkdir()
owner=Path('/Users/sclarke/github/otelc-qualification/2026-10-23/python-exception-boundaries/source-bbd78c6');meta=json.loads(owner.with_suffix('.json').read_text());archive=owner.with_suffix('.tar');repo=Path('/Users/sclarke/github/otelc')
assert meta['head']=='bbd78c6ba0e32ca121c25662805e1440479c04ee'
assert hashlib.sha256(archive.read_bytes()).hexdigest()==meta['archive_sha256']==hashlib.sha256(subprocess.check_output(['git','archive','--format=tar',meta['head']],cwd=repo)).hexdigest()
source=root/'source';source.mkdir()
with tarfile.open(archive) as stream:stream.extractall(source,filter='data')
peer=owner.parent
log=(peer/'focused312.log').read_text();identifiers=re.findall(r'^\w+ \((test_[\w.]+)\) \.\.\. ok$',log,re.M);assert len(identifiers)==len(set(identifiers))==61
old=subprocess.check_output(['git','show',meta.get('base',meta['head']+'^')+':tests/test_python_code_index.py'],cwd=repo)
(root/'before-test_python_code_index.py').write_bytes(old)
(root/'fixture-fault-controls.py').write_text((peer/'fixture-fault-controls.py').read_text())
record={'head':meta['head'],'archive_sha256':meta['archive_sha256'],'source_files':len(meta['files']),'test_ids':identifiers,'runs':[]}
for label,python in {'312':'/Users/sclarke/github/oteleq-qualification/2026-10-23/python-cli-review-b6dbebb/validation-env-312/bin/python','314':'/Users/sclarke/github/oteleq-qualification/2026-10-23/python-http-review-87ab378/validation-env/bin/python'}.items():
 env={**os.environ,'PYTHONDONTWRITEBYTECODE':'1','PYTHONPATH':str(source)+os.pathsep+str(source/'tests')}
 path=root/('focused-'+label+'.log')
 with path.open('wb') as stream:result=subprocess.run([python,'-m','unittest',*identifiers,'-v'],cwd=source,env=env,stdout=stream,stderr=subprocess.STDOUT,timeout=90)
 assert result.returncode==0,path
 controls=subprocess.check_output([python,str(root/'fixture-fault-controls.py'),str(source)],cwd=source,env=env,text=True,timeout=30)
 assert all(hashlib.sha256((folder/name).read_bytes()).hexdigest()==sha for folder in (owner,source) for name,sha in meta['files'].items())
 row={'runtime':label,'exit_code':result.returncode,'tests':61,'log_sha256':hashlib.sha256(path.read_bytes()).hexdigest(),'fixture_fault_controls':json.loads(controls)};record['runs'].append(row);(root/'tests.json').write_text(json.dumps(record,indent=2)+'\n');print(json.dumps(row),flush=True)
