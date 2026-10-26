"""Validate the frozen integrated generator while preserving both held SDKs."""
from datetime import datetime, timezone
import hashlib
import json
import os
from pathlib import Path
import subprocess
import time

BASE = Path(__file__).resolve().parent
INDEX = json.loads((BASE / 'source-0935585.json').read_text())
SOURCE = Path(INDEX['source'])
ROOT = BASE / 'full-gate-0935585'
SPEC = json.loads((ROOT / 'command.json').read_text())
GO = json.loads((BASE.parent / 'go-path-boundaries/full-gate-cb08b82/inputs-after.json').read_text())
NATIVE = json.loads((BASE.parent / 'native-consumer/full-gate-64c42ba/inputs-after.json').read_text())
GO_ROOT = Path('/Users/sclarke/github/oteleq-qualification/2026-10-24/go-scope-provider/sdk-eda9fcc')
NATIVE_ROOT = Path('/Users/sclarke/github/otelc-qualification/work/native-build-context')
HELD = {'go_sdk': (GO_ROOT, GO['sdk']),
        'weaver_source': (GO_ROOT / 'build/go-upstream-scope/source', GO['weaver_source']),
        'tooling': (Path('/'), GO['tooling']),
        'native_sdk': (NATIVE_ROOT, NATIVE['sdk']),
        'native_products': (Path('/'), NATIVE['sdk_products'])}


def facts(path):
    info = path.stat()
    with path.open('rb') as stream:
        digest = hashlib.file_digest(stream, 'sha256').hexdigest()
    return [digest, info.st_dev, info.st_ino, info.st_mode, info.st_size, info.st_mtime_ns, info.st_ctime_ns]


def inputs():
    return {'consumer': {name: facts(SOURCE / name) for name in INDEX['files']},
            **{key: {name: facts(root / name) for name in expected} for key, (root, expected) in HELD.items()}}


def write(name, value):
    (ROOT / name).write_text(json.dumps(value, indent=2) + '\n')


before = inputs()
assert all(before['consumer'][name][0] == digest for name, digest in INDEX['files'].items())
assert all(before[key] == expected for key, (_, expected) in HELD.items()), 'held SDK/source/product/tool facts changed'
write('inputs-before.json', before)
environment = {key: value for key, value in os.environ.items()
               if not key.startswith(('OTEL', 'OTELEQ', 'GH_', 'GITHUB_', 'SONAR_', 'AWS_'))}
tools = SPEC['selected_tools']
rust = Path('/Users/sclarke/.rustup/toolchains/1.98.1-aarch64-apple-darwin/bin')
paths = [rust, *[Path(tools[name]).parent for name in ['OTELC_NODE', 'OTELC_CLANG', 'OTELC_JAVA', 'OTELC_GO']]]
environment.update(tools)
environment.update(PATH=os.pathsep.join(map(str, paths)) + os.pathsep + environment.get('PATH', ''),
                   PYTHONDONTWRITEBYTECODE='1', CARGO_TARGET_DIR=str(ROOT / 'target'))
state = {'head': INDEX['head'], 'status': 'running', 'started': datetime.now(timezone.utc).isoformat(),
         'argv': SPEC['argv'], 'source_files': len(INDEX['files']),
         'scope': 'Full local gate only. Actual generated/retained SDK workflow qualification remains separate.'}
write('status.json', state)
started = time.monotonic()
try:
    with (ROOT / 'stdout').open('xb') as stdout, (ROOT / 'stderr').open('xb') as stderr:
        result = subprocess.run(SPEC['argv'], cwd=SOURCE, env=environment,
                                stdout=stdout, stderr=stderr, timeout=7200)
    state.update(status='passed' if result.returncode == 0 else 'failed', exit_code=result.returncode)
except Exception as error:
    state.update(status='failed', error=repr(error))
finally:
    try:
        after = inputs(); write('inputs-after.json', after)
        state['preservation'] = {name: before[name] == after[name] for name in before}
        if not all(state['preservation'].values()):
            state['status'] = 'failed'
    except OSError as error:
        state.update(status='failed', preservation_error=repr(error))
    state.update(seconds=round(time.monotonic() - started, 3), finished=datetime.now(timezone.utc).isoformat())
    write('status.json', state); print(json.dumps(state, indent=2), flush=True)
    raise SystemExit(0 if state['status'] == 'passed' else 1)
