"""Run the exact frozen consumer gate and real native prepared workflow corpus."""
from datetime import datetime, timezone
import hashlib
import json
import os
from pathlib import Path
import shutil
import subprocess
import time

BASE = Path(__file__).resolve().parent
INDEX = json.loads((BASE / 'source-05e3130.json').read_text())
SOURCE = Path(INDEX['source'])
GATE = BASE.parent / 'native-public-generation/full-gate-0935585'
EXPECTED = json.loads((GATE / 'inputs-after.json').read_text())
SPEC = json.loads((GATE / 'command.json').read_text())
SDK = Path('/Users/sclarke/github/otelc-qualification/work/native-build-context')
GO_SDK = Path('/Users/sclarke/github/oteleq-qualification/2026-10-24/go-scope-provider/sdk-eda9fcc')
HELD = {'native_sdk': (SDK, EXPECTED['native_sdk']),
        'native_products': (Path('/'), EXPECTED['native_products']),
        'go_sdk': (GO_SDK, EXPECTED['go_sdk']),
        'weaver_source': (GO_SDK / 'build/go-upstream-scope/source', EXPECTED['weaver_source']),
        'tooling': (Path('/'), EXPECTED['tooling'])}
assert shutil.disk_usage(BASE).free >= 12 * 1024**3, 'prelaunch qualification headroom'
ROOT = BASE / 'exact-05e3130-02'
ROOT.mkdir(mode=0o700)
TARGET = ROOT / 'target'
subprocess.run(['/bin/cp', '-cR', str(GATE / 'target'), str(TARGET)], check=True)


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
assert all(before[key] == expected for key, (_, expected) in HELD.items()), 'held provider inputs changed'
write('inputs-before.json', before)
tools = SPEC['selected_tools']
rust = Path('/Users/sclarke/.rustup/toolchains/1.98.1-aarch64-apple-darwin/bin')
paths = [rust, *[Path(tools[name]).parent for name in ('OTELC_NODE', 'OTELC_CLANG', 'OTELC_JAVA', 'OTELC_GO')]]
environment = {key: value for key, value in os.environ.items()
               if not key.startswith(('OTEL', 'OTELEQ', 'GH_', 'GITHUB_', 'SONAR_', 'AWS_', 'PYTHON', 'COVERAGE_'))}
environment.update(tools)
environment.update(PATH=os.pathsep.join(map(str, paths)) + os.pathsep + environment.get('PATH', ''),
                   PYTHONDONTWRITEBYTECODE='1', CARGO_TARGET_DIR=str(TARGET))
python = SPEC['argv'][2].split('=', 1)[1]
cli = TARGET / 'debug/quux-oteleq'
state = {'head': INDEX['head'], 'status': 'running', 'started': datetime.now(timezone.utc).isoformat(),
         'source_files': len(INDEX['files']), 'commands': {}, 'free_bytes_before': shutil.disk_usage(BASE).free,
         'scope': 'Exact full local gate and normal-call native build3 project workflow corpus; broader project scope remains open.'}
write('status.json', state)
started = time.monotonic()
cli_before = None
try:
    commands = [('full-gate', SPEC['argv']), ('cargo-build', [str(rust / 'cargo'), 'build', '--locked']),
        ('prepared-qualification', [python, '-B', str(SOURCE / 'tests/qualify_native_project.py'),
            '--otelc-root', str(SDK), '--cli', str(cli), '--backend', 'prepared',
            '--sdk-build', str(SDK / 'build/context-sdk'), '--report-dir', str(ROOT / 'workflow'),
            '--min-free-bytes', str(8 * 1024**3)])]
    for name, argv in commands:
        assert shutil.disk_usage(BASE).free >= 8 * 1024**3, 'pre-command storage refusal: ' + name
        if name == 'prepared-qualification':
            cli_before = facts(cli); write('cli-input.json', cli_before)
        row = {'argv': argv, 'status': 'running', 'started': datetime.now(timezone.utc).isoformat(),
               'free_bytes_before': shutil.disk_usage(BASE).free}
        state['commands'][name] = row; write('status.json', state)
        begin = time.monotonic()
        with (ROOT / (name + '.stdout')).open('xb') as stdout, (ROOT / (name + '.stderr')).open('xb') as stderr:
            result = subprocess.run(argv, cwd=SOURCE, env=environment, stdout=stdout, stderr=stderr, timeout=10800)
        row.update(status='passed' if result.returncode == 0 else 'failed', exit_code=result.returncode,
                   seconds=round(time.monotonic() - begin, 3), finished=datetime.now(timezone.utc).isoformat(),
                   free_bytes_after=shutil.disk_usage(BASE).free)
        write('status.json', state)
        assert result.returncode == 0, name + ' failed; retain original evidence'
    state.update(status='passed', qualification=json.loads((ROOT / 'workflow/qualification.json').read_text()))
except Exception as error:
    state.update(status='failed', error=repr(error))
finally:
    try:
        after = inputs(); write('inputs-after.json', after)
        state['preservation'] = {name: before[name] == after[name] for name in before}
        if cli_before is not None:
            state['preservation']['cli'] = cli_before == facts(cli)
        if not all(state['preservation'].values()):
            state['status'] = 'failed'
    except OSError as error:
        state.update(status='failed', preservation_error=repr(error))
    state.update(seconds=round(time.monotonic() - started, 3), finished=datetime.now(timezone.utc).isoformat(),
                 free_bytes_after=shutil.disk_usage(BASE).free)
    write('status.json', state); print(json.dumps(state, indent=2), flush=True)
    raise SystemExit(0 if state['status'] == 'passed' else 1)
