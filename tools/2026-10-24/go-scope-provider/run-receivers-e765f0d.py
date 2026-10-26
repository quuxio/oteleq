"""Qualify a frozen source-scope receiver route and retain independent inputs."""

import argparse
from datetime import datetime, timezone
import hashlib
import json
import os
from pathlib import Path
import subprocess
import time

parser = argparse.ArgumentParser(description=__doc__)
parser.add_argument('--tagged', action='store_true')
args = parser.parse_args()
BASE = Path(__file__).resolve().parent
label = 'tagged' if args.tagged else 'untagged'
ROOT = BASE / ('receivers-' + label + '-e765f0d-01')
ROOT.mkdir(mode=0o700)
index = json.loads((BASE / 'source-e765f0d.json').read_text())
source = Path(index['source'])
sdk_index = json.loads((BASE / 'sdk-source.json').read_text())
sdk = Path(sdk_index['source'])
python = BASE.parent / 'python-live-metrics/env-312/bin/python'
cli = BASE / 'target-e765f0d-public/debug/quux-oteleq'
directory = sdk / 'build/go-upstream-scope'
tools = json.loads((directory / 'toolchain.json').read_text())
manifest = json.loads((directory / 'scope-source.json').read_text())
tags = ('feature', 'tools', '\u03c0') if args.tagged else ()

def facts(path):
    value = path.stat()
    return [hashlib.sha256(path.read_bytes()).hexdigest(), value.st_dev, value.st_ino, value.st_mode,
            value.st_uid, value.st_gid, value.st_size, value.st_mtime_ns, value.st_ctime_ns]

def inputs():
    return {'consumer': {name: facts(source / name) for name in index['files']},
            'sdk': {name: facts(sdk / name) for name in sdk_index['files']},
            'weaver_source': {name: facts(directory / 'source' / name) for name in manifest['files']},
            'tools': {str(path): facts(path) for path in [directory / 'toolchain.json', directory / 'scope-source.json',
                      *[Path(tools[name]) for name in ('go', 'weaver', 'bundle')], python.resolve(strict=True), cli]}}

def write(path, value):
    path.write_text(json.dumps(value, indent=2) + '\n')

before = inputs()
assert all(before['consumer'][name][0] == digest for name, digest in index['files'].items())
assert all(before['sdk'][name][0] == digest for name, digest in sdk_index['files'].items())
assert all(before['weaver_source'][name][0] == digest for name, digest in manifest['files'].items())
write(ROOT / 'inputs-before.json', before)
command = [str(python), str(source / 'tests/qualify_go_receivers.py'), '--otelc-root', str(sdk),
           '--report-dir', str(ROOT / 'qualification'), '--cli', str(cli), '--backend', 'source-scope-v1']
for tag in tags:
    command += ['--build-tag', tag]
write(ROOT / 'command.json', {'argv': command, 'cwd': str(source), 'head': index['head'], 'sdk_head': sdk_index['head']})
environment = {key: value for key, value in os.environ.items() if not key.startswith(('OTEL', 'OTELEQ', 'GH_', 'GITHUB_', 'SONAR_', 'AWS_'))}
environment.update(OTELEQ_PYTHON=str(python), OTELC_PYTHON=str(python), OTELC_GO=tools['go'],
                   OTELEQ_CLI=str(cli), PYTHONDONTWRITEBYTECODE='1', PATH=str(Path(tools['go']).parent) + os.pathsep + environment.get('PATH', ''))
state = {'status': 'running', 'head': index['head'], 'sdk_head': sdk_index['head'], 'build_tags': list(tags),
         'started': datetime.now(timezone.utc).isoformat()}
write(ROOT / 'status.json', state)
started = time.monotonic()
try:
    with (ROOT / 'qualification.stdout').open('xb') as stdout, (ROOT / 'qualification.stderr').open('xb') as stderr:
        process = subprocess.run(command, cwd=source, env=environment, stdout=stdout, stderr=stderr, timeout=7200)
    state['exit_code'] = process.returncode
    assert process.returncode == 0, process.returncode
    state['qualification'] = json.loads((ROOT / 'qualification/QUALIFICATION.json').read_text())
    state['status'] = 'passed'
except Exception as error:
    state.update(status='failed', error=repr(error))
finally:
    after = inputs()
    write(ROOT / 'inputs-after.json', after)
    state['preservation'] = {name: before[name] == after[name] for name in before}
    if not all(state['preservation'].values()):
        state['status'] = 'failed'
    state.update(seconds=round(time.monotonic() - started, 3), finished=datetime.now(timezone.utc).isoformat())
    write(ROOT / 'status.json', state)
    print(json.dumps(state, indent=2), flush=True)
    raise SystemExit(0 if state['status'] == 'passed' else 1)
