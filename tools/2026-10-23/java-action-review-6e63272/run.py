"""Independent exact-source Java witness review with an owned Maven cache."""

import hashlib
import json
import os
from pathlib import Path
import subprocess
import tarfile
import xml.etree.ElementTree as ET

BASE = Path(__file__).resolve().parent
ORIGINAL = Path('/Users/sclarke/github/otelc-qualification/2026-10-23/java-action-main/source-6e63272')
SOURCE = BASE / 'source-6e63272'
metadata = json.loads(ORIGINAL.with_suffix('.json').read_text())
archive = ORIGINAL.with_suffix('.tar')
assert metadata['head'] == '6e6327299403491ab84ada517b654ef90f436f6e'
assert hashlib.sha256(archive.read_bytes()).hexdigest() == metadata['archive_sha256']
git_archive = subprocess.check_output(['git', 'archive', '--format=tar', metadata['head']], cwd='/Users/sclarke/github/otelc')
assert hashlib.sha256(git_archive).hexdigest() == metadata['archive_sha256']
SOURCE.mkdir()
with tarfile.open(archive) as stream:
    stream.extractall(SOURCE, filter='data')
cache = BASE / 'maven-cache'
subprocess.run(['/bin/cp', '-cR', '/Users/sclarke/.m2/repository', str(cache)], check=True)


def audit(root):
    assert {name: hashlib.sha256((root / name).read_bytes()).hexdigest() for name in metadata['files']} == metadata['files']
    return len(metadata['files'])


record = {'head': metadata['head'], 'base': 'd92262c20292389123f7fc511ef5cc59f4dbd07e',
          'archive_sha256': metadata['archive_sha256'], 'archive_independently_reproduced_from_git': True,
          'original_sources_before': audit(ORIGINAL), 'independent_sources_before': audit(SOURCE), 'runs': []}
environment = {**os.environ, 'JAVA_HOME': '/opt/homebrew/opt/openjdk@21',
               'PATH': '/opt/homebrew/opt/openjdk@21/bin:/opt/homebrew/bin:/usr/bin:/bin',
               'OTELC_JAVA': '/opt/homebrew/opt/openjdk@21/bin/java',
               'OTELC_JAVAC': '/opt/homebrew/opt/openjdk@21/bin/javac',
               'PYTHONPATH': str(SOURCE) + os.pathsep + str(SOURCE / 'tests'),
               'PYTHONDONTWRITEBYTECODE': '1'}
commands = [('maven', ['/opt/homebrew/bin/mvn', '-o', '-Dmaven.repo.local=' + str(cache), '-q',
                       '-f', 'adapters/java/pom.xml', 'verify']),
            ('python', ['/Users/sclarke/github/oteleq-qualification/2026-10-23/python-cli-review-b6dbebb/validation-env-312/bin/python',
                        '-m', 'unittest', 'test_witness_protocol', 'test_witness',
                        'test_prepared_helper_collisions', 'test_java_archives', 'test_prepared_java',
                        'test_java_context', 'test_java_http_context', '-v'])]
for label, command in commands:
    log = BASE / (label + '.log')
    with log.open('wb') as stream:
        process = subprocess.Popen(command, cwd=SOURCE, env=environment, stdout=stream, stderr=subprocess.STDOUT)
        result = process.wait()
    row = {'label': label, 'command': command, 'pid': process.pid, 'exit_code': result,
           'log_sha256': hashlib.sha256(log.read_bytes()).hexdigest()}
    if label == 'maven' and result == 0:
        reports = list((SOURCE / 'adapters/java/target/surefire-reports').glob('TEST-*.xml'))
        counts = {key: sum(int(ET.parse(path).getroot().get(key, 0)) for path in reports)
                  for key in ('tests', 'failures', 'errors', 'skipped')}
        row['junit'] = counts
        coverage = ET.parse(SOURCE / 'adapters/java/target/site/jacoco/jacoco.xml').getroot()
        row['line_coverage'] = {key: int(next(item for item in coverage.findall('counter')
                                             if item.get('type') == 'LINE').get(key)) for key in ('missed', 'covered')}
    record['runs'].append(row)
    record.update(original_sources_after=audit(ORIGINAL), independent_sources_after=audit(SOURCE))
    (BASE / 'tests.json').write_text(json.dumps(record, indent=2) + '\n')
    print(json.dumps(row), flush=True)
    if result:
        raise SystemExit(result)
