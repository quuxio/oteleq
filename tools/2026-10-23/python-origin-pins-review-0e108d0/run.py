"""Independent journal2 and journal1 compatibility checks in a private copy."""

import hashlib
import json
import os
from pathlib import Path
import re
import subprocess

ROOT = Path(__file__).resolve().parent
ORIGINAL = Path('/Users/sclarke/github/otelc-qualification/2026-10-23/python-origin-pins/source-0e108d0')
SOURCE = ROOT / 'source-0e108d0'
METADATA = json.loads(ORIGINAL.with_suffix('.json').read_text())


def audit(root):
    changed = [name for name, digest in METADATA['files'].items()
               if hashlib.sha256((root / name).read_bytes()).hexdigest() != digest]
    if changed:
        raise ValueError('source drift: ' + repr(changed))
    return len(METADATA['files'])


record = {'head': METADATA['head'], 'base': '118ce9d0eb8e45b9abb22b6222ae7317fbcfd57c',
          'original_sources_before': audit(ORIGINAL), 'independent_sources_before': audit(SOURCE), 'runs': []}
names = ['test_python_origin_pins', 'test_python_origin_journal', 'test_python_origin_writer', 'test_python_input_journal',
         'test_python_native_inputs', 'test_python_import_inputs', 'test_python_code_inputs',
         'test_python_native_encoder', 'test_python_input_build', 'test_native_encoder_build',
         'test_python_prepared', 'test_python_frontend_components']
for label, python in [('312', '/Users/sclarke/github/oteleq-qualification/2026-10-23/python-cli-review-b6dbebb/validation-env-312/bin/python'),
                      ('314', '/Users/sclarke/github/oteleq-qualification/2026-10-23/python-http-review-87ab378/validation-env/bin/python')]:
    command = [python, '-m', 'unittest', '-v', *names]
    path = ROOT / ('focused-' + label + '.log')
    with path.open('wb') as output:
        result = subprocess.run(command, cwd=SOURCE,
            env={**os.environ, 'PYTHONPATH': str(SOURCE) + os.pathsep + str(SOURCE / 'tests'),
                 'PYTHONDONTWRITEBYTECODE': '1'}, stdout=output, stderr=subprocess.STDOUT)
    count = re.search(r'Ran (\d+) tests?', path.read_text())
    record['runs'].append({'label': label, 'command': command, 'exit': result.returncode,
                           'tests': int(count[1]) if count else None})
record.update(original_sources_after=audit(ORIGINAL), independent_sources_after=audit(SOURCE))
(ROOT / 'tests.json').write_text(json.dumps(record, indent=2) + '\n')
print(json.dumps(record))
raise SystemExit(any(item['exit'] for item in record['runs']))
