"""Compile and execute the exact supplemental native deadline fix independently."""

import hashlib
import json
import os
from pathlib import Path
import subprocess
import tarfile
import time

ROOT = Path(__file__).resolve().parent
producer = Path('/Users/sclarke/github/otelc-qualification/2026-10-24/native-sdk-budget')
index = json.loads((producer / 'source-3568c8d.json').read_text())
archive = Path(index['archive'])
assert index['head'] == '3568c8d099de3b7bbf3e40fd4109d3e71dce11c2'
assert hashlib.sha256(archive.read_bytes()).hexdigest() == index['archive_sha256'] == '36dc5e892b0743a31b951e2192ba01a71f4561ca28f9a893ae87649347cdfdf5'
source = ROOT / 'source'
source.mkdir()
with tarfile.open(archive) as data:
    data.extractall(source, filter='data')
assert len(index['files']) == 437


def identity(path):
    value = path.stat()
    return [hashlib.sha256(path.read_bytes()).hexdigest(), value.st_dev, value.st_ino,
            value.st_mode, value.st_uid, value.st_gid, value.st_size, value.st_mtime_ns, value.st_ctime_ns]


before = {name: identity(source / name) for name in index['files']}
assert all(before[name][0] == digest for name, digest in index['files'].items())
environment = {key: value for key, value in os.environ.items()
               if not key.startswith(('OTEL', 'OTELEQ', 'LLVM_PROFILE', 'GH_', 'GITHUB_', 'AWS_', 'SONAR_'))}
environment.update(LLVM_CONFIG='/opt/homebrew/opt/llvm@22/bin/llvm-config', PYTHONDONTWRITEBYTECODE='1',
                   PATH='/opt/homebrew/opt/llvm@22/bin:/opt/homebrew/bin:' + environment.get('PATH', ''))
command = ['/Users/sclarke/github/oteleq-qualification/2026-10-24/python-live-metrics/env-312/bin/python',
           '-B', '-m', 'ci.check_native_controls']
(ROOT / 'command.json').write_text(json.dumps({'argv': command, 'cwd': str(source), 'head': index['head'],
    'archive_sha256': index['archive_sha256']}, indent=2) + '\n')
started = time.monotonic()
with (ROOT / 'native-controls.log').open('xb') as output:
    result = subprocess.run(command, cwd=source, env=environment, stdout=output, stderr=subprocess.STDOUT, timeout=1200)
changed = [name for name in before if identity(source / name) != before[name]]
receipt = {'head': index['head'], 'exit_code': result.returncode, 'seconds': round(time.monotonic() - started, 3),
           'source_files_checked': len(before), 'source_preserved': not changed, 'changed': changed,
           'scope': 'independent real SDK compiler-linked controls/functions, including owned parentage and deadline regressions; launcher/oteleq admission is separate'}
(ROOT / 'result.json').write_text(json.dumps(receipt, indent=2) + '\n')
print(json.dumps(receipt, indent=2), flush=True)
raise SystemExit(0 if result.returncode == 0 and not changed else 1)
