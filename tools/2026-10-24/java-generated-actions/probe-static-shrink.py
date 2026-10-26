"""A same-return global mutation must survive generated Java scalar shrinking."""
import hashlib
import json
import os
from pathlib import Path
import sys

REPO = Path('/Users/sclarke/github/oteleq-qualification/work/oteleq-java-generated-actions')
SDK = Path('/Users/sclarke/github/oteleq-qualification/2026-10-23/java-handle-runtime-review-6fb166c/source-6fb166c')
CLI = Path('/Users/sclarke/github/oteleq-qualification/2026-10-23/python-call-sequences/target-runtime-4593e82/debug/quux-oteleq')
ROOT = Path(sys.argv[1]).resolve();ROOT.mkdir()
sys.path.insert(0, str(REPO / 'tests'))
from qualify_generation import command

os.environ.update(OTELEQ_PYTHON=sys.executable, OTELC_JAVA='/opt/homebrew/opt/openjdk@21/bin/java',
    OTELC_JAVAC='/opt/homebrew/opt/openjdk@21/bin/javac', PYTHONDONTWRITEBYTECODE='1',
    JAVA_HOME='/opt/homebrew/opt/openjdk@21')
os.environ['PATH'] = '/opt/homebrew/opt/openjdk@21/bin:' + os.environ['PATH']
source = ROOT / 'application';source.mkdir()
text = '''class Work {
static int total=10;
private static int target(int amount){
boolean on=java.lang.management.ManagementFactory.getRuntimeMXBean().getInputArguments().stream().anyMatch(v->v.contains("opentelemetry-javaagent-2.32.0.jar"));
total+=amount+(on?1:0);return 7;
}
}'''
(source / 'Work.java').write_text(text)
config = ROOT / 'equivalence.toml'
config.write_text('''schema_version=1
languages=["java"]
[adapters.java]
backend="prepared"
profile="safe-methods-v1"
witness_profile="java-sync-private-handle-v1"
[functions]
include=["Work.target(int)"]
[limits]
case_timeout_ms=60000
[[fixtures]]
function="Work.target(int)"
cases=[[7]]
domains=[{kind="integer",minimum=0,maximum=7}]
''')
workspace = Path(command([CLI, 'plan', '--source', source, '--otelc-root', SDK,
    '--workspace-parent', ROOT, '--config', config], ROOT, 'plan'))
command([CLI, 'generate', '--workspace', workspace], ROOT, 'generate')
reports = []

def integer(value):
    return {'kind': 'integer', 'type': 'java.lang.Integer', 'value': str(value), 'bits': 32, 'signed': True}

def report(path):
    value = json.loads(path.read_bytes())
    assert value['source_preserved'] and not value['blocked'] and len(value['cases']) == 1
    case = value['cases'][0];assert case['exit_code'] == 1, case
    amount, = case['arguments'];assert 0 <= amount <= 7
    bundle = json.loads((path.parent / case['case'] / 'typed-bundle.json').read_bytes())['cases'][0]
    for lane in ('baseline', 'instrumented_on'):
        assert len(bundle[lane]) == 2
        for index, row in enumerate(bundle[lane]):
            expected = 10 + amount + (lane == 'instrumented_on')
            before = {'roots': {'global:Work.total': integer(10)}, 'nodes': []}
            after = {'roots': {'global:Work.total': integer(expected)}, 'nodes': []}
            outcome = {'kind': 'return', 'graph': {'roots': {**after['roots'], 'result': integer(7)}, 'nodes': []}}
            observed = row['observation']
            assert observed['gaps'] == [] and observed['before'] == before and observed['after'] == after and observed['outcome'] == outcome, observed
            attempt = path.parent / case['case'] / (lane + '-' + str(index))
            assert (attempt / 'stdout').read_bytes() == (attempt / 'stderr').read_bytes() == b''
            host = json.loads((attempt / 'java-actions/record.json').read_bytes())
            assert len(host['harness']) == 2
            if lane == 'instrumented_on':
                witness = row['execution']['witness']
                assert witness['functions'] == {'Work.target(int)': 1, 'otelc.action.wrapper': 1, 'otelc.action.target': 1}
                assert witness['spans'] == 3 and witness['pending'] == 0 and not any(witness['losses'].values())
    reports.append(str(path))

destination = ROOT / 'run'
command([CLI, 'run', '--workspace', workspace, '--report-dir', destination], ROOT, 'run', expected=1)
report(destination / 'report.json')
print('same-return global difference caught', flush=True)
case, = json.loads((workspace / 'tests/corpus.json').read_bytes())
reduced = ROOT / 'shrink'
command([CLI, 'shrink', '--workspace', workspace, '--case', case['id'], '--report-dir', reduced,
         '--trials', '1'], ROOT, 'shrink', expected=1)
shrink = json.loads((reduced / 'shrink.json').read_bytes())
assert shrink['reduced_arguments'] == [0] and shrink['status'] == 'candidate_rule_minimal'
for path in [reduced / 'original/report.json', reduced / 'confirmation/report.json',
             *[Path(row['report']) for row in shrink['trials']]]:
    report(path)
retained = Path(shrink['workspace'])
output = command([sys.executable, retained / 'tests/test_equivalence.py'], ROOT, 'reduced-framework', expected=1)
for row in output.splitlines():report(Path(json.loads(row)['report']))
replay = json.loads(command([CLI, 'replay', '--workspace', retained, '--case', case['id']], ROOT, 'reduced-replay', expected=1))
report(Path(replay['report']))
assert (source / 'Work.java').read_text() == text
proof = {'kind': 'development_generated_java_action_shrinking', 'reports': reports,
    'scope': 'Real private static source target; identical returns, distinct globals; scalar reduction and sealed reduced framework/replay',
    'reduced_arguments': [0], 'source_preserved': True, 'cli_sha256': hashlib.sha256(CLI.read_bytes()).hexdigest()}
(ROOT / 'proof.json').write_text(json.dumps(proof, indent=2) + '\n')
print(json.dumps({'reports': len(reports), 'status': 'passed'}))
