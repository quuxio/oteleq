"""Run one immutable C++ corpus and verify provider/source/tool bytes around it."""
import datetime,hashlib,json,os,subprocess,sys
from pathlib import Path
ROOT=Path(__file__).parent
SOURCE=ROOT/'source-b40eec6';CLI=ROOT/'quux-oteleq-b40eec6'
MANIFEST=Path('/Users/sclarke/github/otelc-qualification/2026-10-20/integrated-provider/d6d03b7/manifest.json')
PROVIDER=MANIFEST.parent/'provider'
FOLDER=ROOT/'qualification-b40eec6'
def digest(path):
 with path.open('rb') as stream:return hashlib.file_digest(stream,'sha256').hexdigest()
def verify():
 manifest=json.loads(MANIFEST.read_text());counts={}
 for group in ('source_sha256','products_sha256','dependencies'):
  for name,record in manifest[group].items():
   path=PROVIDER/name
   if isinstance(record,str):assert digest(path)==record,name
   elif 'sha256' in record:assert digest(path)==record['sha256'],name
   else:assert path.is_symlink() and os.readlink(path)==record['symlink'] and str(path.resolve())==record['resolved'],name
  counts[group]=len(manifest[group])
 for key in ('clang','clang++','python'):
  tool=manifest['tools'][key];assert digest(Path(tool['resolved']))==tool['sha256'],key
 seal=json.loads((ROOT/'source-b40eec6.json').read_text())
 assert all(digest(SOURCE/name)==sha for name,sha in seal['files'].items())
 return {'provider_commit':manifest['source_commit'],'provider_counts':counts,'selected_tools':3,'provider_manifest_sha256':digest(MANIFEST),'consumer_commit':seal['commit'],'consumer_files':len(seal['files']),'cli_sha256':digest(CLI),'runner_sha256':digest(Path(__file__))}
assert not FOLDER.exists()
record={'started_at':datetime.datetime.now(datetime.UTC).isoformat(),'before':verify()}
(ROOT/'qualification-run-b40eec6.json').write_text(json.dumps(record,indent=2)+'\n')
environment=dict(os.environ,PYTHONDONTWRITEBYTECODE='1',OTELEQ_PYTHON=sys.executable,OTELEQ_CLI=str(CLI),OTELC_CLANG='/opt/homebrew/opt/llvm@22/bin/clang',OTELC_CLANGXX='/opt/homebrew/opt/llvm@22/bin/clang++')
environment.pop('OTELC_CONFIG',None)
environment['PATH']='/opt/homebrew/opt/llvm@22/bin:'+environment['PATH']
argv=[sys.executable,str(SOURCE/'tests/qualify_cpp_sequences.py'),'--cli',str(CLI),'--otelc-root',str(PROVIDER),'--report-dir',str(FOLDER)]
record['argv']=argv
with (ROOT/'qualification-run-b40eec6.log').open('w') as output:
 result=subprocess.run(argv,cwd=SOURCE,env=environment,stdout=output,stderr=subprocess.STDOUT)
record.update(exit_code=result.returncode,finished_at=datetime.datetime.now(datetime.UTC).isoformat(),after=verify())
assert record['before']==record['after']
(ROOT/'qualification-run-b40eec6.json').write_text(json.dumps(record,indent=2)+'\n')
print(json.dumps({'exit_code':result.returncode,'provider_records_preserved':sum(record['after']['provider_counts'].values()),'consumer_files_preserved':record['after']['consumer_files']}))
raise SystemExit(result.returncode)
