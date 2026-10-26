"""Check the bounded group fallback and actual killed-supervisor cleanup."""
import datetime
import hashlib
import json
import os
from pathlib import Path
import re
import subprocess

root = Path(__file__).resolve().parent
source = root / 'source'
setups = json.loads((root.parent / 'python-cli-review-b6dbebb/dependency-before.json').read_text())
rows = []
for setup in setups:
    version = setup['version'].split()[0]
    environment = dict(os.environ)
    environment.update(PYTHONPATH=str(source) + ':' + str(source / 'tests'),
        PYTHONDONTWRITEBYTECODE='1', PATH='/opt/homebrew/opt/llvm@22/bin:/opt/homebrew/bin:/usr/bin:/bin')
    command = [setup['executable'], '-m', 'unittest',
        'test_python_prepared.ProcessGroupCleanupTests',
        'test_python_prepared.PreparedPythonTests.test_public_owner_cleans_children_when_the_supervisor_is_killed', '-v']
    with (root / ('independent-' + version + '.log')).open('w') as output:
        result = subprocess.run(command, cwd=source, env=environment,
            stdout=output, stderr=subprocess.STDOUT, timeout=120)
    counts = re.findall(r'^Ran (\d+) tests', (root / ('independent-' + version + '.log')).read_text(), re.M)
    row = {'version': version, 'command': command, 'exit': result.returncode,
        'distinct_tests': int(counts[-1]) if counts else None}
    rows.append(row)
    (root / 'tests.json').write_text(json.dumps(rows, indent=2) + '\n')
    print(json.dumps(row), flush=True)
    if result.returncode:
        raise SystemExit(result.returncode)
index = json.loads((root / 'source.json').read_text())
assert all(hashlib.sha256((source / name).read_bytes()).hexdigest() == value
    for name, value in index['files'].items())
(root / 'source-after.json').write_text(json.dumps({'head': index['head'],
    'tracked_sources_preserved': len(index['files']),
    'checked_at': datetime.datetime.now(datetime.UTC).isoformat()}, indent=2) + '\n')
