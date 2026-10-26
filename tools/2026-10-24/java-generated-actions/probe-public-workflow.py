"""Development public plan/generate/run/retained/replay/promotion integration."""
import hashlib
import json
import os
from pathlib import Path
import subprocess
import sys
import zipfile

REPO = Path('/Users/sclarke/github/oteleq-qualification/work/oteleq-java-generated-actions')
SDK = Path('/Users/sclarke/github/oteleq-qualification/2026-10-23/java-handle-runtime-review-6fb166c/source-6fb166c')
CLI = Path('/Users/sclarke/github/oteleq-qualification/2026-10-23/python-call-sequences/target-runtime-4593e82/debug/quux-oteleq')
ROOT = Path(sys.argv[1]).resolve();ROOT.mkdir()
PROFILE = sys.argv[2] if len(sys.argv) > 2 else 'safe-methods-v1'
assert PROFILE in ('safe-methods-v1', 'archive-methods-v1')
sys.path.insert(0, str(REPO / 'tests'))
from qualify_generation import command

os.environ.update(OTELEQ_PYTHON=sys.executable, OTELC_JAVA='/opt/homebrew/opt/openjdk@21/bin/java',
                  OTELC_JAVAC='/opt/homebrew/opt/openjdk@21/bin/javac', PYTHONDONTWRITEBYTECODE='1',
                  JAVA_HOME='/opt/homebrew/opt/openjdk@21')
os.environ['PATH'] = '/opt/homebrew/opt/openjdk@21/bin:' + os.environ['PATH']
source = ROOT / 'application';source.mkdir()
text = '''class Counter {
private int value;private static int total;private Counter self=this;
private Counter(int initial){value=initial;}
private static Counter make(int initial){return new Counter(initial);}
private Counter run(int amount){
total++;
if(amount<0)throw new IllegalStateException("negative");
value+=amount;
if(amount>0)run(amount-1);
return this;
}
}'''
jar = None
if PROFILE == 'archive-methods-v1':
    versions = {}
    for label, value in (('base', 1), ('version21', 3)):
        build = ROOT / label;build.mkdir()
        unit = build / 'Library.java'
        unit.write_text('package dep;public class Library {public static int value(){return ' + str(value) + ';}}')
        command(['/opt/homebrew/opt/openjdk@21/bin/javac', '-encoding', 'UTF-8', '-proc:none', '-d', build, unit],
                ROOT, 'compile-' + label)
        versions[label] = (build / 'dep/Library.class').read_bytes()
    jar = source / 'lib/library.jar';jar.parent.mkdir()
    with zipfile.ZipFile(jar, 'x') as archive:
        archive.writestr('META-INF/MANIFEST.MF', b'Manifest-Version: 1.0\r\nMulti-Release: true\r\n\r\n')
        archive.writestr('dep/Library.class', versions['base'])
        archive.writestr('META-INF/versions/21/dep/Library.class', versions['version21'])
        archive.writestr('resource.bin', b'unchanged\x00resource')
    jar_sha = hashlib.sha256(jar.read_bytes()).hexdigest()
    text = text.replace('total++;', 'if(dep.Library.value()!=3)throw new AssertionError("wrong archive body");\ntotal++;')
(source / 'Counter.java').write_text(text)
config = ROOT / 'equivalence.toml'
config.write_text('''schema_version=1
languages=["java"]
[adapters.java]
backend="prepared"
profile="safe-methods-v1"
witness_profile="java-sync-private-handle-v1"
[functions]
include=["Counter.run(int)"]
[limits]
case_timeout_ms=60000
[[fixtures]]
function="Counter.run(int)"
cases=[[0]]
receiver={factory="make",arguments=[10]}
sequence=[
{action="call",arguments="case",metrics={collection=true,emission=true}},
{action="call",arguments=[3],metrics={collection=false,emission=true}},
{action="call",arguments=[-1],expected_baseline={kind="error",category="exception",type="java.lang.IllegalStateException"},metrics={collection=true,emission=false}},
{action="call",arguments=[1],metrics={collection=false,emission=false}}
]
''')
configuration = config.read_text().replace('profile="safe-methods-v1"', 'profile=' + json.dumps(PROFILE))
if jar is not None:
    configuration = configuration.replace('witness_profile="java-sync-private-handle-v1"',
        'witness_profile="java-sync-private-handle-v1"\nsource_roots=["."]\nclasspath=["lib/library.jar"]')
config.write_text(configuration)
workspace = Path(command([CLI, 'plan', '--source', source, '--otelc-root', SDK, '--workspace-parent', ROOT,
                          '--config', config], ROOT, 'plan'))
