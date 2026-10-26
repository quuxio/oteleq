"""Independently check the held Rust component without running an application corpus."""

from datetime import datetime, timezone
import hashlib
import json
import os
from pathlib import Path
import subprocess
import time

BASE = Path(__file__).resolve().parent
OUT = BASE / 'sdk-rust-review-2934455-checks-02'
INDEX = json.loads(Path('/Users/sclarke/github/otelc-qualification/2026-10-25/rust-native-bridge/source-2934455.json').read_text())
ROOT = Path(INDEX['root'])
PYTHON = '/Users/sclarke/github/oteleq-qualification/2026-10-24/python-live-metrics/env-312/bin/python'


def facts(path):
    stat = path.stat()
    with path.open('rb') as stream:
        digest = hashlib.file_digest(stream, 'sha256').hexdigest()
    return dict(sha256=digest, dev=stat.st_dev, ino=stat.st_ino, mode=stat.st_mode,
                size=stat.st_size, mtime_ns=stat.st_mtime_ns, ctime_ns=stat.st_ctime_ns)


def snapshot():
    return {'source': {name: facts(ROOT / name) for name in INDEX['files']},
            'products': {name: facts(Path(name)) for name in INDEX['products']}}


def write(name, value):
    (OUT / name).write_text(json.dumps(value, indent=2) + '\n')


OUT.mkdir(mode=0o700)
before = snapshot()
assert before == {'source': INDEX['files'], 'products': INDEX['products']}
write('inputs-before.json', before)
gate = Path(INDEX['gate'])
environment = {key: value for key, value in os.environ.items()
               if not key.startswith(('OTEL', 'OTELEQ', 'GH_', 'GITHUB_', 'AWS_', 'SONAR_', 'LLVM_PROFILE'))}
environment.update(PYTHONDONTWRITEBYTECODE='1', PYTHONPATH=str(ROOT) + os.pathsep + str(ROOT / 'tests'),
    OTELC_RUST_COMPONENT_OUTPUT=str(OUT / 'cases'),
    OTELC_RUSTC='/Users/sclarke/.rustup/toolchains/1.98.1-aarch64-apple-darwin/bin/rustc',
    OTELC_RUST_COMPILER=str(gate / 'compiler/debug/otelc-rust-compiler'),
    OTELC_RUST_BRIDGE=str(gate / 'bridge/release/libotelc_rust_bridge.rlib'),
    OTELC_NATIVE_SDK_BUILD=str(ROOT / 'build/rust-sdk'),
    LLVM_PROFILE_FILE=str(OUT / 'request-%m-%p.profraw'))
commands = [
    ['make', '-n', 'native-launch-check'],
    ['make', '-n', 'rust-compiler-check'],
    [str(gate / 'compiler/debug/deps/otelc_rust_compiler-66db3165364b61b2')],
    [PYTHON, '-m', 'unittest', 'test_health.HealthShapeTests',
     'ci.rust_compiler_cases.RustCompilerCases.test_wrong_compiler_entry_is_refused_in_both_modes',
     'ci.rust_compiler_cases.RustCompilerCases.test_unbound_module_and_unknown_selection_are_refused',
     'ci.rust_compiler_cases.RustCompilerCases.test_async_and_expanded_selected_bodies_refuse_before_codegen',
     'ci.rust_compiler_cases.RustCompilerCases.test_incompatible_bridge_hooks_refuse_without_a_compiler_crash', '-v'],
]
state = {'head': INDEX['head'], 'status': 'running', 'started': datetime.now(timezone.utc).isoformat(),
         'applications': 0, 'commands': [],
         'scope': 'Independent source/recipe review and existing request, compiler-refusal and health tests. '
                  'No application/runtime corpus, no public language admission.'}
started = time.monotonic()
write('checks.json', state)
try:
    for index, command in enumerate(commands):
        command_started = time.monotonic()
        with (OUT / f'{index}.stdout').open('xb') as stdout, (OUT / f'{index}.stderr').open('xb') as stderr:
            result = subprocess.run(command, cwd=ROOT, env=environment, stdout=stdout, stderr=stderr, timeout=600)
        state['commands'].append({'argv': command, 'exit_code': result.returncode,
                                  'seconds': round(time.monotonic() - command_started, 3)})
        write('checks.json', state)
        assert result.returncode == 0, f'check {index} failed; original channels retained'
    native = (OUT / '0.stdout').read_text()
    rust = (OUT / '1.stdout').read_text()
    state['make_finding_confirmed'] = ('--include=*/otelc/native_launch.py' not in native
        and '--include=*/ci/native_launch_suite.py' not in native
        and '--include=*/otelc/native_launch.py' in rust
        and '--include=*/ci/native_launch_suite.py' in rust)
    assert state['make_finding_confirmed']
    state['status'] = 'passed with confirmed recipe finding'
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
    write('checks.json', state)
    print(json.dumps(state, indent=2), flush=True)
    raise SystemExit(0 if state['status'] == 'passed with confirmed recipe finding' else 1)
