"""Bounded public-input falsifier with a real compiled prepared application."""

import hashlib
import json
import os
from pathlib import Path
import select
import stat
import subprocess
import sys

BASE = Path(__file__).resolve().parent
SOURCE = BASE / 'source-6e63272'
root = BASE / 'fifo-bindings'
root.mkdir()
classes = root / 'classes'
classes.mkdir()
application = root / 'Main.java'
application.write_text('public final class Main { public static void main(String[] args) {} }\n')
compiled = subprocess.run(['/opt/homebrew/opt/openjdk@21/bin/javac', '-d', str(classes), str(application)],
                          capture_output=True, timeout=30, check=True)
manifest = root / 'application.json'
manifest.write_text(json.dumps({'schema_version': 1, 'main_class': 'Main', 'classpath': ['classes'],
    'bindings': {'Main': {'source': str(application), 'policy_path': 'Main.java',
                          'source_sha256': hashlib.sha256(application.read_bytes()).hexdigest(),
                          'class_sha256': hashlib.sha256((classes / 'Main.class').read_bytes()).hexdigest(),
                          'provenance': 'independent actual JDK21 javac invocation'}}}, indent=2) + '\n')
pipe = root / 'bindings.json'
os.mkfifo(pipe, 0o600)
child = root / 'read.py'
child.write_text('''import sys
from pathlib import Path
sys.path.insert(0, sys.argv[1])
from otelc.prepared_java import PreparedApplication
from otelc import witness
application = PreparedApplication.load(Path(sys.argv[2]))
print('prepared-application-loaded', flush=True)
try:
    witness.load_bindings(Path(sys.argv[3]), application)
except (OSError, ValueError) as error:
    print(type(error).__name__, str(error), flush=True)
else:
    raise AssertionError('special file was accepted')
''')
command = [sys.executable, '-I', '-B', str(child), str(SOURCE), str(manifest), str(pipe)]
process = subprocess.Popen(command, stdout=subprocess.PIPE, stderr=subprocess.PIPE)
assert select.select([process.stdout], [], [], 15)[0]
ready = process.stdout.readline()
assert ready == b'prepared-application-loaded\n'
timed_out = False
try:
    out, err = process.communicate(timeout=2)
except subprocess.TimeoutExpired:
    timed_out = True
    process.kill()
    out, err = process.communicate(timeout=5)
(root / 'stdout.bin').write_bytes(ready + out)
(root / 'stderr.bin').write_bytes(err)
record = {'head': '6e6327299403491ab84ada517b654ef90f436f6e', 'command': command,
          'pid': process.pid, 'exit_code': process.returncode, 'reader_timed_out': timed_out,
          'fifo_mode': stat.S_IMODE(pipe.stat().st_mode), 'fifo_is_named_pipe': stat.S_ISFIFO(pipe.stat().st_mode),
          'real_prepared_application_loaded': True, 'application_executed': False,
          'raw_sha256': {path.name: hashlib.sha256(path.read_bytes()).hexdigest()
                         for path in (application, manifest, child, root / 'stdout.bin', root / 'stderr.bin')}}
(root / 'proof.json').write_text(json.dumps(record, indent=2) + '\n')
pipe.unlink()
print(json.dumps(record))
