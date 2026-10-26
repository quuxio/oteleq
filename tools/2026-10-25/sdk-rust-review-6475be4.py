"""Bounded independent correction review with held SDK products and no rebuild."""

from datetime import datetime, timezone
import hashlib
import json
import os
from pathlib import Path
import re
import subprocess
import time

BASE = Path(__file__).resolve().parent
INDEX = json.loads(Path('/Users/sclarke/github/otelc-qualification/2026-10-25/rust-ci-integration/source-6475be4.json').read_text())
ROOT = Path(INDEX['source'])
OUT = BASE / 'sdk-rust-review-6475be4'
PYTHON = '/Users/sclarke/github/oteleq-qualification/2026-10-24/python-live-metrics/env-312/bin/python'


def facts(path):
    stat = path.stat()
    with path.open('rb') as stream:
        digest = hashlib.file_digest(stream, 'sha256').hexdigest()
    return [digest, stat.st_dev, stat.st_ino, stat.st_mode, stat.st_size, stat.st_mtime_ns, stat.st_ctime_ns]


def snapshot():
    return {'source': {name: facts(ROOT / name) for name in INDEX['files']},
            'products': {name: facts(Path(name)) for name in INDEX['product_facts']}}


def write(name, value):
    (OUT / name).write_text(json.dumps(value, indent=2) + '\n')


OUT.mkdir(mode=0o700)
before = snapshot()
assert before == {'source': INDEX['original_facts'], 'products': INDEX['product_facts']}
assert facts(Path(INDEX['archive']))[0] == INDEX['archive_sha256']
write('inputs-before.json', before)
driver = next(Path(name) for name in INDEX['product_facts'] if name.endswith('/compiler/debug/otelc-rust-compiler'))
gate = driver.parent.parent.parent
unit_log = (gate / 'compiler-unit.stderr').read_text()
match = re.search(r'Running unittests[^\n]*\(([^\n)]+)\)', unit_log)
assert match is not None
unit = Path(match[1])
if not unit.is_absolute():
    unit = ROOT / unit
assert str(unit) in INDEX['product_facts']
environment = {key: value for key, value in os.environ.items()
               if not key.startswith(('OTEL', 'OTELEQ', 'GH_', 'GITHUB_', 'AWS_', 'SONAR_', 'LLVM_PROFILE'))}
environment.update(PYTHONDONTWRITEBYTECODE='1', PYTHONPATH=str(ROOT) + os.pathsep + str(ROOT / 'tests'),
                   LLVM_PROFILE_FILE=str(OUT / 'unit-%m-%p.profraw'))
commands = [
    ['make', '-n', 'native-launch-check'], ['make', '-n', 'rust-compiler-check'],
    [PYTHON, '-m', 'unittest', 'test_rust_sonar', 'test_health.HealthShapeTests', '-v'],
    [str(unit)],
    *[[str(ROOT / 'build/correction-native-core' / name)] for name in
      ('otelc_native_controls_test', 'otelc_native_functions_test', 'otelc_native_objects_test')],
    [PYTHON, '-m', 'ci.rust_sonar'],
]
state = {'head': INDEX['head'], 'base': INDEX['base'], 'status': 'running',
         'started': datetime.now(timezone.utc).isoformat(), 'commands': [],
         'scope': 'Source/Make/analysis review, maintained report/health tests and existing profiled native/request '
                  'unit products. No rebuild, eight-application Rust corpus repetition, complete final Make '
                  'gate, hosted/Linux validation or public language admission.'}
write('checks.json', state)
started = time.monotonic()
try:
    for index, command in enumerate(commands):
        then = time.monotonic()
        with (OUT / f'{index}.stdout').open('xb') as stdout, (OUT / f'{index}.stderr').open('xb') as stderr:
            result = subprocess.run(command, cwd=ROOT, env=environment, stdout=stdout, stderr=stderr, timeout=300)
        state['commands'].append({'argv': command, 'exit_code': result.returncode,
                                  'seconds': round(time.monotonic() - then, 3)})
        write('checks.json', state)
        assert result.returncode == 0, f'command {index} failed; retain original channels'
    native, rust = (OUT / '0.stdout').read_text(), (OUT / '1.stdout').read_text()
    assert all(name in native and name not in rust for name in ('otelc/native_launch.py', 'ci/native_launch_suite.py'))
    assert 'test_rust_sonar.py' in rust and 'build/rust-case.coverage' in rust
    state['status'] = 'passed'
except Exception as error:
    state.update(status='failed', error=repr(error))
finally:
    after = snapshot()
    write('inputs-after.json', after)
    state['preservation'] = {name: before[name] == after[name] for name in before}
    if not all(state['preservation'].values()):
        state['status'] = 'failed'
    state.update(seconds=round(time.monotonic() - started, 3), finished=datetime.now(timezone.utc).isoformat())
    write('checks.json', state)
    print(json.dumps(state, indent=2), flush=True)
    raise SystemExit(0 if state['status'] == 'passed' else 1)
