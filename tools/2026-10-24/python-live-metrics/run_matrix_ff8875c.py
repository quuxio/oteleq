"""Run independent frozen Python configurations; stop admission after any failure."""

from concurrent.futures import ThreadPoolExecutor, as_completed
import datetime
import hashlib
import json
import os
from pathlib import Path
import subprocess
import threading
import time

ROOT = Path(__file__).resolve().parent
OUTPUT = ROOT / 'matrix-ff8875c'
SOURCE = ROOT / 'qualification-source-ff8875c'
INDEX = json.loads((ROOT / 'source-ff8875c.json').read_text())
CLI = ROOT / 'runtime-build-5fd7a06/debug/quux-oteleq'
STARTS = ('both-on', 'collection-off', 'emission-off', 'both-off')
PROFILES = {'origins': 'python-native-origins-v2', 'caches': 'python-native-cache-origins-v3'}
STOP = threading.Event()
LOCK = threading.Lock()
STATUS = {}


def now():
    return datetime.datetime.now(datetime.timezone.utc).isoformat()


def save():
    temporary = OUTPUT / 'status.new.json'
    temporary.write_text(json.dumps(STATUS, indent=2) + '\n')
    temporary.replace(OUTPUT / 'status.json')


def run(runtime, profile, start):
    name = '-'.join((runtime, profile, start))
    with LOCK:
        if STOP.is_set():
            STATUS[name] = {'state': 'not_started_after_another_configuration_failed'}
            save()
            return False
        STATUS[name] = {'state': 'starting', 'at': now()}
        save()
    folder, audit = OUTPUT / 'runs' / name, OUTPUT / 'audits' / name
    argv = [str(ROOT / ('env-' + runtime) / 'bin/python'), '-B',
        str(SOURCE / 'tests/qualify_python_controls.py'),
        '--otelc-root', str(ROOT / ('provider-ce4-' + runtime)),
        '--report-dir', str(folder), '--audit-dir', str(audit), '--cli', str(CLI),
        '--profile', PROFILES[profile], '--startup-state', start]
    spec = {'argv': argv, 'cwd': str(SOURCE), 'qualifier_head': INDEX['head'],
        'runtime_head': '5fd7a06bb0186f1e62601a6c9a3be6bbc7a43562',
        'runtime_sha256': hashlib.sha256(CLI.read_bytes()).hexdigest()}
    with (OUTPUT / 'commands' / (name + '.json')).open('x') as handle:
        json.dump(spec, handle, indent=2)
    environment = {key: value for key, value in os.environ.items()
        if not key.startswith(('OTEL', 'GH_', 'GITHUB_', 'SONAR_', 'AWS_'))}
    environment['PYTHONDONTWRITEBYTECODE'] = '1'
    started = time.monotonic()
    with (OUTPUT / 'logs' / (name + '.log')).open('xb') as log:
        process = subprocess.Popen(argv, cwd=SOURCE, env=environment, stdout=log, stderr=subprocess.STDOUT)
        with LOCK:
            STATUS[name].update(state='running', qualifier_pid=process.pid)
            save()
        code = process.wait()
    changed = [name for name, digest in INDEX['files'].items()
        if hashlib.sha256((SOURCE / name).read_bytes()).hexdigest() != digest]
    result = {'exit_code': code, 'seconds': round(time.monotonic() - started, 3),
        'qualifier_source_held': not changed, 'changed': changed, 'qualifier_head': INDEX['head']}
    okay = code == 0 and not changed
    if not okay:
        STOP.set()
    (OUTPUT / 'results' / (name + '.json')).write_text(json.dumps(result, indent=2) + '\n')
    with LOCK:
        STATUS[name].update(state='passed' if okay else 'failed', result=result, finished=now())
        save()
    print(json.dumps({'configuration': name, **result}), flush=True)
    return okay


def main():
    assert len(INDEX['files']) == 518
    assert all(hashlib.sha256((SOURCE / name).read_bytes()).hexdigest() == digest
               for name, digest in INDEX['files'].items())
    OUTPUT.mkdir(mode=0o700)
    for name in ('runs', 'audits', 'commands', 'logs', 'results'):
        (OUTPUT / name).mkdir(mode=0o700)
    configurations = [(runtime, profile, start) for start in STARTS
                      for runtime in ('312', '314') for profile in PROFILES
                      if (runtime, profile, start) != ('312', 'origins', 'both-off')]
    assert len(configurations) == 15
    (OUTPUT / 'plan.json').write_text(json.dumps({
        'qualifier_head': INDEX['head'], 'runtime_head': '5fd7a06bb0186f1e62601a6c9a3be6bbc7a43562',
        'configurations': configurations, 'max_parallel_configurations': 4,
        'existing_separate_configuration': 'qualification-312-origins-both-off-attempt01',
        'note': 'The earlier configuration is a separate live process; this runner does not restart it. '
                'No failed or partial configuration is automatically retried. Results are diagnostic only.'}, indent=2) + '\n')
    with ThreadPoolExecutor(max_workers=4) as pool:
        results = [future.result() for future in as_completed([pool.submit(run, *row) for row in configurations])]
    successful = sum(results)
    print(json.dumps({'successful_configurations': successful, 'requested_configurations': len(configurations)}), flush=True)
    raise SystemExit(0 if successful == len(configurations) else 1)


if __name__ == '__main__':
    main()
