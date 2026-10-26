from datetime import datetime, timezone
import hashlib,json,os,subprocess,time
from pathlib import Path
root=Path(__file__).resolve().parent
index=json.loads((root/'source.json').read_text())
source=root/'source'
python=Path('/Users/sclarke/github/oteleq-qualification/2026-10-24/python-live-metrics/env-314/bin/python')
go=Path('/Users/sclarke/go/pkg/mod/golang.org/toolchain@v0.0.1-go1.27.3.darwin-arm64/bin/go')
def snapshot():
 return {name:hashlib.sha256((source/name).read_bytes()).hexdigest() for name in index['files']}
before=snapshot()
assert before==index['files']
start=time.monotonic()
env=dict(os.environ,PYTHONDONTWRITEBYTECODE='1',OTELC_PYTHON=str(python),OTELC_GO=str(go),PATH=str(go.parent)+os.pathsep+os.environ['PATH'])
argv=[str(python),'-B','-m','unittest','discover','-s','tests','-p','test_go_build_tags.py','-v']
(root/'unit-314-command.json').write_text(json.dumps(argv,indent=2)+'\n')
with (root/'unit-314.log').open('xb') as log:
 result=subprocess.run(argv,cwd=source,env=env,stdout=log,stderr=subprocess.STDOUT)
receipt={'head':index['head'],'exit_code':result.returncode,'seconds':round(time.monotonic()-start,3),'tracked_source_preserved':snapshot()==before,'tracked_files':len(before),'log_sha256':hashlib.sha256((root/'unit-314.log').read_bytes()).hexdigest(),'at':datetime.now(timezone.utc).isoformat()}
(root/'unit-314-result.json').write_text(json.dumps(receipt,indent=2)+'\n')
print(json.dumps(receipt,indent=2))
raise SystemExit(result.returncode or int(not receipt['tracked_source_preserved']))
