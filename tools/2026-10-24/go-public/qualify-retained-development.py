"""Exercise retained and fresh-current-source routes for rebuilt Go workers."""

from datetime import datetime, timezone
import hashlib
import json
import os
from pathlib import Path
import shutil
import subprocess
import time

ROOT = Path('/Users/sclarke/github/oteleq-qualification/2026-10-24/go-public')
BASE = ROOT / 'retained-development-01'
CONSUMER = Path('/Users/sclarke/github/oteleq-qualification/work/oteleq-go-public-provider')
SDK = Path('/Users/sclarke/github/oteleq-qualification/2026-10-24/go-reuse-review-d2ec6bf/source')
ORIGINAL = ROOT / 'scalar-development-05'
WORKSPACE = Path(json.loads((ORIGINAL / 'status.json').read_text())['workspace'])
CLI = ROOT / 'target/debug/quux-oteleq'
PYTHON = Path('/Users/sclarke/github/oteleq-qualification/2026-10-24/python-live-metrics/env-312/bin/python')
GO = Path('/Users/sclarke/go/pkg/mod/golang.org/toolchain@v0.0.1-go1.27.3.darwin-arm64/bin/go')
CASE = '56dcc154c0a128a9296e-0'


def write(path, value):
    path.write_text(json.dumps(value, indent=2) + '\n')


def facts(path):
    info = path.stat()
    return {'sha256': hashlib.sha256(path.read_bytes()).hexdigest(), 'facts': [info.st_dev, info.st_ino,
        info.st_mode, info.st_uid, info.st_gid, info.st_size, info.st_mtime_ns, info.st_ctime_ns]}


def catalogue(root, names):
    return {name: facts(root / name) for name in names}


AUDIT = os.environ.get('OTELEQ_QUAL_AUDIT_RETAINED') == '1'
RESUME = os.environ.get('OTELEQ_QUAL_RESUME_PROMOTION') == '1' or AUDIT
BASE.mkdir(exist_ok=RESUME)
sdk_names = json.loads((SDK.parent / 'inputs-before.json').read_text())['files']
consumer_names = subprocess.check_output(['git', '-C', str(CONSUMER), 'ls-files', '-z']).decode().split('\0')[:-1]
toolchain = json.loads((SDK / 'build/go-upstream/toolchain.json').read_text())
tools = [SDK / 'build/go-upstream/toolchain.json', *[Path(toolchain[name]) for name in ('go', 'weaver', 'bundle')]]
before = {'sdk': catalogue(SDK, sdk_names), 'consumer': catalogue(CONSUMER, consumer_names),
          'tooling': {str(path): facts(path) for path in tools}, 'cli': facts(CLI)}
if RESUME:
    assert before == json.loads((BASE / 'inputs-before.json').read_text()), 'qualification inputs changed'
else:
    write(BASE / 'inputs-before.json', before)
environment = dict(os.environ, OTELEQ_PYTHON=str(PYTHON), OTELC_PYTHON=str(PYTHON), OTELC_GO=str(GO),
                   OTELEQ_WORKSPACE_PARENT=str(BASE), PYTHONDONTWRITEBYTECODE='1',
                   PATH=str(GO.parent) + os.pathsep + os.environ['PATH'])
state = {'status': 'running', 'started': datetime.now(timezone.utc).isoformat(), 'commands': [], 'routes': {}}
if RESUME:
    previous = json.loads((BASE / 'status.json').read_text())
    assert previous['status'] == 'failed'
    if AUDIT:
        assert previous['phase'] == 'promoted-framework-corrected' and previous['commands'][-1]['returncode'] == 0
        write(BASE / 'status-promotion-announcement-driver-failure.json', previous)
    else:
        assert previous['phase'] == 'promoted-framework' and previous['commands'][-1]['returncode'] == 2
        assert 'test_oteleq.py' in (BASE / 'promoted-framework-stderr').read_text()
        write(BASE / 'status-promotion-driver-failure.json', previous)
        shutil.copyfile(BASE / 'inputs-after.json', BASE / 'inputs-after-driver-failure.json')
    state['commands'], state['routes'] = previous['commands'], previous['routes']
    state['continued_after_driver_usage_error'] = True
seen_pids = set()


