"""Independent protocol metadata and actual producer version-consistency review."""
import hashlib,json,os,re,subprocess,tarfile
from pathlib import Path
base=Path(__file__).parent
original=Path('/Users/sclarke/github/otelc-qualification/2026-10-23/python-provider-protocol/source-209b60c')
manifest=json.loads(original.with_suffix('.json').read_text())
source=base/'source-209b60c';source.mkdir()
archive=original.with_suffix('.tar')
if hashlib.sha256(archive.read_bytes()).hexdigest()!=manifest['archive_sha256']:raise ValueError('archive changed')
with tarfile.open(archive) as contents:contents.extractall(source,filter='data')
def verify(root):
 for name,digest in manifest['files'].items():
  if hashlib.sha256((root/name).read_bytes()).hexdigest()!=digest:raise ValueError(name)
 return len(manifest['files'])
r={'head':'209b60c71a6e74f61313d591f3a82df217fb48aa','original_sources_before':verify(original),'independent_sources_before':verify(source),'runs':[]}
for label,python in [('312','/Users/sclarke/github/oteleq-qualification/2026-10-23/python-cli-review-b6dbebb/validation-env-312/bin/python'),('314','/Users/sclarke/github/oteleq-qualification/2026-10-23/python-http-review-87ab378/validation-env/bin/python')]:
 command=[python,'-m','unittest','-v','test_python_provider_protocol','test_python_prepared.PreparedPythonTests.test_public_function_spans_and_metrics_bind_native_code_records']
 log=base/('focused-'+label+'.log')
 with log.open('xb') as output:
  result=subprocess.run(command,cwd=source,env=dict(os.environ,PYTHONPATH='tests',PYTHONDONTWRITEBYTECODE='1'),stdout=output,stderr=subprocess.STDOUT,timeout=240,check=False)
 text=log.read_text();match=re.search(r'Ran (\d+) tests',text)
 r['runs'].append({'label':label,'command':command,'exit':result.returncode,'tests':int(match[1]) if match else None})
r.update(original_sources_after=verify(original),independent_sources_after=verify(source))
(base/'tests.json').write_text(json.dumps(r,indent=2)+'\n');print(json.dumps(r))
raise SystemExit(any(row['exit'] for row in r['runs']))
