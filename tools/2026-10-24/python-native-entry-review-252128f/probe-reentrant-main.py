"""Check whether a genuine nested public entry can borrow the original read."""
import hashlib
import json
import os
from pathlib import Path
import subprocess
import sys

ROOT = Path(__file__).resolve().parent
SOURCE = ROOT / 'source-252128f'
sys.path[:0] = [str(SOURCE), str(SOURCE / 'tests')]
from ci import build_python_inputs as tooling
from otelc import python_origin_journal as journal
from otelc.python_code_descriptor import encode

folder = ROOT / ('nested-main-' + sys.implementation.cache_tag);folder.mkdir()
tool = tooling.build(origin_entry=True)
_, flags = tooling.toolchain()
library = folder / 'control.dylib'
subprocess.run([tooling.compiler(), '-dynamiclib', '-std=c11', '-Wall', '-Wextra', '-Werror',
    str(ROOT / 'reentrant_main.c'), '-o', str(library), *flags], check=True)
entry = folder / 'original.py'
data = b'def chosen(value): return value*2+3\nprint(chosen(7))\n'
entry.write_bytes(data)
path = folder / 'input.journal'
descriptor = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
argv0 = subprocess.check_output([sys.executable, '-I', '-S', '-c', 'import sys;print(sys.orig_argv[0])'], text=True).strip()
try:
    process = subprocess.Popen([str(tool), '--origin-entry', str(descriptor), sys.executable, argv0, '-B', str(entry)],
        cwd=folder, env={**os.environ, 'DYLD_INSERT_LIBRARIES': str(library), 'REVIEW_ENTRY': str(entry),
                        'REVIEW_REPORT': str(folder / 'control.json')}, pass_fds=(descriptor,),
        stdout=subprocess.PIPE, stderr=subprocess.PIPE)
finally:
    os.close(descriptor)
try:
    out, err = process.communicate(timeout=15)
finally:
    if process.poll() is None:
        process.kill();process.wait(timeout=5)
(folder / 'stdout').write_bytes(out);(folder / 'stderr').write_bytes(err)
value = {'pid': process.pid, 'exit_code': process.returncode, 'stdout_hex': out.hex(), 'stderr_hex': err.hex(),
         'original_source_restored': entry.read_bytes() == data}
try:
    observed = journal.read(path, expected_pid=process.pid)
    correct = hashlib.sha256(encode(compile(data, str(entry), 'exec', dont_inherit=True))).hexdigest()
    value.update(capture_complete=observed.capture_complete, roots=len(observed.roots),
        executions=len(observed.executions), original_descriptor_sha256=correct,
        actual_descriptor_sha256=[root.descriptor.sha256 for root in observed.roots])
except ValueError as error:
    value['journal_refusal'] = str(error)
(folder / 'result.json').write_text(json.dumps(value, indent=2) + '\n')
print(json.dumps(value))
