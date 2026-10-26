"""Audit successful completed configurations only; never restart an execution."""

import datetime
import hashlib
import json
import os
from pathlib import Path
import subprocess
import time

ROOT = Path(__file__).resolve().parent
SOURCE = ROOT / 'qualification-source-7495d31'
OUTPUT = ROOT / 'final-audits-7495d31'
INDEX = json.loads((ROOT / 'source-7495d31.json').read_text())
CLI = ROOT / 'runtime-build-7495d31/debug/quux-oteleq'
PROFILES = {'origins': 'python-native-origins-v2', 'caches': 'python-native-cache-origins-v3'}
STARTS = ('both-on', 'collection-off', 'emission-off', 'both-off')


def audit(name, runtime, profile, start, evidence):
    argv = [str(ROOT / ('env-' + runtime) / 'bin/python'), '-B',
        str(SOURCE / 'tests/qualify_python_controls.py'), '--retained-only',
        '--otelc-root', str(ROOT / ('provider-ce4-' + runtime)),
        '--report-dir', str(evidence), '--audit-dir', str(OUTPUT / 'audits' / name),
        '--cli', str(CLI), '--profile', PROFILES[profile], '--startup-state', start]
    marker = OUTPUT / 'commands' / (name + '.json')
    with marker.open('x') as handle:
        json.dump({'argv': argv, 'cwd': str(SOURCE), 'auditor_head': INDEX['head']}, handle, indent=2)
    environment = {key: value for key, value in os.environ.items()
        if not key.startswith(('OTEL', 'GH_', 'GITHUB_', 'SONAR_', 'AWS_'))}
    environment['PYTHONDONTWRITEBYTECODE'] = '1'
    started = time.monotonic()
    with (OUTPUT / 'logs' / (name + '.log')).open('xb') as log:
        process = subprocess.Popen(argv, cwd=SOURCE, env=environment, stdout=log, stderr=subprocess.STDOUT)
        (OUTPUT / 'live.json').write_text(json.dumps({'configuration': name, 'auditor_pid': process.pid}) + '\n')
        code = process.wait()
    changed = [path for path, digest in INDEX['files'].items()
        if hashlib.sha256((SOURCE / path).read_bytes()).hexdigest() != digest]
    result = {'configuration': name, 'exit_code': code, 'seconds': round(time.monotonic() - started, 3),
              'auditor_source_held': not changed, 'changed': changed, 'auditor_head': INDEX['head']}
    (OUTPUT / 'results' / (name + '.json')).write_text(json.dumps(result, indent=2) + '\n')
    (OUTPUT / 'live.json').unlink()
    print(json.dumps(result), flush=True)
    return code == 0 and not changed


def main():
    assert len(INDEX['files']) == 518
    assert all(hashlib.sha256((SOURCE / name).read_bytes()).hexdigest() == digest
               for name, digest in INDEX['files'].items())
    OUTPUT.mkdir(mode=0o700)
    for name in ('audits', 'commands', 'logs', 'results'):
        (OUTPUT / name).mkdir(mode=0o700)
    pending = {(runtime, profile, start) for runtime in ('312', '314') for profile in PROFILES for start in STARTS}
    completed = []
    while pending:
        blocked = []
        for runtime, profile, start in sorted(pending):
            name = '-'.join((runtime, profile, start))
            result_path = ROOT / 'matrix-7495d31/results' / (name + '.json')
            if not result_path.exists():
                continue
            result = json.loads(result_path.read_text())
            if result['exit_code'] != 0 or result['changed']:
                blocked.append(name)
                continue
            evidence = ROOT / 'matrix-7495d31/runs' / name
            if not audit(name, runtime, profile, start, evidence):
                raise SystemExit(1)
            completed.append(name)
            pending.remove((runtime, profile, start))
            break
        else:
            (OUTPUT / 'waiting.json').write_text(json.dumps({'completed': completed,
                'pending': sorted('-'.join(row) for row in pending), 'failed_execution_needs_review': blocked,
                'at': datetime.datetime.now(datetime.timezone.utc).isoformat()}, indent=2) + '\n')
            if len(blocked) == len(pending):
                raise SystemExit('All remaining completed executions require failure review; none restarted.')
            time.sleep(2)
    (OUTPUT / 'complete.json').write_text(json.dumps({'completed': completed, 'configurations': len(completed),
        'auditor_head': INDEX['head'], 'new_target_applications': 0}, indent=2) + '\n')
    print(json.dumps({'audited_configurations': len(completed), 'new_target_applications': 0}), flush=True)


if __name__ == '__main__':
    main()
