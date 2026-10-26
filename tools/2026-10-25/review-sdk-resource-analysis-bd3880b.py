"""Check producer-specific file identities without building native products."""
import hashlib,json,os,subprocess,time
from pathlib import Path
BASE=Path('/Users/sclarke/github/oteleq-qualification');ROOT=Path('/Users/sclarke/github/otelc-qualification/work/native-resource-analysis-identity')
OUT=BASE/'2026-10-25/sdk-resource-analysis-bd3880b-review';OUT.mkdir()
v=json.loads(Path('/Users/sclarke/github/otelc-qualification/2026-10-25/native-resource-analysis-identity/source.json').read_text())
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
before='''import subprocess,types,unittest
from unittest.mock import patch
import test_native_sonar as tests
module=types.ModuleType("held_before_native_sonar")
module.__file__=tests.sonar.__file__
raw=subprocess.check_output(["git","show","b425d1f12b8ac2a9dd0c3dcfed7863f00e9a343b:ci/native_sonar.py"])
exec(compile(raw,module.__file__,"exec"),module.__dict__)
with patch.object(tests,"sonar",module):
 result=unittest.TextTestRunner(verbosity=2).run(unittest.TestSuite([tests.NativeSonarTests("test_resource_frontend_records_keep_the_producers_full_file_identity")]))
assert result.testsRun==1 and len(result.errors)==1 and not result.failures
assert "native Sonar input changed: Resources.cpp" in result.errors[0][1]
print("EXPECTED BEFORE FAILURE: real-resource-shaped full identities refused by old minimal validator")
'''
for version in ('312','314'):
 python=str(BASE/f'2026-10-24/python-live-metrics/env-{version}/bin/python')
 if version=='312':run('before',[python,'-c',before])
 cov=str(OUT/('coverage-'+version))
 run('python'+version,[python,'-m','coverage','run','--data-file='+cov,'--source=ci.native_sonar','-m','unittest','test_native_sonar','-v'])
 run('coverage'+version,[python,'-m','coverage','report','--data-file='+cov,'--show-missing','--fail-under=80'])
run('markdown',['/opt/homebrew/Cellar/node@24/24.21.0_2/bin/node',str(BASE/'work/oteleq-native-generated/ci/markdownlint/node_modules/markdownlint-cli/markdownlint.js'),'docs/native-analysis.md'])
run('diff-check',['git','diff',v['base'],v['head'],'--check'])
held()
r={'head':v['head'],'base':v['base'],'status':'clear for bounded collector correction','findings':[],'checks':checks,'source_files_preserved':len(v['source_facts']),'uid_gid_nlink_preserved':True,'archive_sha256':v['archive_sha256'],'before_control':'old base fails real-resource-shaped positive with Resources.cpp full/minimal identity mismatch','scope':'Explicit producer-role validation of full source/LCOV/compilation-database file facts; remaining producers retain their exact minimal format','sdk_builds':0,'compiler_builds':0,'application_launches':0,'limits':['No new genuine native/Rust SDK execution or Sonar upload; fresh required runtime/coverage/CI remains required','Original records and products remain unchanged']}
(OUT/'review.json').write_text(json.dumps(r,indent=2)+'\n');print('REVIEW',digest(OUT/'review.json'),flush=True)
