"""Finish only unexecuted routes after the development script's path error."""
import ast
import hashlib
import json
import os
from pathlib import Path
import sys

REPO = Path('/Users/sclarke/github/oteleq-qualification/work/oteleq-java-generated-actions')
ROOT = Path('/Users/sclarke/github/oteleq-qualification/2026-10-24/java-generated-actions/public-workflow-development-02')
CLI = Path('/Users/sclarke/github/oteleq-qualification/2026-10-23/python-call-sequences/target-runtime-4593e82/debug/quux-oteleq')
sys.path.insert(0, str(REPO / 'tests'))
from qualify_generation import command

# Reuse the exact independently fixed observation oracle. Do not execute the
# earlier script's setup or repeat any already-qualified application route.
original = ROOT.parent / 'probe-public-workflow.py'
tree = ast.parse(original.read_text(), str(original))
oracle = [node for node in tree.body if isinstance(node, ast.FunctionDef) and node.name == 'report']
assert len(oracle) == 1
exec(compile(ast.Module(body=oracle, type_ignores=[]), str(original), 'exec'))
reports = []
workspace = Path((ROOT / 'plan.stdout').read_text().strip())
source = ROOT / 'application'
source_sha = hashlib.sha256((source / 'Counter.java').read_bytes()).hexdigest()
os.environ.update(OTELEQ_PYTHON=sys.executable, OTELC_JAVA='/opt/homebrew/opt/openjdk@21/bin/java',
    OTELC_JAVAC='/opt/homebrew/opt/openjdk@21/bin/javac', PYTHONDONTWRITEBYTECODE='1',
    JAVA_HOME='/opt/homebrew/opt/openjdk@21')
os.environ['PATH'] = '/opt/homebrew/opt/openjdk@21/bin:' + os.environ['PATH']
report(ROOT / 'run/report.json')
for name in ('framework', 'detached'):
    for row in (ROOT / (name + '.stdout')).read_text().splitlines():
        report(Path(json.loads(row)['report']))
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
assert hashlib.sha256((source / 'Counter.java').read_bytes()).hexdigest() == source_sha
proof = {'kind': 'development_public_generated_java_actions', 'reports': reports,
    'application_launches': len(reports) * 4, 'cli_sha256': hashlib.sha256(CLI.read_bytes()).hexdigest(),
    'source_preserved': True, 'scope': 'Selected safe prepared private receiver, recursion, exception, four metric states; generated, detached, replay and promotion routes'}
(ROOT / 'proof.json').write_text(json.dumps(proof, indent=2) + '\n')
print(json.dumps({'reports': len(reports), 'status': 'passed'}))
