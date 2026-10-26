"""Freeze committed consumer inputs for separate full-gate and public builds."""

import hashlib
import json
from pathlib import Path
import subprocess
import tarfile

ROOT = Path(__file__).resolve().parent
REPO = Path('/Users/sclarke/github/oteleq-qualification/work/oteleq-go-public-provider')
head = subprocess.check_output(['git', 'rev-parse', 'HEAD'], cwd=REPO, text=True).strip()
assert head == 'e765f0d4e98b9e4fa992ec5b28a71c4203b2b386'
assert not subprocess.check_output(['git', 'status', '--porcelain'], cwd=REPO)
source = ROOT / 'source-e765f0d'
source.mkdir()
archive = ROOT / 'source-e765f0d.tar'
with archive.open('xb') as output:
    subprocess.run(['git', 'archive', head], cwd=REPO, stdout=output, check=True)
with tarfile.open(archive) as data:
    data.extractall(source, filter='data')
files = {name: hashlib.sha256((source / name).read_bytes()).hexdigest() for name in
         subprocess.check_output(['git', 'ls-files'], cwd=REPO, text=True).splitlines()}
index = {'head': head, 'source': str(source), 'archive': str(archive), 'files': files,
         'archive_sha256': hashlib.sha256(archive.read_bytes()).hexdigest(),
         'tree': subprocess.check_output(['git', 'rev-parse', 'HEAD^{tree}'], cwd=REPO, text=True).strip()}
(ROOT / 'source-e765f0d.json').write_text(json.dumps(index, indent=2) + '\n')
for relative in ('ci/markdownlint/node_modules', 'ci/java-coverage'):
    subprocess.run(['/bin/cp', '-cR', str(REPO / relative), str(source / relative)], check=True)
gate = ROOT / 'full-gate-e765f0d'
gate.mkdir()
previous = ROOT.parent / 'go-live-controls/full-gate-b2eebdb'
subprocess.run(['/bin/cp', '-cR', str(previous / 'target'), str(gate / 'target')], check=True)
subprocess.run(['/bin/cp', '-cR', str(ROOT / 'target-development-01'), str(ROOT / 'target-e765f0d-public')], check=True)
spec = json.loads((previous / 'command.json').read_text())
spec.update(cwd=str(source), head=head)
(gate / 'command.json').write_text(json.dumps(spec, indent=2) + '\n')
print(json.dumps({key: value for key, value in index.items() if key != 'files'}))
