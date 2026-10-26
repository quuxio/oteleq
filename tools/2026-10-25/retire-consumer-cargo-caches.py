"""Retire inactive consumer compiler caches, preserving all executable products."""
from datetime import datetime, timezone
import hashlib
import json
import os
from pathlib import Path
import shutil
import stat
import subprocess

BASE = Path('/Users/sclarke/github/oteleq-qualification')
RECORD = BASE / '2026-10-25/consumer-cargo-cache-retirement'
RECORD.mkdir()
# Keep the latest warm delivery caches. Only completed older consumer gates qualify.
EXCLUDED = {'full-gate-cfd8c7e', 'full-gate-140a26a-02'}
processes = subprocess.run(['ps', '-axo', 'pid=,command='], capture_output=True, text=True, check=True).stdout
candidates = []
for day in (BASE / '2026-10-24', BASE / '2026-10-25'):
    for parent in day.iterdir():
        if not parent.is_dir() or parent.is_symlink():
            continue
        for gate in parent.glob('full-gate-*'):
            target, status = gate / 'target', gate / 'status.json'
            if gate.name in EXCLUDED or not target.is_dir() or target.is_symlink() or not status.is_file():
                continue
            value = json.loads(status.read_text())
            if value.get('status') not in ('passed', 'failed') or not value.get('finished'):
                continue
            assert str(target) not in processes, 'live cache: ' + str(target)
            assert target.resolve(strict=True) == target
            candidates.append((target, status, hashlib.sha256(status.read_bytes()).hexdigest()))


def identity(path):
    state = path.stat(follow_symlinks=False)
    with path.open('rb') as stream:
        digest = hashlib.file_digest(stream, 'sha256').hexdigest()
    return [digest, state.st_dev, state.st_ino, state.st_mode, state.st_uid,
            state.st_gid, state.st_size, state.st_mtime_ns, state.st_ctime_ns, state.st_nlink]


held = {}
plan = []
for target, _, _ in candidates:
    for folder, directories, files in os.walk(target):
        directories[:] = [name for name in directories if not (Path(folder) / name).is_symlink()]
        for name in files:
            path = Path(folder) / name
            state = path.stat(follow_symlinks=False)
            if not stat.S_ISREG(state.st_mode):
                continue
            if state.st_mode & 0o111 or state.st_nlink != 1:
                held[str(path)] = identity(path)
            elif path.suffix in ('.rlib', '.rmeta', '.d', '.o', '.bc'):
                plan.append((path, state))
(RECORD / 'protected-products.json').write_text(json.dumps(held, indent=2) + '\n')
result = {'status': 'running', 'started': datetime.now(timezone.utc).isoformat(),
          'scope': 'Only rlib/rmeta/d/o/bc compiler-cache files in terminal older consumer full-gate targets. Every executable and multiply linked file is retained with original bytes/facts. Latest warm gates and all source/provider/runtime/evidence paths are excluded.',
          'targets': [str(target) for target, _, _ in candidates],
          'protected_products': len(held), 'planned_files': len(plan),
          'free_bytes_before': shutil.disk_usage(BASE).free, 'deleted_files': 0, 'logical_bytes_removed': 0}
(RECORD / 'plan.json').write_text(json.dumps(result, indent=2) + '\n')
with (RECORD / 'deleted.jsonl').open('w') as log:
    for path, before in plan:
        assert path.stat(follow_symlinks=False) == before, 'cache changed: ' + str(path)
        path.unlink()
        log.write(json.dumps({'path': str(path), 'size': before.st_size}) + '\n')
        result['deleted_files'] += 1
        result['logical_bytes_removed'] += before.st_size
assert held == {name: identity(Path(name)) for name in held}, 'preserved executable facts changed'
for _, receipt, digest in candidates:
    assert hashlib.sha256(receipt.read_bytes()).hexdigest() == digest
result.update(status='passed', protected_bytes_and_facts_held=True,
              finished=datetime.now(timezone.utc).isoformat(), free_bytes_after=shutil.disk_usage(BASE).free)
(RECORD / 'result.json').write_text(json.dumps(result, indent=2) + '\n')
print(json.dumps(result))
