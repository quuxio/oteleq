"""Validate the exact typed private-handle callers revision without editing maintained inputs."""

import datetime
import hashlib
import json
import os
from pathlib import Path
import subprocess
import tarfile

BASE = Path(__file__).resolve().parent
REPO = Path('/Users/sclarke/github/oteleq-qualification/work/oteleq-java-action-session')
assert not subprocess.check_output(['git','status','--porcelain'],cwd=REPO)
head = subprocess.check_output(['git','rev-parse','HEAD'],cwd=REPO,text=True).strip()
parent = subprocess.check_output(['git','rev-parse','HEAD^'],cwd=REPO,text=True).strip()
source = BASE / ('source-' + head[:7])
archive = source.with_suffix('.tar')
meta=json.loads(source.with_suffix('.json').read_text())
before=meta['files']
names=list(before)
def hashes():
    return {name:hashlib.sha256((source/name).read_bytes()).hexdigest() for name in names}
assert hashes()==before and head==meta['head'] and parent==meta['base']
assert hashlib.sha256(archive.read_bytes()).hexdigest()==meta['archive_sha256']
old = Path('/Users/sclarke/github/oteleq-qualification/2026-10-23/qualification-retention/source-2b0f9f1/ci')
subprocess.run(['/bin/cp', '-cR', str(old / 'markdownlint/node_modules'), str(source / 'ci/markdownlint')], check=True)
subprocess.run(['/bin/cp', '-cR', str(old / 'java-coverage'), str(source / 'ci')], check=True)
previous = json.loads(Path('/Users/sclarke/github/oteleq-qualification/2026-10-23/python-runtime-consumer/gate-feb2eae.json').read_text())
command = previous['command']
environment = {**os.environ, **previous['environment']}
source.with_suffix('.json').write_text(json.dumps({
    'head': head, 'base': parent, 'archive_sha256': hashlib.sha256(archive.read_bytes()).hexdigest(),
    'files': before}, indent=2) + '\n')
record = {'head': head, 'base': parent, 'source': str(source), 'owner_pid': os.getpid(),
          'source_files_before': len(before), 'command': command, 'environment': previous['environment'],
          'runner_sha256': hashlib.sha256(Path(__file__).read_bytes()).hexdigest(),
          'started_at': datetime.datetime.now(datetime.timezone.utc).isoformat()}
receipt = BASE / ('gate-' + head[:7] + '.json')
log = BASE / ('gate-' + head[:7] + '.log')
with log.open('wb') as output:
    process = subprocess.Popen(command, cwd=source, env=environment, stdout=output, stderr=subprocess.STDOUT)
    record['make_pid'] = process.pid
    receipt.write_text(json.dumps(record, indent=2) + '\n')
    print(json.dumps({key: record[key] for key in ('head', 'source', 'owner_pid', 'make_pid')}), flush=True)
    result = process.wait()
after = hashes()
record.update(exit_code=result, source_files_after=len(after), source_preserved=after == before,
              log_sha256=hashlib.sha256(log.read_bytes()).hexdigest(),
              finished_at=datetime.datetime.now(datetime.timezone.utc).isoformat())
receipt.write_text(json.dumps(record, indent=2) + '\n')
print(json.dumps({key: record[key] for key in ('head', 'exit_code', 'source_preserved', 'finished_at')}), flush=True)
raise SystemExit(result if after == before else 1)
