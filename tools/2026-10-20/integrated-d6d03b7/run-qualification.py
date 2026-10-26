"""Run frozen maintained qualifiers and keep durable child status."""
import argparse
import datetime
import hashlib
import json
import os
from pathlib import Path
import shutil
import subprocess

ROOT = Path(__file__).resolve().parent
SOURCE = ROOT / 'consumer'
PROVIDER = Path('/Users/sclarke/github/otelc-qualification/2026-10-20/integrated-provider/d6d03b7/provider')
PYTHON = PROVIDER / '.venv/bin/python'
CLI = ROOT / 'quux-oteleq'
TASKS = {
    'fixed': [('examples/capture_otelc_languages.py', ['--comparator', str(CLI)], 'fixed')],
    'generated': [('tests/qualify_generation.py', ['--cli', str(CLI)], 'generated')],
    'configured': [('tests/qualify_project_policy.py', ['--cli', str(CLI)], 'configured')],
    'rust': [('tests/qualify_rust_build.py', ['--cli', str(CLI)], 'rust'),
             ('tests/qualify_rust_semantics.py', ['--cli', str(CLI)], 'rust-semantics')],
}


def digest(path: Path) -> str:
    with path.open('rb') as stream:
        return hashlib.file_digest(stream, 'sha256').hexdigest()


def write(path: Path, record: dict) -> None:
    path.write_text(json.dumps(record, indent=2) + '\n')


parser = argparse.ArgumentParser(description=__doc__)
parser.add_argument('task', choices=TASKS)
args = parser.parse_args()
manifest = json.loads((PROVIDER.parent / 'manifest.json').read_text())
assert digest(PROVIDER.parent/'manifest.json') == '2a8dbf239c6444c0fb536dff049993beade7eaed6578c9654c1e2d7233e9431f'
assert (ROOT/'provider-verified.json').is_file()
runtime = json.loads((ROOT/'runtime.json').read_text())
assert digest(CLI) == runtime['cli_sha256']
assert shutil.disk_usage(ROOT).free > 2*2**30
# Each job consumes the same frozen source archive; the canonical repo is free
# for later independent implementation, and no live input is rewritten.
environment = dict(os.environ)
environment.update(manifest['environment'])
environment.update(OTELEQ_PYTHON=str(PYTHON), OTELC_JAVAC='/opt/homebrew/opt/openjdk@21/bin/javac',
                   OTELC_CLANG='/opt/homebrew/opt/llvm@22/bin/clang',
                   OTELC_CLANGXX='/opt/homebrew/opt/llvm@22/bin/clang++',
                   PYTHONDONTWRITEBYTECODE='1', CARGO_INCREMENTAL='0',
                   PATH='/Users/sclarke/.rustup/toolchains/1.98.1-aarch64-apple-darwin/bin:/Users/sclarke/.cargo/bin:/opt/homebrew/opt/llvm@22/bin:/opt/homebrew/opt/node@24/bin:/opt/homebrew/bin:/usr/bin:/bin')
record = {'task':args.task, 'runtime_commit':runtime['commit'], 'state':'running',
          'started_at':datetime.datetime.now(datetime.timezone.utc).isoformat(), 'steps':[]}
state = ROOT / (args.task+'-state.json')
with (ROOT/(args.task+'.log')).open('xb') as log:
    for script, extra, destination in TASKS[args.task]:
        qualifier = SOURCE / script
        command = [str(PYTHON),str(qualifier),'--otelc-root',str(PROVIDER),
                   '--report-dir',str(ROOT/destination),*extra]
        child = subprocess.Popen(command, cwd=SOURCE,env=environment,stdout=log,stderr=subprocess.STDOUT)
        step = {'script':script,'sha256':digest(qualifier),'pid':child.pid,'state':'running'}
        record['steps'].append(step);write(state,record)
        rc = child.wait();step.update(state='completed',exit_code=rc)
        write(state,record)
        if rc:
            break
record.update(state='completed',exit_code=rc,completed_at=datetime.datetime.now(datetime.timezone.utc).isoformat())
write(state,record);print(json.dumps(record),flush=True)
raise SystemExit(rc)
