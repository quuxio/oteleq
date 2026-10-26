"""Bounded independent source/health review; no SDK builds or applications."""
import hashlib,json,os,subprocess,time
from pathlib import Path
BASE=Path('/Users/sclarke/github/oteleq-qualification')
ROOT=Path('/Users/sclarke/github/otelc-qualification/work/rust-drop-sdk-bridge')
MANIFEST=Path('/Users/sclarke/github/otelc-qualification/2026-10-25/rust-drop-sdk-bridge/source.json')
OUT=BASE/'2026-10-25/sdk-rust-drop-bridge-45d0874-review'
OUT.mkdir()
manifest=json.loads(MANIFEST.read_text())
def digest(path):
 with Path(path).open('rb') as stream:return hashlib.file_digest(stream,'sha256').hexdigest()
def preserved():
 assert subprocess.check_output(['git','rev-parse','HEAD'],cwd=ROOT,text=True).strip()==manifest['head']
 assert not subprocess.check_output(['git','status','--porcelain'],cwd=ROOT,text=True).strip()
 for name,wanted in manifest['source_facts'].items():
  p=ROOT/name;s=p.lstat()
  assert [digest(p),s.st_dev,s.st_ino,s.st_mode,s.st_size,s.st_mtime_ns,s.st_ctime_ns]==wanted,name
  assert [s.st_uid,s.st_gid,s.st_nlink]==manifest['extra_facts'][name],name
 assert digest(manifest['archive'])==manifest['archive_sha256']
preserved()
checks=[]
env={**os.environ,'PYTHONDONTWRITEBYTECODE':'1','PYTHONPATH':str(ROOT)+':'+str(ROOT/'tests')}
def run(label,argv):
 start=time.monotonic()
 with (OUT/(label+'.log')).open('wb') as stream:r=subprocess.run(argv,cwd=ROOT,env=env,stdout=stream,stderr=subprocess.STDOUT,timeout=60)
 checks.append({'label':label,'argv':list(map(str,argv)),'returncode':r.returncode,'seconds':time.monotonic()-start})
 print(label,r.returncode,flush=True)
 assert r.returncode==0,label
for version in ('312','314'):
 python=BASE/f'2026-10-24/python-live-metrics/env-{version}/bin/python'
 cov=OUT/('coverage-'+version)
 run('python'+version,[str(python),'-m','coverage','run','--data-file='+str(cov),'--source=otelc.health,ci.rust_sonar','-m','unittest','test_health.HealthShapeTests','test_rust_drop_health','test_rust_sonar','-v'])
 run('coverage'+version,[str(python),'-m','coverage','report','--data-file='+str(cov),'--show-missing','--fail-under=80'])
node='/opt/homebrew/Cellar/node@24/24.21.0_2/bin/node'
run('markdown',[node,str(BASE/'work/oteleq-native-generated/ci/markdownlint/node_modules/markdownlint-cli/markdownlint.js'),'README.md','docs/rust-drop-bridge.md','docs/rust-drop-engine.md'])
run('rustfmt',['/Users/sclarke/.rustup/toolchains/1.98.1-aarch64-apple-darwin/bin/rustfmt','--edition','2024','--check','native/rust/bridge/src/lib.rs'])
run('diff-check',['git','diff','HEAD^','--check'])
prior=json.loads((BASE/'2026-10-25/sdk-native-errno-quality-49d4b66-review/review.json').read_text())
for i,row in enumerate(prior['checks']):
 argv=[str(a).replace('/Users/sclarke/github/otelc-qualification/work/native-errno-quality',str(ROOT)) for a in row['argv']]
 run('syntax-'+str(i),argv)
preserved()
result={'head':manifest['head'],'base':manifest['base'],'status':'clear for bounded source, health and analysis review','findings':[],
 'checks':checks,'source_files_preserved':len(manifest['source_facts']),'uid_gid_nlink_preserved':True,'archive_sha256':manifest['archive_sha256'],
 'sdk_builds':0,'compiler_builds':0,'compiler_syntax_invocations':5,'application_launches':0,
 'scope':'Private Rust drop ABI/bridge, explicit native plan3 and health5, bounded health/analysis regressions, strict C++ syntax and Rust parser/format checks',
 'limits':['No automatic MIR insertion or public Rust lifetime admission','No new SDK/Rust application execution or coverage; all genuine runtime, original eight plus private four launches, required CI and component floors remain required','No local full gate below the storage start margin']}
(OUT/'review.json').write_text(json.dumps(result,indent=2)+'\n')
print('REVIEW',digest(OUT/'review.json'),flush=True)
