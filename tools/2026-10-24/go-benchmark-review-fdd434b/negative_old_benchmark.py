"""Run the unchanged new four-sample assertion against the old benchmark driver."""
import hashlib,io,json,os,sys,time,unittest
from pathlib import Path
b=Path(__file__).resolve().parent
sys.path[:0]=[str(b/'source'),str(b/'fixed-source-b95780c/tests')]
from test_go_benchmark import GoBenchmarkTests
import test_go_benchmark
# The selected old driver requires its own unchanged example path. Rebind only
# the test fixture root; all independent workload/metric expectations stay fixed.
test_go_benchmark.ROOT=b/'source'
stream=io.StringIO();start=time.monotonic()
r=unittest.TextTestRunner(stream=stream,verbosity=2).run(unittest.TestSuite([GoBenchmarkTests('test_five_modes_have_real_embedded_sdk_costs_and_decoded_metrics')]))
raw=stream.getvalue();(b/'negative-old-benchmark.log').write_text(raw)
index=json.loads((b/'source-index.json').read_text());changed=[n for n,h in index['files'].items() if hashlib.sha256((b/'source'/n).read_bytes()).hexdigest()!=h]
result={'executed_driver':index['head'],'regression_from':'b95780caf370e75afdfd83bd950260212d4ea690','seconds':round(time.monotonic()-start,3),'tests':r.testsRun,'failures':len(r.failures),'errors':len(r.errors),'expected_metric_failure':'70 != 80' in raw,'source_files_held':not changed,'changed':changed,'scope':'Real plain/instrumented benchmark component pair; no performance claim'}
(b/'negative-old-benchmark-result.json').write_text(json.dumps(result,indent=2)+'\n');print(json.dumps(result))
assert r.testsRun==1 and len(r.failures)==1 and not r.errors and result['expected_metric_failure'] and not changed
