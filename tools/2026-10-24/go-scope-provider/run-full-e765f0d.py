"""Run all product gates against one immutable, committed source snapshot."""

import hashlib
import json
import os
from pathlib import Path
import subprocess
import time

BASE = Path(__file__).resolve().parent
ROOT = BASE / 'full-gate-e765f0d'
spec = json.loads((ROOT / 'command.json').read_text())
index = json.loads((BASE / 'source-e765f0d.json').read_text())
source = Path(spec['cwd'])
assert index['head'] == spec['head']

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
(ROOT / 'inputs-before.json').write_text(json.dumps(before, indent=2) + '\n')
environment = {key: value for key, value in os.environ.items() if not key.startswith(('OTEL', 'OTELEQ', 'GH_', 'GITHUB_', 'SONAR_', 'AWS_'))}
tools = spec['selected_tools']
rust = Path('/Users/sclarke/.rustup/toolchains/1.98.1-aarch64-apple-darwin/bin')
paths = [rust, *[Path(tools[key]).parent for key in ('OTELC_NODE', 'OTELC_CLANG', 'OTELC_JAVA', 'OTELC_GO')]]
environment.update(tools)
environment.update(PATH=os.pathsep.join(map(str, paths)) + os.pathsep + environment.get('PATH', ''),
                   CARGO_TARGET_DIR=str(ROOT / 'target'), PYTHONDONTWRITEBYTECODE='1')
started = time.monotonic()
with (ROOT / 'make-check.log').open('xb') as output:
    result = subprocess.run(spec['argv'], cwd=source, env=environment, stdout=output, stderr=subprocess.STDOUT)
after = inputs()
(ROOT / 'inputs-after.json').write_text(json.dumps(after, indent=2) + '\n')
receipt = {'head': spec['head'], 'exit_code': result.returncode, 'seconds': round(time.monotonic() - started, 3),
           'source_preserved': before == after, 'files_checked': len(before),
           'changed': [name for name in before if before[name] != after[name]]}
(ROOT / 'result.json').write_text(json.dumps(receipt, indent=2) + '\n')
print(json.dumps(receipt))
raise SystemExit(0 if result.returncode == 0 and before == after else 1)
