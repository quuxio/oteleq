"""Check the exact frozen runtime component while retaining original source facts."""

from datetime import datetime, timezone
import hashlib
import json
import os
from pathlib import Path
import subprocess
import time

BASE = Path(__file__).resolve().parent
INDEX = json.loads((BASE / 'source-efa5223.json').read_text())
SOURCE = Path(INDEX['frozen_source'])
ORIGINAL = Path(INDEX['source'])
OUT = BASE / 'components-efa5223-01'
PYTHONS = Path('/Users/sclarke/github/oteleq-qualification/2026-10-24/python-live-metrics')
NODE = '/opt/homebrew/Cellar/node@24/24.21.0_2/bin/node'
MARKDOWN = '/Users/sclarke/github/oteleq-qualification/work/oteleq-native-generated/ci/markdownlint/node_modules'


def write(name, value):
    (OUT / name).write_text(json.dumps(value, indent=2) + '\n')


def facts(path):
    state = path.stat()
    with path.open('rb') as stream:
        digest = hashlib.file_digest(stream, 'sha256').hexdigest()
    return [digest, state.st_dev, state.st_ino, state.st_mode, state.st_size,
            state.st_mtime_ns, state.st_ctime_ns]


def snapshot():
    return {'original': {name: facts(ORIGINAL / name) for name in INDEX['files']},
            'frozen': {name: facts(SOURCE / name) for name in INDEX['files']}}


OUT.mkdir(mode=0o700)
before = snapshot()
assert before == {'original': INDEX['original_facts'], 'frozen': INDEX['frozen_facts']}
write('inputs-before.json', before)
environment = {key: value for key, value in os.environ.items()
               if not key.startswith(('OTEL', 'OTELEQ', 'GH_', 'GITHUB_', 'AWS_', 'SONAR_'))}
environment.update(PYTHONDONTWRITEBYTECODE='1', PYTHONPATH=str(SOURCE / 'tests'), NODE_PATH=MARKDOWN,
    PATH='/Users/sclarke/.rustup/toolchains/1.98.1-aarch64-apple-darwin/bin:'
         '/opt/homebrew/Cellar/node@24/24.21.0_2/bin:/usr/bin:/bin:/opt/homebrew/bin')
commands = [
    ['make', 'native-lifetime-check', 'PYTHON=' + str(PYTHONS / 'env-312/bin/python')],
    [str(PYTHONS / 'env-314/bin/python'), '-m', 'unittest', 'test_generation_native_lifetime_execution',
     'test_generation_makefile', '-v'],
    ['make', 'lint', 'examples', 'PYTHON=' + str(PYTHONS / 'env-312/bin/python'),
     'NODE=' + NODE, 'MARKDOWNLINT=' + MARKDOWN + '/.bin/markdownlint'],
    ['cargo', 'fmt', '--all', '--check'],
]
state = {'head': INDEX['head'], 'status': 'running', 'started': datetime.now(timezone.utc).isoformat(),
         'source_files': len(INDEX['files']), 'commands': [], 'applications': 0,
         'scope': 'Exact-head literal reader/preparation/final-health regression/coverage, Python 3.14, '
                  'documentation/examples/workflow syntax and Rust format. Full local gate and actual '
                  'generated lifetime qualification remain separate.'}
write('status.json', state)
started = time.monotonic()
try:
    for index, command in enumerate(commands):
        command_started = time.monotonic()
        with (OUT / f'{index}.stdout').open('xb') as out, (OUT / f'{index}.stderr').open('xb') as err:
            result = subprocess.run(command, cwd=SOURCE, env=environment, stdout=out, stderr=err, timeout=600)
        state['commands'].append({'argv': command, 'exit_code': result.returncode,
                                  'seconds': round(time.monotonic() - command_started, 3)})
        write('status.json', state)
        assert result.returncode == 0, f'command {index} failed; retain original channels'
    state['status'] = 'passed'
except Exception as error:
    state.update(status='failed', error=repr(error))
finally:
    after = snapshot()
    write('inputs-after.json', after)
    state['preservation'] = {name: before[name] == after[name] for name in before}
    if not all(state['preservation'].values()):
        state['status'] = 'failed'
    state.update(seconds=round(time.monotonic() - started, 3),
                 finished=datetime.now(timezone.utc).isoformat())
    write('status.json', state)
    print(json.dumps(state, indent=2), flush=True)
    raise SystemExit(0 if state['status'] == 'passed' else 1)
