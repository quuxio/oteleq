"""Bounded SDK benchmark integration review without compiler or Go workloads."""
import hashlib,json,os,subprocess,time
from pathlib import Path
BASE=Path('/Users/sclarke/github/otelc-qualification/2026-10-25/go-benchmark-delivery')
OUT=Path('/Users/sclarke/github/oteleq-qualification/2026-10-25/sdk-go-benchmark-5dd0d24-review')
PYTHON='/Users/sclarke/github/oteleq-qualification/2026-10-24/python-live-metrics/env-312/bin/python'
old=json.loads((BASE/'source-89026d6.json').read_text())
new=json.loads((BASE/'source-public-update.json').read_text())
OUT.mkdir()
(OUT/'controller.py').write_bytes(Path(__file__).read_bytes())
def digest(p): return hashlib.sha256(p.read_bytes()).hexdigest()
def git(root,*args): return subprocess.check_output(['git',*args],cwd=root)
def preserve(m):
 root=Path(m['source'])
 assert git(root,'rev-parse','HEAD').decode().strip()==m['head']
 assert not git(root,'status','--porcelain').strip()
 for name,facts in m['original_facts'].items():
  p=root/name;s=p.lstat()
  assert [digest(p),s.st_dev,s.st_ino,s.st_mode,s.st_size,s.st_mtime_ns,s.st_ctime_ns]==facts,name
 assert digest(Path(m['archive']))==m['archive_sha256']
for m in (old,new): preserve(m)
root=Path(new['source'])
changed=git(root,'diff','--name-only',old['head'],new['head']).decode().splitlines()
assert changed==['tests/test_sonar_go_scopes.py']
reuse=json.loads((BASE/'reuse.json').read_text())
for name,sha in reuse['reused_files'].items():
 raw=git(root,'show',reuse['source_head']+':'+name)
 assert hashlib.sha256(raw).hexdigest()==sha
 if name.startswith('tests/'): assert raw==(root/name).read_bytes()
make=(root/'Makefile').read_text()
assert "--include='*/otelc/go_benchmark.py' --fail-under=80" in make
assert 'test_go_benchmark test_go_benchmark_failures' in make
for m in (old,new):
 dashboard=json.loads((Path(m['source'])/'deploy/grafana/dashboards/comparison.json').read_text())
 parent=json.loads(git(root,'show',old['base']+':deploy/grafana/dashboards/comparison.json'))
 assert len(dashboard['panels'])==len(parent['panels'])
 assert [p.get('targets') for p in dashboard['panels']]==[p.get('targets') for p in parent['panels']]
argv=[PYTHON,'-m','coverage','run','--data-file='+str(OUT/'bounded.coverage'),'--source=otelc.go_benchmark','-m','unittest','test_go_benchmark_failures','test_cli','test_go_boundaries','test_sonar_go_scopes','-v']
env={**os.environ,'PYTHONDONTWRITEBYTECODE':'1','PYTHONPATH':str(root/'tests')}
start=time.monotonic()
with (OUT/'bounded.log').open('wb') as f:
 result=subprocess.run(argv,cwd=root,env=env,stdout=f,stderr=subprocess.STDOUT)
assert result.returncode==0
seconds=time.monotonic()-start
subprocess.run([PYTHON,'-m','coverage','json','--data-file='+str(OUT/'bounded.coverage'),'-o',str(OUT/'coverage.json')],cwd=root,env=env,check=True,stdout=subprocess.DEVNULL)
for m in (old,new): preserve(m)
result={'status':'clear','head':new['head'],'original_head':old['head'],'base':old['base'],'changed_integration_paths':12,'findings':[],
 'scope':'Reused-source identities, new boundary/error-routing corrections, CLI/Make/Sonar integration, documentation and unchanged dashboard query objects.',
 'original_source_files_preserved':len(old['files']),'corrected_source_files_preserved':len(new['files']),'archives_preserved':[old['archive_sha256'],new['archive_sha256']],
 'reused_actual_benchmark_tests':'Byte-identical to held2481cfe; not executed in this review.',
 'bounded_methods':16,'seconds':seconds,'compiler_builds':0,'sdk_builds':0,'go_application_launches':0,
 'limits':'Not actual five-mode timing/OTLP, complete per-module coverage, live Grafana visual acceptance or final-head required CI. Maintained80percent benchmark floor remains required.'}
(OUT/'review.json').write_text(json.dumps(result,indent=2)+'\n')
print(json.dumps(result)); print('sha256',digest(OUT/'review.json'))
