"""Check the public rebuilt Go route against the existing receiver oracle."""

from datetime import datetime, timezone
import hashlib
import json
import os
from pathlib import Path
import subprocess
import sys
import time

CONSUMER = Path('/Users/sclarke/github/oteleq-qualification/work/oteleq-go-public-provider')
sys.path[:0] = [str(CONSUMER / 'tests'), str(CONSUMER / 'examples')]
import qualify_go_receivers as oracle

BASE = Path('/Users/sclarke/github/oteleq-qualification/2026-10-24/go-public/receiver-development-01')
SDK = Path('/Users/sclarke/github/oteleq-qualification/2026-10-24/go-reuse-review-d2ec6bf/source')
CLI = BASE.parent / 'target/debug/quux-oteleq'
PYTHON = Path('/Users/sclarke/github/oteleq-qualification/2026-10-24/python-live-metrics/env-312/bin/python')
GO = Path('/Users/sclarke/go/pkg/mod/golang.org/toolchain@v0.0.1-go1.27.3.darwin-arm64/bin/go')


def write(path, value):
    path.write_text(json.dumps(value, indent=2) + '\n')


def facts(path):
    info = path.stat()
    return {'sha256': hashlib.sha256(path.read_bytes()).hexdigest(), 'facts': [info.st_dev, info.st_ino,
        info.st_mode, info.st_uid, info.st_gid, info.st_size, info.st_mtime_ns, info.st_ctime_ns]}


def catalogue(root, names):
    return {name: facts(root / name) for name in names}


BASE.mkdir()
application = BASE / 'application'
(application / 'counter').mkdir(parents=True)
(application / 'cmd').mkdir()
(application / 'go.mod').write_text('module example.test/receiver\n\ngo 1.27.2\n')
(application / 'counter/api.go').write_text(oracle.SOURCE)
(application / 'cmd/api.go').write_text(oracle.SOURCE.replace('package counter', 'package main')
    + '\nfunc main(){}\nfunc (value Counter) Main(amount Number)Counter{value.value+=amount;return value}\n')
policy = BASE / 'equivalence.toml'
policy.write_text(oracle.policy_text().replace('[adapters.go]\n', '[adapters.go]\nbackend="source-v1"\nbuild_timeout_ms=900000\n'))
sdk_names = json.loads((SDK.parent / 'inputs-before.json').read_text())['files']
consumer_names = subprocess.check_output(['git', '-C', str(CONSUMER), 'ls-files', '-z']).decode().split('\0')[:-1]
toolchain = json.loads((SDK / 'build/go-upstream/toolchain.json').read_text())
tool_paths = [SDK / 'build/go-upstream/toolchain.json', *[Path(toolchain[name]) for name in ('go', 'weaver', 'bundle')]]
app_names = ['go.mod', 'counter/api.go', 'cmd/api.go']
before = {'sdk': catalogue(SDK, sdk_names), 'consumer': catalogue(CONSUMER, consumer_names),
          'application': catalogue(application, app_names), 'tooling': {str(path): facts(path) for path in tool_paths}, 'cli': facts(CLI)}
write(BASE / 'inputs-before.json', before)
environment = dict(os.environ, OTELEQ_PYTHON=str(PYTHON), OTELC_PYTHON=str(PYTHON), OTELC_GO=str(GO),
                   PYTHONDONTWRITEBYTECODE='1', PATH=str(GO.parent) + os.pathsep + os.environ['PATH'])
state = {'started': datetime.now(timezone.utc).isoformat(), 'status': 'running', 'commands': [],
         'consumer_head': subprocess.check_output(['git', '-C', str(CONSUMER), 'rev-parse', 'HEAD']).decode().strip(),
         'sdk_head': 'd2ec6bf9c7c73db9e9864f758c28cfd305ce0903', 'cli_sha256': before['cli']['sha256']}


def execute(name, arguments, expected=0):
    started = time.monotonic()
    command = [str(CLI), *map(str, arguments)]
    write(BASE / (name + '-command.json'), command)
    state['phase'] = name
    write(BASE / 'status.json', state)
    with (BASE / (name + '-stdout')).open('wb') as stdout, (BASE / (name + '-stderr')).open('wb') as stderr:
        result = subprocess.run(command, env=environment, cwd=CONSUMER, stdout=stdout, stderr=stderr, timeout=7200)
    state['commands'].append({'phase': name, 'returncode': result.returncode, 'seconds': round(time.monotonic() - started, 3)})
    write(BASE / 'status.json', state)
    assert result.returncode == expected, (name, result.returncode, expected)
    return (BASE / (name + '-stdout')).read_text().strip()


