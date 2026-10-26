"""Rerun after building the isolated Java prerequisite; preserve initial failures."""
import hashlib,json,os,re,subprocess
from pathlib import Path
base=Path(__file__).parent;source=base/'source-8ce5b87'
original=Path('/Users/sclarke/github/otelc-qualification/2026-10-23/python-runtime-health/source-8ce5b87')
manifest=json.loads(original.with_suffix('.json').read_text())
def verify(root):
 for name,digest in manifest['files'].items():
  if hashlib.sha256((root/name).read_bytes()).hexdigest()!=digest: raise ValueError(name)
 return len(manifest['files'])
record={'head':'8ce5b8795fb7feafb6034a4cc2fee7f7c07e8edc','prerequisite':'make java-build exit0 in independent copy','runs':[]}
prior=json.loads((base/'tests.json').read_text())
for run in prior['runs']:
 label=run['label'];log=base/('ready-focused-'+label+'.log')
 with log.open('xb') as output:
  completed=subprocess.run(run['command'],cwd=source,env=dict(os.environ,PYTHONPATH='tests',PYTHONDONTWRITEBYTECODE='1'),stdout=output,stderr=subprocess.STDOUT,timeout=420,check=False)
 text=log.read_text();count=re.search(r'Ran (\d+) tests',text)
 record['runs'].append({'label':label,'exit':completed.returncode,'tests':int(count[1]) if count else None,'log':str(log)})
record.update(original_sources_after=verify(original),independent_sources_after=verify(source))
(base/'ready-tests.json').write_text(json.dumps(record,indent=2)+'\n')
print(json.dumps(record))
raise SystemExit(any(run['exit'] for run in record['runs']))
