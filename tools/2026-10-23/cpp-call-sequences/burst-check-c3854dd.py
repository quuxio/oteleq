"""Four-process actual-provider control for one complete 32-call C++ burst."""
import argparse,hashlib,json,os,sys,tomllib
from pathlib import Path
ROOT=Path(__file__).parent
SOURCE=ROOT/'source-c3854dd'
sys.path.insert(0,str(SOURCE/'tests'))
import qualify_cpp_sequences as q
parser=argparse.ArgumentParser()
parser.add_argument('--otelc-root',type=Path,required=True)
parser.add_argument('--report-dir',type=Path,required=True)
parser.add_argument('--cli',type=Path,required=True)
a=parser.parse_args();cli=a.cli.resolve(strict=True);folder=a.report_dir.resolve()
os.environ.update(OTELEQ_PYTHON=sys.executable,OTELEQ_CLI=str(cli))
workspace=q.prepare(cli,a.otelc_root.resolve(strict=True),folder,steps=32,methods=('identity',),compact=True)
q.command([cli,'run','--workspace',workspace,'--report-dir',folder/'comparison'],folder,'run')
assert q.check_report(folder/'comparison/report.json',1,steps=32,compact=True)==4
assert q.verify_receipts(folder)==2
raw=list((folder/'comparison').rglob('command.json'));assert len(raw)==4 and len({hashlib.sha256(p.read_bytes()).hexdigest() for p in raw})==4
for p in (folder/'comparison').rglob('instrumented_on-*/policy.toml'):
 assert tomllib.loads(p.read_text())['export']['max_queued_batches']==64
result={'claim':'equivalence over these tests and observations','actual_application_launches':4,'calls_per_application':32,'raw_instrumented_receipts':2,'completed_roots_per_instrumented_process':32,'decoded_spans_per_instrumented_process':32,'completed_root_queue':64,'losses':0,'scope':'one compact diagnostic receiver burst; not the full corpus or shipping artifact'}
(folder/'burst.json').write_text(json.dumps(result,indent=2)+'\n');print(json.dumps(result))
