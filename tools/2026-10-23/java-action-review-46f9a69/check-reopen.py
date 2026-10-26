"""Retain the actual blocked preparation without starting application code."""

import hashlib
import json
import os
from pathlib import Path
import select
import signal
import shutil
import subprocess
import time

root = Path(__file__).resolve().parent
environment = {**os.environ, 'JAVA_HOME': '/opt/homebrew/opt/openjdk@21',
               'PATH': '/opt/homebrew/opt/openjdk@21/bin:/opt/homebrew/bin:/usr/bin:/bin',
               'OTELC_JAVA': '/opt/homebrew/opt/openjdk@21/bin/java',
               'OTELC_JAVAC': '/opt/homebrew/opt/openjdk@21/bin/javac',
               'PYTHONDONTWRITEBYTECODE': '1'}
command = ['/Users/sclarke/github/oteleq-qualification/2026-10-23/python-cli-review-b6dbebb/validation-env-312/bin/python',
           '-I', '-B', str(root / 'configure-reopen.py')]
stdout = bytearray()
with (root / 'configure-reopen.stderr').open('wb') as errors:
    process = subprocess.Popen(command, env=environment, stdout=subprocess.PIPE, stderr=errors, start_new_session=True)
    try:
        deadline = time.monotonic() + 15
        while b'validated-binding-replaced-with-fifo\n' not in stdout and process.poll() is None and time.monotonic() < deadline:
            if select.select([process.stdout], [], [], .1)[0]:
                stdout.extend(os.read(process.stdout.fileno(), 4096))
        reached = b'validated-binding-replaced-with-fifo\n' in stdout
        timed_out = False
        try:
            process.wait(timeout=2 if reached else 1)
        except subprocess.TimeoutExpired:
            timed_out = True
            os.killpg(process.pid, signal.SIGKILL)
            process.wait(timeout=5)
        stdout.extend(process.stdout.read())
    finally:
        if process.poll() is None:os.killpg(process.pid, signal.SIGKILL);process.wait(timeout=5)
        process.stdout.close()
(root / 'configure-reopen.stdout').write_bytes(stdout)
fifo = root / 'configure-reopen-short/bindings.json'
is_fifo = fifo.is_fifo()
if is_fifo:fifo.unlink()
runtime_path = root / 'configure-reopen-short/runtime-path.txt'
if runtime_path.exists():
    directory = Path(runtime_path.read_text())
    assert directory.parent == Path('/private/tmp') and directory.name.startswith('oteleq-reopen-')
    assert (directory / '.review-owner').read_text() == str(process.pid)
    shutil.copytree(directory, root / 'configure-reopen-short/retained-runtime')
    shutil.rmtree(directory)
proof = {'head': '46f9a69', 'command': command, 'pid': process.pid, 'exit_code': process.returncode,
         'real_bindings_identity_validated': reached, 'reader_timed_out_after_replacement': timed_out,
         'replacement_was_actual_fifo': is_fifo, 'application_executed': False,
         'stdout_sha256': hashlib.sha256(stdout).hexdigest(),
         'stderr_sha256': hashlib.sha256((root / 'configure-reopen.stderr').read_bytes()).hexdigest()}
(root / 'configure-reopen-proof.json').write_text(json.dumps(proof, indent=2) + '\n')
print(json.dumps(proof))
assert reached
