from pathlib import Path
import hashlib,json,os,subprocess,time
root=Path(__file__).resolve().parent
index=json.loads((root/'source.json').read_text())
source=Path(index['source'])
assert all(hashlib.sha256((source/name).read_bytes()).hexdigest()==value for name,value in index['files'].items())
env=dict(os.environ,OTELC_CPP_ANALYSIS='1',OTELC_LLVM_BIN='/opt/homebrew/opt/llvm@22/bin',CC='/opt/homebrew/opt/llvm@22/bin/clang',CXX='/opt/homebrew/opt/llvm@22/bin/clang++',PYTHONDONTWRITEBYTECODE='1')
python='/Users/sclarke/github/oteleq-qualification/2026-10-24/python-live-metrics/env-312/bin/python'
commands=[['make','native-check','llvm-check','PYTHON='+python],[python,'-B','-m','ci.native_sonar']]
results=[]
with (root/'actual-analysis.log').open('xb') as output:
 for argv in commands:
  started=time.monotonic()
  result=subprocess.run(argv,cwd=source,env=env,stdout=output,stderr=subprocess.STDOUT)
  results.append({'argv':argv,'exit_code':result.returncode,'seconds':round(time.monotonic()-started,3)})
  if result.returncode:break
changed=[name for name,value in index['files'].items() if hashlib.sha256((source/name).read_bytes()).hexdigest()!=value]
receipt={'head':index['head'],'commands':results,'source_files':len(index['files']),'source_preserved':not changed,'changed':changed,'scope':'Actual local compiler contexts and generic coverage only; hosted scanner and native application integration remain separate.'}
(root/'actual-analysis-result.json').write_text(json.dumps(receipt,indent=2)+'\n')
print(json.dumps(receipt))
raise SystemExit(0 if len(results)==2 and not changed and all(row['exit_code']==0 for row in results) else 1)
