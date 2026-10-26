"""Compare callbacks introduced by native helper dictionary lookup."""

import hashlib
import json
import os
from pathlib import Path
import subprocess
import sys

base = Path(__file__).resolve().parent
source = base / 'source-de188e5'
sys.path.insert(0, str(source))
from otelc import python_input_journal
products = list((source / 'build/tools/python-inputs').glob('*/build.json'))
matches = [path for path in products if json.loads(path.read_text())['inputs']['interpreter']['path'] == sys.executable]
assert len(matches) == 1
tool = matches[0].parent / 'otelc-python-inputs'
folder = base / ('dictionary-callback-' + sys.implementation.cache_tag)
folder.mkdir()
entry = folder / 'entry.py'
entry.write_text('import builtins\nprint("callbacks", builtins.origin_callback_count)\n')
(folder / 'sitecustomize.py').write_text('''import builtins
import _frozen_importlib_external as external
original = external.__dict__.pop("SourceLoader")
class Key:
    def __hash__(self): return hash("SourceLoader")
    def __eq__(self, other):
        builtins.origin_callback_count += 1
        return type(other) is str and other == "SourceLoader"
external.__dict__[Key()] = original
builtins.origin_callback_count = 0
''')
before = {path.name: hashlib.sha256(path.read_bytes()).hexdigest() for path in folder.glob('*.py')}
environment = {**os.environ, 'PYTHONPATH': str(folder), 'PYTHONHASHSEED': '0', 'PYTHONDONTWRITEBYTECODE': '1'}
argv0 = subprocess.check_output([sys.executable, '-I', '-S', '-B', '-c', 'import sys;print(sys.orig_argv[0])'], text=True).strip()
rows = []
for mode in ('stock', 'native', 'origin'):
    descriptor = None
    if mode == 'stock':
        command = [sys.executable, '-B', str(entry)]
    else:
        path = folder / (mode + '.journal')
        descriptor = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
        command = [str(tool), *(['--origin-observer'] if mode == 'origin' else []),
                   str(descriptor), sys.executable, argv0, '-B', str(entry)]
    try:
        process = subprocess.Popen(command, cwd=folder, env=environment, stdout=subprocess.PIPE, stderr=subprocess.PIPE,
                                   pass_fds=() if descriptor is None else (descriptor,))
        stdout, stderr = process.communicate(timeout=15)
        result = subprocess.CompletedProcess(command, process.returncode, stdout, stderr)
    finally:
        if descriptor is not None:
            os.close(descriptor)
    (folder / (mode + '.stdout')).write_bytes(result.stdout)
    (folder / (mode + '.stderr')).write_bytes(result.stderr)
    row = {'mode': mode, 'pid': process.pid, 'returncode': result.returncode, 'stdout': result.stdout.decode(), 'stderr': result.stderr.decode()}
    if mode != 'stock':
        journal = python_input_journal.read(path, expected_pid=process.pid)
        row.update(capture_failures=journal.capture_failures, complete=journal.complete)
    rows.append(row)
assert before == {path.name: hashlib.sha256(path.read_bytes()).hexdigest() for path in folder.glob('*.py')}
record = {'python': sys.version, 'tool': str(tool), 'source_held': True, 'results': rows}
(folder / 'proof.json').write_text(json.dumps(record, indent=2) + '\n')
print(json.dumps(record))
