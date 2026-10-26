"""Run compact independent candidate checks without rebuilding the SDK."""
import datetime
import hashlib
import json
import os
from pathlib import Path
import subprocess
import time
import shutil

ROOT = Path(__file__).resolve().parent
OUTPUT = ROOT / 'run-02'
OUTPUT.mkdir(exist_ok=True)
SOURCE = ROOT / 'source'
OWNER = Path('/Users/sclarke/github/otelc-qualification/work/native-object-probes')
INDEX = json.loads(Path('/Users/sclarke/github/otelc-qualification/2026-10-25/native-object-probes/source-43a96a5.json').read_text())
PYTHON = '/Users/sclarke/github/oteleq-qualification/2026-10-24/python-live-metrics/env-312/bin/python'


def identity(path):
    state = path.stat()
    return {'sha256': hashlib.file_digest(path.open('rb'), 'sha256').hexdigest(),
            'facts': [state.st_dev, state.st_ino, state.st_mode, state.st_uid, state.st_gid,
                      state.st_size, state.st_mtime_ns, state.st_ctime_ns, state.st_nlink]}


files = {str(SOURCE / name): digest for name, digest in INDEX['files'].items()}
owner_files = {str(OWNER / name): digest for name, digest in INDEX['files'].items()}
coverage = json.loads((OWNER / 'build/native-control-coverage.json').read_text())
products = [coverage[key] for key in ['product', 'function_product', 'object_product']]
for row in products:
    files[row['path']] = row['sha256']
for row in coverage['source_inputs']:
    assert identity(Path(row['path']))['sha256'] == row['sha256']
before = {name: identity(Path(name)) for name in files | owner_files}
assert all(before[name]['sha256'] == digest for name, digest in (files | owner_files).items())
private_products = []
for row in products:
    private = OUTPUT / Path(row['path']).name
    shutil.copyfile(row['path'], private)
    private.chmod(0o700)
    assert identity(private)['sha256'] == row['sha256']
    private_products.append(private)
commands = [[PYTHON, '-B', '-m', 'unittest', 'tests.test_llvm_backend', 'tests.test_native_sonar'],
            *[[str(path)] for path in private_products]]
results = []
for i, command in enumerate(commands):
    started = time.monotonic()
    environment = {key: value for key, value in os.environ.items() if not key.startswith(('OTEL', 'OTELEQ'))}
    environment.update(PYTHONDONTWRITEBYTECODE='1', LLVM_PROFILE_FILE=str(OUTPUT / ('independent-%m-%p.profraw')))
    result = subprocess.run(command, cwd=SOURCE, env=environment, capture_output=True, timeout=120)
    (OUTPUT / f'command-{i}.stdout').write_bytes(result.stdout)
    (OUTPUT / f'command-{i}.stderr').write_bytes(result.stderr)
    results.append({'command': command, 'exit_code': result.returncode,
                    'seconds': round(time.monotonic() - started, 3)})
    print(json.dumps(results[-1]), flush=True)
    assert result.returncode == 0
assert before == {name: identity(Path(name)) for name in before}
value = {'head': INDEX['head'], 'status': 'passed', 'commands': results,
         'preserved_files': len(before), 'owner_source_files': len(owner_files),
         'finished': datetime.datetime.now(datetime.timezone.utc).isoformat(),
         'scope': 'Independent fixed Python reader tests and execution of exact owner-built SDK component test products. No independent SDK rebuild, public launch or downstream OTLP qualification.'}
(OUTPUT / 'checks.json').write_text(json.dumps(value, indent=2) + '\n')
print(json.dumps(value), flush=True)
