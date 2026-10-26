"""Bounded compiler diagnostic review; stock Python children, no compiler build."""
import hashlib,json,os,subprocess,time
from pathlib import Path
BASE=Path('/Users/sclarke/github/oteleq-qualification');ROOT=Path('/Users/sclarke/github/otelc-qualification/work/rust-toolchain-library-search')
OUT=BASE/'2026-10-25/sdk-rust-library-search-8bc9d43-review';OUT.mkdir()
v=json.loads(Path('/Users/sclarke/github/otelc-qualification/2026-10-25/rust-toolchain-library-search/source.json').read_text())
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
module=types.ModuleType("held_before_rust_library_search");sys.modules[module.__name__]=module
module.__file__=tests.rust_compiler.__file__
raw=subprocess.check_output(["git","show","ec5da3d:otelc/rust_compiler.py"])
exec(compile(raw,module.__file__,"exec"),module.__dict__)
with patch.object(tests,"rust_compiler",module):
 result=unittest.TextTestRunner(verbosity=2).run(unittest.TestSuite([tests.RustToolRecordTests("test_public_builder_links_compiler_libraries_from_its_exact_sysroot")]))
assert result.testsRun==1 and len(result.failures)==1 and not result.errors and not result.skipped
assert "-L native=" in result.failures[0][1] and "not found" in result.failures[0][1]
print("EXPECTED BEFORE FAILURE: original compiler recipe omits selected-sysroot native library search")
'''
for version in ('312','314'):
 python=str(BASE/f'2026-10-24/python-live-metrics/env-{version}/bin/python')
 if version=='312':run('before',[python,'-c',before])
 cov=str(OUT/('coverage-'+version))
 run('python'+version,[python,'-m','coverage','run','--data-file='+cov,'--source=otelc.rust_compiler','-m','unittest','test_rust_compiler.RustToolRecordTests','test_rust_compiler.RustCompilerCommandTests','-v'])
 run('coverage'+version,[python,'-m','coverage','report','--data-file='+cov,'--show-missing','--fail-under=80'])
run('markdown',['/opt/homebrew/Cellar/node@24/24.21.0_2/bin/node',str(BASE/'work/oteleq-native-generated/ci/markdownlint/node_modules/markdownlint-cli/markdownlint.js'),'docs/rust-source.md'])
run('diff-check',['git','diff',v['base'],v['head'],'--check'])
workflow=(ROOT/'.github/workflows/rust-public-tools.yml').read_text()
assert '    defaults:\n      run:\n        shell: bash' in workflow
for label,options,wanted in (('original-shell',['-e'],0),('explicit-pipefail',['-e','-o','pipefail'],1)):
 argv=['/bin/bash',*options,'-c','false | /usr/bin/tee /dev/null']
 result=subprocess.run(argv,capture_output=True,env=env,timeout=5)
 assert result.returncode==wanted and result.stdout==b'' and result.stderr==b''
 checks.append({'label':label,'argv':argv,'returncode':result.returncode,'expected_returncode':wanted})
held()
r={'head':v['head'],'base':v['base'],'status':'clear for bounded compiler link-search and workflow failure propagation correction','findings':[],'checks':checks,'source_files_preserved':len(v['source_facts']),'uid_gid_nlink_preserved':True,'archive_sha256':v['archive_sha256'],'before_control':'New selected-sysroot recipe assertion fails against original ec5da3d; expected failure retained','scope':'Compiler adds native lookup for its already selected sysroot library directory, retains runtime rpath, leaves bridge flags empty; explicit Bash workflow preserves failing pipeline exits','sdk_builds':0,'compiler_builds':0,'application_launches':0,'limits':['Only stock Python command children executed locally; genuine public compiler/bridge builds and both host inspection cases remain separate','Original both-host ec5 logs show missing LLVM library exit101; new genuine both-host builder success remains unproven by this bounded review','No new SDK/runtime/coverage or public Rust lifetime admission']}
(OUT/'review.json').write_text(json.dumps(r,indent=2)+'\n');print('REVIEW',digest(OUT/'review.json'),flush=True)
