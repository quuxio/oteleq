"""Measure the real compiler helper separately from Python coverage and SDK evidence."""
import hashlib
import importlib.util
import json
import os
from pathlib import Path
import shutil
import subprocess
import sys
import unittest

ROOT = Path('/Users/sclarke/github/oteleq-qualification/work/oteleq-cpp-receivers')
OUTPUT = Path(sys.argv[1]) if len(sys.argv) > 1 else Path('/Users/sclarke/github/oteleq-qualification/2026-10-21/native-frontend-coverage')
OUTPUT.mkdir(exist_ok=False)
PROFILES = OUTPUT / 'profiles'
PROFILES.mkdir()
os.environ['LLVM_PROFILE_FILE'] = str(PROFILES / '%m-%p.profraw')

spec = importlib.util.spec_from_file_location('frontend_tests', ROOT / 'tests/test_generation_native_frontend.py')
module = importlib.util.module_from_spec(spec)
spec.loader.exec_module(module)
original_build = module.native_frontend.build
compiled_source = []


def instrumented_build(compiler, destination, source_root, execute):
    def profile_compile(command, directory):
        if command[-1] == destination / 'native-discover':
            command = [command[0], '-fprofile-instr-generate', '-fcoverage-mapping', *command[1:]]
        return execute(command, directory)
    result = original_build(compiler, destination, source_root, profile_compile)
    shutil.copy2(destination / 'native-discover', OUTPUT / 'native-discover')
    shutil.copy2(destination / 'source/native_discover.cpp', OUTPUT / 'native_discover.cpp')
    compiled_source.append(str(destination / 'source/native_discover.cpp'))
    return result


module.native_frontend.build = instrumented_build
suite = unittest.defaultTestLoader.loadTestsFromTestCase(module.NativeFrontendTests)
result = unittest.TextTestRunner(verbosity=2).run(suite)
if not result.wasSuccessful():
    raise SystemExit(1)
tools = Path(os.environ['OTELC_CLANG']).resolve().parent
profile = OUTPUT / 'coverage.profdata'
subprocess.run([tools / 'llvm-profdata', 'merge', '-sparse', *sorted(PROFILES.glob('*.profraw')), '-o', profile],
               check=True, timeout=30)
summary = subprocess.run([tools / 'llvm-cov', 'export', OUTPUT / 'native-discover',
    '-instr-profile=' + str(profile), '-summary-only', compiled_source[0]],
    capture_output=True, check=True, timeout=30)
(OUTPUT / 'coverage.json').write_bytes(summary.stdout)
document = json.loads(summary.stdout)
files = [item for data in document['data'] for item in data['files'] if item['filename'] == compiled_source[0]]
if len(files) != 1:
    raise SystemExit('missing or ambiguous helper coverage')
lines = files[0]['summary']['lines']
print(json.dumps({'tests': result.testsRun, 'source_sha256': hashlib.sha256((OUTPUT / 'native_discover.cpp').read_bytes()).hexdigest(),
                  'lines': lines, 'coverage_percent': lines['covered'] * 100 / lines['count']}, indent=2))
if lines['covered'] / lines['count'] < 0.8:
    raise SystemExit('compiled helper coverage below 80%')
