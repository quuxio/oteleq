"""Independent v2 producer review, frozen sources and private Maven products."""

import hashlib
import json
import os
from pathlib import Path
import subprocess
import tarfile
import xml.etree.ElementTree as ET

ROOT = Path(__file__).resolve().parent
ORIGINAL = Path('/Users/sclarke/github/otelc-qualification/2026-10-23/java-action-v2/source-6e027c4')
SOURCE = ROOT / 'source-6e027c4'
metadata = json.loads(ORIGINAL.with_suffix('.json').read_text())
archive = ORIGINAL.with_suffix('.tar')
assert metadata['head'] == '6e027c44aafe227b3c03bbd26a24d1e9bc902eab'
assert hashlib.sha256(archive.read_bytes()).hexdigest() == metadata['archive_sha256']
git = subprocess.check_output(['git', 'archive', '--format=tar', metadata['head']], cwd='/Users/sclarke/github/otelc')
assert hashlib.sha256(git).hexdigest() == metadata['archive_sha256']
SOURCE.mkdir()
with tarfile.open(archive) as stream:stream.extractall(SOURCE, filter='data')


def audit(source):
    assert all(hashlib.sha256((source / name).read_bytes()).hexdigest() == sha for name, sha in metadata['files'].items())
    return len(metadata['files'])


assert audit(SOURCE) == audit(ORIGINAL) == 342
cache = ROOT / 'maven-cache'
subprocess.run(['/bin/cp', '-cR', '/Users/sclarke/github/oteleq-qualification/2026-10-23/java-action-review-46f9a69/maven-cache', str(cache)], check=True)
environment = {**os.environ, 'JAVA_HOME': '/opt/homebrew/opt/openjdk@21',
               'PATH': '/opt/homebrew/opt/openjdk@21/bin:/opt/homebrew/bin:/usr/bin:/bin',
               'OTELC_JAVA': '/opt/homebrew/opt/openjdk@21/bin/java',
               'OTELC_JAVAC': '/opt/homebrew/opt/openjdk@21/bin/javac',
               'PYTHONPATH': str(SOURCE) + os.pathsep + str(SOURCE / 'tests'),
               'PYTHONDONTWRITEBYTECODE': '1'}
modules = ['test_file_inputs_bounds', 'test_witness_input_files', 'test_witness_protocol', 'test_witness',
           'test_prepared_helper_collisions', 'test_java_archives', 'test_prepared_java',
           'test_java_context', 'test_java_http_context', 'test_java_integration']
commands = [('maven', ['/opt/homebrew/bin/mvn', '-o', '-Dmaven.repo.local=' + str(cache), '-q',
                       '-f', 'adapters/java/pom.xml', 'verify']),
            ('python-312', ['/Users/sclarke/github/oteleq-qualification/2026-10-23/python-cli-review-b6dbebb/validation-env-312/bin/python',
                            '-m', 'unittest', *modules, '-v']),
            ('python-314', ['/Users/sclarke/github/oteleq-qualification/2026-10-23/python-http-review-87ab378/validation-env/bin/python',
                            '-m', 'unittest', *modules, '-v'])]
record = {'head': metadata['head'], 'base': '3af861082b7bd61e302a56adb124faa8870269a9',
          'archive_sha256': metadata['archive_sha256'], 'source_files_before': 342, 'runs': []}
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
    record.update(source_files_after=audit(SOURCE), original_source_files_after=audit(ORIGINAL))
    (ROOT / 'tests.json').write_text(json.dumps(record, indent=2) + '\n')
    print(json.dumps(row), flush=True)
    if result:raise SystemExit(result)
