"""Independent actual FIFO replacement controls with bounded owned children."""

import hashlib
import json
import os
from pathlib import Path
import select
import shutil
import signal
import subprocess
import time

ROOT = Path(__file__).resolve().parent
environment = {**os.environ, 'JAVA_HOME': '/opt/homebrew/opt/openjdk@21',
               'PATH': '/opt/homebrew/opt/openjdk@21/bin:/opt/homebrew/bin:/usr/bin:/bin',
               'OTELC_JAVA': '/opt/homebrew/opt/openjdk@21/bin/java',
               'OTELC_JAVAC': '/opt/homebrew/opt/openjdk@21/bin/javac',
               'PYTHONDONTWRITEBYTECODE': '1'}
results = []
for mode in ('snapshot', 'late'):
    command = ['/Users/sclarke/github/oteleq-qualification/2026-10-23/python-cli-review-b6dbebb/validation-env-312/bin/python',
               '-I', '-B', str(ROOT / 'replacement-child.py'), mode]
    output = bytearray()
    error_log = ROOT / ('replace-' + mode + '.stderr')
    with error_log.open('wb') as errors:
        process = subprocess.Popen(command, env=environment, stdout=subprocess.PIPE, stderr=errors, start_new_session=True)
        try:
            deadline = time.monotonic() + 15
            while b'validated-binding-replaced-with-fifo\n' not in output and process.poll() is None and time.monotonic() < deadline:
                if select.select([process.stdout], [], [], .1)[0]:output.extend(os.read(process.stdout.fileno(), 4096))
            reached = b'validated-binding-replaced-with-fifo\n' in output
            timed_out = False
            try:process.wait(timeout=3)
            except subprocess.TimeoutExpired:
                timed_out = True
                os.killpg(process.pid, signal.SIGKILL);process.wait(timeout=5)
            output.extend(process.stdout.read())
        finally:
            if process.poll() is None:os.killpg(process.pid, signal.SIGKILL);process.wait(timeout=5)
            process.stdout.close()
    proof = ROOT / ('replace-' + mode)
    fifo = proof / 'bindings.json'
    actual_fifo = fifo.is_fifo()
    if actual_fifo:fifo.unlink()
    runtime_path = proof / 'runtime-path.txt'
    if runtime_path.exists():
        directory = Path(runtime_path.read_text())
        assert directory.parent == Path('/private/tmp') and directory.name.startswith('oteleq-snapshot-')
        assert (directory / '.review-owner').read_text() == str(process.pid)
        shutil.copytree(directory, proof / 'retained-runtime');shutil.rmtree(directory)
    (ROOT / ('replace-' + mode + '.stdout')).write_bytes(output)
    row = {'mode': mode, 'command': command, 'pid': process.pid, 'exit_code': process.returncode,
           'validated_snapshot_replaced': reached, 'replacement_was_fifo': actual_fifo,
           'timed_out': timed_out, 'application_executed': False,
           'stdout_sha256': hashlib.sha256(output).hexdigest(), 'stderr_sha256': hashlib.sha256(error_log.read_bytes()).hexdigest()}
    results.append(row)
    (ROOT / 'replacement-proof.json').write_text(json.dumps(results, indent=2) + '\n')
    print(json.dumps(row), flush=True)
    assert reached and actual_fifo and not timed_out and process.returncode == 0
    assert output == b'validated-binding-replaced-with-fifo\nsource-change-refused-without-application-execution\n'
    assert error_log.read_bytes() == b''
