"""Freeze the current uncommitted consumer for isolated development execution."""

import hashlib
import json
from pathlib import Path
import shutil
import subprocess

ROOT = Path(__file__).resolve().parent
REPO = Path('/Users/sclarke/github/oteleq-qualification/work/oteleq-go-public-provider')
source = ROOT / 'source-development-01'
source.mkdir()
names = subprocess.check_output(['git', 'ls-files', '--cached', '--others', '--exclude-standard', '-z'], cwd=REPO).split(b'\0')
names = sorted({name.decode() for name in names if name})
files = {}
for name in names:
    original = REPO / name
    assert original.is_file() and not original.is_symlink(), name
    path = source / name
    path.parent.mkdir(parents=True, exist_ok=True)
    shutil.copy2(original, path)
    files[name] = hashlib.sha256(path.read_bytes()).hexdigest()
index = {'source': str(source), 'parent_head': subprocess.check_output(['git', 'rev-parse', 'HEAD'], cwd=REPO, text=True).strip(),
         'dirty_development_snapshot': True, 'files': files}
(ROOT / 'source-development-01.json').write_text(json.dumps(index, indent=2) + '\n')
subprocess.run(['/bin/cp', '-cR', str(ROOT.parent / 'go-live-controls/target-b2eebdb-public'),
                str(ROOT / 'target-development-01')], check=True)
print(json.dumps({'source': str(source), 'files': len(files), 'dirty_development_snapshot': True}))
