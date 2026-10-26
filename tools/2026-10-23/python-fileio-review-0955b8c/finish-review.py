"""Seal the whole review and a behaviour difference on three real runtimes."""

import hashlib
import json
from pathlib import Path
import subprocess

BASE = Path(__file__).resolve().parent
REPO = Path('/Users/sclarke/github/otelc')
HEAD = '0955b8c350e970bb7780f49ef9a87d444a1d6b71'
PARENT = 'd92262c20292389123f7fc511ef5cc59f4dbd07e'
ORIGINAL = Path('/Users/sclarke/github/otelc-qualification/2026-10-23/python-fileio-inputs/source-0955b8c')
metadata = json.loads(ORIGINAL.with_suffix('.json').read_text())
archive = subprocess.check_output(['git', 'archive', '--format=tar', HEAD], cwd=REPO)
assert hashlib.sha256(archive).hexdigest() == metadata['archive_sha256']
diff = subprocess.check_output(['git', 'diff', PARENT, HEAD, '--'], cwd=REPO)
(BASE / 'reviewed.diff').write_bytes(diff)
files = subprocess.check_output(['git', 'diff', '--name-only', PARENT, HEAD, '--'], cwd=REPO, text=True).splitlines()
assert len(files) == 9
runs, falsifiers = [], []
for label, expected_count in (('312', 118), ('314', 118), ('31210', 41)):
    row = json.loads((BASE / ('tests-' + label + '.json')).read_text())
    assert row['exit_code'] == 0 and row['tests'] == expected_count and row['head'] == HEAD
    runs.append(row)
    proof = json.loads((BASE / ('method-equality-' + label) / 'proof.json').read_text())
    assert not proof['behaviour_matches'] and proof['source_preserved']
    assert proof['runs'][0]['output'] == {'content': '616263', 'events': [[True, True]]}
    assert proof['runs'][1]['output'] == {'content': '616263', 'events': [[False, False]]}
    assert all(lane['exit_code'] == 0 for lane in proof['runs'])
    falsifiers.append(proof)
for source in (ORIGINAL, BASE / 'source-312', BASE / 'source-314', BASE / 'source-31210'):
    assert {name: hashlib.sha256((source / name).read_bytes()).hexdigest() for name in metadata['files']} == metadata['files']
record = {'head': HEAD, 'base': PARENT, 'decision': 'changes_requested', 'reviewed_files': files,
          'reviewed_diff_sha256': hashlib.sha256(diff).hexdigest(), 'archive_sha256': metadata['archive_sha256'],
          'archive_independently_reproduced_from_git': True, 'tests': runs, 'additional_falsifiers': falsifiers,
          'source_files_preserved_each': 329, 'source_preserved': True,
          'findings': [{'priority': 2, 'path': 'native/python/FileIOCapture.c', 'line': 203,
                        'title': 'Preserve the original bound read method equality and hash',
                        'body': 'PyCMethod_New creates a callable with the observer implementation instead of the original builtin implementation. An ordinary application profiler comparing the read callable with FileIO.read.__get__ sees equality and matching hashes in stock CPython, but both comparisons become false with the native observer. Actual application stdout differs on CPython 3.12.10, 3.12.15 and 3.14.8 while both processes exit successfully and return the same read bytes. Preserve these callable semantics before qualifying the raw loader profile.'}],
          'scope': 'Complete nine-file source and runtime boundary review. Existing test success does not clear the independently reproduced application behaviour change. No source-origin or provider-admission clearance.'}
(BASE / 'review.json').write_text(json.dumps(record, indent=2) + '\n')
print(json.dumps({'head': HEAD, 'decision': record['decision'], 'files': len(files),
                  'tests_per_context': [row['tests'] for row in runs], 'falsified_contexts': len(falsifiers),
                  'review_sha256': hashlib.sha256((BASE / 'review.json').read_bytes()).hexdigest()}))
