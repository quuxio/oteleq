"""Independently check the Java witness input-reader correction."""

import hashlib
import json
import os
from pathlib import Path
import subprocess
import tarfile
import xml.etree.ElementTree as ET

ROOT = Path(__file__).resolve().parent
SOURCE = ROOT / 'source-46f9a69'
head = subprocess.check_output(['git', 'rev-parse', '46f9a69'], cwd='/Users/sclarke/github/otelc', text=True).strip()
assert head.startswith('46f9a69')
archive = ROOT / 'source-46f9a69.tar'
subprocess.run(['git', 'archive', '--format=tar', '-o', archive, head], cwd='/Users/sclarke/github/otelc', check=True)
SOURCE.mkdir()
with tarfile.open(archive) as stream:
    names = [item.name for item in stream.getmembers() if item.isfile()]
    stream.extractall(SOURCE, filter='data')
hashes = {name: hashlib.sha256((SOURCE / name).read_bytes()).hexdigest() for name in names}
metadata = {'head': head, 'base': '6e6327299403491ab84ada517b654ef90f436f6e',
            'archive_sha256': hashlib.sha256(archive.read_bytes()).hexdigest(), 'files': hashes}
SOURCE.with_suffix('.json').write_text(json.dumps(metadata, indent=2) + '\n')
cache = ROOT / 'maven-cache'
subprocess.run(['/bin/cp', '-cR', '/Users/sclarke/github/oteleq-qualification/2026-10-23/java-action-review-6e63272/maven-cache', str(cache)], check=True)
environment = {**os.environ, 'JAVA_HOME': '/opt/homebrew/opt/openjdk@21',
               'PATH': '/opt/homebrew/opt/openjdk@21/bin:/opt/homebrew/bin:/usr/bin:/bin',
               'OTELC_JAVA': '/opt/homebrew/opt/openjdk@21/bin/java',
               'OTELC_JAVAC': '/opt/homebrew/opt/openjdk@21/bin/javac',
               'PYTHONPATH': str(SOURCE) + os.pathsep + str(SOURCE / 'tests'),
               'PYTHONDONTWRITEBYTECODE': '1'}
commands = [('maven', ['/opt/homebrew/bin/mvn', '-o', '-Dmaven.repo.local=' + str(cache), '-q',
                       '-f', 'adapters/java/pom.xml', 'verify']),
            ('python', ['/Users/sclarke/github/oteleq-qualification/2026-10-23/python-cli-review-b6dbebb/validation-env-312/bin/python',
                        '-m', 'unittest', 'test_file_inputs_bounds', 'test_witness_protocol', 'test_witness',
                        'test_prepared_helper_collisions', 'test_java_archives', 'test_prepared_java',
                        'test_java_context', 'test_java_http_context', 'test_java_integration', '-v'])]
record = {key: metadata[key] for key in ('head', 'base', 'archive_sha256')}
record['source_files_before'], record['runs'] = len(hashes), []
for label, command in commands:
    log = ROOT / (label + '.log')
    with log.open('wb') as stream:
        process = subprocess.Popen(command, cwd=SOURCE, env=environment, stdout=stream, stderr=subprocess.STDOUT)
        result = process.wait()
    row = {'label': label, 'command': command, 'pid': process.pid, 'exit_code': result,
           'log_sha256': hashlib.sha256(log.read_bytes()).hexdigest()}
    if label == 'maven' and result == 0:
        reports = list((SOURCE / 'adapters/java/target/surefire-reports').glob('TEST-*.xml'))
        row['junit'] = {key: sum(int(ET.parse(path).getroot().get(key, 0)) for path in reports)
                        for key in ('tests', 'failures', 'errors', 'skipped')}
    record['runs'].append(row)
    record['source_preserved'] = {name: hashlib.sha256((SOURCE / name).read_bytes()).hexdigest() for name in names} == hashes
    (ROOT / 'tests.json').write_text(json.dumps(record, indent=2) + '\n')
    print(json.dumps(row), flush=True)
    if result or not record['source_preserved']:raise SystemExit(result or 1)
