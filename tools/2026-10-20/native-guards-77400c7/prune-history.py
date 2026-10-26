"""Purge superseded owned native evidence only after verified delivery."""
import datetime
import hashlib
import json
from pathlib import Path
import shutil

LATEST = Path(__file__).resolve().parent
DATE = LATEST.parent
ARCHIVE = DATE.parent
HISTORY = ARCHIVE / 'history-pruned/native-guards'


def read(path):
    return json.loads(path.read_text())


def digest(path):
    with path.open('rb') as stream:
        return hashlib.file_digest(stream, 'sha256').hexdigest()


def measured(folder):
    files = [path for path in folder.rglob('*') if path.is_file() and not path.is_symlink()]
    return {'files': len(files), 'logical_bytes': sum(path.stat().st_size for path in files),
            'allocated_file_bytes': sum(path.stat().st_blocks * 512 for path in files)}


delivery = read(LATEST / 'DELIVERED.json')
assert delivery['merged_main'] == 'a1113491223da1ca54cbb301111dee2e398987c4'
assert delivery['main_checks_passed'] and delivery['merged_by'] == 'quuxio'
checks = {}
for folder, manifest in (('actual', 'raw-manifest.json'), ('native-actual', 'native-raw-manifest.json')):
    for relative, expected in read(LATEST / manifest).items():
        assert not Path(relative).is_absolute() and '..' not in Path(relative).parts
        checks[LATEST / folder / relative] = expected
runtime = read(LATEST / 'runtime.json')
checks[LATEST / 'quux-oteleq'] = runtime['cli_sha256']
checks[LATEST / 'consumer-source.tar'] = runtime['source_archive_sha256']
for path, expected in checks.items():
    assert digest(path) == expected, path
assert len(checks) == 7455
old = DATE / 'cpp-receivers-8c2f7f6'
assert read(old / 'runtime.json')['source_commit'] == '8c2f7f689122b82a74464785966d98c0d160b31b'
raw = old / 'actual'
assert raw.resolve() == raw and not raw.is_symlink()
manifest = read(old / 'raw-manifest.json')
assert len(manifest) == 6008
assert {path.relative_to(raw).as_posix() for path in raw.rglob('*') if path.is_file()} == set(manifest)
for relative, expected in manifest.items():
    assert digest(raw / relative) == expected
HISTORY.mkdir(parents=True, exist_ok=False)
removed = []
for name, commit in (('native-guards-ceee213', 'ceee213571b4017e6c488c9a004c3ad0b92b7f04'),
                     ('native-guards-237cebb', '237cebb7fdac984ff4f622c60ea998590b1f3835')):
    folder = DATE / name
    assert folder.resolve() == folder and not folder.is_symlink()
    assert read(folder / 'runtime.json')['source_commit'] == commit
    if name.endswith('237cebb'):
        assert read(folder / 'STOPPED.json')['status'] == 'intentionally stopped; incomplete evidence'
    saved = HISTORY / name
    saved.mkdir()
    for path in folder.iterdir():
        if path.is_file() and not path.is_symlink():
            shutil.copyfile(path, saved / path.name)
    manifest = {path.relative_to(folder).as_posix(): digest(path)
                for path in sorted(folder.rglob('*')) if path.is_file()}
    (saved / 'original-file-manifest.json').write_text(json.dumps(manifest, indent=2, sort_keys=True) + '\n')
    record = {'path': str(folder), 'reason': 'superseded development candidate', **measured(folder)}
    shutil.rmtree(folder)
    removed.append(record)
record = {'path': str(raw), 'reason': 'superseded C++ corpus; compact source, CLI and receipts retained', **measured(raw)}
shutil.rmtree(raw)
removed.append(record)
for path, expected in checks.items():
    assert digest(path) == expected, path
receipt = {'purged_at': datetime.datetime.now(datetime.timezone.utc).isoformat(), 'removed': removed,
           'allocated_file_bytes_removed': sum(item['allocated_file_bytes'] for item in removed),
           'latest_evidence_records_verified_before_and_after': len(checks),
           'latest_runtime': runtime['source_commit'], 'merged_main': delivery['merged_main'],
           'preserved': ['latest native/C++ corpus', 'other capability evidence', 'frozen providers',
                         'active build-context source', 'shared build caches', 'Git history'],
           'retention_note': 'Original manifests describe historical files; superseded raw data is no longer retained.'}
(old / 'RAW_PRUNED.json').write_text(json.dumps(receipt, indent=2) + '\n')
path = ARCHIVE / 'history-pruned/PURGE-20261020-native-guards.json'
path.write_text(json.dumps(receipt, indent=2) + '\n')
print(json.dumps(receipt), flush=True)
