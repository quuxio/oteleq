"""Retire unused Rust incremental caches from eleven terminal local CLI gates."""

from collections import Counter
import hashlib
import json
import os
from pathlib import Path
import shutil
import stat
import struct
import subprocess
import time

ROOT = Path('/Users/sclarke/github/oteleq-qualification')
OUT = ROOT / '2026-10-25/terminal-cli-incremental-retirement.json'
assert not OUT.exists()
NAMES = ('native-lifetime-components/full-gate-572d9c0',
    'native-lifetime-components/full-gate-572d9c0-02',
    'native-prepared-qualification/exact-05e3130-01',
    'native-prepared-qualification/exact-05e3130-02',
    'native-consumer/full-gate-140a26a', 'native-consumer/full-gate-140a26a-02',
    'native-consumer/full-gate-4c97130', 'native-consumer/full-gate-64c42ba',
    'native-consumer/full-gate-6db6b69', 'go-path-boundaries/full-gate-cb08b82',
    'go-live-validation/full-gate-cfd8c7e')
GATES = tuple(ROOT / '2026-10-25' / name for name in NAMES)
FOLDERS = tuple(gate / relative for gate in GATES for relative in (
    'target/debug/incremental', 'target/llvm-cov-target/debug/incremental'))


def facts(path):
    value = path.lstat()
    with path.open('rb') as stream:
        digest = hashlib.file_digest(stream, 'sha256').hexdigest()
    return [digest, value.st_dev, value.st_ino, value.st_mode, value.st_size,
            value.st_mtime_ns, value.st_ctime_ns]


def inspect_processes():
    result = subprocess.run(['/bin/ps', '-axo', 'pid=,args='], capture_output=True,
                            text=True, check=True)
    for line in result.stdout.splitlines():
        pid, _, arguments = line.strip().partition(' ')
        if int(pid) != os.getpid():
            assert not any(str(folder) in arguments for folder in FOLDERS), 'active cache user'
            assert not any(str(gate) in arguments and ('cargo ' in arguments or 'rustc ' in arguments)
                           for gate in GATES), 'active gate compiler'


def strings(value):
    if isinstance(value, dict):
        for key, item in value.items():
            yield key
            yield from strings(item)
    elif isinstance(value, list):
        for item in value:
            yield from strings(item)
    elif isinstance(value, str):
        yield value


started = time.monotonic()
free_before = shutil.disk_usage(ROOT).free
for gate in GATES:
    state = json.loads((gate / 'status.json').read_bytes())
    assert state['status'] in ('passed', 'failed', 'failed_before_gate'), gate
for folder in FOLDERS:
    assert folder.is_dir() and folder.resolve(strict=True) == folder and not folder.is_symlink()
inspect_processes()
files = {}
for folder in FOLDERS:
    for directory, directories, names in os.walk(folder, followlinks=False):
        assert all(not (Path(directory) / name).is_symlink() for name in directories)
        for name in names:
            path = Path(directory) / name
            value = path.lstat()
            assert stat.S_ISREG(value.st_mode)
            # Rust creates empty lock files with owner execute permission.
            assert not value.st_mode & 0o111 or path.suffix == '.lock' and value.st_size == 0
            assert path.suffix in ('.o', '.bin', '.lock', '.rmeta'), path
            if path.suffix != '.rmeta':
                files[path] = value
# Rust hard-links incremental object files into debug/deps. Retire the whole
# known object group; preserve all rmeta/rlib files and any unknown link group.
cache_inodes = {(value.st_dev, value.st_ino) for value in files.values()}
for gate in GATES:
    for directory in ('target/debug/deps', 'target/llvm-cov-target/debug/deps'):
        for path in (gate / directory).glob('*.rcgu.o'):
            value = path.lstat()
            if (value.st_dev, value.st_ino) in cache_inodes:
                assert stat.S_ISREG(value.st_mode) and not value.st_mode & 0o111
                with path.open('rb') as stream:
                    header = stream.read(16)
                assert len(header) == 16 and struct.unpack_from('<I', header)[0] == 0xFEEDFACF
                assert struct.unpack_from('<I', header, 12)[0] == 1, 'not a Mach-O object'
                files[path] = value
