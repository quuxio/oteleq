import collections,hashlib,json,os
from pathlib import Path
root=Path(__file__).resolve().parent/'maintained-b6d4369'
starts=[]
for directory,dirs,names in os.walk(root):
 dirs[:]=[name for name in dirs if name not in ('go-cache','target','node_modules','.git','__pycache__')]
 if 'go-application-start.json' in names: starts.append(Path(directory)/'go-application-start.json')
applications={};copied=0;sdk={};received=collections.Counter();functions=collections.Counter()
for path in starts:
 data=json.loads(path.read_text());launch=data['launch_id'];raw=path.read_bytes()
 if launch in applications:
  assert applications[launch]['raw']==raw,launch
  copied+=1
 else: applications[launch]={'raw':raw,'path':str(path)}
 receipt=path.parent.parent/'go-verified-telemetry.json'
 if receipt.is_file():
  raw=receipt.read_bytes()
  if launch in sdk: assert sdk[launch]==raw,launch
  else:
   sdk[launch]=raw;value=json.loads(raw)
   assert value['pending']==0 and not any(value['losses'].values())
   received.update(value['health']['received']);functions.update(value['functions'])
assert len(starts)==164 and len(applications)==160 and len(sdk)==80 and copied==4
status=root/'resume-813c33a/status.json'
value=json.loads(status.read_text());assert value['status']=='passed' and value['unique_command_identities']==160
record={'actual_application_launches':len(applications),'actual_sdk_processes':len(sdk),'copied_attempts':copied,'retained_attempt_folders':len(starts),'received':dict(received),'functions':dict(functions),'status_sha256':hashlib.sha256(status.read_bytes()).hexdigest(),'scope':'Retained-only deduplication and health/receipt accounting; no new applications. Original initial audit failure remains retained.'}
(root/'aggregate-audit.json').write_text(json.dumps(record,indent=2)+'\n')
print(json.dumps(record,indent=2))
