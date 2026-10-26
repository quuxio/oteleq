"""Run independent Java resource benchmarks against an exact source archive."""

import hashlib
import json
import os
from pathlib import Path
import subprocess
import tarfile
import xml.etree.ElementTree as ET

BASE = Path(__file__).resolve().parent
ORIGINAL = Path('/Users/sclarke/github/otelc-qualification/2026-10-23/java-benchmark-resources/source-2e42cdd')
SOURCE = BASE / 'source-2e42cdd'
metadata = json.loads(ORIGINAL.with_suffix('.json').read_text())
archive = ORIGINAL.with_suffix('.tar')
assert metadata['head'] == '2e42cdd8e95fd47967929e376c4c3e007e90ec1e'
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


record = {'head': metadata['head'], 'base': metadata['base'],
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
                        '-m', 'unittest', 'test_benchmark', 'test_benchmark_responses', 'test_cli', '-v'])]
for label, command in commands:
    log = BASE / (label + '.log')
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
    record.update(original_sources_after=audit(ORIGINAL), independent_sources_after=audit(SOURCE))
    (BASE / 'tests.json').write_text(json.dumps(record, indent=2) + '\n')
    print(json.dumps(row), flush=True)
    if result:
        raise SystemExit(result)