plan = json.loads((workspace / 'plan.json').read_bytes())
ready = [entry for entry in plan['inventory'] if entry['status'] == 'ready']
assert len(ready) == 1 and ready[0]['otelc_function'] == 'Counter.run(int)', plan['inventory']
assert not any(entry['status'] == 'blocked' for entry in plan['inventory'])
command([CLI, 'generate', '--workspace', workspace], ROOT, 'generate')
reports = []

def report(path):
    value = json.loads(path.read_bytes())
    assert value['source_preserved'] and not value['blocked'] and len(value['cases']) == 1, value
    case = value['cases'][0];assert case['exit_code'] == 0, case
    bundle = json.loads((path.parent / case['case'] / 'typed-bundle.json').read_bytes())['cases'][0]
    for lane in ('baseline', 'instrumented_on'):
        assert len(bundle[lane]) == 2
        for index, row in enumerate(bundle[lane]):
            observed = row['observation']
            assert observed['gaps'] == [] and len(observed['steps']) == 4
            for step, before, after, total in zip(observed['steps'], (10, 10, 16, 16), (10, 16, 16, 17), (1, 5, 6, 8)):
                assert step['before']['nodes'][0]['fields']['value']['value'] == str(before)
                assert step['after']['nodes'][0]['fields']['value']['value'] == str(after)
                assert step['after']['roots']['static:Counter.total']['value'] == str(total)
            attempt = path.parent / case['case'] / (lane + '-' + str(index))
            assert (attempt / 'stdout').read_bytes() == (attempt / 'stderr').read_bytes() == b''
            host = json.loads((attempt / 'java-actions/record.json').read_bytes())
            assert host['plain'] is (lane == 'baseline') and len(host['harness']) == 5
            if lane == 'instrumented_on':
                witness = row['execution']['witness']
                assert witness['spans'] == 20 and witness['functions'] == {
                    'Counter.run(int)': 8, 'otelc.action.wrapper': 4, 'otelc.action.target': 8}
                assert witness['pending'] == 0 and not any(witness['losses'].values())
                verified = json.loads((attempt / 'verified-actions.json').read_bytes())
                assert [action['target_entries'] for action in verified['actions']] == [1, 4, 1, 2]
                assert verified['collected_method_calls'] == 2
            else:
                assert row['execution']['witness'] is None and host['controls'] == []
    reports.append(str(path))

result = ROOT / 'run'
command([CLI, 'run', '--workspace', workspace, '--report-dir', result], ROOT, 'run', timeout=900)
report(result / 'report.json')
print('public generated run passed', flush=True)
output = command([sys.executable, workspace / 'tests/test_equivalence.py'], ROOT, 'framework', timeout=900)
for row in output.splitlines():report(Path(json.loads(row)['report']))
print('generated framework passed', flush=True)
export = ROOT / 'retained'
command([CLI, 'export-tests', '--workspace', workspace, '--destination', export, '--apply'], ROOT, 'export')
output = command([sys.executable, export / 'tests/test_equivalence.py'], ROOT, 'detached', timeout=900)
for row in output.splitlines():report(Path(json.loads(row)['report']))
print('detached framework passed', flush=True)
case = json.loads((workspace / 'tests/corpus.json').read_bytes())[0]
replay = json.loads(command([CLI, 'replay', '--workspace', workspace, '--case', case['id']], ROOT, 'replay', timeout=900))
report(Path(replay['report']))
print('frozen replay passed', flush=True)
promoted = ROOT / 'promoted'
command([CLI, 'promote', '--workspace', workspace, '--source', source, '--destination', promoted, '--apply'], ROOT, 'promote')
os.environ.update(OTELEQ_SOURCE=str(source), OTELEQ_WORKSPACE_PARENT=str(ROOT))
output = command([sys.executable, '-I', '-B', promoted / 'test_equivalence.py'], ROOT, 'promoted', timeout=900)
for row in output.splitlines():
    value = json.loads(row)
    if 'report' in value:report(Path(value['report']))
print('current-source promotion passed', flush=True)
assert (source / 'Counter.java').read_text() == text
if jar is not None:assert hashlib.sha256(jar.read_bytes()).hexdigest() == jar_sha
proof = {'kind': 'development_public_generated_java_actions', 'reports': reports,
         'java_profile': PROFILE, 'multi_release_jar_checked': jar is not None,
         'cli_sha256': hashlib.sha256(CLI.read_bytes()).hexdigest(), 'source_preserved': True,
         'scope': 'Selected safe prepared private receiver, recursion, exception, four metric states, generated/detached/replay/promotion routes'}
(ROOT / 'proof.json').write_text(json.dumps(proof, indent=2) + '\n')
print(json.dumps({'reports': len(reports), 'status': 'passed'}))
