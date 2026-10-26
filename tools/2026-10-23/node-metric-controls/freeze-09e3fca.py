"""Freeze the committed consumer and retain exact tracked content identities."""
import hashlib
import io
import json
import shutil
import subprocess
import tarfile
from pathlib import Path

root = Path(__file__).parent
worktree = Path('/Users/sclarke/github/oteleq-qualification/work/oteleq-node-metric-controls')
commit = '09e3fcaaca634a4a12542524c7e872e97053947b'
assert subprocess.check_output(['git', 'rev-parse', 'HEAD'], cwd=worktree, text=True).strip() == commit
assert not subprocess.check_output(['git', 'status', '--porcelain'], cwd=worktree)
source = root / 'source-09e3fca'
source.mkdir(mode=0o700)
archive = subprocess.check_output(['git', 'archive', commit], cwd=worktree)
with tarfile.open(fileobj=io.BytesIO(archive)) as stream:
    stream.extractall(source, filter='data')
files = {}
for path in sorted(source.rglob('*')):
    if path.is_file():
        files[str(path.relative_to(source))] = hashlib.sha256(path.read_bytes()).hexdigest()
        path.chmod(0o444)
record = {'commit': commit, 'source': str(source),
          'archive_sha256': hashlib.sha256(archive).hexdigest(), 'files': files}
(root / 'source-09e3fca.json').write_text(json.dumps(record, indent=2) + '\n')
previous = root / 'source-d5b45af'
shutil.copytree(previous / 'ci/markdownlint/node_modules', source / 'ci/markdownlint/node_modules', symlinks=True)
for name in ('jacocoagent.jar', 'jacococli.jar'):
    original = previous / 'ci/java-coverage' / name
    destination = source / 'ci/java-coverage' / name
    destination.parent.mkdir(parents=True, exist_ok=True)
    shutil.copy2(original, destination)
    assert hashlib.sha256(original.read_bytes()).digest() == hashlib.sha256(destination.read_bytes()).digest()
print(json.dumps({'commit': commit, 'source': str(source), 'tracked_files': len(files),
                  'archive_sha256': record['archive_sha256']}))
