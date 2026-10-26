"""Retain exact-source component checks on both supported review interpreters."""

import hashlib
import json
import os
from pathlib import Path
import subprocess

ROOT = Path(__file__).resolve().parent
SOURCE = ROOT / 'source-0e4ef41'
metadata = json.loads(SOURCE.with_suffix('.json').read_text())


def audit():
    assert all(hashlib.sha256((SOURCE / name).read_bytes()).hexdigest() == sha for name, sha in metadata['files'].items())
    return len(metadata['files'])


record = {'head': metadata['head'], 'archive_sha256': metadata['archive_sha256'],
          'source_files_before': audit(), 'runs': []}
for label, python in (
    ('312', '/Users/sclarke/github/oteleq-qualification/2026-10-23/python-cli-review-b6dbebb/validation-env-312/bin/python'),
    ('314', '/Users/sclarke/github/oteleq-qualification/2026-10-23/python-http-review-87ab378/validation-env/bin/python')):
    environment = {**os.environ, 'PYTHONDONTWRITEBYTECODE': '1', 'PYTHONPATH': str(SOURCE / 'tests'),
                   'OTELC_JAVA': '/opt/homebrew/opt/openjdk@21/bin/java',
                   'OTELC_JAVAC': '/opt/homebrew/opt/openjdk@21/bin/javac'}
    command = [python, '-m', 'unittest', 'test_generation_java_witness', 'test_generation_java_action',
               'test_generation_java_coverage', '-v']
    log = ROOT / ('focused-' + label + '.log')
    with log.open('wb') as output:
        process = subprocess.Popen(command, cwd=SOURCE, env=environment, stdout=output, stderr=subprocess.STDOUT)
        status = process.wait()
    row = {'runtime': label, 'command': command, 'pid': process.pid, 'exit_code': status,
           'source_files_preserved': audit(), 'log_sha256': hashlib.sha256(log.read_bytes()).hexdigest()}
    record['runs'].append(row)
    (ROOT / 'focused.json').write_text(json.dumps(record, indent=2) + '\n')
    print(json.dumps(row), flush=True)
    if status:raise SystemExit(status)
