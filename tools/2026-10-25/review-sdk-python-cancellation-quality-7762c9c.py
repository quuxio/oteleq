"""Check the span-completion extraction and actual bounded Python SDK routes."""
import hashlib,json,os,re,subprocess,time
from pathlib import Path
BASE=Path('/Users/sclarke/github/oteleq-qualification');ROOT=Path('/Users/sclarke/github/otelc-qualification/work/python-cancellation-quality')
OUT=BASE/'2026-10-25/sdk-python-cancellation-quality-7762c9c-review';OUT.mkdir()
v=json.loads(Path('/Users/sclarke/github/otelc-qualification/2026-10-25/python-cancellation-quality/source.json').read_text())
def digest(path):
 with Path(path).open('rb') as stream:return hashlib.file_digest(stream,'sha256').hexdigest()
def held():
 assert subprocess.check_output(['git','rev-parse','HEAD'],cwd=ROOT,text=True).strip()==v['head']
 assert not subprocess.check_output(['git','status','--porcelain'],cwd=ROOT,text=True).strip()
 for name,wanted in v['source_facts'].items():
  p=ROOT/name;s=p.lstat();assert [digest(p),s.st_dev,s.st_ino,s.st_mode,s.st_size,s.st_mtime_ns,s.st_ctime_ns]==wanted,name
  assert [s.st_uid,s.st_gid,s.st_nlink]==v['extra_facts'][name],name
 assert digest(v['archive'])==v['archive_sha256']
def contents(head,name):return subprocess.check_output(['git','show',head+':'+name],cwd=ROOT)
held();checks=[];env=dict(os.environ,PYTHONDONTWRITEBYTECODE='1',PYTHONPATH=str(ROOT)+':'+str(ROOT/'tests'))
main='03907018d6c5160cacc05ec41cac11ed8893e6d6';node=['adapters/node/src/local-metric-control.ts','adapters/node/src/source-sdk-child.ts','docs/node-development.md','package-lock.json','package.json']
assert all(contents(v['head'],n)==contents(main,n) for n in node)
assert set(subprocess.check_output(['git','diff','--name-only',v['base'],v['head']],cwd=ROOT,text=True).splitlines())==set(node)|{'otelc/python_runtime.py','tests/test_python_cancellation.py'}
previous=json.loads((BASE/'2026-10-25/sdk-python-cancellation-bfd8d59-review/review.json').read_text())
for row in previous['independent_checks']:
 label='python'+row['python'];argv=[a.replace('sdk-python-cancellation-bfd8d59-review','sdk-python-cancellation-quality-7762c9c-review') for a in row['argv']]
 tick=time.monotonic()
 with (OUT/(label+'.log')).open('wb') as f:r=subprocess.run(argv,cwd=ROOT,env=env,stdout=f,stderr=subprocess.STDOUT,timeout=60)
 checks.append({'label':label,'argv':argv,'returncode':r.returncode,'seconds':time.monotonic()-tick});print(label,r.returncode,flush=True);assert r.returncode==0
 text=(OUT/(label+'.log')).read_text();assert 'Ran 43 tests' in text and '... skipped ' not in text
 cov=[argv[0],'-m','coverage','report','--data-file='+str(OUT/(row['python']+'.coverage')),'--include=*/otelc/python_runtime.py','--show-missing','--fail-under=80']
 with (OUT/('coverage'+row['python']+'.log')).open('wb') as f:r=subprocess.run(cov,cwd=ROOT,env=env,stdout=f,stderr=subprocess.STDOUT)
 assert r.returncode==0
for label,argv in (('markdown',['/opt/homebrew/Cellar/node@24/24.21.0_2/bin/node',str(BASE/'work/oteleq-native-generated/ci/markdownlint/node_modules/markdownlint-cli/markdownlint.js'),'docs/node-development.md']),('diff-check',['git','diff',v['base'],v['head'],'--check'])):
 with (OUT/(label+'.log')).open('wb') as f:r=subprocess.run(argv,cwd=ROOT,env=env,stdout=f,stderr=subprocess.STDOUT,timeout=60)
 checks.append({'label':label,'argv':argv,'returncode':r.returncode});assert r.returncode==0
held()
r={'head':v['head'],'base':v['base'],'status':'clear for bounded Python cancellation quality integration','findings':[],'checks':checks,'source_files_preserved':len(v['source_facts']),'uid_gid_nlink_preserved':True,'archive_sha256':v['archive_sha256'],'unchanged_reviewed_node_paths':node,'scope':'Exact existing span-completion block extracted without changing order/values; direct hostile-type classifier and normal/error/cancellation span controls plus actual SDK/public CLI/monitor component tests on both supported interpreters','sdk_builds':0,'compiler_builds':0,'limits':['Fresh exact-head protected CI/Sonar and broader Python consumer admission remain required','Bootstrap asyncio import retains the previously recorded application visibility/startup trade-off','No general semantic identity or new lifecycle/build/provider/shipping qualification']}
(OUT/'review.json').write_text(json.dumps(r,indent=2)+'\n');print('REVIEW',digest(OUT/'review.json'),flush=True)
