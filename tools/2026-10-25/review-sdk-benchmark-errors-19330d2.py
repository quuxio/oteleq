"""Bounded independent benchmark failure-priority review."""
import hashlib,json,os,subprocess,time
from pathlib import Path
OWNER=Path('/Users/sclarke/github/otelc-qualification/2026-10-25/benchmark-error-priority')
ROOT=Path('/Users/sclarke/github/otelc-qualification/work/benchmark-error-priority')
OUT=Path('/Users/sclarke/github/oteleq-qualification/2026-10-25/sdk-benchmark-errors-19330d2-review')
OUT.mkdir();(OUT/'controller.py').write_bytes(Path(__file__).read_bytes())
m=json.loads((OWNER/'source.json').read_text())
def digest(p):return hashlib.sha256(p.read_bytes()).hexdigest()
def git(*args):return subprocess.check_output(['git',*args],cwd=ROOT)
def preserve():
 assert git('rev-parse','HEAD').decode().strip()==m['head']
 assert not git('status','--porcelain').strip()
 for name,e in m['source_facts'].items():
  p=ROOT/name;s=p.lstat()
  assert [digest(p),s.st_dev,s.st_ino,s.st_mode,s.st_size,s.st_mtime_ns,s.st_ctime_ns]==e,name
 assert digest(Path(m['archive']))==m['archive_sha256']
preserve()
changed=git('diff','--name-only',m['base'],'HEAD').decode().splitlines();assert len(changed)==15
assert "--include='*/otelc/benchmark_cleanup.py' --fail-under=80" in (ROOT/'Makefile').read_text()
results=[]
env={**os.environ,'PYTHONPATH':str(ROOT/'tests'),'PYTHONDONTWRITEBYTECODE':'1'}
for tag in ('312','314'):
 argv=list(m['checks'][0]['command']);argv[0]='/Users/sclarke/github/oteleq-qualification/2026-10-24/python-live-metrics/env-'+tag+'/bin/python'
 argv=[('--data-file='+str(OUT/(tag+'.coverage'))) if a.startswith('--data-file=') else a for a in argv]
 start=time.monotonic()
 with (OUT/(tag+'.log')).open('wb') as f:r=subprocess.run(argv,cwd=ROOT,env=env,stdout=f,stderr=subprocess.STDOUT)
 assert r.returncode==0,tag
 results.append({'python':tag,'returncode':r.returncode,'seconds':time.monotonic()-start,'argv':argv})
 subprocess.run([argv[0],'-m','coverage','report','--data-file='+str(OUT/(tag+'.coverage')),'--include=*/otelc/benchmark_cleanup.py','--fail-under=80'],cwd=ROOT,env=env,check=True)
preserve()
result={'status':'clear','head':m['head'],'base':m['base'],'changed':changed,'findings':[],
 'scope':'Shared cleanup ordering/error precedence and all15-file adapter/CLI/test/document integration; retained input/drain checks stay mandatory.',
 'independent_checks':results,'methods_per_python':42,'source_files_preserved':len(m['source_facts']),'archive_sha256':m['archive_sha256'],
 'observed_contract':['Body error or cancellation remains primary; all later cleanup steps attempted and their stage/type notes retained.', 'With no body error the first cleanup error still fails the run.', 'Stop attempts reap and both pipes; Node/native/Python final input/drain checks still run after earlier failure.', 'Failed final validation prevents successful return/publication; CLI shows secondary notes.'],
 'sdk_builds':0,'native_compiler_builds':0,'application_workload':'Existing real stock Python subprocess controls only; no instrumented SDK workload.',
 'limits':'Not actual Java/Node/native SDK or full final-head coverage/CI, new benchmark timings, Grafana acceptance or Go common-helper integration.'}
(OUT/'review.json').write_text(json.dumps(result,indent=2)+'\n')
print(json.dumps({k:v for k,v in result.items() if k!='independent_checks'}));print('receipt_sha256',digest(OUT/'review.json'))
