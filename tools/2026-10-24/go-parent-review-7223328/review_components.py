"""Check the producer's parent-only namespace correction on a frozen source."""
from pathlib import Path
import hashlib,json,os,subprocess,time
r=Path(__file__).resolve().parent;s=r/'source';index=json.loads((r/'source-index.json').read_text())
def facts():
    result={}
    for name,digest in index['files'].items():
        path=s/name;info=path.stat();assert hashlib.sha256(path.read_bytes()).hexdigest()==digest,name
        result[name]=(info.st_dev,info.st_ino,info.st_mode,info.st_size,info.st_mtime_ns,info.st_ctime_ns)
    return result
before=facts();go=Path('/Users/sclarke/go/pkg/mod/golang.org/toolchain@v0.0.1-go1.27.3.darwin-arm64/bin/go')
env={k:v for k,v in os.environ.items() if not k.startswith(('OTEL','OTELEQ','GH_','GITHUB_','SONAR_','AWS_'))}
env.update(PATH=str(go.parent)+os.pathsep+env.get('PATH',''),OTELC_GO=str(go),GOPATH=str(r/'go-path'),GOMODCACHE='/Users/sclarke/github/oteleq-qualification/2026-10-24/go-source-review-67b1b0d/source/build/go-module-cache',GOCACHE='/Users/sclarke/github/oteleq-qualification/2026-10-24/go-http-review-b58d798/go-cache',PYTHONPATH=str(s/'tests'),PYTHONDONTWRITEBYTECODE='1')
tests=['test_prepared_go.PreparedGoTests.test_execution_reader_accepts_parent_one_without_allowing_child_one_or_coercion','test_prepared_go.PreparedGoTests.test_execution_reader_refuses_changed_actual_owners_sdk_counts_and_exit']
results=[]
for version in ['312','314']:
    python=Path('/Users/sclarke/github/oteleq-qualification/2026-10-24/python-live-metrics')/('env-'+version)/'bin/python'
    argv=[str(python),'-B','-m','unittest','-v',*tests]
    (r/('command-'+version+'.json')).write_text(json.dumps({'argv':argv,'cwd':str(s),'selected_go':str(go)},indent=2)+'\n')
    start=time.monotonic()
    with (r/(version+'.log')).open('xb') as output:result=subprocess.run(argv,cwd=s,env=env,stdout=output,stderr=subprocess.STDOUT)
    held=facts()==before
    row={'head':index['head'],'python':version,'tests':2,'exit_code':result.returncode,'seconds':round(time.monotonic()-start,3),'source_files_bytes_and_facts_held':len(before) if held else 0}
    results.append(row);(r/'results.json').write_text(json.dumps(results,indent=2)+'\n');print(json.dumps(row),flush=True)
    if result.returncode or not held:raise SystemExit(1)