def check_report(report_path, entries):
    report = json.loads(report_path.read_text())
    assert report['source_preserved'] and report['blocked'] == [] and len(report['cases']) == 9
    pids, sdk_pids = set(), set()
    differences = {'InstanceDifference', 'GlobalDifference', 'AliasDifference'}
    for case in report['cases']:
        entry = next(row for row in entries if row['otelc_function'] == case['function'])
        method = entry['name'].rsplit('.', 1)[-1]
        assert case['exit_code'] == int(method in differences), case
        expected_functions = {entry['otelc_runtime_function']: 1,
                              entry['go_context']['import_path'] + '.' + entry['receiver_fixture']['factory']: 1}
        case_folder = report_path.parent / case['case']
        bundle = json.loads((case_folder / 'typed-bundle.json').read_text())['cases'][0]
        for lane in ('baseline', 'instrumented_on'):
            assert len(bundle[lane]) == 2
            for repeat, attempt in enumerate(bundle[lane]):
                observation = attempt['observation']
                assert observation['gaps'] == [] and observation['function_id'] == entry['otelc_runtime_function']
                oracle.state(observation['before'], method, 3, lane, after=False)
                oracle.state(observation['after'], method, 3, lane, after=True)
                oracle.state(observation['outcome']['graph'], method, 3, lane, after=True)
                outcome = observation['outcome']
                if method == 'Fail':
                    assert outcome['kind'] == 'error' and outcome['category'] == 'panic'
                    assert outcome['graph']['roots']['error'] == {'kind': 'string', 'type': 'go.string', 'encoding': 'raw_bytes', 'value': '6b6e6f776e'}
                else:
                    assert outcome['kind'] == 'return'
                    result = outcome['graph']['roots']['result']
                    if method == 'Add':
                        assert result == outcome['graph']['roots']['receiver']
                    elif method == 'Main':
                        oracle.copied_result(outcome['graph'], 3)
                    elif method == 'Void':
                        assert result == {'kind': 'undefined'}
                    else:
                        expected = 13 if method == 'Copy' else 3 if method == 'Read' else 7
                        assert result['kind'] == 'integer' and result['value'] == str(expected)
                folder = case_folder / (lane + '-' + str(repeat))
                assert (folder / 'stdout').read_bytes() == (folder / 'stderr').read_bytes() == b''
                start = json.loads((folder / 'go-runtime/oteleq-go-start.json').read_text())
                app, supervisor = start['kernel']['application'], start['kernel']['supervisor']
                assert app['parent_pid'] == supervisor['pid'] == app['process_group'] == supervisor['process_group']
                assert app['pid'] not in pids
                pids.add(app['pid'])
                if lane == 'instrumented_on':
                    receipt = json.loads((folder / 'go-verified-telemetry.json').read_text())
                    assert receipt['functions'] == expected_functions and receipt['sdk_pid'] == app['pid']
                    assert receipt['pending'] == 0 and not any(receipt['losses'].values())
                    assert receipt['received']['spans'] == 2 and receipt['health']['metric_exported_points'] is None
                    sdk_pids.add(app['pid'])
                    witness = attempt['execution']['witness']
                    assert set(witness) == {'decoder', 'raw_otlp_sha256', 'functions', 'spans', 'losses', 'pending'}
                    assert witness['functions'] == expected_functions
                else:
                    assert attempt['execution']['witness'] is None
    assert len(pids) == 36 and len(sdk_pids) == 18
    return {'actual_applications': len(pids), 'actual_sdk_processes': len(sdk_pids), 'cases': 9,
            'same_return_mutation_differences': sorted(differences), 'complete_literal_observations_checked': 36}


try:
    workspace = Path(execute('plan', ['plan', '--source', application, '--otelc-root', SDK,
        '--config', policy, '--workspace-parent', BASE]))
    state['workspace'] = str(workspace)
    plan = json.loads((workspace / 'plan.json').read_text())
    entries = [row for row in plan['inventory'] if row['status'] == 'ready']
    assert len(entries) == 9 and not any(row['status'] == 'blocked' for row in plan['inventory'])
    execute('generate', ['generate', '--workspace', workspace])
    execute('run', ['run', '--workspace', workspace, '--report-dir', BASE / 'report'], expected=1)
    state['independent_result'] = check_report(BASE / 'report/report.json', entries)
    state['status'] = 'passed'
except Exception as error:
    state['status'], state['error'] = 'failed', repr(error)
finally:
    after = {'sdk': catalogue(SDK, sdk_names), 'consumer': catalogue(CONSUMER, consumer_names),
             'application': catalogue(application, app_names), 'tooling': {str(path): facts(path) for path in tool_paths}, 'cli': facts(CLI)}
    write(BASE / 'inputs-after.json', after)
    state['preservation'] = {name: before[name] == after[name] for name in before}
    if not all(state['preservation'].values()):
        state['status'] = 'failed'
    state['finished'] = datetime.now(timezone.utc).isoformat()
    write(BASE / 'status.json', state)
    print(json.dumps(state, indent=2), flush=True)
    raise SystemExit(0 if state['status'] == 'passed' else 1)
