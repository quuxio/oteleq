"""Cover changed default Java integration tests on the same frozen products."""

import hashlib
import json
import os
from pathlib import Path
import subprocess

BASE = Path(__file__).resolve().parent
SOURCE = BASE / 'source-6e63272'
metadata = json.loads(Path('/Users/sclarke/github/otelc-qualification/2026-10-23/java-action-main/source-6e63272.json').read_text())
before = {name: hashlib.sha256((SOURCE / name).read_bytes()).hexdigest() for name in metadata['files']}
assert before == metadata['files']
command = ['/Users/sclarke/github/oteleq-qualification/2026-10-23/python-cli-review-b6dbebb/validation-env-312/bin/python',
           '-m', 'unittest', 'test_java_integration', '-v']
environment = {**os.environ, 'JAVA_HOME': '/opt/homebrew/opt/openjdk@21',
               'PATH': '/opt/homebrew/opt/openjdk@21/bin:/opt/homebrew/bin:/usr/bin:/bin',
               'OTELC_JAVA': '/opt/homebrew/opt/openjdk@21/bin/java',
               'OTELC_JAVAC': '/opt/homebrew/opt/openjdk@21/bin/javac',
               'PYTHONPATH': str(SOURCE) + os.pathsep + str(SOURCE / 'tests'), 'PYTHONDONTWRITEBYTECODE': '1'}
log = BASE / 'python-default-integration.log'
with log.open('wb') as stream:
    process = subprocess.Popen(command, cwd=SOURCE, env=environment, stdout=stream, stderr=subprocess.STDOUT)
    result = process.wait()
assert {name: hashlib.sha256((SOURCE / name).read_bytes()).hexdigest() for name in metadata['files']} == before
record = {'head': metadata['head'], 'command': command, 'pid': process.pid, 'exit_code': result,
          'source_files_preserved': len(before), 'source_preserved': True,
          'log_sha256': hashlib.sha256(log.read_bytes()).hexdigest()}
(BASE / 'python-default-integration.json').write_text(json.dumps(record, indent=2) + '\n')
print(json.dumps(record))
raise SystemExit(result)
