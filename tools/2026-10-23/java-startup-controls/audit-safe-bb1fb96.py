"""Recheck four completed safe corpora without launching an application."""
import datetime
import hashlib
import json
from pathlib import Path
import sys

root = Path(__file__).resolve().parent
source = root / 'source-bb1fb96'
sys.path.insert(0, str(source / 'tests'))
import qualify_java_startup as startup
import java_startup_receipts as receipts
from qualify_project_tests import command as recorded_command


def comparison_command(arguments, folder, name, expected=0, environment=None):
    assert len(arguments) == 3 and arguments[1] == 'compare-observations'
    assert name == 'startup-recomparison'
    key = hashlib.sha256(str(Path(arguments[-1]).resolve()).encode()).hexdigest()[:24]
    destination = root / 'safe-recomparisons-bb1fb96' / key
    destination.mkdir(mode=0o700, parents=True)
    return recorded_command(arguments, destination, name, expected, environment)


startup.command = comparison_command

matrix = json.loads((root / 'matrix-bb1fb96.json').read_text())
rows = [row for row in matrix['runs'] if row['profile'] == 'safe-methods-v1']
assert len(rows) == 4 and all(row['state'] == 'completed' and row['exit'] == 0 for row in rows)
results = []
for row in rows:
    folder = Path(row['folder'])
    states = startup.startup_states(row['startup'])
    actual = startup.recheck(folder, root / 'quux-oteleq-bb1fb96', states)
    workspaces = list((folder / 'corpus/cases').glob('oteleq-run-*/plan.json'))
    assert len(workspaces) == 1
    plan = json.loads(workspaces[0].read_text())
    entry = next(item for item in plan['inventory'] if item.get('otelc_function') == 'Counter.identity(int)')
    control_root = folder / 'evidence-controls'
    controls = json.loads((control_root / 'QUALIFICATION.json').read_text())
    assert controls['evidence_refusals'] == 14 and controls['actual_applications'] == 0
    receipts.verify(control_root / 'positive', entry)
    for control in controls['controls']:
        try:
            receipts.verify(control_root / ('altered-' + control['name']), entry)
        except ValueError as error:
            assert str(error) == control['reason']
        else:
            raise AssertionError('Previously refused actual evidence was accepted')
    results.append({'startup': row['startup'], 'actual_jvms': actual['actual_jvm_launches'],
        'raw_attempts': actual['raw_attempt_folders'], 'copies_excluded': actual['copied_attempts_excluded'],
        'comparisons_recomputed': actual['typed_comparisons_recomputed'],
        'reports_checked': actual['qualified_reports'], 'refusals_rechecked': len(controls['controls'])})
index = json.loads((root / 'source-bb1fb96.json').read_text())
assert all(hashlib.sha256((source / name).read_bytes()).hexdigest() == value for name, value in index['files'].items())
result = {'executor_commit': index['commit'], 'verifier_commit': index['commit'],
    'profiles': results, 'actual_jvms': sum(row['actual_jvms'] for row in results),
    'comparisons_recomputed': sum(row['comparisons_recomputed'] for row in results),
    'refusals_rechecked': sum(row['refusals_rechecked'] for row in results),
    'source_files_preserved': len(index['files']), 'new_application_launches': 0,
    'partial': True, 'scope': 'Four safe initial states only. Final archive cohort and full final audit remain pending.',
    'checked_at': datetime.datetime.now(datetime.UTC).isoformat()}
(root / 'partial-safe-audit-bb1fb96.json').write_text(json.dumps(result, indent=2) + '\n')
print(json.dumps(result))
