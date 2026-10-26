"""Freeze the committed consumer and an isolated full-gate environment."""

import hashlib
import json
from pathlib import Path
import subprocess
import tarfile

ROOT = Path(__file__).resolve().parent
REPO = Path('/Users/sclarke/github/oteleq-qualification/work/oteleq-go-public-provider')
head = subprocess.check_output(['git', 'rev-parse', 'HEAD'], cwd=REPO, text=True).strip()
assert head == 'b2eebdbf03f938b91ac7b08c9751a3591274ecce'
assert not subprocess.check_output(['git', 'status', '--porcelain'], cwd=REPO)
source = ROOT / 'source-b2eebdb'
source.mkdir()
archive = ROOT / 'source-b2eebdb.tar'
with archive.open('xb') as output:
    subprocess.run(['git', 'archive', head], cwd=REPO, stdout=output, check=True)
with tarfile.open(archive) as data:
    data.extractall(source, filter='data')
files = {name: hashlib.sha256((source / name).read_bytes()).hexdigest()
         for name in subprocess.check_output(['git', 'ls-files'], cwd=REPO, text=True).splitlines()}
index = {'head': head, 'tree': subprocess.check_output(['git', 'rev-parse', head + '^{tree}'], cwd=REPO, text=True).strip(),
         'source': str(source), 'archive': str(archive), 'archive_sha256': hashlib.sha256(archive.read_bytes()).hexdigest(),
         'files': files}
(ROOT / 'source-b2eebdb.json').write_text(json.dumps(index, indent=2) + '\n')
for relative in ('ci/markdownlint/node_modules', 'ci/java-coverage'):
    destination = source / relative
    if destination.exists():
        for item in (REPO / relative).iterdir():
            if not (destination / item.name).exists():
                subprocess.run(['/bin/cp', '-cR', str(item), str(destination / item.name)], check=True)
    else:
        subprocess.run(['/bin/cp', '-cR', str(REPO / relative), str(destination)], check=True)
gate = ROOT / 'full-gate-b2eebdb'
gate.mkdir()
subprocess.run(['/bin/cp', '-cR', str(ROOT / 'target-development-01'), str(gate / 'target')], check=True)
previous = ROOT.parent / 'go-frontend-retention/full-gate-3029064-02'
spec = json.loads((previous / 'command.json').read_text())
spec.update(cwd=str(source), head=head)
(gate / 'command.json').write_text(json.dumps(spec, indent=2) + '\n')
(gate / 'runner.py').write_text((previous / 'runner.py').read_text().replace('source-3029064.json', 'source-b2eebdb.json'))
print(json.dumps({key: value for key, value in index.items() if key != 'files'}))
