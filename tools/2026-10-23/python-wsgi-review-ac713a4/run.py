"""Review direct-loopback fixture isolation on both native Python toolchains."""

import hashlib
import json
import os
from pathlib import Path
import subprocess
import tarfile

ROOT = Path(__file__).resolve().parent
ORIGINAL = Path('/Users/sclarke/github/otelc-qualification/2026-10-23/python-wsgi-deterministic/source-ac713a4')
meta = json.loads(ORIGINAL.with_suffix('.json').read_text())
archive = ORIGINAL.with_suffix('.tar')
assert meta['head'] == 'ac713a4038b5cf91aed106931ca9823094b42aad'
assert hashlib.sha256(archive.read_bytes()).hexdigest() == meta['archive_sha256']
git = subprocess.check_output(['git', 'archive', '--format=tar', meta['head']], cwd='/Users/sclarke/github/otelc')
assert hashlib.sha256(git).hexdigest() == meta['archive_sha256']


def audit(source):
    assert all(hashlib.sha256((source / name).read_bytes()).hexdigest() == sha for name, sha in meta['files'].items())
    return len(meta['files'])


record = {'head': meta['head'], 'base': '99d90d50e81417037e993898bda39c44505710c5',
          'archive_sha256': meta['archive_sha256'], 'runs': []}
for label, python in (
    ('312', '/Users/sclarke/github/oteleq-qualification/2026-10-23/python-cli-review-b6dbebb/validation-env-312/bin/python'),
    ('314', '/Users/sclarke/github/oteleq-qualification/2026-10-23/python-http-review-87ab378/validation-env/bin/python')):
    source = ROOT / ('source-' + label);source.mkdir()
    with tarfile.open(archive) as stream:stream.extractall(source, filter='data')
    assert audit(source) == audit(ORIGINAL) == 333
    command = [python, '-m', 'unittest', 'test_python_http_context.PythonHttpContextTests.test_native_wsgi_close_keeps_getter_side_effects_and_the_second_lookup_callable', '-v']
    environment = {**os.environ, 'PYTHONDONTWRITEBYTECODE': '1',
                   'PYTHONPATH': str(source) + os.pathsep + str(source / 'tests')}
    log = ROOT / (label + '.log')
    with log.open('wb') as output:
        process = subprocess.Popen(command, cwd=source, env=environment, stdout=output, stderr=subprocess.STDOUT)
        status = process.wait()
    row = {'runtime': label, 'command': command, 'pid': process.pid, 'exit_code': status,
           'source_files_preserved': audit(source), 'owner_source_files_preserved': audit(ORIGINAL),
           'log_sha256': hashlib.sha256(log.read_bytes()).hexdigest()}
    record['runs'].append(row)
    (ROOT / 'tests.json').write_text(json.dumps(record, indent=2) + '\n')
    print(json.dumps(row), flush=True)
    if status:raise SystemExit(status)
