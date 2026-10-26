"""Review profile correction and exact-head/all-base CI without native builds."""
import copy,hashlib,json,os,subprocess,time
from pathlib import Path
BASE=Path('/Users/sclarke/github/oteleq-qualification');ROOT=Path('/Users/sclarke/github/otelc-qualification/work/rust-public-health-profile')
OUT=BASE/'2026-10-25/sdk-rust-profile-ci-89508d5-review-02';OUT.mkdir()
manifest_paths=[Path('/Users/sclarke/github/otelc-qualification/2026-10-25/rust-public-health-profile/source.json'),Path('/Users/sclarke/github/otelc-qualification/2026-10-25/stacked-pr-checks/source.json')]
records=[json.loads(p.read_text()) for p in manifest_paths]
def digest(p):
 with Path(p).open('rb') as f:return hashlib.file_digest(f,'sha256').hexdigest()
def held():
 for v in records:
  root=Path(v['root']);assert subprocess.check_output(['git','rev-parse','HEAD'],cwd=root,text=True).strip()==v['head']
  assert not subprocess.check_output(['git','status','--porcelain'],cwd=root,text=True).strip()
  for name,wanted in v['source_facts'].items():
   p=root/name;s=p.lstat();assert [digest(p),s.st_dev,s.st_ino,s.st_mode,s.st_size,s.st_mtime_ns,s.st_ctime_ns]==wanted,(v['head'],name)
   assert [s.st_uid,s.st_gid,s.st_nlink]==v['extra_facts'][name],(v['head'],name)
  assert digest(v['archive'])==v['archive_sha256']
def contents(head,name):return subprocess.check_output(['git','show',head+':'+name],cwd=ROOT)
def parse_yaml(raw):
 script="const yaml=require('/Users/sclarke/github/oteleq-qualification/work/oteleq-native-generated/ci/markdownlint/node_modules/js-yaml');let raw='';process.stdin.setEncoding('utf8');process.stdin.on('data',x=>raw+=x);process.stdin.on('end',()=>process.stdout.write(JSON.stringify(yaml.load(raw))));"
 return json.loads(subprocess.check_output(['/opt/homebrew/Cellar/node@24/24.21.0_2/bin/node','-e',script],input=raw))
def check_ci(before,after):
 old=parse_yaml(contents(before,'.github/workflows/ci.yml'));new=parse_yaml(contents(after,'.github/workflows/ci.yml'))
 assert new['on']['pull_request'] in ('',None,{})
 expected=copy.deepcopy(old);expected['on']['pull_request']=new['on']['pull_request']
 ref='${{ github.event.pull_request.head.sha || github.sha }}'
 changed=[]
 for job in ('quality','macos'):
  checkout=next(step for step in expected['jobs'][job]['steps'] if step.get('uses','').startswith('actions/checkout@'))
  assert 'with' not in checkout;checkout['with']={'ref':ref};changed.append(job)
 assert expected==new
 for job in new['jobs'].values():
  assert next(step for step in job['steps'] if step.get('uses','').startswith('actions/checkout@'))['with']['ref']==ref
 return {'before':before,'after':after,'jobs_preserved':list(new['jobs']),'only_changes':['all PR base branches','quality/macOS checkout exact PR head'],'permissions_and_fork_guard_and_job_scripts_preserved':True}
held();checks=[];ci_checks=[check_ci(records[1]['base'],records[1]['head']),check_ci('6f03e77',records[0]['head'])]
assert subprocess.check_output(['git','diff','--name-only','829c066',records[0]['head']],cwd=ROOT,text=True).splitlines()==['.github/workflows/ci.yml','README.md']
rust_paths=subprocess.check_output(['git','ls-tree','-r','--name-only','6dcaa2b','native/rust'],cwd=ROOT,text=True).splitlines()
assert all(contents(records[0]['head'],p)==contents('6dcaa2b',p) for p in rust_paths)
# All unchanged reviewed parent modules retain their exact bytes.
parents={'8bc9d43':['otelc/rust_compiler.py','otelc/rust_build.py'], 'd5fd575':['otelc/rust_benchmark.py'], '714b3a8':['otelc/benchmark_cleanup.py','otelc/native_benchmark_launch.py','otelc/node_benchmark.py','otelc/python_benchmark.py','otelc/python_benchmark_launch.py'], 'bd3880b':['ci/native_sonar.py']}
for head,names in parents.items():
 for p in names:assert contents(records[0]['head'],p)==contents(head,p),(head,p)
