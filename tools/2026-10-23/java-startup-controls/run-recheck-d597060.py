"""Audit all original startup corpora with the frozen corrected verifier."""

from concurrent.futures import ThreadPoolExecutor, as_completed
import datetime
import hashlib
import json
import os
from pathlib import Path
import subprocess
import threading

ROOT = Path(__file__).resolve().parent
SOURCE = ROOT / 'source-d597060'
HEAD = 'd597060bdc8f78723ac7832b2fc7e4212230a33d'
PYTHON = '/Users/sclarke/github/oteleq-qualification/2026-10-22/node-source-consumer-0f05020/validation-hash-env/bin/python'
CLI = ROOT / 'quux-oteleq-bb1fb96'
RECEIPT = ROOT / 'recheck-d597060-env.json'
LOCK = threading.Lock()


def now():
    return datetime.datetime.now(datetime.UTC).isoformat()


def sha(path):
    assert path.is_file() and not path.is_symlink()
    return hashlib.sha256(path.read_bytes()).hexdigest()


def source_check():
    index = json.loads((ROOT / 'source-d597060.json').read_text())
    assert index['commit'] == HEAD and len(index['files']) == 400
    assert all(sha(SOURCE / name) == value for name, value in index['files'].items())
    assert sha(CLI) == '59a27ba2a5b95140fd9fddf83f4fec98745fdd56d5372fa1f147c3aaada7aea7'


def save():
    temporary = RECEIPT.with_suffix('.json.tmp')
    temporary.write_text(json.dumps(record, indent=2) + '\n')
    temporary.replace(RECEIPT)


def run(row):
    tag = row['profile'].split('-')[0] + '-' + row['startup']
    logfile = ROOT / ('recheck-d597060-env-' + tag + '.log')
    arguments = [PYTHON, '-B', str(SOURCE / 'tests/qualify_java_startup.py'),
        '--recheck', '--cli', str(CLI), '--otelc-root', row['provider'],
        '--report-dir', row['folder'], '--startup-state', row['startup'],
        '--java-profile', row['profile']]
    environment = dict(os.environ, **record['environment'])
    with logfile.open('x') as output:
        process = subprocess.Popen(arguments, cwd=SOURCE, env=environment,
            stdout=output, stderr=subprocess.STDOUT)
        with LOCK:
            row.update(state='running', pid=process.pid, command=arguments, started=now(), log=str(logfile))
            save()
        status = process.wait()
    with LOCK:
        row.update(state='completed' if status == 0 else 'failed', exit=status, finished=now())
        if status == 0:
            result = json.loads(logfile.read_text().splitlines()[-1])
            assert result['mode'] == 'retained_recheck' and result['new_application_launches'] == 0
            assert result['actual_jvm_launches'] == 188 and result['typed_comparisons_recomputed'] == 48
            row['audit_directory'] = result['audit_directory']
            row['qualification_sha256'] = sha(Path(result['audit_directory']) / 'QUALIFICATION.json')
        save()
    print(json.dumps({'profile': row['profile'], 'startup': row['startup'], 'exit': status}), flush=True)
    return status


assert not RECEIPT.exists(), 'Never restart an existing recheck on observation timeout'
source_check()
matrix_path = ROOT / 'matrix-bb1fb96.json'
matrix = json.loads(matrix_path.read_text())
assert matrix['state'] == 'failed_cohort'
assert len(matrix['runs']) == 12 and all(row['state'] in ('completed', 'failed') for row in matrix['runs'])
originals = {str(matrix_path): sha(matrix_path)}
rows = []
for original in matrix['runs']:
    root = Path(original['folder'])
    result = root / 'QUALIFICATION.json'
    assert result.exists() == (original['state'] == 'completed')
    if result.exists():
        originals[str(result)] = sha(result)
    rows.append({key: original[key] for key in ('profile', 'provider', 'provider_commit', 'startup', 'folder')}
    )
record = {'executor_commit': matrix['executor_commit'], 'verifier_commit': HEAD,
    'original_controller_results': {'success': 8, 'failed_build_audit': 4},
    'original_files_sha256': originals, 'started': now(), 'state': 'running',
    'max_workers': 3, 'new_application_launches': 0, 'runs': rows,
    'environment': json.loads((ROOT / 'runtime-build-bb1fb96.json').read_text())['environment']}
save()
with ThreadPoolExecutor(max_workers=3) as pool:
    statuses = [future.result() for future in as_completed([pool.submit(run, row) for row in rows])]
source_check()
assert all(sha(Path(name)) == value for name, value in originals.items())
assert all((Path(row['folder']) / 'QUALIFICATION.json').exists() == (row['profile'] != 'archive-methods-v1') for row in rows)
record.update(state='completed' if all(status == 0 for status in statuses) else 'failed',
    finished=now(), original_results_preserved=True, verifier_sources_preserved=400)
save()
raise SystemExit(0 if record['state'] == 'completed' else 1)
