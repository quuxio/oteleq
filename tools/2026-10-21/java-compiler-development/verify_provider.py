"""Verify the frozen legacy provider's declared source, product and dependency bytes."""
import hashlib
import json
import os
from pathlib import Path
import sys

manifest = Path('/Users/sclarke/github/otelc-qualification/2026-10-20/integrated-provider/d6d03b7/manifest.json')
data = json.loads(manifest.read_text())
root = Path(data['source_root'])
def digest(path):
    result = hashlib.sha256()
    with path.open('rb') as stream:
        for block in iter(lambda: stream.read(1024 * 1024), b''):
            result.update(block)
    return result.hexdigest()
counts = {}
for key in ('source_sha256', 'products_sha256', 'dependencies'):
    for name, expected in data[key].items():
        path = root / name
        if isinstance(expected, str):
            assert digest(path) == expected, path
        elif 'symlink' in expected:
            assert path.is_symlink() and os.readlink(path) == expected['symlink'], path
            assert str(path.resolve(strict=True)) == expected['resolved'], path
        else:
            assert digest(path) == expected['sha256'], path
    counts[key] = len(data[key])
for expected in data['tools'].values():
    assert digest(Path(expected['path'])) == expected['sha256'], expected['path']
result = {'provider_commit': data['source_commit'], 'manifest_sha256': digest(manifest),
          'verified_records': sum(counts.values()), 'counts': counts, 'tools': len(data['tools'])}
Path(sys.argv[1]).write_text(json.dumps(result, indent=2) + '\n')
print(json.dumps(result))
