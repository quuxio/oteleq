"""Retain every named compiler-cache product; evict only unreferenced -d files."""
import hashlib,json,os,re,stat,sys,time
from pathlib import Path
root=Path(__file__).resolve().parent
bases=[root.parent/name for name in ('go-public','go-tagged','go-sequences')]
pattern=re.compile(rb'/[^\x00-\x20"\\<>]+/go-cache/build/[0-9a-f]{2}/[0-9a-f]{64}-[ad]')

def facts(path):
 s=path.stat();return (s.st_dev,s.st_ino,s.st_mode,s.st_uid,s.st_gid,s.st_size,s.st_mtime_ns,s.st_ctime_ns,s.st_nlink)

def digest(path):
 h=hashlib.sha256()
 with path.open('rb') as f:
  while b:=f.read(1024*1024): h.update(b)
 return h.hexdigest()

started=time.monotonic();caches=[];references=set();caller_expected={};metadata={};external=set()
for base in bases:
 for directory,dirs,names in os.walk(base):
  parent=Path(directory)
  if 'go-cache' in dirs:
   cache=parent/'go-cache/build'
   if cache.is_dir(): caches.append(cache)
   dirs.remove('go-cache')
  dirs[:]=[name for name in dirs if name not in ('target','node_modules','.git','__pycache__')]
  for name in names:
   p=parent/name
   if p.suffix!='.json' and name not in ('stdout','stderr') and p.suffix not in ('.stdout','.stderr'): continue
   assert p.is_file() and not p.is_symlink(),p
   before=facts(p); assert before[5]<=32*1024*1024,p
   raw=p.read_bytes(); assert facts(p)==before,p
   metadata[str(p)]={'facts':before,'sha256':hashlib.sha256(raw).hexdigest()}
   references.update(Path(value.decode()) for value in pattern.findall(raw))
   if name=='go-caller.json':
    data=json.loads(raw)
    for value,expected in data['reads'].items():
     old=caller_expected.setdefault(value,expected);assert old==expected,('conflicting caller read',value)
   if b'/otelc-qualification/work/go-source-adapter/' in raw:
    external.add(str(p))
(root/'compiler-cache-reference-sources.json').write_text(json.dumps({'metadata':metadata,'external_adapter_mentions':sorted(external)},indent=2)+'\n')
protected={}
for path in sorted(references):
 assert path.is_file() and not path.is_symlink(),path
 protected[str(path)]={'facts':facts(path),'sha256':digest(path)}
unavailable=[name for name in caller_expected if not Path(name).is_file()]
caller_expected={name:value for name,value in caller_expected.items() if '/go-cache/build/' in name}
for name,(identity,expected_facts) in caller_expected.items():
 p=Path(name)
 assert list(facts(p))==expected_facts,('caller cache facts changed',name)
 assert digest(p)==identity['sha256'] and p.stat().st_size==identity['size'],('caller cache bytes changed',name)
removed=[];kept=[]
for cache in caches:
 assert cache.resolve()==cache and not cache.is_symlink()
 for folder,dirs,names in os.walk(cache):
  assert not any((Path(folder)/name).is_symlink() for name in dirs)
  for name in names:
   p=Path(folder)/name;s=p.lstat()
   assert stat.S_ISREG(s.st_mode),p
   if re.fullmatch('[0-9a-f]{64}-d',name) and p not in references and s.st_nlink==1:
    removed.append({'path':str(p),'facts':facts(p)})
   else: kept.append(p)
plan={'scope':'Only terminal Go corpus go-cache/build unreferenced single-link content products. Module/source trees, compiler products named by any retained channel/metadata, caller facts, indexes, tooling and report evidence remain.','caches':list(map(str,caches)),'metadata_files':len(metadata),'named_cache_products':len(protected),'caller_cache_read_products':len(caller_expected),'preexisting_unavailable_noncache_inputs':unavailable,'evict_files':len(removed),'evict_logical_bytes':sum(row['facts'][5] for row in removed),'plan_seconds':round(time.monotonic()-started,3),'protected':protected,'evictions':removed}
(root/'compiler-cache-compaction-plan.json').write_text(json.dumps(plan,indent=2)+'\n')
print(json.dumps({k:v for k,v in plan.items() if k not in ('protected','evictions')}),flush=True)
if '--apply' not in sys.argv: raise SystemExit()
for row in removed:
 p=Path(row['path']);assert facts(p)==row['facts'],('eviction changed',p);p.unlink()
for name,row in protected.items():
 p=Path(name);assert facts(p)==row['facts'] and digest(p)==row['sha256'],('protected product changed',name)
for name,row in metadata.items():
 p=Path(name);assert facts(p)==row['facts'] and digest(p)==row['sha256'],('retained metadata changed',name)
for name,(identity,expected_facts) in caller_expected.items():
 p=Path(name);assert list(facts(p))==expected_facts and digest(p)==identity['sha256'],('caller product changed',name)
result={k:v for k,v in plan.items() if k not in ('protected','evictions')}
result.update(protected_cache_products_held=True,caller_cache_products_held=True,retained_metadata_held=True,seconds=round(time.monotonic()-started,3),disk_free_bytes=__import__('shutil').disk_usage(root).free)
(root/'compiler-cache-compaction-result.json').write_text(json.dumps(result,indent=2)+'\n')
print(json.dumps(result),flush=True)
