"""Reduce a real source-provider receiver difference and replay its final suite."""

from datetime import datetime, timezone
import hashlib
import json
import os
from pathlib import Path
import subprocess
import sys
import time

ROOT = Path('/Users/sclarke/github/oteleq-qualification/2026-10-24/go-public')
BASE = ROOT / 'shrink-development-01'
CONSUMER = Path('/Users/sclarke/github/oteleq-qualification/work/oteleq-go-public-provider')
SDK = Path('/Users/sclarke/github/oteleq-qualification/2026-10-24/go-reuse-review-d2ec6bf/source')
sys.path[:0] = [str(CONSUMER / 'tests'), str(CONSUMER / 'examples')]
import qualify_go_receivers as oracle

CLI = ROOT / 'target/debug/quux-oteleq'
PYTHON = Path('/Users/sclarke/github/oteleq-qualification/2026-10-24/python-live-metrics/env-312/bin/python')
GO = Path('/Users/sclarke/go/pkg/mod/golang.org/toolchain@v0.0.1-go1.27.3.darwin-arm64/bin/go')
WORKSPACE = Path(json.loads((ROOT / 'receiver-development-01/status.json').read_text())['workspace'])
CASE = '4d8b2990ec67bbd075dd-0'


def write(path, value):
    path.write_text(json.dumps(value, indent=2) + '\n')


def facts(path):
    info = path.stat()
    return {'sha256': hashlib.sha256(path.read_bytes()).hexdigest(), 'facts': [info.st_dev, info.st_ino,
        info.st_mode, info.st_uid, info.st_gid, info.st_size, info.st_mtime_ns, info.st_ctime_ns]}


def catalogue(root, names):
    return {name: facts(root / name) for name in names}


BASE.mkdir()
sdk_names = json.loads((SDK.parent / 'inputs-before.json').read_text())['files']
consumer_names = subprocess.check_output(['git', '-C', str(CONSUMER), 'ls-files', '-z']).decode().split('\0')[:-1]
tools = json.loads((SDK / 'build/go-upstream/toolchain.json').read_text())
paths = [SDK / 'build/go-upstream/toolchain.json', *[Path(tools[name]) for name in ('go', 'weaver', 'bundle')]]
before = {'sdk': catalogue(SDK, sdk_names), 'consumer': catalogue(CONSUMER, consumer_names),
          'tooling': {str(path): facts(path) for path in paths}, 'cli': facts(CLI)}
write(BASE / 'inputs-before.json', before)
environment = dict(os.environ, OTELEQ_PYTHON=str(PYTHON), OTELC_PYTHON=str(PYTHON), OTELC_GO=str(GO),
                   PYTHONDONTWRITEBYTECODE='1', PATH=str(GO.parent) + os.pathsep + os.environ['PATH'])
state = {'status': 'running', 'started': datetime.now(timezone.utc).isoformat(), 'commands': []}
seen = set()


def execute(name, arguments, expected):
    state['phase'] = name
    write(BASE / 'status.json', state)
    write(BASE / (name + '-command.json'), list(map(str, arguments)))
    started = time.monotonic()
    with (BASE / (name + '-stdout')).open('wb') as stdout, (BASE / (name + '-stderr')).open('wb') as stderr:
        result = subprocess.run(list(map(str, arguments)), cwd=CONSUMER, env=environment,
                                stdout=stdout, stderr=stderr, timeout=3600)
    state['commands'].append({'phase': name, 'returncode': result.returncode, 'seconds': round(time.monotonic() - started, 3)})
    write(BASE / 'status.json', state)
    assert result.returncode == expected, (name, result.returncode, expected)
    return (BASE / (name + '-stdout')).read_text().strip()


