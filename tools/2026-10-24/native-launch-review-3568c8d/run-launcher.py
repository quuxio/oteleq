"""Execute the fixed native launcher from the same exact 437-file review tree."""

import hashlib
import json
import os
from pathlib import Path
import shutil
import subprocess
import time

ROOT = Path(__file__).resolve().parent
SOURCE = ROOT / 'source'
index = json.loads(Path('/Users/sclarke/github/otelc-qualification/2026-10-24/native-sdk-budget/source-3568c8d.json').read_text())
original = Path('/Users/sclarke/github/otelc-qualification/work/native-sdk-budget/build/libotelc_native_runtime.dylib')
assert hashlib.sha256(original.read_bytes()).hexdigest() == '2efafd5580982742570f152bf08b56eb53f20d739dee2227f20a70a6e3218f4f'
assert original.stat().st_size == 2949952
library = ROOT / original.name
shutil.copy2(original, library)


def identity(path):
    value = path.stat()
    return [hashlib.sha256(path.read_bytes()).hexdigest(), value.st_dev, value.st_ino, value.st_mode,
            value.st_uid, value.st_gid, value.st_size, value.st_mtime_ns, value.st_ctime_ns]


before = {name: identity(SOURCE / name) for name in index['files']}
assert all(before[name][0] == digest for name, digest in index['files'].items())
products = {str(path): identity(path) for path in (original, library)}
environment = {key: value for key, value in os.environ.items()
               if not key.startswith(('OTEL', 'OTELEQ', 'LLVM_PROFILE', 'GH_', 'GITHUB_', 'AWS_', 'SONAR_'))}
environment.update(OTELC_NATIVE_LIBRARY=str(library), OTELC_NATIVE_TEST_REPORT=str(ROOT / 'launcher-tests.json'),
                   LLVM_PROFILE_FILE=str(ROOT / 'launcher-%p.profraw'), LLVM_CONFIG='/opt/homebrew/opt/llvm@22/bin/llvm-config',
                   PYTHONPATH=str(SOURCE), PYTHONDONTWRITEBYTECODE='1',
                   PATH='/opt/homebrew/opt/llvm@22/bin:/opt/homebrew/bin:' + environment.get('PATH', ''))
command = ['/Users/sclarke/github/oteleq-qualification/2026-10-24/python-live-metrics/env-312/bin/python',
           '-B', '-m', 'ci.native_launch_suite']
(ROOT / 'launcher-command.json').write_text(json.dumps({'argv': command, 'cwd': str(SOURCE), 'head': index['head'],
    'sdk_products': products, 'sdk_build_origin': 'counterpart fixed product; independent execution, not an independent SDK rebuild'}, indent=2) + '\n')
started = time.monotonic()
with (ROOT / 'launcher-tests.log').open('xb') as output:
    result = subprocess.run(command, cwd=SOURCE, env=environment, stdout=output, stderr=subprocess.STDOUT, timeout=600)
changed = [name for name in before if identity(SOURCE / name) != before[name]]
changed_products = [name for name in products if identity(Path(name)) != products[name]]
tests = json.loads((ROOT / 'launcher-tests.json').read_text()) if (ROOT / 'launcher-tests.json').is_file() else None
record = {'head': index['head'], 'exit_code': result.returncode, 'seconds': round(time.monotonic() - started, 3),
          'tests': tests, 'source_files_checked': len(before), 'source_preserved': not changed,
          'sdk_products_preserved': not changed_products, 'changed': changed, 'changed_products': changed_products,
          'scope': 'independent execution of the fixed native launcher against the explicitly identified producer product; complete language and oteleq admission remains open'}
(ROOT / 'launcher-result.json').write_text(json.dumps(record, indent=2) + '\n')
print(json.dumps(record, indent=2), flush=True)
raise SystemExit(0 if result.returncode == 0 and not changed and not changed_products
                 and tests and tests['tests_run'] == tests['selected'] == 14 and tests['skipped'] == 0 else 1)
