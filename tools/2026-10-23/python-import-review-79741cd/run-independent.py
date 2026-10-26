"""Independently exercise frozen benchmark boundaries with both pinned Pythons."""

import datetime
import hashlib
import json
import os
from pathlib import Path
import re
import subprocess

ROOT = Path(__file__).resolve().parent
SOURCE = ROOT / 'source'
INDEX = json.loads((ROOT / 'source.json').read_text())
ENVIRONMENTS = (
    '/Users/sclarke/github/oteleq-qualification/2026-10-23/python-cli-review-b6dbebb/validation-env-312/bin/python',
    '/Users/sclarke/github/oteleq-qualification/2026-10-23/python-http-review-87ab378/validation-env/bin/python',
)
assert not (ROOT / 'tests.json').exists()
assert all(hashlib.sha256((SOURCE / name).read_bytes()).hexdigest() == value for name, value in INDEX['files'].items())
rows = []
for executable in ENVIRONMENTS:
    probe = subprocess.check_output([executable, '-c',
        'import importlib.metadata,json,sys;print(json.dumps({"version":sys.version,"packages":{d.metadata["Name"].lower():d.version for d in importlib.metadata.distributions()}}))'], text=True)
    installed = json.loads(probe)
    pins = dict(re.findall(r'^([a-zA-Z0-9_-]+)==([^ \\\n]+)', (SOURCE / 'requirements.txt').read_text(), re.M))
    assert len(pins) == 23
    assert all(installed['packages'][name.lower()] == version for name, version in pins.items())
    version = installed['version'].split()[0]
    environment = dict(os.environ, PYTHONPATH=str(SOURCE) + ':' + str(SOURCE / 'tests'),
        PYTHONDONTWRITEBYTECODE='1', PATH='/opt/homebrew/opt/llvm@22/bin:/opt/homebrew/bin:/usr/bin:/bin')
    arguments = [executable, '-B', '-m', 'unittest', 'test_python_native_inputs', 'test_python_import_inputs',
        'test_python_input_journal', 'test_python_prepared.PythonPreparedTests.test_public_plain_and_instrumented_launch_retain_original_import_reads',
        'test_python_benchmark.PythonBenchmarkTests.test_native_five_modes_share_one_instrumented_pid_and_separate_sdk_costs', '-v']
    record = {'version': version, 'pinned_dependencies': pins, 'command': arguments,
        'started': datetime.datetime.now(datetime.UTC).isoformat()}
    logfile = ROOT / ('independent-' + version + '.log')
    with logfile.open('x') as output:
        result = subprocess.run(arguments, cwd=SOURCE, env=environment, stdout=output,
            stderr=subprocess.STDOUT, timeout=360)
    counts = re.findall(r'^Ran (\d+) tests', logfile.read_text(), re.M)
    record.update(exit=result.returncode, distinct_tests=int(counts[-1]) if counts else None,
        finished=datetime.datetime.now(datetime.UTC).isoformat())
    rows.append(record)
    (ROOT / 'tests.json').write_text(json.dumps(rows, indent=2) + '\n')
    print(json.dumps({key: record[key] for key in ('version', 'exit', 'distinct_tests')}), flush=True)
assert all(hashlib.sha256((SOURCE / name).read_bytes()).hexdigest() == value for name, value in INDEX['files'].items())
(ROOT / 'source-after.json').write_text(json.dumps({'commit': INDEX['commit'],
    'tracked_files_preserved': len(INDEX['files'])}, indent=2) + '\n')
raise SystemExit(0 if all(row['exit'] == 0 for row in rows) else 1)
