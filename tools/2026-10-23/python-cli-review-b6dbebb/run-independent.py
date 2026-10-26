"""Review the frozen CLI entry in both pinned SDK Python environments."""
import datetime
import hashlib
import json
import os
from pathlib import Path
import re
import subprocess

root = Path(__file__).resolve().parent
source = root / 'source'
index = json.loads((root / 'source.json').read_text())
environments = json.loads((root / 'dependency-before.json').read_text())
modules = ['test_cli_bootstrap', 'test_python_sdk_process', 'test_python_prepared']
rows = []
for setup in environments:
    version = setup['version'].split()[0]
    environment = dict(os.environ)
    environment.update(PYTHONPATH=str(source) + ':' + str(source / 'tests'),
        PYTHONDONTWRITEBYTECODE='1',
        PATH='/opt/homebrew/opt/llvm@22/bin:/opt/homebrew/bin:/usr/bin:/bin')
    command = [setup['executable'], '-m', 'unittest', *modules, '-v']
    record = {'version': version, 'command': command,
        'started': datetime.datetime.now(datetime.UTC).isoformat()}
    with (root / ('independent-' + version + '.log')).open('w') as output:
        result = subprocess.run(command, cwd=source, env=environment,
            stdout=output, stderr=subprocess.STDOUT, timeout=300)
    text = (root / ('independent-' + version + '.log')).read_text()
    counts = re.findall(r'^Ran (\d+) tests', text, re.M)
    record.update(exit=result.returncode, distinct_tests=int(counts[-1]) if counts else None,
        finished=datetime.datetime.now(datetime.UTC).isoformat())
    rows.append(record)
    (root / 'tests.json').write_text(json.dumps(rows, indent=2) + '\n')
    print(json.dumps(record), flush=True)
    if result.returncode:
        raise SystemExit(result.returncode)
assert all(hashlib.sha256((source / name).read_bytes()).hexdigest() == value
    for name, value in index['files'].items())
(root / 'source-after.json').write_text(json.dumps({'head': index['head'],
    'tracked_files_preserved': len(index['files'])}, indent=2) + '\n')