def execute(name, arguments, expected=0):
    marker = BASE / (name + '-command.json')
    assert not marker.exists(), 'inspect the previous operation before restarting it'
    write(marker, list(map(str, arguments)))
    state['phase'] = name
    write(BASE / 'status.json', state)
    started = time.monotonic()
    with (BASE / (name + '-stdout')).open('wb') as stdout, (BASE / (name + '-stderr')).open('wb') as stderr:
        result = subprocess.run(list(map(str, arguments)), cwd=CONSUMER, env=environment,
                                stdout=stdout, stderr=stderr, timeout=3600)
    state['commands'].append({'phase': name, 'returncode': result.returncode, 'seconds': round(time.monotonic() - started, 3)})
    write(BASE / 'status.json', state)
    assert result.returncode == expected, (name, result.returncode, expected)
    return (BASE / (name + '-stdout')).read_text().strip()


def check_report(path, result=22, expected_cases=1):
    report = json.loads(path.read_text())
    assert report['exit_code'] == 0 and report['source_preserved'] and report['blocked'] == []
    assert len(report['cases']) == expected_cases
    integer = lambda value: {'bits': 64, 'kind': 'integer', 'signed': True, 'type': 'go.int', 'value': str(value)}
    count = 0
    for case in report['cases']:
        assert case['exit_code'] == 0 and case['arguments'] == [21]
        for lane in ('baseline', 'instrumented_on'):
            for repeat in range(2):
                folder = path.parent / case['case'] / (lane + '-' + str(repeat))
                observation = json.loads((folder / 'typed-observation.json').read_text())
                function = observation['function_id']
                assert function in ('example.test/gopublic.Add', 'example.test/gopublic/extra.Add')
                root = 'global:Count' if '/extra.' in function else 'global:Total'
                assert observation['gaps'] == [] and observation['fixture'] == {'status': 'ready'}
                assert observation['before'] == {'nodes': [], 'roots': {root: integer(0)}}
                assert observation['after'] == {'nodes': [], 'roots': {root: integer(21)}}
                assert observation['outcome'] == {'kind': 'return', 'graph': {'nodes': [], 'roots': {root: integer(21), 'result': integer(result)}}}
                assert (folder / 'stdout').read_bytes() == (folder / 'stderr').read_bytes() == b''
                start = json.loads((folder / 'go-runtime/oteleq-go-start.json').read_text())
                app, supervisor = start['kernel']['application'], start['kernel']['supervisor']
                assert app['parent_pid'] == supervisor['pid'] == app['process_group'] == supervisor['process_group']
                assert app['pid'] not in seen_pids
                seen_pids.add(app['pid'])
                if lane == 'instrumented_on':
                    receipt = json.loads((folder / 'go-verified-telemetry.json').read_text())
                    assert receipt['functions'] == {function: 1} and receipt['sdk_pid'] == app['pid']
                    assert receipt['received']['spans'] == 1 and receipt['pending'] == 0
                    assert not any(receipt['losses'].values()) and receipt['health']['metric_exported_points'] is None
                count += 1
    return count


def framework(name, script, result=22, cases=1):
    raw = execute(name, [PYTHON, '-I', '-B', script])
    results = [json.loads(line) for line in raw.splitlines()]
    assert len(results) == cases
    return sum(check_report(Path(item['report']), result) for item in results)


