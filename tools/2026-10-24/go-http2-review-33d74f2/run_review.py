"""Run actual frozen HTTP2 checks and preserve all source identities."""
from pathlib import Path
import hashlib,json,os,subprocess,time
root=Path(__file__).resolve().parent
source=root/'source'
index=json.loads((root/'source-index.json').read_text())
def facts():
 result={}
 for name,digest in index['files'].items():
  p=source/name; s=p.stat()
  assert hashlib.sha256(p.read_bytes()).hexdigest()==digest
  result[name]=(s.st_dev,s.st_ino,s.st_mode,s.st_size,s.st_mtime_ns,s.st_ctime_ns)
 return result
before=facts()
env={k:v for k,v in os.environ.items() if not k.startswith(('OTEL','GH_','GITHUB_','SONAR_','AWS_'))}
go=Path('/Users/sclarke/go/pkg/mod/golang.org/toolchain@v0.0.1-go1.27.3.darwin-arm64/bin/go')
env.update(PATH=str(go.parent)+os.pathsep+env.get('PATH',''),GOPATH=str(root/'go-path'),GOMODCACHE='/Users/sclarke/github/oteleq-qualification/2026-10-24/go-source-review-67b1b0d/source/build/go-module-cache',GOCACHE='/Users/sclarke/github/oteleq-qualification/2026-10-24/go-http-review-b58d798/go-cache',PYTHONPATH=str(source/'tests'),PYTHONDONTWRITEBYTECODE='1')
results=[]
for version in ['312','314']:
 python=Path('/Users/sclarke/github/oteleq-qualification/2026-10-24/python-live-metrics')/('env-'+version)/'bin/python'
 argv=[str(python),'-B','-m','unittest','-v','test_go_http2']
 (root/('command-'+version+'.json')).write_text(json.dumps({'argv':argv,'cwd':str(source),'selected_go':str(go)},indent=2)+'\n')
 started=time.monotonic()
 with (root/(version+'.log')).open('xb') as out:
  run=subprocess.run(argv,cwd=source,env=env,stdout=out,stderr=subprocess.STDOUT)
 result={'python':version,'exit_code':run.returncode,'seconds':round(time.monotonic()-started,3),'source_files_held':len(before) if facts()==before else 0}
 results.append(result)
 (root/'test-results.json').write_text(json.dumps(results,indent=2)+'\n')
 print(json.dumps(result),flush=True)
 if run.returncode:raise SystemExit(run.returncode)
