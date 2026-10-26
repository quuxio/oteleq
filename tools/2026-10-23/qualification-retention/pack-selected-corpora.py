"""Pack two reviewed cold corpora without removing any original file."""
import datetime,hashlib,json,os,sys
from pathlib import Path
base=Path(__file__).parent;sys.path.insert(0,str(base/'source-367b599'))
from ci import evidence_archive as archive
plan_bytes=(base/'cold-selection-plan.json').read_bytes()
if hashlib.sha256(plan_bytes).hexdigest()!='d79207032eab2157b245af916607d58ddd9236e7c008567b1a6f771c21c8e2a4':raise ValueError('plan changed')
plan=json.loads(plan_bytes)
parent=base/'archives';parent.mkdir(mode=0o700,exist_ok=True)
os.nice(10)
for row in plan['groups']:
 if not any(row['root'].endswith(s) for s in ('controls-a295-node24','qualification-bb1fb96-stock-emission-off')):continue
 selection=Path(row['selection'])
 if hashlib.sha256(selection.read_bytes()).hexdigest()!=row['selection_sha256']:raise ValueError('selection changed')
 store=parent/selection.stem
 result=archive.pack(Path(row['root']),selection,store)
 result.update(head='367b599e7fe55a01364810f194b3e54e3c29ab8d',root=row['root'],store=str(store),selection_sha256=row['selection_sha256'],finished_at=datetime.datetime.now(datetime.UTC).isoformat())
 path=base/('packed-'+selection.stem+'.json')
 with path.open('x') as output:json.dump(result,output,indent=2);output.write('\n')
 print(json.dumps({k:result[k] for k in ('root','files','original_bytes','archive_bytes','originals_removed')}),flush=True)
