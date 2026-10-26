"""Seal the corrected whole change with preserved failed-environment evidence."""

import hashlib
import json
from pathlib import Path
import subprocess

BASE = Path(__file__).resolve().parent
REPO = Path('/Users/sclarke/github/otelc')
HEAD = '406260df97d35dfb35daa4274a6e9651eada4394'
PARENT = 'd92262c20292389123f7fc511ef5cc59f4dbd07e'
ORIGINAL = Path('/Users/sclarke/github/otelc-qualification/2026-10-23/python-fileio-inputs/source-406260d')
metadata = json.loads(ORIGINAL.with_suffix('.json').read_text())
archive = subprocess.check_output(['git', 'archive', '--format=tar', HEAD], cwd=REPO)
assert hashlib.sha256(archive).hexdigest() == metadata['archive_sha256']
diff = subprocess.check_output(['git', 'diff', PARENT, HEAD, '--'], cwd=REPO)
(BASE / 'reviewed.diff').write_bytes(diff)
files = subprocess.check_output(['git', 'diff', '--name-only', PARENT, HEAD, '--'], cwd=REPO, text=True).splitlines()
assert len(files) == 10
runs = [json.loads((BASE / ('tests-' + label + '.json')).read_text()) for label in ('312', '314-normal', '31210')]
assert [row['tests'] for row in runs] == [119, 119, 42]
assert all(row['exit_code'] == 0 and row['head'] == HEAD for row in runs)
additional = []
for label in ('312', '314', '31210'):
    values = []
    for fixture in ('method-equality-', 'startup-keys-'):
        path = BASE / (fixture + label) / 'proof.json'
        proof = json.loads(path.read_text())
        assert proof['producer_head'] == HEAD and proof['behaviour_matches'] and proof['source_preserved']
        values.append({'path': str(path), 'sha256': hashlib.sha256(path.read_bytes()).hexdigest(), 'proof': proof})
    additional.append({'context': label, 'checks': values})
sandbox = json.loads((BASE / 'tests-314.json').read_text())
focused_sandbox = json.loads((BASE / 'owner-cleanup-focused.json').read_text())
normal = json.loads((BASE / 'owner-cleanup-normal.json').read_text())
permissions = json.loads((BASE / 'process-inspection-permissions.json').read_text())
assert sandbox['exit_code'] == 1 and focused_sandbox['failures'] == 6
assert permissions['normal_permissions_exit'] == 0 and permissions['membership_rows'] > 0
assert normal['runs'] == 12 and normal['success'] and normal['failures'] == normal['errors'] == 0
for root in (ORIGINAL, BASE / 'source-312', BASE / 'source-314', BASE / 'source-314-normal', BASE / 'source-31210'):
    assert {name: hashlib.sha256((root / name).read_bytes()).hexdigest() for name in metadata['files']} == metadata['files']
record = {'head': HEAD, 'base': PARENT, 'decision': 'clear', 'findings': [],
          'reviewed_files': files, 'reviewed_diff_sha256': hashlib.sha256(diff).hexdigest(),
          'archive_sha256': metadata['archive_sha256'], 'archive_independently_reproduced_from_git': True,
          'tests': runs, 'additional_actual_application_checks': additional,
          'resolved_findings': [{'priority': 2, 'previous_head': '0955b8c350e970bb7780f49ef9a87d444a1d6b71',
                                 'title': 'Preserve bound read method equality and hash',
                                 'result': 'Original callable, method definition and native implementation retained; per-result vectorcall forwards literal arguments. Stock/native falsifier matches on all three runtimes.'}],
          'environment_failure_preserved': {'broad': sandbox, 'focused': focused_sandbox,
                                            'permissions': permissions, 'normal_permission_recheck': normal,
                                            'cause': 'Codex sandbox denies spawning /bin/ps; original fail-closed process-membership checks require normal process-inspection permissions and were not changed or skipped.'},
          'source_files_preserved_each': 329, 'source_preserved': True,
          'review_checks': ['Complete ten-file diff, weak slot lifecycle, exact byte/FD/stat/generation binding and exception preservation',
                            'Original bound method metadata/equality/hash, native calling convention, repeated loader dispatch and direct method calls',
                            'Actual sitecustomize startup-cached read/initialiser dictionary, set and frozenset membership on all three runtimes',
                            'Nested/concurrent scopes, original sourceless read, capacity/weak lifetime, foreign interpreter and normal-permission owner cleanup'],
          'scope': 'Independent macOS ARM64 source/component/runtime boundary review. Producer full gate, native coverage and required GitHub checks remain required. No source-origin, complete-source, shipping or generated-provider admission clearance.'}
(BASE / 'review.json').write_text(json.dumps(record, indent=2) + '\n')
print(json.dumps({'head': HEAD, 'decision': 'clear', 'files': len(files), 'tests_per_context': [119, 119, 42],
                  'source_preserved': True, 'review_sha256': hashlib.sha256((BASE / 'review.json').read_bytes()).hexdigest()}))
