"""Repeat the independent review with the real frontend module name."""

import hashlib
import json
import os
from pathlib import Path
import re
import subprocess

ROOT = Path(__file__).resolve().parent
ORIGINAL = Path('/Users/sclarke/github/otelc-qualification/2026-10-23/python-native-executable/source-3a636ec')
SOURCE = ROOT / 'source-3a636ec'
METADATA = json.loads(ORIGINAL.with_suffix('.json').read_text())


def audit(root):
    changed = [name for name, digest in METADATA['files'].items()
               if hashlib.sha256((root / name).read_bytes()).hexdigest() != digest]
    if changed:
        raise ValueError('source drift: ' + repr(changed))
    return len(METADATA['files'])


record = {'head': METADATA['head'], 'base': METADATA['base'],
          'original_sources_before': audit(ORIGINAL),
          'independent_sources_before': audit(SOURCE), 'runs': [],
          'supersedes_harness_error': 'tests.json and focused-{312,314}.log are preserved; nonexistent test_python_frontend corrected'}
names = ['test_python_native_inputs', 'test_python_import_inputs', 'test_python_code_inputs',
         'test_python_native_encoder', 'test_python_input_build', 'test_native_encoder_build',
         'test_python_prepared', 'test_python_frontend_components']
for label, python in [('312', '/Users/sclarke/github/oteleq-qualification/2026-10-23/python-cli-review-b6dbebb/validation-env-312/bin/python'),
                      ('314', '/Users/sclarke/github/oteleq-qualification/2026-10-23/python-http-review-87ab378/validation-env/bin/python')]:
    command = [python, '-m', 'unittest', '-v', *names]
    path = ROOT / ('corrected-' + label + '.log')
    with path.open('wb') as output:
        result = subprocess.run(command, cwd=SOURCE,
            env={**os.environ, 'PYTHONPATH': str(SOURCE) + os.pathsep + str(SOURCE / 'tests'),
                 'PYTHONDONTWRITEBYTECODE': '1'}, stdout=output, stderr=subprocess.STDOUT)
    count = re.search(r'Ran (\d+) tests?', path.read_text())
    record['runs'].append({'label': label, 'command': command, 'exit': result.returncode,
                           'tests': int(count[1]) if count else None})
record.update(original_sources_after=audit(ORIGINAL), independent_sources_after=audit(SOURCE))
(ROOT / 'corrected-tests.json').write_text(json.dumps(record, indent=2) + '\n')
print(json.dumps(record))
raise SystemExit(any(item['exit'] for item in record['runs']))
