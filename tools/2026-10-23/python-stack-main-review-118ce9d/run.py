"""Independent journal2 and journal1 compatibility checks in a private copy."""

import hashlib
import json
import os
from pathlib import Path
import re
import subprocess

ROOT = Path(__file__).resolve().parent
ORIGINAL = Path('/Users/sclarke/github/otelc-qualification/2026-10-23/python-stack-main/source-118ce9d')
SOURCE = ROOT / 'source-118ce9d'
METADATA = json.loads(ORIGINAL.with_suffix('.json').read_text())


def audit(root):
    changed = [name for name, digest in METADATA['files'].items()
               if hashlib.sha256((root / name).read_bytes()).hexdigest() != digest]
    if changed:
        raise ValueError('source drift: ' + repr(changed))
    return len(METADATA['files'])


record = {'head': METADATA['head'], 'base': 'eb380d2f2c1e958046b89cf339ee84eb37da71c4',
          'original_sources_before': audit(ORIGINAL), 'independent_sources_before': audit(SOURCE), 'runs': []}
names = ['test_python_recipe', 'test_python_frontend_components', 'test_python_prepared', 'test_cli_bootstrap', 'test_python_provider_protocol', 'test_python_native_inputs', 'test_cli']
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
