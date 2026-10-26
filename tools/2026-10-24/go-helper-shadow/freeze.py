import hashlib,json,subprocess,tarfile
from pathlib import Path
root=Path(__file__).resolve().parent
repo=Path('/Users/sclarke/github/oteleq-qualification/work/oteleq-go-public-provider')
head=subprocess.check_output(['git','rev-parse','HEAD'],cwd=repo,text=True).strip()
assert head.startswith('3e15589') and not subprocess.check_output(['git','status','--porcelain'],cwd=repo)
source=root/'source-3e15589';source.mkdir()
archive=root/'source-3e15589.tar'
with archive.open('xb') as output: subprocess.run(['git','archive','HEAD'],cwd=repo,stdout=output,check=True)
with tarfile.open(archive) as data: data.extractall(source,filter='data')
files={name:hashlib.sha256((source/name).read_bytes()).hexdigest() for name in subprocess.check_output(['git','ls-files'],cwd=repo,text=True).splitlines()}
index={'head':head,'tree':subprocess.check_output(['git','rev-parse','HEAD^{tree}'],cwd=repo,text=True).strip(),'source':str(source),'archive':str(archive),'archive_sha256':hashlib.sha256(archive.read_bytes()).hexdigest(),'files':files}
(root/'source-3e15589.json').write_text(json.dumps(index,indent=2)+'\n')
for relative in ('ci/markdownlint/node_modules','ci/java-coverage'):
 target=source/relative
 if target.exists():
  for item in (repo/relative).iterdir():
   if item.name.startswith('.') or item.suffix=='.py': continue
   if not (target/item.name).exists(): subprocess.run(['/bin/cp','-cR',str(item),str(target/item.name)],check=True)
 else: subprocess.run(['/bin/cp','-cR',str(repo/relative),str(target)],check=True)
# Independent cloned cache keeps every earlier public CLI inode intact.
subprocess.run(['/bin/cp','-cR','/Users/sclarke/github/oteleq-qualification/2026-10-24/go-sequences/target',str(root/'target')],check=True)
old=root.parent/'go-sequences'
folder=root/'full-gate-3e15589';folder.mkdir()
spec=json.loads((old/'full-gate-b226ae8/command.json').read_text());spec.update(cwd=str(source),head=head)
(folder/'command.json').write_text(json.dumps(spec,indent=2)+'\n')
(folder/'runner.py').write_text((old/'full-gate-b226ae8/runner.py').read_text().replace('source-b226ae8.json','source-3e15589.json'))
(root/'build-cli.py').write_text((old/'build-cli.py').read_text().replace('full-gate-b226ae8','full-gate-3e15589').replace('source-b226ae8.json','source-3e15589.json'))
print(json.dumps({k:v for k,v in index.items() if k!='files'}))
