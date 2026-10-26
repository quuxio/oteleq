"""Check the exact cache correction without modifying its source archive."""
import hashlib
from importlib import metadata
import json
import os
from pathlib import Path
import re
import subprocess
import sys

root = Path(__file__).parent
source = root / 'source'
index = json.loads((root / 'source.json').read_bytes())
locked = dict(re.findall(r'^([A-Za-z0-9_.-]+)==([^ \\n]+)', (source / 'requirements.txt').read_text(), re.M))
for name, expected in locked.items():
    assert metadata.version(name) == expected, (name, metadata.version(name), expected)
env = {**os.environ, 'PYTHONDONTWRITEBYTECODE': '1', 'PYTHONPATH': str(source) + os.pathsep + str(source / 'tests')}
modules = [p.stem for p in sorted((source / 'tests').glob('test_python_*.py'))
           if p.stem.startswith(('test_python_monitor', 'test_python_lifetime', 'test_python_cache'))]
with (root / 'independent-cache-tests.log').open('wb') as log:
    test = subprocess.run([sys.executable, '-B', '-m', 'unittest', '-v', *modules], cwd=source, env=env, stdout=log, stderr=subprocess.STDOUT, timeout=180)
print('focused tests exit', test.returncode, flush=True)
assert test.returncode == 0
(root / 'native-call').mkdir(exist_ok=True)
with (root / 'unchanged-native-reproducer.log').open('wb') as log:
    reproduction = subprocess.run([sys.executable, '-B', str(root / 'reproduce-native-cache-gc-lock.py')], cwd=source, env=env, stdout=log, stderr=subprocess.STDOUT, timeout=15)
print('unchanged native reproducer exit', reproduction.returncode, flush=True)
assert reproduction.returncode == 0
report_paths = list((root / 'native-call').rglob('python-sdk-status.json'))
assert len(report_paths) == 1, report_paths
sdk_report = json.loads(report_paths[0].read_bytes())
assert sdk_report['phase'] == 'closed'
assert sdk_report['producer']['lifetimes']['gc_completed'] == 2
for name, expected in index['files'].items():
    assert hashlib.sha256((source / name).read_bytes()).hexdigest() == expected, name
text = (root / 'independent-cache-tests.log').read_text()
count = int(re.search(r'Ran (\d+) tests?', text).group(1))
record = {'head': index['commit'], 'base': index['base'], 'whole_delta_files': 5,
          'independent_focused_tests': count, 'test_exit': test.returncode,
          'unchanged_original_native_gc_reproducer_exit': reproduction.returncode,
          'sdk_phase': sdk_report['phase'], 'actual_gc_completed': 2,
          'pinned_dependency_versions_matched': len(locked), 'source_files_preserved': len(index['files']),
          'findings': [], 'scope': 'Whole five-file correction plus original normal application-call two-thread monitoring/GC/SDK reproducer. Exact-head gates and provider admission remain separate.'}
(root / 'review.json').write_text(json.dumps(record, indent=2) + '\n')
print(json.dumps(record), flush=True)
