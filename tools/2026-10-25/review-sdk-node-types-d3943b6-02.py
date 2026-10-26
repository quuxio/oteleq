"""Check the narrow Node declaration correction in a byte-bound transient copy."""
import base64,hashlib,json,os,shutil,subprocess,time
from pathlib import Path
ROOT=Path('/Users/sclarke/github/otelc-qualification/work/node26-types-integration')
TOOLS=Path('/Users/sclarke/github/otelc-qualification/2026-10-24/native-function-runtime/full-2481cfe-permitted-retry/source/node_modules')
OWNER=Path('/Users/sclarke/github/otelc-qualification/2026-10-25/node26-type-compatibility')
OUT=Path('/Users/sclarke/github/oteleq-qualification/2026-10-25/sdk-node-types-d3943b6-review-02')
OUT.mkdir(); (OUT/'controller.py').write_bytes(Path(__file__).read_bytes())
m=json.loads((OWNER/'source.json').read_text())
def git(*args):return subprocess.check_output(['git',*args],cwd=ROOT)
def digest(p):return hashlib.sha256(p.read_bytes()).hexdigest()
def preserve():
 assert git('rev-parse','HEAD').decode().strip()==m['head']
 assert not git('status','--porcelain').strip()
 for name,e in m['source_facts'].items():
  p=ROOT/name;s=p.lstat()
  assert [digest(p),s.st_dev,s.st_ino,s.st_mode,s.st_size,s.st_mtime_ns,s.st_ctime_ns]==e,name
 assert digest(Path(m['archive']))==m['archive_sha256']
preserve()
changed=git('diff','--name-only',m['base'],'HEAD').decode().splitlines()
assert len(changed)==5,changed
package=json.loads((ROOT/'package.json').read_text())
lock=json.loads((ROOT/'package-lock.json').read_text())
held={}
for name,version in package['dependencies'].items():
 p=TOOLS/name/'package.json'; found=json.loads(p.read_text())
 actual=version.removeprefix('npm:typescript@') if name=='typescript-api' else version
 assert found['version']==actual,(name,version,found['version'])
 held[str(p)]=digest(p)
for name,archive in (('@types/node','types-node.tgz'),('undici-types','undici-types.tgz')):
 pin=lock['packages']['node_modules/'+name]
 assert pin['integrity']=='sha512-'+base64.b64encode(hashlib.sha512((OWNER/archive).read_bytes()).digest()).decode()
copy=OUT/'source-copy';copy.mkdir()
for name in m['source_facts']:
 p=copy/name;p.parent.mkdir(parents=True,exist_ok=True);shutil.copyfile(ROOT/name,p)
 assert digest(p)==m['source_facts'][name][0]
(copy/'node_modules').symlink_to(TOOLS,target_is_directory=True)
env={**os.environ,'NODE_PATH':str(TOOLS)}
results=[]
def execute(argv,label):
 start=time.monotonic()
 with (OUT/(label+'.log')).open('wb') as f:
  r=subprocess.run(argv,cwd=copy,env=env,stdout=f,stderr=subprocess.STDOUT)
 row={'argv':list(map(str,argv)),'returncode':r.returncode,'seconds':time.monotonic()-start,'log':str(OUT/(label+'.log'))}
 results.append(row)
 if r.returncode: raise AssertionError(row)
runtimes=[Path('/opt/homebrew/Cellar/node@24/24.21.0_2/bin/node'),Path('/opt/homebrew/bin/node')]
for i,node in enumerate(runtimes):
 for compiler in ('typescript','typescript-api'):
  for declarations in ('node24','node26'):
   argv=[str(node),str(TOOLS/compiler/'bin/tsc'),'--project','adapters/node/tsconfig.json']
   if declarations=='node26':argv+=['--typeRoots',str(OWNER/'types')]
   execute(argv,str(i)+'-'+compiler+'-'+declarations)
 execute([str(node),'--test','--experimental-test-coverage','--test-coverage-include=**/adapters/node/src/local-metric-control.ts','--test-coverage-include=**/adapters/node/src/metric-controls.ts','--test-coverage-lines=80','adapters/node/test/sdk-pipeline.test.ts','adapters/node/test/gated-metrics.test.ts','adapters/node/test/source-handoff.test.ts'],str(i)+'-sdk-controls')
for name,e in m['source_facts'].items():assert digest(copy/name)==e[0]
for path,e in held.items():assert digest(Path(path))==e
preserve()
result={'status':'clear','head':m['head'],'base':m['base'],'changed':changed,'findings':[],
 'scope':'Narrow declaration-lock update, byte/string socket narrowing, optional IPC disconnect and dual compiler SDK/test typechecks.',
 'source_files_preserved':len(m['source_facts']),'archive_sha256':m['archive_sha256'],
 'independent_checks':results,'typescript_typecheck_invocations':8,'sdk_control_test_runs':2,
 'copy':'All tracked files copied with matching SHA256; only transient copy received a readonly dependency symlink. Original source unchanged.',
 'native_sdk_builds':0,'application_qualification_launches':0,
 'limits':'Not full Node source-child coverage, native observer rebuilding, complete final-head CI or language/shipping qualification.'}
(OUT/'review.json').write_text(json.dumps(result,indent=2)+'\n')
print(json.dumps({k:v for k,v in result.items() if k!='independent_checks'}));print('receipt_sha256',digest(OUT/'review.json'))
