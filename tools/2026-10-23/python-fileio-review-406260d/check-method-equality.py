"""Stock/native falsifier for identity-based builtin method equality."""

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

root = BASE / ('method-equality-' + label)
root.mkdir()
(root / 'data.bin').write_bytes(b'abc')
application = root / 'entry.py'
application.write_text('''import _io, json, sys
from importlib._bootstrap_external import FileLoader
events = []
def profile(frame, event, function):
    if event == "c_call" and getattr(function, "__name__", None) == "read":
        file = getattr(function, "__self__", None)
        if type(file) is _io.FileIO:
            expected = _io.FileIO.read.__get__(file, _io.FileIO)
            events.append([function == expected, hash(function) == hash(expected)])
sys.setprofile(profile)
result = FileLoader("data", "data.bin").get_data("data.bin")
sys.setprofile(None)
print(json.dumps({"content": result.hex(), "events": events}, sort_keys=True))
''')
before = hashlib.sha256(application.read_bytes()).hexdigest()
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
        process = subprocess.Popen(command, cwd=root, pass_fds=descriptors, stdout=subprocess.PIPE, stderr=subprocess.PIPE)
    finally:
        if fd is not None:
            os.close(fd)
    out, err = process.communicate(timeout=15)
    (root / (lane + '.stdout')).write_bytes(out)
    (root / (lane + '.stderr')).write_bytes(err)
    assert process.returncode == 0 and not err
    runs.append({'lane': lane, 'pid': process.pid, 'argv': command, 'exit_code': process.returncode,
                 'output': json.loads(out)})
assert runs[0]['output'] == {'content': '616263', 'events': [[True, True]]}
assert hashlib.sha256(application.read_bytes()).hexdigest() == before
record = {'producer_head': '406260df97d35dfb35daa4274a6e9651eada4394', 'python': sys.version,
          'source_sha256': before, 'source_preserved': True, 'runs': runs,
          'behaviour_matches': runs[0]['output'] == runs[1]['output'],
          'raw_sha256': {path.name: hashlib.sha256(path.read_bytes()).hexdigest() for path in root.iterdir() if path.is_file()}}
(root / 'proof.json').write_text(json.dumps(record, indent=2) + '\n')
print(json.dumps(record))
