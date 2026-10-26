"""Remove only superseded owned C++ runs after the replacement is delivered."""
import datetime
import hashlib
import json
import os
from pathlib import Path
import shutil

ROOT = Path(__file__).resolve().parent
BASE = ROOT.parents[1]
HISTORY = BASE / 'history-pruned/cpp-receivers'
TARGETS = [ROOT.parent / name for name in ('cpp-development', 'cpp-receivers-4999339',
                                          'cpp-receivers-710279f', 'cpp-receivers-c58cfac')]


def digest(path: Path) -> str:
    with path.open('rb') as stream:
        return hashlib.file_digest(stream, 'sha256').hexdigest()


def verify_current() -> int:
    verification = json.loads((ROOT / 'verification.json').read_text())
    manifest = ROOT / 'raw-manifest.json'
    assert digest(manifest) == verification['raw_manifest_sha256']
    records = json.loads(manifest.read_text())
    for relative, expected in records.items():
        name = Path(relative)
        assert not name.is_absolute() and '..' not in name.parts
        path = ROOT / 'actual' / name
        assert path.is_file() and not path.is_symlink() and digest(path) == expected, path
    runtime = json.loads((ROOT / 'runtime.json').read_text())
    assert digest(ROOT / 'quux-oteleq') == runtime['cli_sha256']
    assert digest(ROOT / 'consumer-source.tar') == runtime['source_archive_sha256']
    return len(records)


delivery = json.loads((ROOT / 'DELIVERED.json').read_text())
assert delivery['merged_by'] == 'quuxio' and delivery['main_checks_passed']
assert delivery['canonical_clean'] and delivery['open_pull_requests'] == 0
before = verify_current()
print('Replacement evidence verified before cleanup:', before, flush=True)
HISTORY.mkdir(parents=True, exist_ok=True)
removed = []
for target in TARGETS:
    assert target.parent == ROOT.parent and target != ROOT and not target.is_symlink()
    assert target.is_dir(), target
    destination = HISTORY / target.name
    destination.mkdir(exist_ok=False)
    retained = {}
    allocated = logical = files = 0
    for directory, _, names in os.walk(target, followlinks=False):
        for name in names:
            info = (Path(directory) / name).lstat()
            logical += info.st_size
            allocated += info.st_blocks * 512
            files += 1
    for source in sorted(target.iterdir()):
        if source.is_file() and not source.is_symlink() and source.suffix in (
                '.json', '.log', '.md', '.py', '.tar', '.stdout', '.stderr'):
            copied = destination / source.name
            shutil.copy2(source, copied)
            retained[source.name] = digest(copied)
    if target.name == 'cpp-development':
        for child in sorted(target.iterdir()):
            if child.is_dir() and not child.is_symlink():
                for source in sorted(child.iterdir()):
                    if source.is_file() and not source.is_symlink() and source.suffix in (
                            '.json', '.log', '.md', '.py', '.stdout', '.stderr'):
                        copied = destination / child.name / source.name
                        copied.parent.mkdir(exist_ok=True)
                        shutil.copy2(source, copied)
                        retained[str(copied.relative_to(destination))] = digest(copied)
    (destination / 'HISTORICAL.md').write_text(
        '# Superseded C++ qualification history\n\n'
        'These summaries, source archives, logs and original manifests describe a historical run. '
        'Its raw workspaces, binaries and caches have been removed. Manifest entries are historical digests, '
        'not claims that those files are still present. The accepted replacement is '
        '`2026-10-20/cpp-receivers-8c2f7f6`. Git history and frozen otelc providers are preserved.\n')
    shutil.rmtree(target)
    removed.append({'path': str(target), 'files': files, 'logical_bytes': logical,
                    'allocated_bytes': allocated, 'retained_summary_sha256': retained})
    print('Removed superseded run:', target.name, flush=True)
after = verify_current()
assert before == after
receipt = {'completed_at': datetime.datetime.now(datetime.timezone.utc).isoformat(),
           'removed': removed, 'removed_allocated_bytes': sum(item['allocated_bytes'] for item in removed),
           'accepted_raw_records_verified_before': before, 'accepted_raw_records_verified_after': after,
           'accepted_runtime_commit': delivery['runtime_commit'], 'merged_main': delivery['merged_main'],
           'preserved': ['accepted C++ source/CLI/corpus', 'frozen otelc providers', 'other capability corpora',
                         'active source checkout', 'shared compiler caches', 'Git history']}
path = BASE / 'history-pruned/PURGE-20261020-cpp-receivers.json'
path.write_text(json.dumps(receipt, indent=2) + '\n')
print(json.dumps({'receipt': str(path), 'removed_allocated_bytes': receipt['removed_allocated_bytes'],
                  'preserved_records': after}), flush=True)
