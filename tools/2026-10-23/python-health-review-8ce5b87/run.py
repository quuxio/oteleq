"""Review health in an independent source copy, isolating compiled test products."""
import hashlib,json,os,subprocess,tarfile
from pathlib import Path
base=Path(__file__).parent
original=Path('/Users/sclarke/github/otelc-qualification/2026-10-23/python-runtime-health/source-8ce5b87')
manifest=json.loads(original.with_suffix('.json').read_text())
archive=original.with_suffix('.tar')
expected=manifest.get('archive_sha256')
if expected is not None and hashlib.sha256(archive.read_bytes()).hexdigest()!=expected: raise ValueError('archive changed')
source=base/'source-8ce5b87';source.mkdir()
with tarfile.open(archive) as contents: contents.extractall(source,filter='data')
def verify(root):
 for name,digest in manifest['files'].items():
  if hashlib.sha256((root/name).read_bytes()).hexdigest()!=digest: raise ValueError('source changed: '+str(root/name))
 return len(manifest['files'])
record={'head':'8ce5b8795fb7feafb6034a4cc2fee7f7c07e8edc','source':str(source),'original_source':str(original),
 'original_sources_before':verify(original),'independent_sources_before':verify(source),'runs':[]}
for label,python in [('312','/Users/sclarke/github/oteleq-qualification/2026-10-23/python-cli-review-b6dbebb/validation-env-312/bin/python'),('314','/Users/sclarke/github/oteleq-qualification/2026-10-23/python-http-review-87ab378/validation-env/bin/python')]:
 command=[python,'-m','unittest','-v','test_python_health','test_python_prepared','test_control','test_health','test_python_lifetime_components','test_python_frontend_components']
 with (base/('focused-'+label+'.log')).open('xb') as output:
  result=subprocess.run(command,cwd=source,env=dict(os.environ,PYTHONPATH='tests',PYTHONDONTWRITEBYTECODE='1'),stdout=output,stderr=subprocess.STDOUT,timeout=420,check=False)
 record['runs'].append({'label':label,'command':command,'exit':result.returncode})
record['original_sources_after']=verify(original);record['independent_sources_after']=verify(source)
(base/'tests.json').write_text(json.dumps(record,indent=2)+'\n')
print(json.dumps({'head':record['head'],'sources':record['independent_sources_after'],'exits':[v['exit'] for v in record['runs']]}))
raise SystemExit(any(v['exit'] for v in record['runs']))
