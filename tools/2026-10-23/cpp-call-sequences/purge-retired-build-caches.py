"""Remove completed owned Cargo caches; preserve frozen sources and copied CLIs."""
import hashlib,json,os,re,shutil,subprocess
from pathlib import Path
root=Path(__file__).parent.resolve()
receipt=root/'PURGE-retired-build-caches.json';assert not receipt.exists()
tags=('aa5c3ec','bfa7d0b','1502c22','70cbdbc')
protected={}
for tag in tags:
 gate=json.loads((root/('gate-'+tag+'.json')).read_text())
 build=json.loads((root/('runtime-build-'+tag+'.json')).read_text())
 assert type(gate.get('exit_code')) is int and build['exit_code']==0
 seal=json.loads((root/('source-'+tag+'.json')).read_text())
 for name,sha in seal['files'].items():protected[str(root/('source-'+tag)/name)]=sha
 protected[str(root/('quux-oteleq-'+tag))]=build['cli_sha256']
def verify():
 for name,sha in protected.items():
  with Path(name).open('rb') as stream:assert hashlib.file_digest(stream,'sha256').hexdigest()==sha,name
verify()
paths=[root/('target-'+kind+'-'+tag) for tag in tags for kind in ('runtime','cli')]
paths=[p for p in paths if p.exists()]
assert all(p.parent==root and p.is_dir() and not p.is_symlink() and re.fullmatch(r'target-(runtime|cli)-[0-9a-f]{7}',p.name) for p in paths)
commands=subprocess.check_output(['ps','-axo','pid=,command='],text=True).splitlines()
assert not any(str(path) in row for path in paths for row in commands),'a process references a selected cache'
seen=set();allocated=0;items=[]
for path in paths:
 size=0;files=0
 for directory,_,names in os.walk(path,followlinks=False):
  for name in names:
   info=(Path(directory)/name).lstat();key=(info.st_dev,info.st_ino)
   if key not in seen:seen.add(key);size+=info.st_blocks*512
   files+=1
 allocated+=size;items.append({'path':str(path),'files':files,'allocated_bytes':size})
record={'status':'planned','scope':'Retired owned build caches only; raw application evidence, provider products, source archives, copied CLIs and active7b/c385/50outputs retained','allocated_bytes':allocated,'items':items,'protected_source_and_cli_files':len(protected)}
receipt.write_text(json.dumps(record,indent=2)+'\n')
for path in paths:shutil.rmtree(path)
verify();record['status']='complete';record['protected_hashes_match']=True
receipt.write_text(json.dumps(record,indent=2)+'\n')
print(json.dumps({'removed_cache_directories':len(paths),'allocated_bytes_removed':allocated,'protected_hashes_preserved':len(protected)}))
