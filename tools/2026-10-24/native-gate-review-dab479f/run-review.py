"""Compile and execute the frozen pre-exec gate independently on two Pythons."""

import hashlib
import json
import os
from pathlib import Path
import subprocess
import tarfile
import time

ROOT = Path(__file__).resolve().parent
index = json.loads((ROOT / 'source-index.json').read_text())
environment = {key: value for key, value in os.environ.items() if not key.startswith(('OTEL', 'OTELEQ', 'GH_', 'GITHUB_', 'SONAR_', 'AWS_', 'LLVM_PROFILE'))}
environment.update(LLVM_CONFIG='/opt/homebrew/opt/llvm@22/bin/llvm-config',
                   PATH='/opt/homebrew/opt/llvm@22/bin:/opt/homebrew/bin:' + environment.get('PATH', ''),
                   PYTHONDONTWRITEBYTECODE='1')
receipts = []
for suffix in ('312', '314'):
    folder = ROOT / ('python-' + suffix)
    folder.mkdir()
    source = folder / 'source'
    source.mkdir()
    with tarfile.open(index['archive']) as data:
        data.extractall(source, filter='data')
    def inputs():
        result = {}
        for name, digest in index['files'].items():
            path = source / name
            value = path.stat()
            observed = hashlib.sha256(path.read_bytes()).hexdigest()
            assert observed == digest, name
            result[name] = [observed, value.st_dev, value.st_ino, value.st_mode, value.st_uid,
                            value.st_gid, value.st_size, value.st_mtime_ns, value.st_ctime_ns]
        return result
    before = inputs()
    (folder / 'inputs-before.json').write_text(json.dumps(before, indent=2) + '\n')
    python = ROOT.parent / ('python-live-metrics/env-' + suffix + '/bin/python')
    command = [str(python), '-B', '-m', 'coverage', 'run', '--data-file=' + str(folder / 'review.coverage'),
               str(ROOT / 'test-main.py'), str(folder / 'tests.json')]
    (folder / 'command.json').write_text(json.dumps({'argv': command, 'cwd': str(source), 'head': index['head']}, indent=2) + '\n')
    started = time.monotonic()
    with (folder / 'tests.log').open('xb') as output:
        process = subprocess.run(command, cwd=source, env=environment, stdout=output, stderr=subprocess.STDOUT, timeout=600)
    after = inputs()
    (folder / 'inputs-after.json').write_text(json.dumps(after, indent=2) + '\n')
    receipt = {'head': index['head'], 'python': suffix, 'exit_code': process.returncode,
               'seconds': round(time.monotonic() - started, 3), 'source_preserved': before == after,
               'files_checked': len(before), 'tests': json.loads((folder / 'tests.json').read_text())}
    if process.returncode == 0:
        coverage = json.loads((source / 'build/native-gate-coverage.json').read_text())
        receipt['native_coverage'] = coverage['line_coverage']
    (folder / 'result.json').write_text(json.dumps(receipt, indent=2) + '\n')
    receipts.append(receipt)
    print(json.dumps(receipt), flush=True)
    assert process.returncode == 0 and before == after
(ROOT / 'execution-results.json').write_text(json.dumps(receipts, indent=2) + '\n')
