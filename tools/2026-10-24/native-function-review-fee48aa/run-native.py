import hashlib,json,os,subprocess,time
from pathlib import Path
root=Path(__file__).resolve().parent
index=json.loads((root/'source.json').read_text())
source=Path(index['source'])
python='/Users/sclarke/github/oteleq-qualification/2026-10-24/python-live-metrics/env-312/bin/python'
env=dict(os.environ,PYTHONDONTWRITEBYTECODE='1',OTELC_LLVM_BIN='/opt/homebrew/opt/llvm@22/bin',CC='/opt/homebrew/opt/llvm@22/bin/clang',CXX='/opt/homebrew/opt/llvm@22/bin/clang++',PATH='/opt/homebrew/opt/llvm@22/bin:'+os.environ['PATH'])
before={name:hashlib.sha256((source/name).read_bytes()).hexdigest() for name in index['files']}
assert before==index['files']
argv=['make','native-check','PYTHON='+python]
(root/'native-command.json').write_text(json.dumps(argv,indent=2)+'\n')
started=time.monotonic()
with (root/'native-check.log').open('xb') as log:
 result=subprocess.run(argv,cwd=source,env=env,stdout=log,stderr=subprocess.STDOUT)
after={name:hashlib.sha256((source/name).read_bytes()).hexdigest() for name in index['files']}
receipt={'head':index['head'],'exit_code':result.returncode,'seconds':round(time.monotonic()-started,3),'source_preserved':before==after,'tracked_files':len(before),'log_sha256':hashlib.sha256((root/'native-check.log').read_bytes()).hexdigest(),'scope':'Independent native SDK engine and compiler-linked fixtures only; public bootstrap, OTLP receipt and consumer admission remain separate.'}
(root/'native-result.json').write_text(json.dumps(receipt,indent=2)+'\n')
print(json.dumps(receipt,indent=2))
raise SystemExit(result.returncode or int(before!=after))
