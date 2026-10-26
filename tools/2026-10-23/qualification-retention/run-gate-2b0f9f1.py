"""Run final revision gates after the earlier shared-cache gate has stopped."""
import datetime,hashlib,json,subprocess
from pathlib import Path
base=Path(__file__).parent;source=base/'source-2b0f9f1'
manifest=json.loads((base/'source-2b0f9f1.json').read_text())
previous=json.loads((base/'gate-367b599.json').read_text())
if 'exit_code' not in previous: raise ValueError('earlier gate not terminal')
for name in ('ci/markdownlint/node_modules','ci/java-coverage'):
 subprocess.run(['/bin/cp','-cR',str(base/'source-367b599'/name),str(source/name)],check=True)
def verify():
 for name,digest in manifest['files'].items():
  if hashlib.sha256((source/name).read_bytes()).hexdigest()!=digest: raise ValueError('source changed: '+name)
 return len(manifest['files'])
record={'head':manifest['head'],'source':str(source),'source_files_before':verify(),
 'command':previous['command'],'environment':previous['environment'],
 'started_at':datetime.datetime.now(datetime.UTC).isoformat()}
(base/'gate-2b0f9f1.json').write_text(json.dumps(record,indent=2)+'\n')
with (base/'gate-2b0f9f1.log').open('xb') as output:
 result=subprocess.run(record['command'],cwd=source,env=record['environment'],stdout=output,stderr=subprocess.STDOUT,check=False)
record.update(exit_code=result.returncode,source_files_after=verify(),finished_at=datetime.datetime.now(datetime.UTC).isoformat())
(base/'gate-2b0f9f1.json').write_text(json.dumps(record,indent=2)+'\n')
print(json.dumps({'head':manifest['head'],'exit_code':result.returncode,'sources':record['source_files_after']}))
raise SystemExit(result.returncode)
