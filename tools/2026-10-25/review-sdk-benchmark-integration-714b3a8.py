"""Check reviewed cleanup plus native-helper integration without SDK workloads."""
import ast,hashlib,json,os,re,subprocess,time
from pathlib import Path
BASE=Path('/Users/sclarke/github/oteleq-qualification');ROOT=Path('/Users/sclarke/github/otelc-qualification/work/benchmark-error-priority-quality')
OUT=BASE/'2026-10-25/sdk-benchmark-integration-714b3a8-review';OUT.mkdir()
v=json.loads(Path('/Users/sclarke/github/otelc-qualification/2026-10-25/benchmark-error-priority-quality/source.json').read_text())
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
shared='19330d2481ff43b0b7be85ae0f1cb995b161349c';native='c829fb30284440b781036c93d9841bf307e39afd';main='03907018d6c5160cacc05ec41cac11ed8893e6d6'
changed=subprocess.check_output(['git','diff','--name-only',v['base'],v['head']],cwd=ROOT,text=True).splitlines()
unchanged_shared=[n for n in changed if n!='otelc/native_benchmark.py']
assert len(unchanged_shared)==14 and all(contents(v['head'],n)==contents(shared,n) for n in unchanged_shared)
node=['adapters/node/src/local-metric-control.ts','adapters/node/src/source-sdk-child.ts','docs/node-development.md','package-lock.json','package.json']
assert all(contents(v['head'],n)==contents(main,n) for n in node)
def functions(raw):
 text=raw.decode();tree=ast.parse(text)
 return {n.name:ast.get_source_segment(text,n) for n in tree.body if isinstance(n,(ast.FunctionDef,ast.AsyncFunctionDef))}
current=functions(contents(v['head'],'otelc/native_benchmark.py'));prior=functions(contents(native,'otelc/native_benchmark.py'))
assert set(current)==set(prior)
assert all(current[n]==prior[n] for n in current if n!='measure')
previous=json.loads((BASE/'2026-10-25/sdk-benchmark-errors-19330d2-review/review.json').read_text())
for row in previous['independent_checks']:
 label='python'+row['python'];argv=[a.replace('sdk-benchmark-errors-19330d2-review','sdk-benchmark-integration-714b3a8-review') for a in row['argv']]
 tick=time.monotonic()
 with (OUT/(label+'.log')).open('wb') as f:r=subprocess.run(argv,cwd=ROOT,env=env,stdout=f,stderr=subprocess.STDOUT,timeout=60)
 checks.append({'label':label,'argv':argv,'returncode':r.returncode,'seconds':time.monotonic()-tick});print(label,r.returncode,flush=True);assert r.returncode==0
 text=(OUT/(label+'.log')).read_text();assert 'Ran 42 tests' in text and '... skipped ' not in text
 python=argv[0]
 with (OUT/('coverage'+row['python']+'.log')).open('wb') as f:
  cov=subprocess.run([python,'-m','coverage','report','--data-file='+str(OUT/(row['python']+'.coverage')),'--include=*/otelc/benchmark_cleanup.py','--fail-under=80'],cwd=ROOT,env=env,stdout=f,stderr=subprocess.STDOUT)
 assert cov.returncode==0
for label,argv in (('markdown',['/opt/homebrew/Cellar/node@24/24.21.0_2/bin/node',str(BASE/'work/oteleq-native-generated/ci/markdownlint/node_modules/markdownlint-cli/markdownlint.js'),'README.md','docs/benchmarks.md']),('diff-check',['git','diff',v['base'],v['head'],'--check'])):
 tick=time.monotonic()
 with (OUT/(label+'.log')).open('wb') as f:r=subprocess.run(argv,cwd=ROOT,env=env,stdout=f,stderr=subprocess.STDOUT,timeout=60)
 checks.append({'label':label,'argv':argv,'returncode':r.returncode,'seconds':time.monotonic()-tick});assert r.returncode==0
held()
r={'head':v['head'],'base':v['base'],'parents':[shared,native],'status':'clear for bounded reviewed cleanup/native-helper integration','findings':[],'checks':checks,'source_files_preserved':len(v['source_facts']),'uid_gid_nlink_preserved':True,'archive_sha256':v['archive_sha256'],'unchanged_shared_cleanup_paths':unchanged_shared,'unchanged_reviewed_node_paths':node,'native_helper_functions_preserved':[n for n in current if n!='measure'],'scope':'Combined native accounting/workload helpers with both inner-owner and outer final-drain primary-error preservation; reviewed parents retained','sdk_builds':0,'compiler_builds':0,'application_launches':0,'limits':['Only bounded Python/stock-command checks executed locally; genuine native/other-language benchmark processes, timings and full component coverage remain required','Fresh exact-head protected CI/Sonar required; prior green results do not transfer']}
(OUT/'review.json').write_text(json.dumps(r,indent=2)+'\n');print('REVIEW',digest(OUT/'review.json'),flush=True)
