"""Retire only old unlinked Go cache entries absent from retained references."""
from pathlib import Path
import datetime
import hashlib
import json
import os
import re
import shutil
import stat
import subprocess
import time

BASE = Path(__file__).resolve().parent
index = json.loads((BASE / 'all-text-references.json').read_text())
cache = Path(index['cache'])
assert str(cache) == '/Users/sclarke/github/otelc-qualification/work/go-source-adapter/build/go-build-cache'
assert cache.resolve(strict=True) == cache and not cache.is_symlink()
processes = subprocess.check_output(['/bin/ps', 'eww', '-axo', 'pid=,comm=,args='], text=True)
assert not re.search(r'(?:^|\s)GOCACHE=' + re.escape(str(cache)) + r'(?:\s|$)', processes), 'selected cache has a live user'


def facts(path):
    s = path.stat()
    return [s.st_dev, s.st_ino, s.st_mode, s.st_uid, s.st_gid, s.st_size,
            s.st_mtime_ns, s.st_ctime_ns, s.st_nlink]


references = set(index['references'])
held = {name: {'facts': facts(Path(name)), 'sha256': hashlib.file_digest(Path(name).open('rb'), 'sha256').hexdigest()}
        for name in references if Path(name).is_file()}
missing = sorted(name for name in references if not Path(name).is_file())
(BASE / 'protected-before.json').write_text(json.dumps(held, indent=2) + '\n')
cutoff = time.time() - 3600
result = {'cache': str(cache), 'cutoff': cutoff, 'started': datetime.datetime.now(datetime.timezone.utc).isoformat(),
          'free_bytes_before': shutil.disk_usage(cache).free, 'protected': len(held),
          'preexisting_missing_references': missing, 'deleted_files': 0, 'logical_bytes_removed': 0,
          'skipped_recent_linked_or_referenced': 0, 'failures': [],
          'scope': 'Only canonical Go action/data cache files, older than one hour, single-link and absent from390 references found across all retained nonbinary qualification inputs. Source, tools, indexes, linked/recent files and every existing referenced byte/file fact preserved.'}
started = time.monotonic()
with (BASE / 'deleted.jsonl').open('w') as log:
    for folder in cache.iterdir():
        if not re.fullmatch('[0-9a-f]{2}', folder.name) or folder.is_symlink() or not folder.is_dir():
            continue
        for entry in os.scandir(folder):
            if not re.fullmatch('[0-9a-f]{64}-[ad]', entry.name):
                continue
            path = Path(entry.path)
            state = entry.stat(follow_symlinks=False)
            if (not stat.S_ISREG(state.st_mode) or state.st_nlink != 1 or str(path) in references
                    or max(state.st_mtime, state.st_ctime) >= cutoff):
                result['skipped_recent_linked_or_referenced'] += 1
                continue
            if path.stat(follow_symlinks=False) != state:
                result['failures'].append(str(path) + ': changed before unlink')
                continue
            path.unlink()
            log.write(json.dumps({'path': str(path), 'size': state.st_size}) + '\n')
            result['deleted_files'] += 1
            result['logical_bytes_removed'] += state.st_size
            if result['deleted_files'] % 25000 == 0:
                print(json.dumps({'deleted_files': result['deleted_files'], 'logical_bytes_removed': result['logical_bytes_removed'], 'free_bytes': shutil.disk_usage(cache).free}), flush=True)
assert held == {name: {'facts': facts(Path(name)), 'sha256': hashlib.file_digest(Path(name).open('rb'), 'sha256').hexdigest()} for name in held}
result.update(status='passed', seconds=round(time.monotonic() - started, 3), free_bytes_after=shutil.disk_usage(cache).free,
              retained_file_facts_unchanged=True, finished=datetime.datetime.now(datetime.timezone.utc).isoformat())
(BASE / 'cleanup.json').write_text(json.dumps(result, indent=2) + '\n')
print(json.dumps(result), flush=True)
