"""Review fixed Go benchmarks with actual owned-process CPU/RSS observation."""
import datetime,hashlib,json,os,subprocess,time
from pathlib import Path
b=Path(__file__).resolve().parent;s=b/'fixed-source-b95780c';i=json.loads((b/'fixed-source-b95780c-index.json').read_text());cache=Path('/Users/sclarke/github/oteleq-qualification/2026-10-24/go-source-review-67b1b0d/source/build')
for runtime in ('312','314'):
 a=[str(Path('/Users/sclarke/github/oteleq-qualification/2026-10-24/python-live-metrics')/('env-'+runtime)/'bin/python'),'-B','-m','coverage','run','--source=otelc.go_benchmark','-m','unittest','-v','test_go_benchmark','test_go_supervisor','test_cli']
 e={k:v for k,v in os.environ.items() if not k.startswith(('OTEL','GH_','GITHUB_','SONAR_','AWS_'))};e.update(PATH='/Users/sclarke/go/pkg/mod/golang.org/toolchain@v0.0.1-go1.27.3.darwin-arm64/bin:/opt/homebrew/bin:/usr/bin:/bin:/usr/sbin:/sbin',PYTHONPATH=str(s)+':'+str(s/'tests'),PYTHONDONTWRITEBYTECODE='1',COVERAGE_FILE=str(b/('fixed-focused-'+runtime+'.coverage')),GOCACHE=str(cache/'go-build-cache'),GOMODCACHE=str(cache/'go-module-cache'))
 (b/('fixed-focused-'+runtime+'-command.json')).write_text(json.dumps({'argv':a,'cwd':str(s),'head':i['head'],'started':datetime.datetime.now(datetime.timezone.utc).isoformat(),'process_sampling':'ps for actual owned application and supervisor CPU/RSS'},indent=2)+'\n');t=time.monotonic()
 with (b/('fixed-focused-'+runtime+'.log')).open('xb') as log:r=subprocess.run(a,cwd=s,env=e,stdout=log,stderr=subprocess.STDOUT)
 changed=[n for n,h in i['files'].items() if hashlib.sha256((s/n).read_bytes()).hexdigest()!=h]
 result={'head':i['head'],'exit_code':r.returncode,'seconds':round(time.monotonic()-t,3),'source_files':len(i['files']),'source_held':not changed,'changed':changed}
 (b/('fixed-focused-'+runtime+'-result.json')).write_text(json.dumps(result,indent=2)+'\n');print(json.dumps({'python':runtime,**result}),flush=True)
 if r.returncode or changed:raise SystemExit(r.returncode or 1)
