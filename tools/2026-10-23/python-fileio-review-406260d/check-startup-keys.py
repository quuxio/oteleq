"""Verify actual site-startup cached method keys across native installation."""

import hashlib
import json
import os
from pathlib import Path
import subprocess
import sys

BASE = Path(__file__).resolve().parent
label = sys.argv[1]
source = BASE / ('source-' + label)
sys.path[:0] = [str(source)]
from ci import build_python_inputs

root = BASE / ('startup-keys-' + label)
root.mkdir()
data = root / 'data.bin'
data.write_bytes(b'abc')
startup = root / 'sitecustomize.py'
startup.write_text('''import _io
file = _io.FileIO(DATA, 'r')
read = file.read
initialiser = file.__init__
read_hash = hash(read)
init_hash = hash(initialiser)
mapping = {read: 'original', initialiser: 'init'}
members = {read, initialiser}
frozen = frozenset(members)
'''.replace('DATA', repr(str(data))))
application = root / 'entry.py'
application.write_text('''import _io, json, sitecustomize as early
checks = [hash(early.read) == early.read_hash, hash(early.initialiser) == early.init_hash,
          early.mapping[early.read] == 'original', early.mapping[early.initialiser] == 'init',
          early.read in early.members, early.initialiser in early.members,
          early.read in early.frozen, early.initialiser in early.frozen,
          early.read == _io.FileIO.read.__get__(early.file, _io.FileIO), early.read() == b'abc']
assert all(checks), checks
early.file.close()
print(json.dumps(checks))
''')
inputs = {path.name: hashlib.sha256(path.read_bytes()).hexdigest() for path in (data, startup, application)}
tool = build_python_inputs.build()
argv0 = subprocess.check_output([sys.executable, '-I', '-S', '-c', 'import sys;print(sys.orig_argv[0])'], text=True).strip()
runs = []
for lane in ('stock', 'native'):
    command = [sys.executable, '-B', str(application)]
    descriptors = ()
    fd = None
    if lane == 'native':
        fd = os.open(root / 'inputs.journal', os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
        descriptors = (fd,)
        command = [str(tool), str(fd), sys.executable, argv0, '-B', str(application)]
    try:
        process = subprocess.Popen(command, cwd=root, pass_fds=descriptors,
                                   env={**os.environ, 'PYTHONPATH': str(root), 'PYTHONDONTWRITEBYTECODE': '1'},
                                   stdout=subprocess.PIPE, stderr=subprocess.PIPE)
    finally:
        if fd is not None:
            os.close(fd)
    out, err = process.communicate(timeout=15)
    (root / (lane + '.stdout')).write_bytes(out)
    (root / (lane + '.stderr')).write_bytes(err)
    assert process.returncode == 0 and not err and json.loads(out) == [True] * 10, (out, err)
    runs.append({'lane': lane, 'pid': process.pid, 'argv': command, 'exit_code': process.returncode,
                 'checks': json.loads(out)})
assert {path.name: hashlib.sha256(path.read_bytes()).hexdigest() for path in (data, startup, application)} == inputs
record = {'producer_head': '406260df97d35dfb35daa4274a6e9651eada4394', 'python': sys.version,
          'source_preserved': True, 'inputs': inputs, 'runs': runs, 'behaviour_matches': True,
          'raw_sha256': {path.name: hashlib.sha256(path.read_bytes()).hexdigest() for path in root.iterdir() if path.is_file()}}
(root / 'proof.json').write_text(json.dumps(record, indent=2) + '\n')
print(json.dumps({'python': sys.version.split()[0], 'behaviour_matches': True, 'checks_per_lane': 10}))