def initial_routes():
    replay = json.loads(execute('replay', [CLI, 'replay', '--workspace', WORKSPACE, '--case', CASE]))
    state['routes']['replay'] = check_report(Path(replay['report']))
    state['routes']['generated_framework'] = framework('generated-framework', WORKSPACE / 'tests/test_equivalence.py')
    exported = BASE / 'exported'
    dry = json.loads(execute('export-dry', [CLI, 'export-tests', '--workspace', WORKSPACE, '--destination', exported]))
    assert dry['mode'] == 'dry-run' and 'go-source-provider' in dry['copy'] and not exported.exists()
    execute('export-apply', [CLI, 'export-tests', '--workspace', WORKSPACE, '--destination', exported, '--apply'])
    hidden = WORKSPACE.with_name(WORKSPACE.name + '-unavailable')
    WORKSPACE.rename(hidden)
    try:
        state['routes']['detached_framework'] = framework('detached-framework', exported / 'tests/test_equivalence.py')
    finally:
        hidden.rename(WORKSPACE)
    for control in ('changed-probe', 'missing-probe'):
        destination = BASE / control
        execute(control + '-export', [CLI, 'export-tests', '--workspace', exported, '--destination', destination, '--apply'])
        record = destination / 'go-source-provider/protocol/response.json'
        if control == 'changed-probe':
            record.write_bytes(record.read_bytes() + b' ')
        else:
            record.unlink()
        execute(control, [CLI, 'replay', '--workspace', destination, '--case', CASE], expected=4)
        assert b'frozen Go provider probes changed' in (BASE / (control + '-stderr')).read_bytes()
        assert not (destination / 'runs').exists()
    current = BASE / 'current-source'
    shutil.copytree(ORIGINAL / 'application', current)
    promoted = BASE / 'current-tests'
    dry = json.loads(execute('promote-dry', [CLI, 'promote', '--workspace', WORKSPACE, '--source', current, '--destination', promoted]))
    assert dry['mode'] == 'dry-run' and not promoted.exists()
    execute('promote-apply', [CLI, 'promote', '--workspace', WORKSPACE, '--source', current, '--destination', promoted, '--apply'])
    (current / 'main.go').write_text((current / 'main.go').read_text().replace('return Total+1', 'return Total+2'))
    (current / 'extra').mkdir()
    (current / 'extra/api.go').write_text('package extra\nvar Count int\nfunc Add(value int)int{Count=value;return value+2}\n')
    return current, promoted


try:
    if RESUME:
        replay = json.loads((BASE / 'replay-stdout').read_text())
        assert check_report(Path(replay['report'])) == 4
        for name in ('generated-framework', 'detached-framework'):
            results = [json.loads(line) for line in (BASE / (name + '-stdout')).read_text().splitlines()]
            assert len(results) == 1 and check_report(Path(results[0]['report'])) == 4
        current, promoted = BASE / 'current-source', BASE / 'current-tests'
        assert 'return Total+2' in (current / 'main.go').read_text()
        assert (current / 'extra/api.go').is_file()
    else:
        current, promoted = initial_routes()
    environment['OTELEQ_SOURCE'] = str(current)
    if AUDIT:
        records = [json.loads(line) for line in (BASE / 'promoted-framework-corrected-stdout').read_text().splitlines()]
        announcements = [row for row in records if 'project_source' in row]
        reports = [row for row in records if 'report' in row]
        assert len(records) == 3 and len(announcements) == 1 and len(reports) == 2
        assert announcements[0]['project_source'] == str(current)
        assert announcements[0]['claim'] == 'equivalence over these tests and observations'
        plan = json.loads((Path(announcements[0]['workspace']) / 'plan.json').read_text())
        assert {row['otelc_runtime_function'] for row in plan['inventory'] if row['status'] == 'ready'} == {
            'example.test/gopublic.Add', 'example.test/gopublic/extra.Add'}
        state['routes']['promoted_changed_and_added'] = sum(check_report(Path(row['report']), result=23) for row in reports)
        state['retained_only_audit'] = True
        state['new_applications_in_this_audit'] = 0
    else:
        state['routes']['promoted_changed_and_added'] = framework('promoted-framework-corrected', promoted / 'test_equivalence.py', result=23, cases=2)
    state['actual_applications'] = len(seen_pids)
    assert state['actual_applications'] == 20
    state['prelaunch_refusals'] = 2
    state['status'] = 'passed'
except Exception as error:
    state['status'], state['error'] = 'failed', repr(error)
finally:
    after = {'sdk': catalogue(SDK, sdk_names), 'consumer': catalogue(CONSUMER, consumer_names),
             'tooling': {str(path): facts(path) for path in tools}, 'cli': facts(CLI)}
    write(BASE / 'inputs-after.json', after)
    state['preservation'] = {name: before[name] == after[name] for name in before}
    if not all(state['preservation'].values()):
        state['status'] = 'failed'
    state['finished'] = datetime.now(timezone.utc).isoformat()
    write(BASE / 'status.json', state)
    print(json.dumps(state, indent=2), flush=True)
    raise SystemExit(0 if state['status'] == 'passed' else 1)
