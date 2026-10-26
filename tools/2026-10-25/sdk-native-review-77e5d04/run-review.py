"""Independently execute real C compiler tests without changing owner outputs."""
from datetime import datetime, timezone
import hashlib
import importlib.util
import json
import os
from pathlib import Path
import sys
import tarfile
import time
import unittest

BASE = Path(__file__).resolve().parent
OWNER = Path('/Users/sclarke/github/otelc-qualification/work/c-resource-launch')
RECORD = Path('/Users/sclarke/github/otelc-qualification/2026-10-25/c-resource-launch/source-77e5d04.json')
INDEX = json.loads(RECORD.read_text())
SOURCE = BASE / 'source'
SOURCE.mkdir()
with tarfile.open(RECORD.with_suffix('.tar')) as stream:
    stream.extractall(SOURCE, filter='data')
products = [OWNER / 'build/resource-sdk/native-sdk-build.json', OWNER / 'build/resource-sdk/libotelc_native_runtime.dylib']


def facts(path):
    info = path.stat()
    with path.open('rb') as stream:
        digest = hashlib.file_digest(stream, 'sha256').hexdigest()
    return [digest, info.st_dev, info.st_ino, info.st_mode, info.st_size, info.st_mtime_ns, info.st_ctime_ns, info.st_nlink]


def inputs():
    return {'owner': {name: facts(OWNER / name) for name in INDEX['files']},
            'frozen': {name: facts(SOURCE / name) for name in INDEX['files']},
            'products': {str(path): facts(path) for path in products}}


before = inputs()
assert all(before[group][name][0] == digest for group in ('owner', 'frozen') for name, digest in INDEX['files'].items())
(BASE / 'inputs-before.json').write_text(json.dumps(before, indent=2) + '\n')
mirror = BASE / 'test-root'; mirror.mkdir(); (mirror / 'build').mkdir(); (mirror / 'native').symlink_to(OWNER / 'native', target_is_directory=True)
for name in ('bin', 'otelc'):
    (mirror / name).symlink_to(OWNER / name, target_is_directory=True)
for name in list(os.environ):
    if name.startswith(('OTEL', 'OTELEQ', 'GH_', 'GITHUB_', 'AWS_', 'SONAR_', 'LLVM_PROFILE')):
        del os.environ[name]
os.environ.update(OTELC_CPP_ANALYSIS='1', LLVM_CONFIG='/opt/homebrew/opt/llvm@22/bin/llvm-config', PYTHONDONTWRITEBYTECODE='1',
    OTELC_PUBLIC_RESOURCE_SDK=str(OWNER / 'build/resource-sdk'), LLVM_PROFILE_FILE=str(BASE / 'runtime-%m-%p.profraw'))
sys.path.insert(0, str(OWNER)); sys.path.insert(0, str(OWNER / 'tests'))
suite = unittest.TestSuite()
for name in ('test_native_public_resources', 'test_native_resource_build'):
    spec = importlib.util.spec_from_file_location(name, OWNER / 'tests' / (name + '.py'))
    module = importlib.util.module_from_spec(spec); sys.modules[name] = module; spec.loader.exec_module(module)
    module.ROOT = mirror
    suite.addTests(unittest.defaultTestLoader.loadTestsFromModule(module))
state = {'head': INDEX['head'], 'status': 'running', 'source_files': len(INDEX['files']),
         'started': datetime.now(timezone.utc).isoformat(),
         'scope': 'Independent public C resource build/CLI/SDK/OTLP and record checks; broader acceptance and inherited compiler correction remain open.'}
(BASE / 'status.json').write_text(json.dumps(state, indent=2) + '\n')
started = time.monotonic()
result = None
try:
    with (BASE / 'tests.log').open('x') as stream:
        result = unittest.TextTestRunner(stream=stream, verbosity=2).run(suite)
    state.update(status='passed' if result.wasSuccessful() else 'failed', tests=result.testsRun,
                 failures=len(result.failures), errors=len(result.errors), skipped=len(result.skipped))
finally:
    after = inputs(); (BASE / 'inputs-after.json').write_text(json.dumps(after, indent=2) + '\n')
    state['preservation'] = {key: before[key] == after[key] for key in before}
    if not all(state['preservation'].values()): state['status'] = 'failed'
    state.update(seconds=round(time.monotonic() - started, 3), finished=datetime.now(timezone.utc).isoformat())
    (BASE / 'status.json').write_text(json.dumps(state, indent=2) + '\n')
    print(json.dumps(state, indent=2), flush=True)
    raise SystemExit(0 if state['status'] == 'passed' else 1)
