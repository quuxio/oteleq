"""Retain bounded native control quality checks with unchanged source facts."""

import hashlib
import json
import os
from pathlib import Path
import re
import subprocess
import time

ROOT = Path('/Users/sclarke/github/oteleq-qualification/work/oteleq-native-control-quality')
BASE = Path('/Users/sclarke/github/oteleq-qualification/2026-10-25/native-metric-controls')
OUTPUT = BASE / 'quality-components-01'


def facts() -> dict:
    names = subprocess.check_output(['git', 'ls-files', '-z'], cwd=ROOT).decode().rstrip('\0').split('\0')
    result = {}
    for name in names:
        path = ROOT / name
        info = path.lstat()
        with path.open('rb') as stream:
            digest = hashlib.file_digest(stream, 'sha256').hexdigest()
        result[name] = [digest, info.st_dev, info.st_ino, info.st_mode, info.st_size,
                        info.st_mtime_ns, info.st_ctime_ns, info.st_uid, info.st_gid, info.st_nlink]
    return result


def main() -> None:
    OUTPUT.mkdir()
    original = facts()
    environment = dict(os.environ, PYTHONDONTWRITEBYTECODE='1',
        PYTHONPATH=str(ROOT / 'tests'), NODE_PATH='/Users/sclarke/github/oteleq-qualification/work/oteleq-native-generated/ci/markdownlint/node_modules',
        OTELC_CLANG='/opt/homebrew/opt/llvm@22/bin/clang', OTELC_CLANGXX='/opt/homebrew/opt/llvm@22/bin/clang++',
        OTELC_LLVM_BIN='/opt/homebrew/opt/llvm@22/bin')
    previous = json.loads((BASE / 'final-components-02/status.json').read_bytes())
    checks = []
    for row in previous['checks']:
        started = time.monotonic()
        result = subprocess.run(row['argv'], cwd=ROOT, env=environment, capture_output=True, timeout=180)
        for channel in ('stdout', 'stderr'):
            (OUTPUT / (row['label'] + '.' + channel)).write_bytes(getattr(result, channel))
        check = {'label': row['label'], 'argv': row['argv'], 'returncode': result.returncode,
                 'seconds': time.monotonic() - started}
        matches = re.findall(rb'Ran (\d+) tests?', result.stderr)
        if matches:
            check['methods'] = sum(int(count) for count in matches)
        checks.append(check)
        (OUTPUT / 'checks.json').write_text(json.dumps(checks, indent=2) + '\n')
        print(json.dumps(check), flush=True)
        result.check_returncode()
    assert facts() == original
    record = {'status': 'passed', 'source_files_held': len(original), 'checks': checks,
        'sdk_builds': 0, 'compiler_builds': 0, 'native_application_launches': 0,
        'scope': 'bounded native controls and compatibility; strict syntax probes only',
        'remaining': 'Required exact-head CI/Sonar and genuine native application qualification'}
    (OUTPUT / 'status.json').write_text(json.dumps(record, indent=2) + '\n')
    print(json.dumps(record))


if __name__ == '__main__':
    main()
