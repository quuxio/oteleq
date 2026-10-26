"""Independent frozen-source review of universal-binary coverage export."""

import hashlib
import json
import os
from pathlib import Path
import subprocess
import tarfile

ROOT = Path(__file__).resolve().parent
ORIGINAL = Path('/Users/sclarke/github/otelc-qualification/2026-10-23/python-coverage-architecture/source-d12cb76')
metadata = json.loads(ORIGINAL.with_suffix('.json').read_text())
archive = ORIGINAL.with_suffix('.tar')
assert metadata['head'] == 'd12cb7668dbd97dffad99377a4a514baa712980a'
assert hashlib.sha256(archive.read_bytes()).hexdigest() == metadata['archive_sha256']
git = subprocess.check_output(['git', 'archive', '--format=tar', metadata['head']], cwd='/Users/sclarke/github/otelc')
assert hashlib.sha256(git).hexdigest() == metadata['archive_sha256']


def audit(source):
    assert all(hashlib.sha256((source / name).read_bytes()).hexdigest() == sha for name, sha in metadata['files'].items())
    return len(metadata['files'])


record = {'head': metadata['head'], 'base': '20509540d6d45dd31f6414de7c5a5d4e9bef033f',
          'archive_sha256': metadata['archive_sha256'], 'archive_independently_reproduced_from_git': True,
          'original_source_files': audit(ORIGINAL), 'runs': []}
for label, python in (
    ('312', '/Users/sclarke/github/oteleq-qualification/2026-10-23/python-cli-review-b6dbebb/validation-env-312/bin/python'),
    ('314', '/Users/sclarke/github/oteleq-qualification/2026-10-23/python-http-review-87ab378/validation-env/bin/python')):
    source = ROOT / ('source-' + label)
    source.mkdir()
    with tarfile.open(archive) as stream:stream.extractall(source, filter='data')
    assert audit(source) == 329
    environment = {**os.environ, 'PYTHONDONTWRITEBYTECODE': '1',
                   'PYTHONPATH': str(source) + os.pathsep + str(source / 'tests'),
                   'OTELC_LLVM_BIN': '/opt/homebrew/opt/llvm@22/bin'}
    command = [python, '-m', 'unittest', 'test_python_input_coverage', '-v']
    log = ROOT / (label + '.log')
    with log.open('wb') as output:
        process = subprocess.Popen(command, cwd=source, env=environment, stdout=output, stderr=subprocess.STDOUT)
        status = process.wait()
    row = {'runtime': label, 'command': command, 'pid': process.pid, 'exit_code': status,
           'source_files_preserved': audit(source), 'original_source_files_preserved': audit(ORIGINAL),
           'log_sha256': hashlib.sha256(log.read_bytes()).hexdigest()}
    if status == 0:
        report = source / 'build/python-native-coverage.json'
        data = json.loads(report.read_text())
        assert data['architecture'] == 'arm64'
        assert len(data['sources']) == 7 and all(item['lines']['percent'] >= 80 for item in data['sources'].values())
        row['native_line_coverage'] = {name: item['lines']['percent'] for name, item in data['sources'].items()}
        row['report_sha256'] = hashlib.sha256(report.read_bytes()).hexdigest()
    record['runs'].append(row)
    (ROOT / 'tests.json').write_text(json.dumps(record, indent=2) + '\n')
    print(json.dumps(row), flush=True)
    if status:raise SystemExit(status)
