"""Prune superseded qualification runs and rebuildable generated Go caches."""
import hashlib
import json
import os
from pathlib import Path
import shutil
import stat
import subprocess
import time

root=Path('/Users/sclarke/github/oteleq-qualification')
audit=root/'2026-10-20/merge-http'
metadata=root/'history-pruned';metadata.mkdir(exist_ok=True)
superseded=[
 '2026-10-19/project-policy-default-3db1d51','2026-10-19/project-policy-failed-3db1d51',
 '2026-10-19/python-resource-edb78ce','2026-10-19/python-resource-b2-50bb758',
 '2026-10-19/python-resource-e73-b824b0b','2026-10-19/scalar-edb78ce',
 '2026-10-19/scalar-f8875f8','2026-10-19/rust-frontend-4db9bb9',
 '2026-10-19/rust-llvm-main65-provider-ce8e1a0','2026-10-19/rust-source-column-c9bd330',
 '2026-10-20/ready-stack-489879b','2026-10-20/rust-main67-4db9bb9',
]
caches=json.loads((audit/'cache-purge-candidates.json').read_text())
caches=[name for name in caches if not any(Path(name).is_relative_to(Path(old)) for old in superseded)]
protected=[root/'2026-10-20/pause-for-reboot',root/'2026-10-20/merge-http',root/'work']
selected=[root/name for name in superseded+caches]
for p in selected:
 assert p.is_relative_to(root) and not any(p.is_relative_to(q) or q.is_relative_to(p) for q in protected)
 assert not p.is_symlink() and p.resolve().is_relative_to(root.resolve()),p
# Never remove a directory with an open file/cwd owned by a running process.
opened=subprocess.run(['/usr/sbin/lsof','-nP','-Fpn'],capture_output=True,text=True)
assert opened.returncode in (0,1)
for line in opened.stdout.splitlines():
 if not line.startswith('n/'):continue
 p=Path(line[1:])
 assert not any(p==q or p.is_relative_to(q) for q in selected), 'selected history has a live file reference'
receipt={'started':time.time(),'policy':'Retain latest distinct capability evidence and small historical summaries; remove superseded snapshots and generated Go build/module caches. Preserve current HTTP evidence/SDK and active workspace.','free_bytes_before':shutil.disk_usage(root).free,'removed_snapshots':[],'removed_cache_directories':[],'retained_metadata':[]}

def save():
 (metadata/'PURGE.json').write_text(json.dumps(receipt,indent=2)+'\n')

def readonly_retry(function,path,error):
 p=Path(path)
 os.chmod(p.parent,stat.S_IMODE(p.parent.stat().st_mode)|0o700)
 if p.is_dir() and not p.is_symlink():os.chmod(p,stat.S_IMODE(p.stat().st_mode)|0o700)
 function(path)

save()
for name in superseded:
 p=root/name
 if not p.exists():continue
 for f in p.iterdir():
  if f.is_file() and not f.is_symlink() and f.suffix in ('.json','.md','.log','.txt') and f.stat().st_size<=4*1024*1024:
   dest=metadata/'summaries'/name/f.name;dest.parent.mkdir(parents=True,exist_ok=True)
   shutil.copy2(f,dest)
   receipt['retained_metadata'].append({'path':str(dest.relative_to(root)),'sha256':hashlib.sha256(dest.read_bytes()).hexdigest()})
 shutil.rmtree(p,onexc=readonly_retry)
 receipt['removed_snapshots'].append(name);save()
 print('removed superseded snapshot',name,flush=True)
for name in caches:
 p=root/name
 if not p.exists():continue
 shutil.rmtree(p,onexc=readonly_retry)
 receipt['removed_cache_directories'].append(name)
 if len(receipt['removed_cache_directories'])%25==0:
  save();print('removed cache directories',len(receipt['removed_cache_directories']),flush=True)
receipt['finished']=time.time();receipt['free_bytes_after']=shutil.disk_usage(root).free;receipt['status']='complete';save()
print(json.dumps({'removed_snapshots':len(receipt['removed_snapshots']),'removed_cache_directories':len(receipt['removed_cache_directories']),'net_free_bytes_gained':receipt['free_bytes_after']-receipt['free_bytes_before']}),flush=True)
