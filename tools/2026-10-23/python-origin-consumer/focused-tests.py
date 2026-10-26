"""Bind focused interpreter results and source preservation to the revision."""

import hashlib
import importlib.util
import json
import os
from pathlib import Path
import subprocess
import sys

BASE = Path(__file__).resolve().parent
SOURCE = BASE / 'source-d4c663d'
manifest = json.loads((BASE / 'source-d4c663d-manifest.json').read_text())


def hashes():
    return {name: hashlib.sha256((SOURCE / name).read_bytes()).hexdigest() for name in manifest}


assert hashes() == manifest
version = '.'.join(map(str, sys.version_info[:3]))
command = [sys.executable, '-m']
coverage = importlib.util.find_spec('coverage') is not None
if coverage:
    command.extend(['coverage', 'run', '--data-file=' + str(BASE / ('focused-' + version + '.coverage')),
                    '--include=*/python_origin.py,*/python_code_match.py', '-m'])
command.extend(['unittest', 'test_generation_python_origin', 'test_generation_python_code_match',
                'test_generation_python_code', 'test_generation_python_journal', '-v'])
environment = {**os.environ, 'PYTHONPATH': 'tests', 'PYTHONDONTWRITEBYTECODE': '1'}
with (BASE / ('focused-' + version + '.log')).open('wb') as stream:
    process = subprocess.Popen(command, cwd=SOURCE, env=environment, stdout=stream, stderr=subprocess.STDOUT)
    result = process.wait()
record = {'consumer_head': 'd4c663d0f6f86579dfa3ed3b326664db7406439e',
          'python': sys.version, 'command': command, 'owner_pid': os.getpid(), 'test_pid': process.pid,
          'exit_code': result, 'source_files': len(manifest), 'source_preserved': hashes() == manifest,
          'coverage_available': coverage,
          'log_sha256': hashlib.sha256((BASE / ('focused-' + version + '.log')).read_bytes()).hexdigest()}
if coverage and result == 0:
    report = subprocess.run([sys.executable, '-m', 'coverage', 'report',
                            '--data-file=' + str(BASE / ('focused-' + version + '.coverage')), '-m', '--fail-under=80'],
                            cwd=SOURCE, capture_output=True, check=True)
    (BASE / ('focused-' + version + '-coverage.txt')).write_bytes(report.stdout + report.stderr)
    record['coverage_report_sha256'] = hashlib.sha256(report.stdout + report.stderr).hexdigest()
(BASE / ('focused-' + version + '.json')).write_text(json.dumps(record, indent=2) + '\n')
print(json.dumps({key: record[key] for key in ('python', 'exit_code', 'source_files', 'source_preserved', 'coverage_available')}))
raise SystemExit(result if record['source_preserved'] else 1)
