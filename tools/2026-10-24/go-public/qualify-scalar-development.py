"""Exercise the public oteleq route against an independently extracted SDK."""

from datetime import datetime, timezone
import hashlib
import json
import os
from pathlib import Path
import subprocess
import sys
import time

NAME = sys.argv[1] if len(sys.argv) > 1 else 'scalar-development-02'
assert NAME.startswith('scalar-development-') and Path(NAME).name == NAME
BASE = Path('/Users/sclarke/github/oteleq-qualification/2026-10-24/go-public') / NAME
SDK = Path('/Users/sclarke/github/oteleq-qualification/2026-10-24/go-reuse-review-d2ec6bf/source')
CONSUMER = Path('/Users/sclarke/github/oteleq-qualification/work/oteleq-go-public-provider')
CLI = BASE.parent / 'target/debug/quux-oteleq'
PYTHON = Path('/Users/sclarke/github/oteleq-qualification/2026-10-24/python-live-metrics/env-312/bin/python')
GO = Path('/Users/sclarke/go/pkg/mod/golang.org/toolchain@v0.0.1-go1.27.3.darwin-arm64/bin/go')


def write(path, value):
    path.write_text(json.dumps(value, indent=2) + '\n')


def facts(path):
    data = path.read_bytes()
    info = path.stat()
    return {'sha256': hashlib.sha256(data).hexdigest(), 'facts': [info.st_dev, info.st_ino, info.st_mode,
        info.st_uid, info.st_gid, info.st_size, info.st_mtime_ns, info.st_ctime_ns]}


def catalogue(root, names):
    return {name: facts(root / name) for name in names}


BASE.mkdir(exist_ok=True)
application = BASE / 'application'
if not application.exists():
    application.mkdir()
    (application / 'go.mod').write_text('module example.test/gopublic\n\ngo 1.26.0\n')
    (application / 'main.go').write_text('package main\nvar Total int\nfunc Add(value int)int{Total+=value;return Total+1}\nfunc main(){}\n')
policy = BASE / 'equivalence.toml'
if not policy.exists():
    policy.write_text('''schema_version=1
languages=["go"]
[adapters.go]
backend="source-v1"
module_roots=["."]
build_timeout_ms=900000
[functions]
include=["*.Add"]
[limits]
baseline_repeats=2
instrumented_repeats=2
case_timeout_ms=30000
[[fixtures]]
function="*.Add"
cases=[[21]]
''')
sdk_index = json.loads((SDK.parent / 'inputs-before.json').read_text())
consumer_names = subprocess.check_output(['git', '-C', str(CONSUMER), 'ls-files', '-z']).decode().split('\0')[:-1]
toolchain = json.loads((SDK / 'build/go-upstream/toolchain.json').read_text())
tool_paths = [SDK / 'build/go-upstream/toolchain.json', *[Path(toolchain[name]) for name in ('go', 'weaver', 'bundle')]]
before = {'sdk': catalogue(SDK, sdk_index['files']), 'consumer': catalogue(CONSUMER, consumer_names),
          'application': catalogue(application, ['go.mod', 'main.go']), 'tooling': {str(path): facts(path) for path in tool_paths},
          'cli': facts(CLI)}
if (BASE / 'inputs-before.json').exists():
    assert before == json.loads((BASE / 'inputs-before.json').read_text()), 'original qualification inputs changed'
else:
    write(BASE / 'inputs-before.json', before)
environment = dict(os.environ, OTELEQ_PYTHON=str(PYTHON), OTELC_PYTHON=str(PYTHON), OTELC_GO=str(GO),
                   PYTHONDONTWRITEBYTECODE='1', PATH=str(GO.parent) + os.pathsep + os.environ['PATH'])
state = {'started': datetime.now(timezone.utc).isoformat(), 'status': 'running', 'commands': [],
         'sdk_head': sdk_index['head'], 'consumer_head': subprocess.check_output(['git', '-C', str(CONSUMER), 'rev-parse', 'HEAD']).decode().strip(),
         'consumer_has_uncommitted_fix': True, 'cli_sha256': before['cli']['sha256']}


def execute(name, arguments):
    started = time.monotonic()
    command = [str(CLI), *map(str, arguments)]
    write(BASE / (name + '-command.json'), command)
    state['phase'] = name
    write(BASE / 'status.json', state)
    with (BASE / (name + '-stdout')).open('wb') as stdout, (BASE / (name + '-stderr')).open('wb') as stderr:
        result = subprocess.run(command, env=environment, cwd=CONSUMER, stdout=stdout, stderr=stderr, timeout=1800)
    state['commands'].append({'phase': name, 'returncode': result.returncode, 'seconds': round(time.monotonic() - started, 3)})
    write(BASE / 'status.json', state)
    if result.returncode:
        raise RuntimeError(name + ' failed; inspect retained command/stdout/stderr')
    raw = (BASE / (name + '-stdout')).read_text()
    return {'workspace': raw.strip()} if name == 'plan' else json.loads(raw)


try:
    if (BASE / 'status.json').exists():
        previous = json.loads((BASE / 'status.json').read_text())
        assert previous['status'] == 'failed' and previous['commands'][-1]['phase'] == 'plan'
        assert previous['commands'][-1]['returncode'] == 0 and previous['error'].startswith('Expecting value')
        write(BASE / 'status-driver-parse-failure.json', previous)
        planned = {'workspace': (BASE / 'plan-stdout').read_text().strip()}
        state['commands'] = previous['commands']
        state['continued_existing_successful_plan'] = True
    else:
        planned = execute('plan', ['plan', '--source', application, '--otelc-root', SDK,
                                  '--config', policy, '--workspace-parent', BASE])
    state['plan'] = planned
    workspace = Path(planned['workspace'])
    state['workspace'] = str(workspace)
    state['generated'] = execute('generate', ['generate', '--workspace', workspace])
    state['run'] = execute('run', ['run', '--workspace', workspace, '--report-dir', BASE / 'report'])
    state['status'] = 'passed'
except Exception as error:
    state['status'], state['error'] = 'failed', str(error)
finally:
    after = {'sdk': catalogue(SDK, sdk_index['files']), 'consumer': catalogue(CONSUMER, consumer_names),
             'application': catalogue(application, ['go.mod', 'main.go']), 'tooling': {str(path): facts(path) for path in tool_paths},
             'cli': facts(CLI)}
    write(BASE / 'inputs-after.json', after)
    state['preservation'] = {name: before[name] == after[name] for name in before}
    if not all(state['preservation'].values()):
        state['status'] = 'failed'
        state['preservation_changed'] = [name for name in before if before[name] != after[name]]
    state['finished'] = datetime.now(timezone.utc).isoformat()
    write(BASE / 'status.json', state)
    print(json.dumps(state, indent=2), flush=True)
    raise SystemExit(0 if state['status'] == 'passed' else 1)
