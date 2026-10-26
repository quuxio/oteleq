"""Independent frozen-input review; no application is executed."""
import hashlib
import json
import os
from pathlib import Path
import subprocess
import time

root = Path(__file__).parent
source = Path('/Users/sclarke/github/otelc-qualification/2026-10-23/python-source-attribution/source-ecf80a9')
manifest = json.loads(source.with_suffix('.json').read_text())
interpreters = [
    Path('/Users/sclarke/github/oteleq-qualification/2026-10-23/python-cli-review-b6dbebb/validation-env-312/bin/python'),
    Path('/Users/sclarke/github/oteleq-qualification/2026-10-23/python-http-review-87ab378/validation-env/bin/python'),
]

def verify():
    for name, digest in manifest['files'].items():
        if hashlib.sha256((source/name).read_bytes()).hexdigest() != digest:
            raise ValueError('frozen source changed: '+name)
    return len(manifest['files'])

result = {'head': manifest['head'], 'base': manifest['base'], 'source': str(source),
          'source_count_before': verify(), 'runs': [], 'new_application_launches': 0}
for ordinal, interpreter in enumerate(interpreters):
    argv = [str(interpreter), '-m', 'unittest', '-v', 'test_python_code_evidence',
            'test_python_code_candidate', 'test_python_code_comparison',
            'test_python_code_worker', 'test_python_code_index']
    env = dict(os.environ, PYTHONPATH='tests', PYTHONDONTWRITEBYTECODE='1')
    started = time.time()
    log = root/f'tests-{ordinal}.log'
    with log.open('xb') as output:
        run = subprocess.run(argv, cwd=source, env=env, stdout=output,
                             stderr=subprocess.STDOUT, timeout=240, check=False)
    result['runs'].append({'argv': argv, 'returncode': run.returncode,
                           'elapsed_seconds': time.time()-started, 'log': str(log)})
result['source_count_after'] = verify()
(root/'tests.json').write_text(json.dumps(result, indent=2)+'\n')
if any(run['returncode'] for run in result['runs']):
    raise SystemExit(1)
print(json.dumps({'head': result['head'], 'sources': result['source_count_after'],
                  'returncodes': [run['returncode'] for run in result['runs']]}))
