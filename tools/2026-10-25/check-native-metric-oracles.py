"""Retain bounded literal-oracle checks, coverage floors and original source facts."""

import hashlib
import json
import os
from pathlib import Path
import subprocess
import time

ROOT = Path('/Users/sclarke/github/oteleq-qualification/work/oteleq-native-metric-qualification')
OUTPUT = Path('/Users/sclarke/github/oteleq-qualification/2026-10-25/native-metric-controls/qualification-components-02')
MODULES = ('native_metric_cases', 'native_metric_frames', 'native_metric_health', 'native_metric_otlp',
           'native_metric_receipt', 'native_metric_test_capture')


def facts() -> dict:
    names = subprocess.check_output(['git', 'ls-files', '-c', '-o', '--exclude-standard', '-z'], cwd=ROOT).decode().rstrip('\0').split('\0')
    result = {}
    for name in names:
        path = ROOT / name; info = path.lstat()
        with path.open('rb') as stream:
            digest = hashlib.file_digest(stream, 'sha256').hexdigest()
        result[name] = [digest, info.st_dev, info.st_ino, info.st_mode, info.st_size,
                        info.st_mtime_ns, info.st_ctime_ns, info.st_uid, info.st_gid, info.st_nlink]
    return result


def main() -> None:
    OUTPUT.mkdir()
    original = facts()
    (OUTPUT / 'original-source-facts.json').write_text(json.dumps(original, indent=2) + '\n')
    environment = dict(os.environ, PYTHONDONTWRITEBYTECODE='1', PYTHONPATH=str(ROOT / 'tests'))
    checks = []
    def run(argv, label):
        started = time.monotonic()
        result = subprocess.run(argv, cwd=ROOT, env=environment, capture_output=True, timeout=180)
        (OUTPUT / (label + '.stdout')).write_bytes(result.stdout)
        (OUTPUT / (label + '.stderr')).write_bytes(result.stderr)
        row = {'argv': argv, 'label': label, 'returncode': result.returncode, 'seconds': time.monotonic() - started}
        checks.append(row); (OUTPUT / 'checks.json').write_text(json.dumps(checks, indent=2) + '\n')
        print(json.dumps(row), flush=True); result.check_returncode()
    for version in ('312', '314'):
        python = '/Users/sclarke/github/oteleq-qualification/2026-10-24/python-live-metrics/env-' + version + '/bin/python'
        data = str(OUTPUT / (version + '.coverage'))
        run([python, '-B', '-m', 'coverage', 'run', '--data-file=' + data,
             '--include=' + ','.join('*/' + module + '.py' for module in MODULES),
             '-m', 'unittest', 'test_generation_native_metric_qualification', 'test_generation_native_receipt_qualification', '-v'], version)
        run([python, '-m', 'coverage', 'json', '--data-file=' + data, '-o', str(OUTPUT / (version + '-coverage.json'))], version + '-coverage-json')
        for module in MODULES:
            run([python, '-m', 'coverage', 'report', '--data-file=' + data, '--include=*/' + module + '.py',
                 '--fail-under=80'], version + '-' + module)
    assert facts() == original
    result = {'status': 'passed', 'source_files_held': len(original), 'checks': checks,
        'methods_per_python': 16, 'authored_workloads': 28, 'authored_lanes_per_workload': 2,
        'sdk_builds': 0, 'compiler_builds': 0, 'native_application_launches': 0,
        'scope': 'literal independent reader regression records; actual public workflows remain required'}
    (OUTPUT / 'status.json').write_text(json.dumps(result, indent=2) + '\n')
    print(json.dumps(result))


if __name__ == '__main__':
    main()
