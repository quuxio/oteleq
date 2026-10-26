"""Independently execute the frozen native launcher with its retained SDK product."""

import hashlib
import json
import os
from pathlib import Path
import shutil
import subprocess
import tarfile
import time

ROOT = Path(__file__).resolve().parent
PRODUCER = Path('/Users/sclarke/github/otelc-qualification/2026-10-24/native-function-runtime')
index = json.loads((PRODUCER / 'source-4d98c97.json').read_text())
archive = Path(index['archive'])
assert hashlib.sha256(archive.read_bytes()).hexdigest() == index['archive_sha256'] == 'fe736b7ad1cccd1fbcc3aff772378aaa43dfae23f0ba6f649185c5a1125f31cc'
source = ROOT / 'source'
source.mkdir()
with tarfile.open(archive) as data:
    data.extractall(source, filter='data')
assert len(index['files']) == 436
assert all(hashlib.sha256((source / name).read_bytes()).hexdigest() == digest for name, digest in index['files'].items())
producer_source = PRODUCER / 'full-4d98c97-permitted/source'
sdk = json.loads((producer_source / 'build/native-launch-coverage.json').read_text())
original = Path(sdk['product']['path'])
assert hashlib.sha256(original.read_bytes()).hexdigest() == sdk['product']['sha256']
for row in sdk['source_inputs']:
    path = Path(row['path'])
    relative = path.relative_to(producer_source)
    assert hashlib.sha256((source / relative).read_bytes()).hexdigest() == row['sha256']
library = ROOT / original.name
shutil.copy2(original, library)


def identity(path):
    value = path.stat()
    return {'sha256': hashlib.sha256(path.read_bytes()).hexdigest(),
            'facts': [value.st_dev, value.st_ino, value.st_mode, value.st_uid, value.st_gid,
                      value.st_size, value.st_mtime_ns, value.st_ctime_ns]}


before = {name: identity(source / name) for name in index['files']}
products = {str(path): identity(path) for path in (library, original)}
environment = {key: value for key, value in os.environ.items()
               if not key.startswith(('OTEL', 'OTELEQ', 'LLVM_PROFILE', 'GH_', 'GITHUB_', 'AWS_', 'SONAR_'))}
environment.update(OTELC_NATIVE_LIBRARY=str(library), OTELC_NATIVE_TEST_REPORT=str(ROOT / 'native-tests.json'),
                   LLVM_PROFILE_FILE=str(ROOT / 'runtime-%p.profraw'), LLVM_CONFIG='/opt/homebrew/opt/llvm@22/bin/llvm-config',
                   PYTHONPATH=str(source), PYTHONDONTWRITEBYTECODE='1',
                   PATH='/opt/homebrew/opt/llvm@22/bin:/opt/homebrew/bin:' + environment.get('PATH', ''))
python = '/Users/sclarke/github/oteleq-qualification/2026-10-24/python-live-metrics/env-312/bin/python'
command = [python, '-B', '-m', 'ci.native_launch_suite']
(ROOT / 'command.json').write_text(json.dumps({'argv': command, 'cwd': str(source),
    'head': index['head'], 'archive_sha256': index['archive_sha256'], 'sdk_product': products,
    'sdk_build_origin': 'counterpart frozen full-gate product; independently executed here, not independently rebuilt'}, indent=2) + '\n')
started = time.monotonic()
with (ROOT / 'native-tests.log').open('xb') as output:
    result = subprocess.run(command, cwd=source, env=environment, stdout=output, stderr=subprocess.STDOUT, timeout=600)
changed = [name for name in before if identity(source / name) != before[name]]
changed_products = [name for name in products if identity(Path(name)) != products[name]]
tests = json.loads((ROOT / 'native-tests.json').read_text()) if (ROOT / 'native-tests.json').is_file() else None
receipt = {'head': index['head'], 'exit_code': result.returncode, 'seconds': round(time.monotonic() - started, 3),
           'tests': tests, 'source_files_checked': len(before), 'source_preserved': not changed,
           'sdk_products_preserved': not changed_products, 'changed': changed, 'changed_products': changed_products,
           'scope': 'independent native launcher execution against the separately identified producer-built SDK; full language/oteleq admission remains open'}
(ROOT / 'native-result.json').write_text(json.dumps(receipt, indent=2) + '\n')
print(json.dumps(receipt, indent=2), flush=True)
raise SystemExit(0 if result.returncode == 0 and not changed and not changed_products
                 and tests and tests['selected'] == tests['tests_run'] == 14 and tests['skipped'] == 0 else 1)
