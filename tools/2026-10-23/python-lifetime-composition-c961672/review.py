"""Check the complete merged tree without changing either parent's checkout."""
import hashlib,json,subprocess
from pathlib import Path
base=Path(__file__).parent
repo=Path('/Users/sclarke/github/otelc-qualification/work/python-lifetimes-policy-integration')
head='c961672752a0458823db6ca69a352e4eb9c712f3';left='ff25281b9058f3ab32d0b346cb8c07f48ca0fedf';right='9ae3240274edbcd73b5f8777dae1e78d253c0f1a'
def git(*args):return subprocess.check_output(['git',*args],cwd=repo)
ancestor=git('merge-base',left,right).decode().strip()
def tree(commit):
 result={}
 for item in git('ls-tree','-rz',commit).split(b'\0'):
  if not item:continue
  identity,name=item.split(b'\t',1);result[name.decode()]=tuple(identity.decode().split())
 return result
old,a,b,current=map(tree,(ancestor,left,right,head))
if set(current)!=set(a)|set(b):raise ValueError('unexpected merged path set')
overlap=[]
for name in sorted(current):
 x,y,z=a.get(name),b.get(name),old.get(name)
 if x==y:expected=x
 elif x==z:expected=y
 elif y==z:expected=x
 else:
  if x[:2]!=y[:2] or x[:2]!=z[:2]:raise ValueError('non-text overlap')
  for label,commit in [('left',left),('base',ancestor),('right',right)]:
   (base/label).write_bytes(git('show',commit+':'+name))
  merged=subprocess.run(['git','merge-file','-p',str(base/'left'),str(base/'base'),str(base/'right')],capture_output=True,check=False)
  if merged.returncode or merged.stdout!=git('show',head+':'+name):raise ValueError('overlap differs: '+name)
  overlap.append(name);continue
 if current[name]!=expected:raise ValueError('non-overlap differs: '+name)
source=Path('/Users/sclarke/github/otelc-qualification/2026-10-23/python-lifetimes-policy-integration/source-c961672')
manifest=json.loads(source.with_suffix('.json').read_text())
for name,digest in manifest['files'].items():
 if hashlib.sha256((source/name).read_bytes()).hexdigest()!=digest:raise ValueError(name)
changed=git('diff','--name-only',left,head).decode().splitlines()
if len(changed)!=4:raise ValueError(changed)
r={'head':head,'parents':[left,right],'merge_base':ancestor,'complete_tree_paths_verified':len(current),
 'source_hashes_verified':len(manifest['files']),'overlapping_paths_reproduced_without_conflicts':overlap,
 'delta_from_prior_lifetime_tree':changed,'findings':[],
 'scope':'Complete merge composition proof plus all four inherited correction diffs read. Three overlapping files reproduce exactly through independent git merge-file. No new manual content; lifetime-only and frontend-only blobs retain their parent identities. Prior whole-lifetime review and separate103 correction review remain separately attributed; no new execution or provider admission claimed.'}
(base/'review.json').write_text(json.dumps(r,indent=2)+'\n');print(json.dumps(r))
for label in ('left','base','right'):(base/label).unlink()
