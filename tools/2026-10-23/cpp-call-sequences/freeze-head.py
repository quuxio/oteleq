"""Archive this isolated consumer head and prepare independent immutable runners."""
import hashlib,io,json,shutil,subprocess,tarfile
from pathlib import Path
root=Path(__file__).parent
work=Path('/Users/sclarke/github/oteleq-qualification/work/oteleq-cpp-call-sequences')
commit=subprocess.check_output(['git','rev-parse','HEAD'],cwd=work,text=True).strip();short=commit[:7]
assert not subprocess.check_output(['git','status','--porcelain'],cwd=work)
source=root/('source-'+short);source.mkdir()
archive=subprocess.check_output(['git','archive',commit],cwd=work)
with tarfile.open(fileobj=io.BytesIO(archive)) as bundle:bundle.extractall(source,filter='data')
files=subprocess.check_output(['git','ls-tree','-r','--name-only',commit],cwd=work,text=True).splitlines()
seal={'commit':commit,'archive_sha256':hashlib.sha256(archive).hexdigest(),'files':{name:hashlib.sha256((source/name).read_bytes()).hexdigest() for name in files}}
(root/('source-'+short+'.json')).write_text(json.dumps(seal,indent=2)+'\n')
for name in files:(source/name).chmod(0o444)
for name in ['ci/markdownlint/node_modules','ci/java-coverage']:
 old=root/'source-1502c22'/name;new=source/name
 if old.exists():shutil.copytree(old,new,dirs_exist_ok=True)
for base in ['run-gate','build-cli','run-qualification']:
 content=(root/(base+'-1502c22.py')).read_text().replace('1502c22744366ed54337bd5674fe3fb26d3d31a7',commit).replace('1502c22',short)
 (root/(base+'-'+short+'.py')).write_text(content)
print(json.dumps({'commit':commit,'files':len(files),'source':str(source)}))
