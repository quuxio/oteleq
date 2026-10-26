"""Run the complete consumer gate against one held committed source tree."""
from datetime import datetime, timezone
import hashlib
import json
import os
from pathlib import Path
import subprocess
import time

BASE = Path(__file__).resolve().parent
INDEX = json.loads((BASE / 'source-51e5438.json').read_bytes())
SOURCE = Path(INDEX['source'])
SDK = Path('/Users/sclarke/github/otelc-qualification/work/native-prepared')
SDK_INDEX = json.loads(Path('/Users/sclarke/github/otelc-qualification/2026-10-24/native-prepared/source-4a85c18.json').read_bytes())
ROOT = BASE / 'full-gate-51e5438'
SPEC = json.loads((ROOT / 'command.json').read_bytes())


def facts(path):
    info = path.stat()
    return [hashlib.sha256(path.read_bytes()).hexdigest(), info.st_dev, info.st_ino, info.st_mode,
            info.st_size, info.st_mtime_ns, info.st_ctime_ns]


def inputs():
    products = [SDK / 'build/prepared-sdk/native-sdk-build.json', SDK / 'build/prepared-sdk/libotelc_native_runtime.dylib']
    return {'consumer': {name: facts(SOURCE / name) for name in INDEX['files']},
            'sdk': {name: facts(SDK / name) for name in SDK_INDEX['files']},
            'sdk_products': {str(path): facts(path) for path in products}}


def write(name, value):
    (ROOT / name).write_text(json.dumps(value, indent=2) + '\n')


before = inputs(); write('inputs-before.json', before)
assert all(before['consumer'][name][0] == sha for name, sha in INDEX['files'].items())
assert all(before['sdk'][name][0] == sha for name, sha in SDK_INDEX['files'].items())
environment = {key: value for key, value in os.environ.items() if not key.startswith(('OTEL', 'OTELEQ', 'GH_', 'GITHUB_', 'SONAR_', 'AWS_'))}
tools = SPEC['selected_tools']
rust = Path('/Users/sclarke/.rustup/toolchains/1.98.1-aarch64-apple-darwin/bin')
paths = [rust, *[Path(tools[name]).parent for name in ('OTELC_NODE', 'OTELC_CLANG', 'OTELC_JAVA', 'OTELC_GO')]]
environment.update(tools)
environment.update(PATH=os.pathsep.join(map(str, paths)) + os.pathsep + environment.get('PATH', ''),
                   PYTHONDONTWRITEBYTECODE='1', CARGO_TARGET_DIR=str(ROOT / 'target'))
state = {'head': INDEX['head'], 'status': 'running', 'started': datetime.now(timezone.utc).isoformat(),
         'argv': SPEC['argv'], 'source_files': len(INDEX['files'])}
write('status.json', state); started = time.monotonic()
try:
    with (ROOT / 'stdout').open('xb') as stdout, (ROOT / 'stderr').open('xb') as stderr:
        process = subprocess.run(SPEC['argv'], cwd=SOURCE, env=environment, stdout=stdout, stderr=stderr, timeout=7200)
    state.update(status='passed' if process.returncode == 0 else 'failed', exit_code=process.returncode)
except Exception as error:
    state.update(status='failed', error=repr(error))
finally:
    after = inputs(); write('inputs-after.json', after)
    state['preservation'] = {name: before[name] == after[name] for name in before}
    if not all(state['preservation'].values()): state['status'] = 'failed'
    state.update(seconds=round(time.monotonic() - started, 3), finished=datetime.now(timezone.utc).isoformat())
    write('status.json', state); print(json.dumps(state, indent=2), flush=True)
    raise SystemExit(0 if state['status'] == 'passed' else 1)
