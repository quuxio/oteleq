"""Run immutable Java startup experiments in cohorts of at most four."""
from concurrent.futures import ThreadPoolExecutor, as_completed
import datetime
import hashlib
import json
import os
from pathlib import Path
import subprocess
import threading

ROOT = Path(__file__).resolve().parent
HEAD = 'bb1fb9696abea1b57b9b1e2ad605c5614f92c387'
SOURCE = ROOT / 'source-bb1fb96'
CLI = ROOT / 'quux-oteleq-bb1fb96'
PYTHON = '/Users/sclarke/github/oteleq-qualification/2026-10-22/node-source-consumer-0f05020/validation-hash-env/bin/python'
RECEIPT = ROOT / 'matrix-bb1fb96.json'
STARTS = ('both-on', 'collection-off', 'emission-off', 'both-off')
LOCK = threading.Lock()


def now():
    return datetime.datetime.now(datetime.UTC).isoformat()


def digest(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()


def preserved(expected):
    for row in expected['providers']:
        provider = Path(row['provider'])
        paths = list(provider.rglob('*'))
        assert not row['symlinks'] and not any(path.is_symlink() for path in paths)
        actual = {str(path.relative_to(provider)): digest(path) for path in paths if path.is_file()}
        assert actual == row['files'], row['profile']
    for name, value in expected['external_tools'].items():
        path = Path(name)
        assert str(path.resolve(strict=True)) == value['resolved'] and digest(path) == value['sha256']
    index = json.loads((ROOT / 'source-bb1fb96.json').read_text())
    assert index['commit'] == HEAD
    assert all(digest(SOURCE / name) == value for name, value in index['files'].items())
    assert digest(CLI) == '59a27ba2a5b95140fd9fddf83f4fec98745fdd56d5372fa1f147c3aaada7aea7'
    return len(index['files'])


assert not RECEIPT.exists(), 'Never restart an existing experiment on observation timeout'
expected = json.loads((ROOT / 'providers-before-e593.json').read_text())
preserved(expected)
before = {'executor_commit': HEAD, 'verifier_commit': HEAD, 'checked_at': now(),
    'providers': expected['providers'], 'external_tools': expected['external_tools'],
    'scope': 'Current byte/file-set checks before corrected experiments; not runtime admission.'}
(ROOT / 'providers-before-bb1fb96.json').write_text(json.dumps(before, indent=2) + '\n')
environment = json.loads((ROOT / 'runtime-build-bb1fb96.json').read_text())['environment']
environment.update(OTELEQ_PYTHON=PYTHON, OTELEQ_CLI=str(CLI))
rows = []
for provider in before['providers']:
    for start in STARTS:
        tag = provider['profile'].split('-')[0]
        folder = ROOT / ('qualification-bb1fb96-' + tag + '-' + start)
        assert not folder.exists()
        rows.append({'profile': provider['profile'], 'provider': provider['provider'],
            'provider_commit': provider['source_commit'], 'startup': start,
            'folder': str(folder), 'state': 'queued'})
record = {'executor_commit': HEAD, 'verifier_commit': HEAD, 'started': now(),
    'max_controllers': 4, 'state': 'running', 'planned_JVMs': 2256,
    'planned_evidence_refusals': 168, 'planned_typed_comparisons': 576,
    'scope': 'Planned totals are not passing results. Failed older experiments remain retained.',
    'runs': rows}


def save():
    temporary = RECEIPT.with_suffix('.json.tmp')
    temporary.write_text(json.dumps(record, indent=2) + '\n')
    temporary.replace(RECEIPT)


def run(row):
    tag = row['profile'].split('-')[0] + '-' + row['startup']
    command = [PYTHON, str(SOURCE / 'tests/qualify_java_startup.py'), '--cli', str(CLI),
        '--otelc-root', row['provider'], '--report-dir', row['folder'],
        '--startup-state', row['startup'], '--java-profile', row['profile']]
    with (ROOT / ('qualification-bb1fb96-' + tag + '.log')).open('w') as output:
        process = subprocess.Popen(command, cwd=SOURCE, env=environment,
            stdout=output, stderr=subprocess.STDOUT)
        with LOCK:
            row.update(state='running', controller_pid=process.pid, started=now(), command=command)
            save()
        status = process.wait()
    with LOCK:
        row.update(state='completed' if status == 0 else 'failed', exit=status, finished=now())
        save()
    print(json.dumps({'profile': row['profile'], 'startup': row['startup'], 'exit': status}), flush=True)
    return status


save()
for offset in range(0, len(rows), 4):
    with ThreadPoolExecutor(max_workers=4) as pool:
        statuses = [future.result() for future in as_completed(
            [pool.submit(run, row) for row in rows[offset:offset + 4]])]
    if any(statuses):
        record.update(state='failed_cohort', finished=now())
        save()
        raise SystemExit(1)
files = preserved(before)
record.update(state='completed', exit=0, finished=now(), sources_preserved=files)
save()
(ROOT / 'providers-after-bb1fb96.json').write_text(json.dumps({
    'executor_commit': HEAD, 'verifier_commit': HEAD, 'checked_at': now(),
    'provider_files_preserved': {row['profile']: len(row['files']) for row in before['providers']},
    'external_tools_preserved': len(before['external_tools']), 'source_files_preserved': files,
    'scope': 'Byte/file-set preservation; admission requires complete actual cohort audit.'}, indent=2) + '\n')
