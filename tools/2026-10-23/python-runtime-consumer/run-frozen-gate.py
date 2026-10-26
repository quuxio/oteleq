"""Gate an already frozen source archive without reading a moving worktree."""

import datetime
import hashlib
import json
import os
from pathlib import Path
import subprocess
import sys

base = Path(__file__).resolve().parent
prefix = sys.argv[1]
metadata = json.loads((base / ('source-' + prefix + '.json')).read_text())
source = base / ('source-' + prefix)
expected = metadata['files']


def held():
    return all(hashlib.sha256((source / name).read_bytes()).hexdigest() == digest for name, digest in expected.items())


assert held(), 'frozen source differs before gate'
old = Path('/Users/sclarke/github/oteleq-qualification/2026-10-23/qualification-retention/source-2b0f9f1/ci')
subprocess.run(['/bin/cp', '-cR', str(old / 'markdownlint/node_modules'), str(source / 'ci/markdownlint')], check=True)
subprocess.run(['/bin/cp', '-cR', str(old / 'java-coverage'), str(source / 'ci')], check=True)
previous = json.loads((base.parent / 'python-provider-consumer/gate-6e3a21f.json').read_text())
record = {'head': metadata['head'], 'source': str(source), 'source_files_before': len(expected),
          'command': previous['command'], 'environment': previous['environment'], 'owner_pid': os.getpid(),
          'runner_sha256': hashlib.sha256(Path(__file__).read_bytes()).hexdigest(),
          'started_at': datetime.datetime.now(datetime.timezone.utc).isoformat()}
receipt = base / ('gate-' + prefix + '.json')
receipt.write_text(json.dumps(record, indent=2) + '\n')
print(json.dumps({'head': record['head'], 'gate': str(receipt), 'owner_pid': record['owner_pid']}), flush=True)
with (base / ('gate-' + prefix + '.log')).open('wb') as output:
    result = subprocess.run(record['command'], cwd=source, env={**os.environ, **record['environment']},
                            stdout=output, stderr=subprocess.STDOUT)
record.update(exit_code=result.returncode, source_files_after=len(expected), source_preserved=held(),
              finished_at=datetime.datetime.now(datetime.timezone.utc).isoformat())
receipt.write_text(json.dumps(record, indent=2) + '\n')
print(json.dumps(record), flush=True)
raise SystemExit(result.returncode)
