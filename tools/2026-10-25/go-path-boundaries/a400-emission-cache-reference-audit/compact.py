"""Retire only audited inactive, unreferenced Go cache entries."""
from pathlib import Path
from datetime import datetime,timezone
import gzip
import hashlib
import json
import os
import re
import shutil
import stat
import subprocess
import time

BASE=Path(__file__).resolve().parent
plan=json.loads((BASE/'audit.json').read_text())
cache=Path(plan['cache'])
assert str(cache)=='/Users/sclarke/github/oteleq-qualification/2026-10-24/go-live-controls/startup-additional-a400885-01/emission-off/cases/oteleq-run-a4hr_740/go-cache/build'
assert cache.resolve(strict=True)==cache and not cache.is_symlink()
processes=subprocess.check_output(['/bin/ps','eww','-axo','pid=,comm=,args='],text=True)
assert not re.search(r'(?:^|\s)GOCACHE='+re.escape(str(cache))+r'(?:\s|$)',processes),'cache has a live user'
def facts(path):
 s=path.stat()
 return [s.st_dev,s.st_ino,s.st_mode,s.st_uid,s.st_gid,s.st_size,s.st_mtime_ns,s.st_ctime_ns,s.st_nlink]
def held():
 result={}
 for name in plan['protected']:
  p=Path(name)
  with p.open('rb') as stream:digest=hashlib.file_digest(stream,'sha256').hexdigest()
  result[name]={'facts':facts(p),'sha256':digest}
 return result
assert held()==plan['protected'],'protected files changed after reference audit'
references=set(plan['references']);cutoff=plan['cutoff'];started=time.monotonic()
result={'cache':str(cache),'free_bytes_before':shutil.disk_usage(cache).free,'deleted_files':0,
        'logical_bytes_removed':0,'skipped':0,'protected_files':len(plan['protected']),
        'preexisting_missing_references':len(plan['preexisting_missing']),
        'scope':'Only old canonical Go action/data files: unreferenced, regular, single-link and nonexecutable. All referenced bytes and file facts preserved; no source, tool, current attempt or held provider removed.',
        'started_at':datetime.now(timezone.utc).isoformat()}
with gzip.open(BASE/'deleted-relative-paths.jsonl.gz','wt') as log:
 for directory in cache.iterdir():
  if not re.fullmatch('[0-9a-f]{2}',directory.name) or directory.is_symlink() or not directory.is_dir():continue
  for entry in os.scandir(directory):
   if not re.fullmatch('[0-9a-f]{64}-[ad]',entry.name):continue
   s=entry.stat(follow_symlinks=False);p=Path(entry.path)
   if not stat.S_ISREG(s.st_mode) or s.st_nlink!=1 or s.st_mode&0o111 or str(p) in references or max(s.st_mtime,s.st_ctime)>=cutoff:
    result['skipped']+=1;continue
   assert p.stat(follow_symlinks=False)==s,'cache entry changed before retirement'
   p.unlink();log.write(json.dumps({'path':str(p.relative_to(cache)),'size':s.st_size})+'\n')
   result['deleted_files']+=1;result['logical_bytes_removed']+=s.st_size
assert held()==plan['protected'],'protected bytes or file facts changed'
result.update(status='passed',retained_bytes_and_facts_unchanged=True,
              free_bytes_after=shutil.disk_usage(cache).free,seconds=round(time.monotonic()-started,3),
              finished_at=datetime.now(timezone.utc).isoformat())
(BASE/'cleanup.json').write_text(json.dumps(result,indent=2)+'\n');print(json.dumps(result),flush=True)
