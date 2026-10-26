"""Independent four-file launcher delta review with exact frozen sources."""
import hashlib,json,os,subprocess
from pathlib import Path
base=Path(__file__).parent
source=Path('/Users/sclarke/github/otelc-qualification/2026-10-23/python-frontend-policy-gates/source-10302b2')
manifest=json.loads(source.with_suffix('.json').read_text())
head='10302b2e35d69ec17f70e9798cffcafc44116a82'
def verify():
 for name,digest in manifest['files'].items():
  if hashlib.sha256((source/name).read_bytes()).hexdigest()!=digest: raise ValueError(name)
 return len(manifest['files'])
record={'head':head,'sources_before':verify(),'runs':[]}
for label,python in [('312','/Users/sclarke/github/oteleq-qualification/2026-10-23/python-cli-review-b6dbebb/validation-env-312/bin/python'),('314','/Users/sclarke/github/oteleq-qualification/2026-10-23/python-http-review-87ab378/validation-env/bin/python')]:
 command=[python,'-m','unittest','-v','test_python_frontend_components']
 with (base/('focused-'+label+'.log')).open('xb') as output:
  result=subprocess.run(command,cwd=source,env=dict(os.environ,PYTHONPATH='tests',PYTHONDONTWRITEBYTECODE='1'),stdout=output,stderr=subprocess.STDOUT,timeout=240,check=False)
 record['runs'].append({'label':label,'command':command,'exit':result.returncode})
record['sources_after']=verify()
(base/'tests.json').write_text(json.dumps(record,indent=2)+'\n')
print(json.dumps({'head':head,'sources':record['sources_after'],'exits':[v['exit'] for v in record['runs']]}))
raise SystemExit(any(v['exit'] for v in record['runs']))
