"""Execute one fresh compact32-call case with the final installed CLI."""
from pathlib import Path
import datetime,hashlib,json,os,runpy,sys
ROOT=Path(__file__).parent;SOURCE=ROOT/'source-6ba15b2'
sys.path[:0]=[str(SOURCE/'tests')]
import qualify_python_sequences as q
from qualify_project_tests import command
CLI=ROOT/'installed-6ba15b2/bin/quux-oteleq'
PROVIDER=Path('/Users/sclarke/github/otelc-qualification/2026-10-20/integrated-provider/d6d03b7/provider')
folder=ROOT/'installed-smoke-6ba15b2'
record_path=ROOT/'installed-smoke-6ba15b2.json';assert not record_path.exists() and not folder.exists()
verify=runpy.run_path(str(ROOT/'run-corpus-18f70b9.py'))['verify']
record={'commit':'6ba15b27a5ccc3d678fd6d87c072c0e2cc6e86f9','cli_sha256':hashlib.sha256(CLI.read_bytes()).hexdigest(),'started_at':datetime.datetime.now(datetime.UTC).isoformat(),'before':verify()}
record_path.write_text(json.dumps(record,indent=2)+'\n')
os.environ.update(PYTHONDONTWRITEBYTECODE='1',OTELEQ_PYTHON=sys.executable,OTELEQ_CLI=str(CLI));os.environ.pop('OTELC_CONFIG',None)
workspace=q.prepare(CLI,PROVIDER,folder,steps=32,methods=('identity',),compact=True)
command([CLI,'run','--workspace',workspace,'--report-dir',folder/'comparison'],folder,'run',0)
observations=q.check_report(folder/'comparison/report.json',1,steps=32,compact=True)
receipts=q.verify_receipts(folder)
assert observations==4 and receipts==2
record.update(exit_code=0,actual_application_launches=4,calls_per_application=32,complete_raw_and_typed_observations=observations,raw_instrumented_receipts=receipts,after=verify(),finished_at=datetime.datetime.now(datetime.UTC).isoformat())
assert record['before']==record['after']
seal=json.loads((ROOT/'source-6ba15b2.json').read_text());assert all(hashlib.sha256((SOURCE/name).read_bytes()).hexdigest()==value for name,value in seal['files'].items())
record['publication_source_files_preserved']=len(seal['files'])
record_path.write_text(json.dumps(record,indent=2)+'\n');print(json.dumps(record))
