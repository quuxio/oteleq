from datetime import datetime,timezone
import hashlib,json,os,subprocess,time
from pathlib import Path
root=Path(__file__).resolve().parent
index=json.loads((root/'source.json').read_text())
source=Path(index['source'])
sdk=Path('/Users/sclarke/github/oteleq-qualification/2026-10-24/go-reuse-review-d2ec6bf/source')
sdkindex=json.loads((sdk.parent/'inputs-before.json').read_text())
cli=Path('/Users/sclarke/github/oteleq-qualification/2026-10-24/go-public/target/debug/quux-oteleq')
python=Path('/Users/sclarke/github/oteleq-qualification/2026-10-24/python-live-metrics/env-312/bin/python')
go=Path('/Users/sclarke/go/pkg/mod/golang.org/toolchain@v0.0.1-go1.27.3.darwin-arm64/bin/go')
def facts(path):
 info=path.stat()
 return {'sha256':hashlib.sha256(path.read_bytes()).hexdigest(),'facts':[info.st_dev,info.st_ino,info.st_mode,info.st_uid,info.st_gid,info.st_size,info.st_mtime_ns,info.st_ctime_ns]}
def inputs():
 tools=json.loads((sdk/'build/go-upstream/toolchain.json').read_text())
 return {'source':{name:facts(source/name) for name in index['files']},'sdk':{name:facts(sdk/name) for name in sdkindex['files']},'tooling':{str(path):facts(path) for path in [sdk/'build/go-upstream/toolchain.json',*[Path(tools[name]) for name in ('go','weaver','bundle')]]},'cli':facts(cli)}
before=inputs()
assert all(before['source'][name]['sha256']==value for name,value in index['files'].items())
(root/'inputs-before.json').write_text(json.dumps(before,indent=2)+'\n')
argv=[str(python),'-B',str(source/'tests/qualify_go_receivers.py'),'--otelc-root',str(sdk),'--report-dir',str(root/'evidence'),'--cli',str(cli),'--backend','source-v1']
env=dict(os.environ,OTELEQ_PYTHON=str(python),OTELC_PYTHON=str(python),OTELC_GO=str(go),PYTHONDONTWRITEBYTECODE='1',PATH=str(go.parent)+os.pathsep+os.environ['PATH'])
started=time.monotonic()
(root/'command.json').write_text(json.dumps(argv,indent=2)+'\n')
with (root/'corpus.log').open('xb') as log:
 result=subprocess.run(argv,cwd=source,env=env,stdout=log,stderr=subprocess.STDOUT)
after=inputs()
(root/'inputs-after.json').write_text(json.dumps(after,indent=2)+'\n')
receipt={'at':datetime.now(timezone.utc).isoformat(),'head':index['head'],'exit_code':result.returncode,'seconds':round(time.monotonic()-started,3),'preservation':{name:before[name]==after[name] for name in before},'scope':'Maintained untagged Go source-v1 receiver/framework/export/shrink corpus only; other profiles and full project remain separate.'}
if result.returncode==0:
 receipt['qualification']=json.loads((root/'evidence/QUALIFICATION.json').read_text())
(root/'result.json').write_text(json.dumps(receipt,indent=2)+'\n')
print(json.dumps(receipt,indent=2))
raise SystemExit(0 if result.returncode==0 and all(receipt['preservation'].values()) else 1)
