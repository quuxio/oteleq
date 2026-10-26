"""Independently review the encoder distribution fix without shared builds."""

import hashlib
import json
import os
from pathlib import Path
import re
import subprocess
import sys
import tarfile

BASE = Path(__file__).resolve().parent
ORIGINAL = Path('/Users/sclarke/github/otelc-qualification/2026-10-23/python-builtin-encoder/source-7ff4cdd')
metadata = json.loads(ORIGINAL.with_suffix('.json').read_text())
archive = ORIGINAL.with_suffix('.tar')
assert hashlib.sha256(archive.read_bytes()).hexdigest() == metadata['archive_sha256']
label = sys.argv[1]
python = sys.argv[2]
source = BASE / ('source-' + label)
source.mkdir()
with tarfile.open(archive) as stream:
    stream.extractall(source, filter='data')


def audit(root):
    actual = {name: hashlib.sha256((root / name).read_bytes()).hexdigest() for name in metadata['files']}
    assert actual == metadata['files']
    return len(actual)


record = {'head': metadata['head'], 'base': '305834bc330b2ab423a3aebdd789073413e25911',
          'archive_sha256': metadata['archive_sha256'], 'label': label,
          'original_sources_before': audit(ORIGINAL), 'independent_sources_before': audit(source)}
names = ['test_python_native_inputs', 'test_python_import_inputs', 'test_python_code_inputs',
         'test_python_native_encoder', 'test_python_input_build', 'test_native_encoder_build',
         'test_python_prepared', 'test_python_frontend_components']
if label == '31210':
    names = ['test_native_encoder_build', 'test_python_native_encoder']
command = [python, '-m', 'unittest', '-v', *names]
log = BASE / ('tests-' + label + '.log')
environment = {**os.environ, 'PYTHONPATH': str(source) + os.pathsep + str(source / 'tests'),
               'PYTHONDONTWRITEBYTECODE': '1', 'OTELC_LLVM_BIN': '/opt/homebrew/opt/llvm@22/bin'}
with log.open('wb') as stream:
    process = subprocess.Popen(command, cwd=source, env=environment, stdout=stream, stderr=subprocess.STDOUT)
    result = process.wait()
count = re.search(r'Ran (\d+) tests?', log.read_text())
record.update(command=command, owner_pid=os.getpid(), test_pid=process.pid, exit_code=result,
              tests=int(count[1]) if count else None,
              log_sha256=hashlib.sha256(log.read_bytes()).hexdigest(),
              original_sources_after=audit(ORIGINAL), independent_sources_after=audit(source))
(BASE / ('tests-' + label + '.json')).write_text(json.dumps(record, indent=2) + '\n')
print(json.dumps(record))
raise SystemExit(result)
