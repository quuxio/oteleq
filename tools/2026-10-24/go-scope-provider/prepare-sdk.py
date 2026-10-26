"""Prepare isolated frozen SDK source and its explicit scope-safe Go tooling."""

import hashlib
import json
import os
from pathlib import Path
import subprocess
import tarfile
import time

ROOT = Path(__file__).resolve().parent
producer = Path('/Users/sclarke/github/otelc-qualification/2026-10-24/go-scope-tooling')
index = json.loads((producer / 'source-eda9fcc.json').read_text())
archive = Path(index['archive'])
assert index['head'] == 'eda9fccdfac281dc8763b485a540e10219f45ea7'
assert hashlib.sha256(archive.read_bytes()).hexdigest() == index['archive_sha256'] == '8700550add162ba276c56368c00715fa26b5c0b30f6ad568e9ad907803f01013'
source = ROOT / 'sdk-eda9fcc'
source.mkdir()
with tarfile.open(archive) as data:
    data.extractall(source, filter='data')
assert len(index['files']) == 500


def facts():
    result = {}
    for name, expected in index['files'].items():
        path = source / name
        value = path.stat()
        digest = hashlib.sha256(path.read_bytes()).hexdigest()
        assert digest == expected
        result[name] = [digest, value.st_dev, value.st_ino, value.st_mode, value.st_uid,
                        value.st_gid, value.st_size, value.st_mtime_ns, value.st_ctime_ns]
    return result


before = facts()
(ROOT / 'sdk-source.json').write_text(json.dumps({**index, 'source': str(source), 'facts': before}, indent=2) + '\n')
module_cache = Path('/Users/sclarke/github/oteleq-qualification/2026-10-24/go-source-review-67b1b0d/source/build/go-module-cache')
(source / 'build').mkdir()
subprocess.run(['/bin/cp', '-cR', str(module_cache), str(source / 'build/go-module-cache')], check=True)
environment = {key: value for key, value in os.environ.items()
               if not key.startswith(('OTEL', 'OTELEQ', 'GH_', 'GITHUB_', 'AWS_', 'SONAR_'))}
environment.update(PYTHONDONTWRITEBYTECODE='1')
go = '/Users/sclarke/go/pkg/mod/golang.org/toolchain@v0.0.1-go1.27.3.darwin-arm64/bin/go'
python = '/Users/sclarke/github/oteleq-qualification/2026-10-24/python-live-metrics/env-312/bin/python'
command = [python, '-B', '-m', 'ci.build_go_upstream', '--go', go, '--scope-safe',
           '--output', str(source / 'build/go-upstream-scope')]
(ROOT / 'setup-command.json').write_text(json.dumps({'argv': command, 'cwd': str(source)}, indent=2) + '\n')
started = time.monotonic()
with (ROOT / 'setup.stdout').open('xb') as output, (ROOT / 'setup.stderr').open('xb') as error:
    result = subprocess.run(command, cwd=source, env=environment, stdout=output, stderr=error, timeout=1200)
record = {'sdk_head': index['head'], 'exit_code': result.returncode,
          'seconds': round(time.monotonic() - started, 3), 'source_files_checked': len(before),
          'source_preserved': facts() == before, 'scope': 'SDK/tool setup only, no consumer admission'}
(ROOT / 'setup-result.json').write_text(json.dumps(record, indent=2) + '\n')
print(json.dumps(record, indent=2), flush=True)
raise SystemExit(0 if result.returncode == 0 and record['source_preserved'] else 1)
