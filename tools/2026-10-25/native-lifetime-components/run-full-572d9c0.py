"""Validate the frozen lifetime-contract components without changing held inputs."""
from datetime import datetime, timezone
import hashlib
import json
import os
from pathlib import Path
import shutil
import subprocess
import time

BASE = Path(__file__).resolve().parent
SOURCE = BASE / 'source-572d9c0'
OUTPUT = BASE / 'full-gate-572d9c0'
INDEX = json.loads((BASE / 'source-572d9c0.json').read_text())
NATIVE = Path('/Users/sclarke/github/oteleq-qualification/2026-10-25/native-prepared-qualification')
HELD = json.loads((NATIVE / 'exact-05e3130-02/inputs-after.json').read_text())
NEW_SDK = Path('/Users/sclarke/github/otelc-qualification/work/c-resource-quality')
SDK_INDEX = json.loads(Path('/Users/sclarke/github/otelc-qualification/2026-10-25/c-resource-quality/source-b425d1f.json').read_text())
SPEC = json.loads(Path('/Users/sclarke/github/oteleq-qualification/2026-10-25/go-path-boundaries/full-gate-cb08b82/command.json').read_text())
assert shutil.disk_usage(BASE).free >= 12 * 1024**3
OUTPUT.mkdir(mode=0o700)
TARGET = OUTPUT / 'target'
subprocess.run(['/bin/cp', '-cR', str(NATIVE / 'exact-05e3130-02/target'), str(TARGET)], check=True)


def facts(path):
    state = path.stat()
    with path.open('rb') as stream:
        digest = hashlib.file_digest(stream, 'sha256').hexdigest()
    return [digest, state.st_dev, state.st_ino, state.st_mode, state.st_size,
            state.st_mtime_ns, state.st_ctime_ns]


def inputs():
    groups = {'consumer': {name: facts(SOURCE / name) for name in INDEX['files']}}
    for key in ['native_sdk', 'native_products', 'go_sdk', 'weaver_source', 'tooling']:
        groups[key] = {name: facts(Path(name)) for name in HELD[key]}
    groups['lifetime_sdk'] = {name: facts(NEW_SDK / name) for name in SDK_INDEX['files']}
    groups['lifetime_products'] = {name: facts(NEW_SDK / 'build/quality-sdk' / name)
                                  for name in ['native-sdk-build.json', 'libotelc_native_runtime.dylib']}
    return groups


def write(name, value):
    (OUTPUT / name).write_text(json.dumps(value, indent=2) + '\n')


before = inputs()
assert all(before['consumer'][name][0] == digest for name, digest in INDEX['files'].items())
write('inputs-before.json', before)
tools = SPEC['selected_tools']
rust = Path('/Users/sclarke/.rustup/toolchains/1.98.1-aarch64-apple-darwin/bin')
environment = {key: value for key, value in os.environ.items()
               if not key.startswith(('OTEL', 'OTELEQ', 'GH_', 'GITHUB_', 'AWS_', 'SONAR_'))}
environment.update(tools)
environment.update(PYTHONDONTWRITEBYTECODE='1', CARGO_TARGET_DIR=str(TARGET),
    PATH=os.pathsep.join(map(str, [rust, *[Path(tools[name]).parent for name in
        ['OTELC_NODE', 'OTELC_CLANG', 'OTELC_JAVA', 'OTELC_GO']]])) + os.pathsep + environment.get('PATH', ''))
command = ['make', 'check', 'PYTHON=/Users/sclarke/github/oteleq-qualification/2026-10-24/python-live-metrics/env-312/bin/python',
           'NODE=' + tools['OTELC_NODE']]
state = {'head': INDEX['head'], 'status': 'running', 'started': datetime.now(timezone.utc).isoformat(),
         'command': command, 'selected_tools': tools, 'source_files': len(INDEX['files']),
         'free_bytes_before': shutil.disk_usage(BASE).free,
         'scope': 'Full local functional/coverage gate for lifetime protocol and SDK-source components only. Generated build4/build5 and shipping qualification remain open.'}
write('status.json', state)
started = time.monotonic()
try:
    with (OUTPUT / 'stdout').open('xb') as out, (OUTPUT / 'stderr').open('xb') as err:
        result = subprocess.run(command, cwd=SOURCE, env=environment, stdout=out, stderr=err, timeout=7200)
    state.update(status='passed' if result.returncode == 0 else 'failed', exit_code=result.returncode)
except Exception as error:
    state.update(status='failed', error=repr(error))
finally:
    after = inputs()
    write('inputs-after.json', after)
    state['preservation'] = {name: before[name] == after[name] for name in before}
    if not all(state['preservation'].values()):
        state['status'] = 'failed'
    state.update(seconds=round(time.monotonic() - started, 3), free_bytes_after=shutil.disk_usage(BASE).free,
                 finished=datetime.now(timezone.utc).isoformat())
    write('status.json', state)
    print(json.dumps(state, indent=2), flush=True)
    raise SystemExit(0 if state['status'] == 'passed' else 1)