env=dict(os.environ,PYTHONDONTWRITEBYTECODE='1',PYTHONPATH=str(ROOT)+':'+str(ROOT/'tests'))
modules=['test_rust_compiler.RustToolRecordTests','test_rust_compiler.RustCompilerCommandTests','test_rust_public.RustInputTests','test_rust_public.RustBoundaryTests','test_rust_benchmark','test_rust_lifetimes','test_rust_sonar','test_native_sonar','test_benchmark_failures','test_native_benchmark.NativeBenchmarkAccountingTests','test_rust_drop_health','test_health.HealthShapeTests','test_cli','test_python_benchmark_drain','test_python_benchmark_manager_drain','test_python_stock_benchmark']
source='otelc.rust_compiler,otelc.rust_build,otelc.rust_launch,otelc.rust_benchmark,otelc.rust_lifetimes,otelc.benchmark_cleanup,otelc.native_benchmark,otelc.native_benchmark_launch,ci.native_sonar,ci.rust_sonar'
for version in ('312','314'):
 python=str(BASE/f'2026-10-24/python-live-metrics/env-{version}/bin/python');cov=str(OUT/(version+'.coverage'));argv=[python,'-m','coverage','run','--data-file='+cov,'--source='+source,'-m','unittest',*modules,'-v'];tick=time.monotonic()
 with (OUT/(version+'.log')).open('wb') as f:r=subprocess.run(argv,cwd=ROOT,env=env,stdout=f,stderr=subprocess.STDOUT,timeout=60)
 checks.append({'python':version,'argv':argv,'returncode':r.returncode,'seconds':time.monotonic()-tick});print(version,r.returncode,flush=True);assert r.returncode==0
 text=(OUT/(version+'.log')).read_text();assert 'Ran 115 tests' in text and '... skipped ' not in text
 with (OUT/(version+'-coverage.log')).open('wb') as f:r=subprocess.run([python,'-m','coverage','report','--data-file='+cov,'--show-missing'],cwd=ROOT,env=env,stdout=f,stderr=subprocess.STDOUT)
 assert r.returncode==0
 for name in ('ci/native_sonar.py','ci/rust_sonar.py','otelc/benchmark_cleanup.py','otelc/rust_benchmark.py','otelc/rust_lifetimes.py','otelc/rust_compiler.py'):
  subprocess.run([python,'-m','coverage','report','--data-file='+cov,'--include=*/'+name,'--fail-under=80'],cwd=ROOT,env=env,check=True,stdout=subprocess.DEVNULL)
# Parse each shell run block without executing it.
for index,v in enumerate(records):
 workflow=parse_yaml((Path(v['root'])/'.github/workflows/ci.yml').read_bytes())
 for job in workflow['jobs'].values():
  for step in job['steps']:
   if 'run' in step:subprocess.run(['/bin/bash','-n'],input=step['run'].encode(),check=True,capture_output=True)
subprocess.run(['/opt/homebrew/Cellar/node@24/24.21.0_2/bin/node',str(BASE/'work/oteleq-native-generated/ci/markdownlint/node_modules/markdownlint-cli/markdownlint.js'),'README.md','docs/rust-source.md'],cwd=ROOT,env=env,check=True)
subprocess.run(['git','diff','6f03e77',records[0]['head'],'--check'],cwd=ROOT,check=True)
held()
r={'head':records[0]['head'],'base':records[0]['base'],'status':'clear for bounded Rust public profile correction and reviewed component integration','findings':[],'resolved_finding':{'original_head':'6f03e77','original_receipt':str(BASE/'2026-10-25/sdk-rust-runtime-6f03e77-review/review.json'),'contract':'Public plan2/function profile requires health1, no private drop accounting, and lifetime-disabled policy; generic private health5 remains valid'},'checks':checks,'ci_semantic_checks':ci_checks,'source_files_preserved':len(records[0]['source_facts']),'ci_source_files_preserved':len(records[1]['source_facts']),'uid_gid_nlink_preserved':True,'archive_sha256':records[0]['archive_sha256'],'ci_archive_sha256':records[1]['archive_sha256'],'unchanged_rust_source_paths':rust_paths,'unchanged_reviewed_parent_modules':parents,'sdk_builds':0,'compiler_builds':0,'native_rust_application_launches':0,'scope':'Exact P2 correction, both public boundaries, independent positive/private clean/lost/censor/wrong-version/policy controls, valid private health controls, reviewed module union and semantic CI comparison; stock Python unit-command children only','limits':['Both-host genuine full SDK/runtime/benchmark and all required final-head checks remain required','Build/launch statement coverage from bounded mocks is not represented as complete component coverage','No automatic Rust lifetime, general build/dependency or oteleq consumer admission']}
(OUT/'review.json').write_text(json.dumps(r,indent=2)+'\n');print('REVIEW',digest(OUT/'review.json'),flush=True)
