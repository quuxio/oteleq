"""Check the explicitly planned roots against current own-user processes/open files."""
import datetime
import hashlib
import json
import os
import re
from pathlib import Path
import subprocess

base=Path(__file__).parent
plan_bytes=(base/'cold-selection-plan.json').read_bytes()
plan_sha256=hashlib.sha256(plan_bytes).hexdigest()
if plan_sha256!='d79207032eab2157b245af916607d58ddd9236e7c008567b1a6f771c21c8e2a4': raise ValueError('selection plan changed')
plan=json.loads(plan_bytes)
roots=[row['root']+'/' for row in plan['groups']]
roots += ['/System/Volumes/Data'+root for root in list(roots) if root.startswith('/Users/')]
started=datetime.datetime.now(datetime.UTC).isoformat()
processes=subprocess.run(['/bin/ps','-axo','pid=,command='],capture_output=True,text=True,check=True)
patterns=[re.compile(re.escape(root.rstrip('/'))+r'''(?=/|\s|$|["'])''') for root in roots]
matched_commands=[]
for line in processes.stdout.splitlines():
 matches=[root.rstrip('/') for root,pattern in zip(roots,patterns) if pattern.search(line)]
 if matches:matched_commands.append({'pid':line.split(None,1)[0],'matched_roots':matches})
opened=subprocess.run(['/usr/sbin/lsof','-n','-P','-a','-u',str(os.getuid()),'-F','pn'],capture_output=True,text=True,check=False)
if opened.returncode not in (0,1): raise RuntimeError('lsof failed: '+str(opened.returncode))
process=None;matched_files=[]
for line in opened.stdout.splitlines():
 if line.startswith('p'): process=line[1:]
 elif line.startswith('n') and any(line[1:]==root.rstrip('/') or line[1:].startswith(root) for root in roots):
  matched_files.append({'pid':process,'path':line[1:]})
result={'started_at':started,'finished_at':datetime.datetime.now(datetime.UTC).isoformat(),
 'scope':'Current own-user process argv and lsof open-file snapshot; not a persistent lease or other-user assertion.',
 'planned_roots':len(plan['groups']),'path_aliases_checked':len(roots),'plan_sha256':plan_sha256,'matched_commands':matched_commands,'matched_open_files':matched_files,
 'lsof_exit':opened.returncode,'lsof_stderr':opened.stderr,'originals_removed':0}
path=base/('cold-open-check-'+datetime.datetime.now(datetime.UTC).strftime('%H%M%S')+'.json')
descriptor=os.open(path,os.O_WRONLY|os.O_CREAT|os.O_EXCL,0o600)
with os.fdopen(descriptor,'w') as output:json.dump(result,output,indent=2);output.write('\n')
print(json.dumps({'receipt':str(path),'matched_commands':len(matched_commands),
 'matched_open_files':len(matched_files),'stderr_bytes':len(opened.stderr)}))
if matched_commands or matched_files or opened.stderr: raise SystemExit(1)
