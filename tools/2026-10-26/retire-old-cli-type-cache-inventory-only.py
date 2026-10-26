"""Retire unreferenced type metadata from named, inactive CLI build caches."""

from __future__ import annotations

import argparse
import hashlib
import json
import os
from pathlib import Path
import shutil
import stat
import subprocess
import time

ROOT = Path('/Users/sclarke/github/oteleq-qualification')
OUT = ROOT / '2026-10-26/old-cli-type-cache-retirement-02'
NAMES = (
    'project-tests-target', 'project-reporting-target', 'java-quality-target',
    'node-boundary-target', 'hash-workflow-target', 'node-source-target',
    'capability-guard-target', 'sdk-capability-target',
)
TARGETS = tuple(ROOT / 'work' / name for name in NAMES)
HISTORICAL_INVENTORIES = {'/Users/sclarke/github/oteleq-qualification/2026-10-23/qualification-large-file-footprint.json': '5b45559ec8b98761475e4d9719dae7848201496087efb70b759eec02020e0a79', '/Users/sclarke/github/oteleq-qualification/2026-10-26/old-cli-type-cache-retirement-01/plan.json': '574e78585d9c5c14358f7521edc36cc4155822def8b075e0460957093b2ebed7'}
MAXIMUM_MTIME = 1792796400  # 2026-10-24: all candidates predate current work.


def facts(path: Path) -> list:
    """Retain bytes and all non-access-time file facts."""
    info = path.lstat()
    assert stat.S_ISREG(info.st_mode) and not path.is_symlink(), path
    with path.open('rb') as stream:
        digest = hashlib.file_digest(stream, 'sha256').hexdigest()
    return [digest, info.st_dev, info.st_ino, info.st_mode, info.st_uid,
            info.st_gid, info.st_size, info.st_mtime_ns, info.st_ctime_ns,
            info.st_nlink]


def idle() -> set[str]:
    """Refuse while a compiler or any candidate file is in active use."""
    processes = subprocess.run(
        ['/bin/ps', '-axo', 'comm='], capture_output=True, text=True, check=True,
    ).stdout.splitlines()
    assert not any(Path(line.strip()).name in ('cargo', 'rustc') for line in processes), 'active compiler'
    opened = subprocess.run(['/usr/sbin/lsof', '-Fn'], capture_output=True, text=True)
    assert opened.returncode in (0, 1), 'cannot inspect open files'
    return {line[1:] for line in opened.stdout.splitlines() if line.startswith('n/')}


def strings(value):
    """Inspect catalogue keys as well as values without printing their contents."""
    if isinstance(value, dict):
        for key, item in value.items():
            yield key
            yield from strings(item)
    elif isinstance(value, list):
        for item in value:
            yield from strings(item)
    elif isinstance(value, str):
        yield value


def references(candidates: set[str]) -> tuple[set[str], int]:
    """Preserve any candidate explicitly named by bounded evidence catalogues."""
    referenced, count = set(), 0
    for workspace in (ROOT, ROOT.with_name('otelc-qualification')):
        pending = [(workspace, 0)]
        while pending:
            directory, depth = pending.pop()
            for path in directory.iterdir():
                if str(path) in HISTORICAL_INVENTORIES:
                    assert hashlib.sha256(path.read_bytes()).hexdigest() == HISTORICAL_INVENTORIES[str(path)]
                    continue
                if path.is_symlink() or path == OUT:
                    continue
                if path.is_file() and path.suffix == '.json' and path.stat().st_size <= 64 * 1024**2:
                    try:
                        value = json.loads(path.read_bytes())
                    except (OSError, ValueError):
                        continue
                    referenced.update(text for text in strings(value) if text in candidates)
                    count += 1
                elif path.is_dir() and depth < 3 and path.name not in (
                    'work', 'history-pruned', 'build', 'target', 'node_modules',
                    '.git', 'modules', 'go-cache', 'source', 'source-ab561e7',
                ):
                    pending.append((path, depth + 1))
    return referenced, count


