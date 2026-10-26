"""Run one startup corpus with held inputs and explicit storage headroom."""
from datetime import datetime, timezone
import hashlib
import json
import os
from pathlib import Path
import shutil
import subprocess
import time

BASE = Path(__file__).resolve().parent
SOURCE = BASE / 'source-cb08b82'
ROOT = BASE / 'collection-off-cb08b82-01'
GATE = BASE / 'full-gate-cb08b82'
HEAD = 'cb08b8267d70be6e578f9f76089f7a60f3a8b3cb'
assert json.loads((GATE / 'status.json').read_text())['status'] == 'passed'
EXPECTED = json.loads((GATE / 'inputs-after.json').read_text())
SDK = Path('/Users/sclarke/github/oteleq-qualification/2026-10-24/go-scope-provider/sdk-eda9fcc')
WEAVER = SDK / 'build/go-upstream-scope/source'
assert shutil.disk_usage(BASE).free >= 12 * 1024**3
ROOT.mkdir(mode=0o700)
TARGET = BASE / 'target-cb08b82-collection-off'
assert not TARGET.exists()
subprocess.run(['/bin/cp', '-cR', str(GATE / 'target'), str(TARGET)], check=True)


def facts(path):
    state = path.stat()
    return [hashlib.file_digest(path.open('rb'), 'sha256').hexdigest(), state.st_dev,
            state.st_ino, state.st_mode, state.st_size, state.st_mtime_ns, state.st_ctime_ns]


def inputs():
    return {'consumer': {name: facts(SOURCE / name) for name in EXPECTED['consumer']},
            'sdk': {name: facts(SDK / name) for name in EXPECTED['sdk']},
            'weaver_source': {name: facts(WEAVER / name) for name in EXPECTED['weaver_source']},
            'tooling': {name: facts(Path(name)) for name in EXPECTED['tooling']}}


def write(name, value):
    (ROOT / name).write_text(json.dumps(value, indent=2) + '\n')


before = inputs(); assert before == EXPECTED
write('inputs-before.json', before)
spec = json.loads((GATE / 'command.json').read_text())
tools = spec['selected_tools']
rust = Path('/Users/sclarke/.rustup/toolchains/1.98.1-aarch64-apple-darwin/bin')
paths = [rust, *[Path(tools[name]).parent for name in ['OTELC_NODE', 'OTELC_CLANG', 'OTELC_JAVA', 'OTELC_GO']]]
env = {key: value for key, value in os.environ.items() if not key.startswith(('OTEL', 'OTELEQ', 'GH_', 'GITHUB_', 'SONAR_', 'AWS_'))}
env.update(tools)
env.update(PATH=os.pathsep.join(map(str, paths)) + os.pathsep + env.get('PATH', ''),
           PYTHONDONTWRITEBYTECODE='1', CARGO_TARGET_DIR=str(TARGET))
state = {'head': HEAD, 'status': 'running', 'started': datetime.now(timezone.utc).isoformat(),
         'startup': 'collection-off', 'commands': {}, 'free_bytes_before': shutil.disk_usage(BASE).free,
         'scope': 'One serial startup corpus only. Other startup states remain separate.'}
write('status.json', state)
started = time.monotonic()
cli = TARGET / 'debug/quux-oteleq'
cli_before = None
try:
    commands = [('cargo-build', [str(rust / 'cargo'), 'build', '--locked'], SOURCE),
                ('qualification', [spec['argv'][2].split('=', 1)[1], '-B', str(SOURCE / 'tests/qualify_go_controls.py'),
                    '--otelc-root', str(SDK), '--cli', str(cli), '--startup-state', 'collection-off',
                    '--report-dir', str(ROOT / 'workflow'), '--audit-dir', str(ROOT / 'audit'),
                    '--min-free-bytes', str(8 * 1024**3), '--cache-max-bytes', str(512 * 1024**2)], SOURCE)]
    for name, argv, directory in commands:
        if name == 'qualification':
            cli_before = facts(cli); write('cli-input.json', cli_before)
        row = {'argv': argv, 'status': 'running', 'free_bytes_before': shutil.disk_usage(BASE).free,
               'started': datetime.now(timezone.utc).isoformat()}
        state['commands'][name] = row; write('status.json', state)
        begin = time.monotonic()
        with (ROOT / (name + '.stdout')).open('xb') as out, (ROOT / (name + '.stderr')).open('xb') as err:
            result = subprocess.run(argv, cwd=directory, env=env, stdout=out, stderr=err, timeout=7200)
        row.update(exit_code=result.returncode, status='passed' if result.returncode == 0 else 'failed',
                   seconds=round(time.monotonic() - begin, 3), free_bytes_after=shutil.disk_usage(BASE).free,
                   finished=datetime.now(timezone.utc).isoformat())
        write('status.json', state)
        assert result.returncode == 0, name + ' failed; preserve original outputs'
    state.update(status='passed', qualification=json.loads((ROOT / 'audit/QUALIFICATION.json').read_text()))
except Exception as error:
    state.update(status='failed', error=repr(error))
finally:
    try:
        after = inputs(); write('inputs-after.json', after)
        state['preservation'] = {name: before[name] == after[name] for name in before}
        if cli_before is not None: state['preservation']['cli'] = cli_before == facts(cli)
        if not all(state['preservation'].values()): state['status'] = 'failed'
    except OSError as error:
        state.update(status='failed', preservation_error=repr(error))
    state.update(seconds=round(time.monotonic() - started, 3), free_bytes_after=shutil.disk_usage(BASE).free,
                 finished=datetime.now(timezone.utc).isoformat())
    write('status.json', state); print(json.dumps(state, indent=2), flush=True)
    raise SystemExit(0 if state['status'] == 'passed' else 1)
