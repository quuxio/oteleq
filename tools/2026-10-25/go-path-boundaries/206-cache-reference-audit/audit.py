"""Inventory old Go compiler cache references before any retirement."""
from pathlib import Path
from datetime import datetime, timezone
import hashlib
import json
import os
import re
import shutil
import stat
import subprocess
import time

BASE = Path(__file__).resolve().parent
CACHE = Path('/Users/sclarke/github/oteleq-qualification/2026-10-24/go-live-controls/matrix-2065261-01/both-on/cases/oteleq-run-3hkiqpfr/go-cache/build')
ROOTS = ['/Users/sclarke/github/otelc-qualification', '/Users/sclarke/github/oteleq-qualification']
assert CACHE.resolve(strict=True) == CACHE and not CACHE.is_symlink()
processes = subprocess.check_output(['/bin/ps', 'eww', '-axo', 'pid=,comm=,args='], text=True)
active = [line.split(None,2)[:2] for line in processes.splitlines()
          if re.search(r'(?:^|\s)GOCACHE=' + re.escape(str(CACHE)) + r'(?:\s|$)', line)]
assert not active, 'cache still has live users'
pattern = re.escape(str(CACHE)) + r'/[0-9a-f]{2}/[0-9a-f]{64}-[ad]'
command = ['rg','--hidden','--no-ignore','--no-filename','--only-matching','--no-messages',pattern,
           '-g','!**/node_modules/**','-g','!**/.git/**','-g','!**/compiler-cache/**',
           '-g','!**/go-build-cache/**','-g','!**/go-cache/**','-g','!**/target*/**',*ROOTS]
started=time.monotonic()
result=subprocess.run(command,capture_output=True,text=True)
assert result.returncode in (0,1), result.stderr
references=set(result.stdout.splitlines())
(BASE/'scan-references.json').write_text(json.dumps({'cache':str(CACHE),'references':sorted(references),'command':command,'scan_exit_code':result.returncode},indent=2)+'\n')
def facts(path):
 s=path.stat()
 return [s.st_dev,s.st_ino,s.st_mode,s.st_uid,s.st_gid,s.st_size,s.st_mtime_ns,s.st_ctime_ns,s.st_nlink]
held={}
missing=[]
for name in sorted(references):
 p=Path(name)
 if p.is_file():
  with p.open('rb') as stream:digest=hashlib.file_digest(stream,'sha256').hexdigest()
  held[name]={'facts':facts(p),'sha256':digest}
 elif not p.is_dir():missing.append(name)
cutoff=time.time()-3600
candidates=0
size=0
skipped=0
for directory in CACHE.iterdir():
 if not re.fullmatch('[0-9a-f]{2}',directory.name) or directory.is_symlink() or not directory.is_dir():continue
 for entry in os.scandir(directory):
  if not re.fullmatch('[0-9a-f]{64}-[ad]',entry.name):continue
  s=entry.stat(follow_symlinks=False)
  if not stat.S_ISREG(s.st_mode) or s.st_nlink!=1 or s.st_mode & 0o111 or entry.path in references or max(s.st_mtime,s.st_ctime)>=cutoff:
   skipped+=1;continue
  candidates+=1;size+=s.st_size
value={'cache':str(CACHE),'roots':ROOTS,'command':command,'scan_exit_code':result.returncode,
       'references':sorted(references),'protected':held,'preexisting_missing':missing,'cutoff':cutoff,
       'candidate_files':candidates,'candidate_logical_bytes':size,'skipped_recent_linked_or_referenced':skipped,
       'free_bytes':shutil.disk_usage(CACHE).free,'seconds':round(time.monotonic()-started,3),
       'finished_at':datetime.now(timezone.utc).isoformat(),'deletion_performed':False}
(BASE/'audit.json').write_text(json.dumps(value,indent=2)+'\n')
print(json.dumps({key:value[key] for key in ('candidate_files','candidate_logical_bytes','free_bytes','seconds')}|{'references':len(references),'protected':len(held),'missing_before':len(missing)}),flush=True)