counts = Counter((value.st_dev, value.st_ino) for value in files.values())
deferred = [path for path, value in files.items() if value.st_nlink != counts[value.st_dev, value.st_ino]]
deferred_paths = set(deferred)
files = {path: value for path, value in files.items() if path not in deferred_paths}
counts = Counter((value.st_dev, value.st_ino) for value in files.values())
assert all(value.st_nlink == counts[value.st_dev, value.st_ino] for value in files.values()), 'external hard link'
file_names = frozenset(map(str, files))

# Bounded catalogue search: top-level evidence JSON and the next three levels,
# never SDK/build/module trees. Cache paths mentioned by any catalogue refuse.
catalogues = []
referenced = set()
for workspace in (ROOT, ROOT.with_name('otelc-qualification')):
    pending = [(workspace, 0)]
    while pending:
        directory, depth = pending.pop()
        for path in directory.iterdir():
            if path.is_symlink():
                continue
            if path.is_file() and path.suffix == '.json':
                if path.stat().st_size <= 64 * 1024**2:
                    try:
                        value = json.loads(path.read_bytes())
                    except (OSError, ValueError):
                        continue
                    for text in strings(value):
                        if text in file_names:
                            referenced.add(Path(text))
                        elif any(text == str(folder) for folder in FOLDERS):
                            referenced.update(candidate for candidate in files if candidate.is_relative_to(text))
                    catalogues.append(str(path))
            elif path.is_dir() and depth < 3 and path.name not in (
                'work', 'history-pruned', 'build', 'target', 'node_modules', '.git',
                'modules', 'go-cache', 'source', 'source-ab561e7'):
                pending.append((path, depth + 1))

referenced_inodes = {(files[path].st_dev, files[path].st_ino) for path in referenced}
retained_references = {path: value for path, value in files.items()
                       if (value.st_dev, value.st_ino) in referenced_inodes}
files = {path: value for path, value in files.items() if path not in retained_references}
assert files, 'every candidate cache file is retained evidence'
opened = subprocess.run(['/usr/sbin/lsof', '-Fn'], capture_output=True, text=True)
assert opened.returncode in (0, 1)
open_paths = {line[1:] for line in opened.stdout.splitlines() if line.startswith('n/')}
assert not any(str(folder) in name for name in open_paths for folder in FOLDERS), 'open cache file'
assert not open_paths.intersection(map(str, files)), 'open linked object'
protected = {}
for path in retained_references:
    protected[path] = facts(path)
for gate in GATES:
    for path in gate.iterdir():
        if path.is_file() and not path.is_symlink():
            protected[path] = facts(path)
    for directory in ('target/debug', 'target/debug/deps', 'target/llvm-cov-target/debug/deps'):
        for path in (gate / directory).glob('*'):
            if path.is_file() and not path.is_symlink() and path.stat().st_mode & 0o111:
                protected[path] = facts(path)
inspect_processes()
for path, before in files.items():
    after = path.lstat()
    assert (after.st_dev, after.st_ino, after.st_size, after.st_mtime_ns, after.st_ctime_ns) == (
        before.st_dev, before.st_ino, before.st_size, before.st_mtime_ns, before.st_ctime_ns)
for path in files:
    path.unlink()
for folder in FOLDERS:
    for directory, _, _ in os.walk(folder, topdown=False):
        try:
            Path(directory).rmdir()
        except OSError:
            pass  # Retained rmeta or an unknown hard-link group keeps its directory.
assert all(facts(path) == before for path, before in protected.items())
result = {'status': 'retired', 'seconds': round(time.monotonic() - started, 3),
    'scope': 'Only Rust incremental compiler state from eleven terminal CLI gates. '
             'All source, SDK products, executable binaries, reports and profiles retained.',
    'directories': list(map(str, FOLDERS)), 'files': len(files),
    'deferred_unknown_hardlink_files': len(deferred),
    'referenced_candidate_files_retained': len(retained_references),
    'logical_bytes': sum(value.st_size for value in files.values()),
    'catalogues_checked': len(catalogues), 'protected_files_held': len(protected),
    'protected_facts': {str(path): before for path, before in protected.items()},
    'free_before': free_before, 'free_after': shutil.disk_usage(ROOT).free}
OUT.write_text(json.dumps(result, indent=2) + '\n')
print(json.dumps({key: value for key, value in result.items()
                  if key not in ('directories', 'protected_facts')}))
