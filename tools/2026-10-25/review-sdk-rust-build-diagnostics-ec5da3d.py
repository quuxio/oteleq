"""Bounded compiler diagnostic review; stock Python children, no compiler build."""
import hashlib,json,os,subprocess,time
from pathlib import Path
BASE=Path('/Users/sclarke/github/oteleq-qualification');ROOT=Path('/Users/sclarke/github/otelc-qualification/work/rust-build-diagnostics')
OUT=BASE/'2026-10-25/sdk-rust-build-diagnostics-ec5da3d-review';OUT.mkdir()
v=json.loads(Path('/Users/sclarke/github/otelc-qualification/2026-10-25/rust-build-diagnostics/source.json').read_text())
def digest(path):
 with Path(path).open('rb') as stream:return hashlib.file_digest(stream,'sha256').hexdigest()
def held():
 assert subprocess.check_output(['git','rev-parse','HEAD'],cwd=ROOT,text=True).strip()==v['head']
 assert not subprocess.check_output(['git','status','--porcelain'],cwd=ROOT,text=True).strip()
 for name,wanted in v['source_facts'].items():
  p=ROOT/name;s=p.lstat()
  assert [digest(p),s.st_dev,s.st_ino,s.st_mode,s.st_size,s.st_mtime_ns,s.st_ctime_ns]==wanted,name
  assert [s.st_uid,s.st_gid,s.st_nlink]==v['extra_facts'][name],name
 assert digest(v['archive'])==v['archive_sha256']
held();checks=[];env=dict(os.environ,PYTHONDONTWRITEBYTECODE='1',PYTHONPATH=str(ROOT)+':'+str(ROOT/'tests'))
def run(label,argv):
 tick=time.monotonic()
 with (OUT/(label+'.log')).open('wb') as f:r=subprocess.run(argv,cwd=ROOT,env=env,stdout=f,stderr=subprocess.STDOUT,timeout=60)
 checks.append({'label':label,'argv':argv,'returncode':r.returncode,'seconds':time.monotonic()-tick});print(label,r.returncode,flush=True);assert r.returncode==0
before='''import subprocess,sys,types,unittest
from unittest.mock import patch
import test_rust_compiler as tests
module=types.ModuleType("held_before_rust_compiler");sys.modules[module.__name__]=module
module.__file__=tests.rust_compiler.__file__
raw=subprocess.check_output(["git","show","abbcd71:otelc/rust_compiler.py"])
exec(compile(raw,module.__file__,"exec"),module.__dict__)
names=["test_actual_success_failure_and_literal_arguments_have_retained_channels","test_failure_summary_retains_only_a_bounded_escaped_stderr_tail"]
with patch.object(tests,"rust_compiler",module):
 result=unittest.TextTestRunner(verbosity=2).run(unittest.TestSuite(tests.RustCompilerCommandTests(name) for name in names))
assert result.testsRun==2 and len(result.failures)==2 and not result.errors and not result.skipped
assert all("not found" in text for _,text in result.failures)
print("EXPECTED BEFORE FAILURES: original diagnostics omit exit codes and bounded stderr summary")
'''
for version in ('312','314'):
 python=str(BASE/f'2026-10-24/python-live-metrics/env-{version}/bin/python')
 if version=='312':run('before',[python,'-c',before])
 cov=str(OUT/('coverage-'+version))
 run('python'+version,[python,'-m','coverage','run','--data-file='+cov,'--source=otelc.rust_compiler','-m','unittest','test_rust_compiler.RustToolRecordTests','test_rust_compiler.RustCompilerCommandTests','-v'])
 run('coverage'+version,[python,'-m','coverage','report','--data-file='+cov,'--show-missing','--fail-under=80'])
run('markdown',['/opt/homebrew/Cellar/node@24/24.21.0_2/bin/node',str(BASE/'work/oteleq-native-generated/ci/markdownlint/node_modules/markdownlint-cli/markdownlint.js'),'docs/rust-source.md'])
run('diff-check',['git','diff',v['base'],v['head'],'--check'])
held()
r={'head':v['head'],'base':v['base'],'status':'clear for bounded retained compiler diagnostics','findings':[],'checks':checks,'source_files_preserved':len(v['source_facts']),'uid_gid_nlink_preserved':True,'archive_sha256':v['archive_sha256'],'before_control':'Both new diagnostic assertions fail against original abbcd71; expected failures retained','scope':'Failure exit code and bounded escaped final4096 stderr bytes; complete original channels retained; public recipe and all protected/runtime gates unchanged','sdk_builds':0,'compiler_builds':0,'application_launches':0,'limits':['Only stock Python command children executed locally; genuine public compiler/bridge builds and both host inspection cases remain separate','Underlying full247 compiler-build failure is not diagnosed or fixed by this change','No new SDK/runtime/coverage or public Rust lifetime admission']}
(OUT/'review.json').write_text(json.dumps(r,indent=2)+'\n');print('REVIEW',digest(OUT/'review.json'),flush=True)
