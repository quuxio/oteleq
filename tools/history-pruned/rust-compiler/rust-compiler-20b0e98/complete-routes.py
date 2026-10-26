import json,os,sys
from pathlib import Path
repo=Path('/Users/sclarke/github/oteleq-qualification/work/oteleq-rust-compiler')
sys.path.insert(0,str(repo/'tests'))
import qualify_rust_build as qb
from qualify_generation import command
p=Path(__file__).resolve().parent
f=p/'evidence'
cli=p/'quux-oteleq'
workspace=next(f.glob('oteleq-run-*/plan.json')).parent
os.environ.update(OTELEQ_CLI=str(cli),OTELEQ_PYTHON=sys.executable)
def inspect(report):
 d=json.loads(report.read_text());assert d['source_preserved'] and len(d['cases']) in (1,4)
 for case in d['cases']:qb.check_case(case,report.parent,'compiler',None)
 return len(d['cases'])*6
def framework(workspace,name):
 text=command([sys.executable,workspace/'tests/test_equivalence.py'],f,name,timeout=900)
 rows=[json.loads(line) for line in text.splitlines()];assert len(rows)==4
 return sum(inspect(Path(row['report'])) for row in rows)
launches=inspect(f/'comparison/report.json')
launches+=framework(workspace,'framework')
exported=f/'exported'
command([cli,'export-tests','--workspace',workspace,'--destination',exported,'--apply'],f,'export')
command([cli,'run','--workspace',exported,'--report-dir',f/'export-comparison'],f,'export-run',timeout=900)
launches+=inspect(f/'export-comparison/report.json')
launches+=framework(exported,'export-framework')
identities={qb.capture.file_digest(path) for path in f.rglob('command.json') if path.parent.name.startswith(('baseline-','instrumented_on-'))}
assert launches==96 and len(identities)==launches
record={'runtime_commit':'20b0e9856e6f7f2e0e5df66085580ca7741ab1d8','provider_commit':'50635ef0eccfe063eddf164a9e82520a78f2c6f1','cases':4,'matching_cases':4,'routes':['run','generated unittest/replay','exported run','exported unittest/replay'],'actual_application_launches':launches,'unique_command_identities':len(identities),'source_preserved':True,'scope':'standalone Rust scalar compiler schema3; no general async/module/shipping claim'}
(f/'complete-routes.json').write_text(json.dumps(record,indent=2)+'\n')
print(json.dumps(record),flush=True)
