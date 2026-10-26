"""Seal the complete reviewed diff and three independent runtime cohorts."""

import hashlib
import json
from pathlib import Path
import subprocess

BASE = Path(__file__).resolve().parent
REPO = Path('/Users/sclarke/github/otelc')
HEAD = '7ff4cdd0c07343b1c24b9edf2517cd0083dac9ca'
PARENT = '305834bc330b2ab423a3aebdd789073413e25911'
archive = subprocess.check_output(['git', 'archive', '--format=tar', HEAD], cwd=REPO)
expected_archive = 'b48b00b4e8eb526e4cc6f72fa8ee28cdb50e2128e33eab665e2077cb80950437'
assert hashlib.sha256(archive).hexdigest() == expected_archive
diff = subprocess.check_output(['git', 'diff', PARENT, HEAD, '--'], cwd=REPO)
(BASE / 'reviewed.diff').write_bytes(diff)
files = subprocess.check_output(['git', 'diff', '--name-only', PARENT, HEAD, '--'], cwd=REPO, text=True).splitlines()
assert len(files) == 6
runs = [json.loads((BASE / ('tests-' + label + '.json')).read_text()) for label in ('312', '314', '31210')]
assert [row['tests'] for row in runs] == [104, 104, 20]
assert all(row['exit_code'] == 0 and row['head'] == HEAD and row['base'] == PARENT
           and row['original_sources_before'] == row['original_sources_after'] == 326
           and row['independent_sources_before'] == row['independent_sources_after'] == 326 for row in runs)
record = {'head': HEAD, 'base': PARENT, 'decision': 'clear', 'findings': [],
          'reviewed_files': files, 'reviewed_diff_sha256': hashlib.sha256(diff).hexdigest(),
          'archive_sha256': expected_archive, 'archive_independently_reproduced_from_git': True,
          'runtime_cohorts': runs, 'actual_builtin_distribution': json.loads((BASE / 'distribution-31210.json').read_text()),
          'scope': 'complete six-file builtin encoder, selected-library search and fixture-startup diff',
          'limits': ['No clearance of the separate sourceless FileIO capture change',
                     'No authentic source-origin or generated-provider admission qualification',
                     'Full producer gate and required CI are independently required before merge'],
          'source_preserved': True}
(BASE / 'review.json').write_text(json.dumps(record, indent=2) + '\n')
print(json.dumps({'head': HEAD, 'decision': 'clear', 'files': len(files), 'tests_per_context': [104, 104, 20],
                  'source_preserved': True, 'review_sha256': hashlib.sha256((BASE / 'review.json').read_bytes()).hexdigest()}))
