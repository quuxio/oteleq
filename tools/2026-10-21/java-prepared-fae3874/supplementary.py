"""Actual packaged-recursion and legacy compatibility checks for one frozen CLI."""
from pathlib import Path
import hashlib
import json
import shutil
import sys

sys.path.insert(0, str(Path(sys.argv[1]) / 'tests'))
from qualify_generation import command
from qualify_java_receivers import prepare, check_report

root = Path(__file__).resolve().parent
cli = root / 'quux-oteleq'
provider, legacy = map(lambda text: Path(text).resolve(strict=True), sys.argv[2:4])
folder = root / 'packaged-recursive'
folder.mkdir()
source = folder / 'application'
(source / 'sample').mkdir(parents=True)
(source / 'sample/App.java').write_text('''package sample;
public class App {
 static int total=0;
 public static int selected(int value){
  if(value>0){selected(0);try{Thread.sleep(2500);}catch(InterruptedException error){throw new RuntimeException(error);}}
  total+=value;System.out.println("out"+value);System.err.println("err"+value);return value+4;
 }
}
''')
config = folder / 'equivalence.toml'
config.write_text('''schema_version=1
languages=["java"]
[adapters.java]
backend="prepared"
[functions]
include=["sample.App.selected(int)"]
[[fixtures]]
function="sample.App.selected(int)"
cases=[[3]]
expected_baseline={kind="return_value",value={kind="integer",type="java.lang.Integer",value="7",bits=32,signed=true}}
''')
workspace = Path(command([cli, 'plan', '--source', source, '--otelc-root', provider,
                          '--workspace-parent', folder, '--config', config], folder, 'plan'))
command([cli, 'generate', '--workspace', workspace], folder, 'generate')
command([cli, 'run', '--workspace', workspace, '--report-dir', folder / 'comparison'], folder, 'run')
report = json.loads((folder / 'comparison/report.json').read_text())
assert len(report['cases']) == 1 and not report['blocked'] and report['source_preserved']
case = report['cases'][0]
assert case['exit_code'] == 0
attempts = folder / 'comparison' / case['case']
bundle = json.loads((attempts / 'typed-bundle.json').read_text())['cases'][0]
def integer(number):
    return dict(kind='integer', type='java.lang.Integer', value=str(number), bits=32, signed=True)
for lane in ('baseline', 'instrumented_on'):
    assert len(bundle[lane]) == 2
    for index, attempt in enumerate(bundle[lane]):
        observed = attempt['observation']
        assert observed['function_id'] == 'sample.App.selected(int)' and not observed['gaps']
        assert observed['before'] == dict(nodes=[], roots={'global:App.total': integer(0)})
        assert observed['after'] == dict(nodes=[], roots={'global:App.total': integer(3)})
        assert observed['outcome'] == dict(kind='return', graph=dict(nodes=[], roots={'global:App.total': integer(3), 'result': integer(7)}))
        raw = attempts / (lane + '-' + str(index))
        assert (raw / 'stdout').read_bytes() == b'out0\nout3\n'
        assert (raw / 'stderr').read_bytes() == b'err0\nerr3\n'
        archive = json.loads((raw / 'runtime-archive.json').read_text())
        assert not Path(archive['original']).exists()
        for name, identity in archive['files'].items():
            assert hashlib.sha256((raw / 'sdk-runtime' / name).read_bytes()).hexdigest() == identity['sha256']
        if lane == 'instrumented_on':
            assert attempt['execution']['witness']['functions'] == {'sample.App.selected(int)': 2}
            health = json.loads((raw / 'sdk-runtime/health.json').read_text())
            assert health['trace_exports']['units_succeeded'] == '2'
            assert health['trace_exports']['units_failed'] == health['metric_exports']['units_failed'] == '0'
result = dict(actual_launches=4, case='packaged recursive method', full_literal_observations_checked=True,
              exact_stdout_stderr_checked=True, spans_per_instrumented_repeat=2, source_preserved=True,
              cli_sha256=hashlib.sha256(cli.read_bytes()).hexdigest())
(folder / 'qualification.json').write_text(json.dumps(result, indent=2) + '\n')
folder = root / 'legacy-compatibility'
folder.mkdir()
workspace = prepare(cli, legacy, folder / 'cases', methods=('identity', 'static_only'))
command([cli, 'run', '--workspace', workspace, '--report-dir', folder / 'comparison'], folder, 'run', expected=1)
launches, report = check_report(folder / 'comparison/report.json', 2)
assert launches == 8
result = dict(actual_launches=8, cases=2, matching_cases=1, same_return_state_differences=1,
              source_preserved=report['source_preserved'], provider_commit='d6d03b72026cde8962b11ce3cc184ff3ebcb60d4')
(folder / 'qualification.json').write_text(json.dumps(result, indent=2) + '\n')
print('Twelve supplementary actual JVM launches passed their independent oracles')
