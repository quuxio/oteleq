"""Independently reproduce the LLVM compiler component tests on frozen sources."""
from pathlib import Path
import hashlib,json,os,subprocess,time
r=Path(__file__).resolve().parent;s=Path('/Users/sclarke/github/oteleq-qualification/work/oteleq-go-source-workflow');index=json.loads((r/'source-index.json').read_text())
def facts():
    result={}
    for n,d in index['files'].items():
        p=s/n;i=p.stat();assert hashlib.sha256(p.read_bytes()).hexdigest()==d,n
        result[n]=(i.st_dev,i.st_ino,i.st_mode,i.st_size,i.st_mtime_ns,i.st_ctime_ns)
    return result
before=facts();env={k:v for k,v in os.environ.items() if not k.startswith(('OTEL','OTELEQ','GH_','GITHUB_','SONAR_','AWS_'))}
env.update(OTELC_GO='/Users/sclarke/go/pkg/mod/golang.org/toolchain@v0.0.1-go1.27.3.darwin-arm64/bin/go',LLVM_CONFIG='/opt/homebrew/opt/llvm@22/bin/llvm-config',OTELC_LLVM_BIN='/opt/homebrew/opt/llvm@22/bin',PYTHONPATH=str(s/'tests'),PYTHONDONTWRITEBYTECODE='1')
rows=[]
for version in ('312','314'):
    python=Path('/Users/sclarke/github/oteleq-qualification/2026-10-24/python-live-metrics')/('env-'+version)/'bin/python'
    env['COVERAGE_FILE']=str(r/(version+'.coverage'))
    argv=[str(python),'-B','-m','coverage','run','-m','unittest','-v','test_generation_go_caller','test_generation_go_source_build','test_generation_go_project']
    (r/('command-'+version+'.json')).write_text(json.dumps({'argv':argv,'cwd':str(s)},indent=2)+'\n')
    start=time.monotonic()
    with (r/(version+'.log')).open('xb') as out:result=subprocess.run(argv,cwd=s,env=env,stdout=out,stderr=subprocess.STDOUT)
    held=facts()==before
    row={'head':index['head'],'python':version,'exit_code':result.returncode,'seconds':round(time.monotonic()-start,3),'source_files_bytes_and_facts_held':len(before) if held else 0}
    rows.append(row);(r/'results.json').write_text(json.dumps(rows,indent=2)+'\n');print(json.dumps(row),flush=True)
    if result.returncode or not held:raise SystemExit(1)
