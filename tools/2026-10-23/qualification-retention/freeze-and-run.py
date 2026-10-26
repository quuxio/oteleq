"""Freeze the exact commit and run its full gate without editing inputs."""
import datetime
import hashlib
import json
import os
from pathlib import Path
import subprocess
import tarfile

root=Path(__file__).parent
checkout=Path('/Users/sclarke/github/oteleq-qualification/work/oteleq-qualification-retention')
head='676564618d49bafaf4b7e16990f0da795f1017b2'
source=root/'source-6765646'
archive=root/'source-6765646.tar'
subprocess.run(['git','archive','--format=tar','-o',str(archive),head],cwd=checkout,check=True)
source.mkdir()
with tarfile.open(archive) as contents:
    contents.extractall(source,filter='data')
tracked={str(p.relative_to(source)):hashlib.sha256(p.read_bytes()).hexdigest() for p in source.rglob('*') if p.is_file()}
manifest={'head':head,'files':tracked,'archive_sha256':hashlib.sha256(archive.read_bytes()).hexdigest()}
(root/'source-6765646.json').write_text(json.dumps(manifest,indent=2)+'\n')
old=Path('/Users/sclarke/github/oteleq-qualification/2026-10-23/python-call-sequences/source-6ba15b2')
for name in ('ci/markdownlint/node_modules','ci/java-coverage'):
    subprocess.run(['/bin/cp','-cR',str(old/name),str(source/name)],check=True)
prior=json.loads((old.parent/'gate-6ba15b2.json').read_text())
env=prior['environment']
record={'head':head,'source':str(source),'source_files_before':len(tracked),'command':prior['command'],
        'environment':env,'started_at':datetime.datetime.now(datetime.UTC).isoformat()}
(root/'gate-6765646.json').write_text(json.dumps(record,indent=2)+'\n')
with (root/'gate-6765646.log').open('xb') as output:
    result=subprocess.run(record['command'],cwd=source,env=env,stdout=output,stderr=subprocess.STDOUT,check=False)
for name,digest in tracked.items():
    if hashlib.sha256((source/name).read_bytes()).hexdigest()!=digest: raise ValueError('source changed: '+name)
record.update(exit_code=result.returncode,source_files_after=len(tracked),finished_at=datetime.datetime.now(datetime.UTC).isoformat())
(root/'gate-6765646.json').write_text(json.dumps(record,indent=2)+'\n')
print(json.dumps({'head':head,'returncode':result.returncode,'sources':len(tracked)}))
raise SystemExit(result.returncode)
