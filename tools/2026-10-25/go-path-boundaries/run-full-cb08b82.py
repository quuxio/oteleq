"""Validate one frozen Go consumer revision without starting a new SDK corpus."""
from datetime import datetime, timezone
import hashlib
import json
import os
from pathlib import Path
import subprocess
import time

BASE = Path(__file__).resolve().parent
INDEX = json.loads((BASE / 'source-cb08b82.json').read_text())
SOURCE = Path(INDEX['source'])
ROOT = BASE / 'full-gate-cb08b82'
SPEC = json.loads((ROOT / 'command.json').read_text())
PRIOR = json.loads(Path('/Users/sclarke/github/oteleq-qualification/2026-10-24/go-live-controls/matrix-a400885-01/inputs-before.json').read_text())
SDK = Path('/Users/sclarke/github/oteleq-qualification/2026-10-24/go-scope-provider/sdk-eda9fcc')
WEAVER = SDK / 'build/go-upstream-scope/source'


def facts(path):
    state = path.stat()
    return [hashlib.file_digest(path.open('rb'), 'sha256').hexdigest(), state.st_dev,
            state.st_ino, state.st_mode, state.st_size, state.st_mtime_ns, state.st_ctime_ns]


def inputs():
    return {'consumer': {name: facts(SOURCE / name) for name in INDEX['files']},
            'sdk': {name: facts(SDK / name) for name in PRIOR['sdk']},
            'weaver_source': {name: facts(WEAVER / name) for name in PRIOR['weaver_source']},
            'tooling': {name: facts(Path(name)) for name in PRIOR['tooling']}}


def write(name, value):
    (ROOT / name).write_text(json.dumps(value, indent=2) + '\n')


before = inputs()
assert all(before['consumer'][name][0] == digest for name, digest in INDEX['files'].items())
assert all(before[key] == PRIOR[key] for key in ['sdk', 'weaver_source', 'tooling']), 'held SDK/weaver/tooling changed'
write('inputs-before.json', before)
environment = {key: value for key, value in os.environ.items() if not key.startswith(('OTEL', 'OTELEQ', 'GH_', 'GITHUB_', 'SONAR_', 'AWS_'))}
tools = SPEC['selected_tools']
rust = Path('/Users/sclarke/.rustup/toolchains/1.98.1-aarch64-apple-darwin/bin')
paths = [rust, *[Path(tools[name]).parent for name in ['OTELC_NODE', 'OTELC_CLANG', 'OTELC_JAVA', 'OTELC_GO']]]
environment.update(tools)
environment.update(PATH=os.pathsep.join(map(str, paths)) + os.pathsep + environment.get('PATH', ''),
                   PYTHONDONTWRITEBYTECODE='1', CARGO_TARGET_DIR=str(ROOT / 'target'))
state = {'head': INDEX['head'], 'status': 'running', 'started': datetime.now(timezone.utc).isoformat(),
         'argv': SPEC['argv'], 'source_files': len(INDEX['files']), 'scope': 'Full local check only. No maintained SDK corpus launched.'}
write('status.json', state)
started = time.monotonic()
try:
    with (ROOT / 'stdout').open('xb') as stdout, (ROOT / 'stderr').open('xb') as stderr:
        result = subprocess.run(SPEC['argv'], cwd=SOURCE, env=environment, stdout=stdout, stderr=stderr, timeout=7200)
    state.update(status='passed' if result.returncode == 0 else 'failed', exit_code=result.returncode)
except Exception as error:
    state.update(status='failed', error=repr(error))
finally:
    try:
        after = inputs(); write('inputs-after.json', after)
        state['preservation'] = {name: before[name] == after[name] for name in before}
        if not all(state['preservation'].values()): state['status'] = 'failed'
    except OSError as error:
        state.update(status='failed', preservation_error=repr(error))
    state.update(seconds=round(time.monotonic() - started, 3), finished=datetime.now(timezone.utc).isoformat())
    write('status.json', state)
    print(json.dumps(state, indent=2), flush=True)
    raise SystemExit(0 if state['status'] == 'passed' else 1)