def plan() -> None:
    """Produce a reviewable deletion plan while preserving every other file."""
    assert not OUT.exists()
    opened = idle()
    candidates, protected = {}, {}
    for root in TARGETS:
        assert root.resolve(strict=True) == root and root.is_dir() and not root.is_symlink()
        for folder, directories, files in os.walk(root, followlinks=False):
            assert all(not (Path(folder) / name).is_symlink() for name in directories)
            for name in files:
                path = Path(folder) / name
                info = path.lstat()
                assert stat.S_ISREG(info.st_mode), path
                relative = path.relative_to(root).parts
                eligible = (
                    path.suffix == '.rmeta' and info.st_nlink == 1
                    and not info.st_mode & 0o111 and info.st_mtime < MAXIMUM_MTIME
                    and relative[:-1] in (('debug', 'deps'), ('llvm-cov-target', 'debug', 'deps'))
                )
                if eligible and str(path) not in opened:
                    candidates[str(path)] = facts(path)
                else:
                    protected[str(path)] = facts(path)
    referenced, count = references(set(candidates))
    for name in referenced:
        protected[name] = candidates.pop(name)
    assert candidates, 'no disposable metadata'
    OUT.mkdir()
    value = {
        'status': 'planned', 'targets': list(map(str, TARGETS)),
        'scope': 'Only unreferenced, single-link, non-executable .rmeta type-cache files in eight old CLI targets. All source, executable products, object/rlib/dylib files, profiles and existing evidence stay held.',
        'historical_inventories': HISTORICAL_INVENTORIES,
        'historical_inventory_scope': 'The storage footprint and previous cache-retirement snapshot are historical measurements, not application/build-input catalogues. Their original bytes stay held. Only their otherwise-unreferenced inactive CLI type caches are retired.',
        'catalogues_checked': count, 'explicit_references_preserved': len(referenced),
        'free_before': shutil.disk_usage(ROOT).free,
        'planned_files': len(candidates), 'logical_bytes': sum(row[6] for row in candidates.values()),
        'candidates': candidates, 'protected': protected,
    }
    (OUT / 'plan.json').write_text(json.dumps(value, indent=2) + '\n')
    print(json.dumps({key: value for key, value in value.items() if key not in ('candidates', 'protected')}))


def apply() -> None:
    """Apply only the unchanged reviewed plan and verify all retained files."""
    path = OUT / 'plan.json'
    value = json.loads(path.read_text())
    assert value['status'] == 'planned' and value['targets'] == list(map(str, TARGETS))
    assert not (OUT / 'result.json').exists()
    opened = idle()
    assert not opened.intersection(value['candidates']), 'active cache file'
    for name, expected in (value['candidates'] | value['protected']).items():
        assert facts(Path(name)) == expected, 'changed cache: ' + name
    newly_referenced, count = references(set(value['candidates']))
    assert not newly_referenced, 'newly referenced metadata'
    started = time.monotonic()
    with (OUT / 'deleted.jsonl').open('x') as log:
        for name, expected in value['candidates'].items():
            candidate = Path(name)
            assert facts(candidate) == expected, 'cache changed before deletion'
            candidate.unlink()
            log.write(json.dumps({'path': name, 'original_facts': expected}) + '\n')
    assert all(facts(Path(name)) == expected for name, expected in value['protected'].items())
    result = {
        'status': 'retired', 'scope': value['scope'],
        'historical_inventories': HISTORICAL_INVENTORIES,
        'deleted_files': len(value['candidates']), 'logical_bytes': value['logical_bytes'],
        'protected_files_held': len(value['protected']), 'catalogues_rechecked': count,
        'free_before': value['free_before'], 'free_after': shutil.disk_usage(ROOT).free,
        'seconds': round(time.monotonic() - started, 3),
    }
    (OUT / 'result.json').write_text(json.dumps(result, indent=2) + '\n')
    print(json.dumps(result))


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('operation', choices=('plan', 'apply'))
    arguments = parser.parse_args()
    plan() if arguments.operation == 'plan' else apply()
