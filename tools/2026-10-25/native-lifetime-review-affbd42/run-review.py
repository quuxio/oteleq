"""Run independent SDK component checks against the held archive."""
import hashlib
import json
import os
from pathlib import Path
import subprocess
import time

ROOT = Path(__file__).resolve().parent
SOURCE = ROOT / 'source'
INDEX = json.loads((ROOT / 'source-index.json').read_text())
PYTHON = '/Users/sclarke/github/oteleq-qualification/2026-10-24/python-live-metrics/env-312/bin/python'


def facts():
    result = {}
    for name, expected in INDEX['files'].items():
        path = SOURCE / name
        info = path.lstat()
        sha = hashlib.sha256(path.read_bytes()).hexdigest()
        if sha != expected:
            raise ValueError('archive input mismatch: ' + name)
        result[name] = [sha, info.st_dev, info.st_ino, info.st_mode, info.st_uid,
                        info.st_gid, info.st_size, info.st_mtime_ns,
                        info.st_ctime_ns, info.st_nlink]
    return result


before = facts()
(ROOT / 'inputs-before.json').write_text(json.dumps(before, indent=2) + '\n')
environment = dict(os.environ, PYTHONDONTWRITEBYTECODE='1',
                   PATH='/opt/homebrew/opt/llvm@22/bin:/opt/homebrew/bin:/usr/bin:/bin:/usr/sbin:/sbin')
commands = [
    ['make', 'native-lifetimes-check', 'PYTHON=' + PYTHON],
    [PYTHON, '-B', '-m', 'unittest', 'discover', '-s', 'tests', '-p', 'test_native_sonar.py', '-v'],
]
results = []
for index, command in enumerate(commands):
    started = time.monotonic()
    (ROOT / f'command-{index}.json').write_text(json.dumps(command, indent=2) + '\n')
    with (ROOT / f'command-{index}.stdout').open('xb') as stdout, (ROOT / f'command-{index}.stderr').open('xb') as stderr:
        process = subprocess.run(command, cwd=SOURCE, env=environment,
                                 stdout=stdout, stderr=stderr, timeout=600)
    results.append({'argv': command, 'exit_code': process.returncode,
                    'seconds': round(time.monotonic() - started, 3)})
    if process.returncode:
        break
after = facts()
(ROOT / 'inputs-after.json').write_text(json.dumps(after, indent=2) + '\n')
value = {'head': INDEX['head'], 'commands': results,
         'source_files': len(before), 'source_preserved': before == after,
         'passed': before == after and len(results) == len(commands)
                   and all(row['exit_code'] == 0 for row in results),
         'scope': 'Clang semantic component and converter; no application lifetime instrumentation admission'}
(ROOT / 'test-result.json').write_text(json.dumps(value, indent=2) + '\n')
print(json.dumps(value))
raise SystemExit(0 if value['passed'] else 1)