def check_report(path, argument):
    report = json.loads(path.read_text())
    assert report['exit_code'] == 1 and report['source_preserved'] and not report['blocked'] and len(report['cases']) == 1
    case = report['cases'][0]
    assert case['exit_code'] == 1 and case['arguments'] == [argument]
    folder = path.parent / case['case']
    bundle = json.loads((folder / 'typed-bundle.json').read_text())['cases'][0]
    for lane in ('baseline', 'instrumented_on'):
        assert len(bundle[lane]) == 2
        for repeat, attempt in enumerate(bundle[lane]):
            observation = attempt['observation']
            assert not observation['gaps']
            oracle.state(observation['before'], 'InstanceDifference', argument, lane, after=False)
            oracle.state(observation['after'], 'InstanceDifference', argument, lane, after=True)
            oracle.state(observation['outcome']['graph'], 'InstanceDifference', argument, lane, after=True)
            assert observation['outcome']['kind'] == 'return'
            assert observation['outcome']['graph']['roots']['result']['value'] == '7'
            attempt_folder = folder / (lane + '-' + str(repeat))
            assert (attempt_folder / 'stdout').read_bytes() == (attempt_folder / 'stderr').read_bytes() == b''
            request = json.loads((attempt_folder / 'go-runtime/go-request.json').read_text())
            assert request['launch_id'] not in seen
            seen.add(request['launch_id'])
            if lane == 'instrumented_on':
                receipt = json.loads((attempt_folder / 'go-verified-telemetry.json').read_text())
                assert receipt['functions'] == {'example.test/receiver/counter.Counter.InstanceDifference': 1,
                                                 'example.test/receiver/counter.New': 1}
                assert receipt['pending'] == 0 and not any(receipt['losses'].values())


try:
    summary = json.loads(execute('shrink', [CLI, 'shrink', '--workspace', WORKSPACE, '--case', CASE,
        '--report-dir', BASE / 'reduction', '--trials', 2], expected=1))
    state['summary'] = summary
    record = json.loads((BASE / 'reduction/shrink.json').read_text())
    write(BASE / 'retained-shrink-record.json', record)
    # The final replay workspace is supplied by the successful public operation.
    reduced = Path(summary['workspace'])
    case = json.loads((reduced / 'tests/corpus.json').read_text())[0]
    assert case['arguments'] == [0]
    assert (reduced / 'go-source-provider').is_dir()
    for path in sorted((BASE / 'reduction').glob('**/report.json')):
        report = json.loads(path.read_text())
        assert len(report['cases']) == 1
        check_report(path, report['cases'][0]['arguments'][0])
    replay = json.loads(execute('replay', [CLI, 'replay', '--workspace', reduced, '--case', case['id']], expected=1))
    check_report(Path(replay['report']), 0)
    exported = BASE / 'exported'
    execute('export', [CLI, 'export-tests', '--workspace', reduced, '--destination', exported, '--apply'], expected=0)
    raw = execute('framework', [PYTHON, '-I', '-B', exported / 'tests/test_equivalence.py'], expected=1)
    results = [json.loads(line) for line in raw.splitlines()]
    assert len(results) == 1
    check_report(Path(results[0]['report']), 0)
    state['actual_applications'] = len(seen)
    assert len(seen) >= 20
    state['original_argument'], state['reduced_argument'] = 3, 0
    state['status'] = 'passed'
except Exception as error:
    state['status'], state['error'] = 'failed', repr(error)
finally:
    after = {'sdk': catalogue(SDK, sdk_names), 'consumer': catalogue(CONSUMER, consumer_names),
             'tooling': {str(path): facts(path) for path in paths}, 'cli': facts(CLI)}
    write(BASE / 'inputs-after.json', after)
    state['preservation'] = {name: before[name] == after[name] for name in before}
    if not all(state['preservation'].values()):
        state['status'] = 'failed'
    state['finished'] = datetime.now(timezone.utc).isoformat()
    write(BASE / 'status.json', state)
    print(json.dumps(state, indent=2), flush=True)
    raise SystemExit(0 if state['status'] == 'passed' else 1)
