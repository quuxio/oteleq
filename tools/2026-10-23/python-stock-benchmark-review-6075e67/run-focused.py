"""Independent exact-snapshot code/input/public-OTLP review on two interpreters."""
import datetime,hashlib,json,os,re,subprocess
from pathlib import Path
root=Path(__file__).parent;source=root/'source-6075e67'
interpreters={
 '312':'/Users/sclarke/github/oteleq-qualification/2026-10-23/python-cli-review-b6dbebb/validation-env-312/bin/python',
 '314':'/Users/sclarke/github/oteleq-qualification/2026-10-23/python-http-review-87ab378/validation-env/bin/python'}
tests=['test_python_benchmark','test_python_stock_benchmark']
expected=dict(re.findall(r'^([A-Za-z0-9_-]+)==([^\s\\]+)',(source/'requirements.txt').read_text(),re.M))
normalize=lambda name:name.lower().replace('_','-')
expected={normalize(k):v for k,v in expected.items()}
record={'commit':'6075e6787047ddec0c35e0d62b33246c033ce852','started_at':datetime.datetime.now(datetime.UTC).isoformat(),'test_selectors':tests,'interpreters':{}}
for label,python in interpreters.items():
 version=subprocess.check_output([python,'--version'],text=True).strip()
 actual=json.loads(subprocess.check_output([python,'-c','import importlib.metadata,json;print(json.dumps({d.metadata["Name"].lower().replace("_","-"):d.version for d in importlib.metadata.distributions()}))'],text=True))
 assert all(actual.get(k)==v for k,v in expected.items()),label
 environment=dict(os.environ,PYTHONPATH=str(source/'tests'),PYTHONDONTWRITEBYTECODE='1',CC='/opt/homebrew/opt/llvm@22/bin/clang')
 with (root/('tests-'+label+'.log')).open('w') as output:
  result=subprocess.run([python,'-m','unittest',*tests,'-v'],cwd=source,env=environment,stdout=output,stderr=subprocess.STDOUT)
 record['interpreters'][label]={'version':version,'runtime_pins_matched':len(expected),'exit_code':result.returncode}
 (root/'tests.json').write_text(json.dumps(record,indent=2)+'\n')
seal=json.loads((root/'source-6075e67.json').read_text())
assert all(hashlib.sha256((source/name).read_bytes()).hexdigest()==sha for name,sha in seal['files'].items())
record.update(source_files_preserved=len(seal['files']),finished_at=datetime.datetime.now(datetime.UTC).isoformat())
(root/'tests.json').write_text(json.dumps(record,indent=2)+'\n');print(json.dumps(record))
raise SystemExit(any(v['exit_code'] for v in record['interpreters'].values()))
