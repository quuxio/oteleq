"""Freeze the committed Go live qualifier and independent build directories."""
import hashlib
import json
from pathlib import Path
import subprocess
import tarfile

BASE = Path(__file__).resolve().parent
REPO = Path('/Users/sclarke/github/oteleq-qualification/work/oteleq-go-public-provider')
HEAD = 'dbc8c45df83f699a8bad7b324145941447488559'
assert subprocess.check_output(['git', 'rev-parse', 'HEAD'], cwd=REPO, text=True).strip() == HEAD
assert not subprocess.check_output(['git', 'status', '--porcelain'], cwd=REPO)
source = BASE / 'source-dbc8c45'; source.mkdir()
archive = BASE / 'source-dbc8c45.tar'
with archive.open('xb') as output:
    subprocess.run(['git', 'archive', HEAD], cwd=REPO, stdout=output, check=True)
with tarfile.open(archive) as data:
    data.extractall(source, filter='data')
names = subprocess.check_output(['git', 'ls-files'], cwd=REPO, text=True).splitlines()
index = {'source': str(source), 'head': HEAD, 'tree': subprocess.check_output(['git', 'rev-parse', 'HEAD^{tree}'], cwd=REPO, text=True).strip(),
         'archive': str(archive), 'archive_sha256': hashlib.sha256(archive.read_bytes()).hexdigest(),
         'files': {name: hashlib.sha256((source / name).read_bytes()).hexdigest() for name in names}}
(BASE / 'source-dbc8c45.json').write_text(json.dumps(index, indent=2) + '\n')
for relative in ('ci/markdownlint/node_modules', 'ci/java-coverage'):
    subprocess.run(['/bin/cp', '-cR', str(REPO / relative), str(source / relative)], check=True)
previous = BASE.parent / 'go-scope-provider/full-gate-e765f0d'
gate = BASE / 'full-gate-dbc8c45'; gate.mkdir()
subprocess.run(['/bin/cp', '-cR', str(previous / 'target'), str(gate / 'target')], check=True)
subprocess.run(['/bin/cp', '-cR', str(BASE.parent / 'go-scope-provider/target-e765f0d-public'),
                str(BASE / 'target-dbc8c45-public')], check=True)
spec = json.loads((previous / 'command.json').read_text()); spec.update(cwd=str(source), head=HEAD)
(gate / 'command.json').write_text(json.dumps(spec, indent=2) + '\n')
print(json.dumps({key: value for key, value in index.items() if key != 'files'}), flush=True)
print('files=' + str(len(index['files'])), flush=True)
