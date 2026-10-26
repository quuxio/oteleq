"""Run focused feature reviews against independently frozen source trees."""
import hashlib
from importlib import metadata
import json
import os
from pathlib import Path
import re
import subprocess
import sys

base = Path(__file__).parent
slug, *modules = sys.argv[1:]
root = base / slug
source = root / 'source'
index = json.loads((root / 'source.json').read_bytes())
locked = dict(re.findall(r'^([A-Za-z0-9_.-]+)==([^ \\n]+)', (source / 'requirements.txt').read_text(), re.M))
for name, expected in locked.items():
    assert metadata.version(name) == expected, (name, metadata.version(name), expected)
env = {**os.environ, 'PYTHONDONTWRITEBYTECODE': '1', 'PYTHONPATH': str(source) + os.pathsep + str(source / 'tests')}
with (root / 'independent-tests.log').open('wb') as log:
    result = subprocess.run([sys.executable, '-B', '-m', 'unittest', '-v', *modules], cwd=source, env=env, stdout=log, stderr=subprocess.STDOUT, timeout=240)
for name, expected in index['files'].items():
    assert hashlib.sha256((source / name).read_bytes()).hexdigest() == expected, name
text = (root / 'independent-tests.log').read_text()
matches = list(re.finditer(r'Ran (\d+) tests?', text))
match = matches[-1] if matches else None
record = {'head': index['commit'], 'base': index['base'], 'independent_tests': int(match.group(1)) if match else None,
          'test_exit': result.returncode, 'modules': modules,
          'pinned_dependency_versions_matched': len(locked), 'source_files_preserved': len(index['files'])}
(root / 'tests.json').write_text(json.dumps(record, indent=2) + '\n')
print(json.dumps(record), flush=True)
sys.exit(result.returncode)
