"""Verify the distinct integrated provider without executing its metadata."""
import datetime
import hashlib
import json
from pathlib import Path

OUT = Path(__file__).resolve().parent
ROOT = Path('/Users/sclarke/github/otelc-qualification/2026-10-20/integrated-provider/d6d03b7/provider')
MANIFEST = ROOT.parent / 'manifest.json'
EXPECTED = '2a8dbf239c6444c0fb536dff049993beade7eaed6578c9654c1e2d7233e9431f'


def digest(path: Path) -> str:
    with path.open('rb') as stream:
        return hashlib.file_digest(stream, 'sha256').hexdigest()


assert digest(MANIFEST) == EXPECTED
manifest = json.loads(MANIFEST.read_text())
assert manifest['source_commit'] == 'd6d03b72026cde8962b11ce3cc184ff3ebcb60d4'
assert manifest['source_root'] == str(ROOT)
counts = {}
paths = set()
links = 0
for kind in ('source_sha256', 'products_sha256', 'dependencies'):
    records = manifest[kind]
    for relative, record in records.items():
        path = ROOT / relative
        assert not Path(relative).is_absolute() and '..' not in Path(relative).parts
        assert relative not in paths
        paths.add(relative)
        if isinstance(record, dict) and 'symlink' in record:
            assert set(record) == {'symlink', 'resolved'}
            assert path.is_symlink() and str(path.readlink()) == record['symlink']
            assert str(path.resolve(strict=True)) == record['resolved']
            links += 1
        else:
            expected = record['sha256'] if isinstance(record, dict) else record
            assert path.resolve() == path and path.is_file() and not path.is_symlink()
            assert digest(path) == expected
    counts[kind] = len(records)
assert counts == {'source_sha256':413,'products_sha256':586,'dependencies':6361}
for record in manifest['tools'].values():
    path = Path(record['path'])
    assert path.is_absolute() and str(path.resolve(strict=True)) == record['resolved']
    assert digest(path) == record['sha256']
profile = ROOT / 'target/debug/otelc-rust-compiler.json'
assert digest(profile) == manifest['profile_relocation']['retained_sha256']
result = {'verified_at':datetime.datetime.now(datetime.timezone.utc).isoformat(),
          'provider_commit':manifest['source_commit'],'provider_tree':manifest['source_tree'],
          'manifest_sha256':EXPECTED,'verified_records':len(paths),'counts':counts,
          'symlinks':links,'external_tools_verified':len(manifest['tools']),
          'cli_sha256':manifest['products_sha256']['target/debug/quux-otelc'],
          'profile_relocation':manifest['profile_relocation'],
          'scope':'Content verification only; actual behavioural qualification pending.',
          'verification_script_sha256':digest(Path(__file__))}
(OUT / 'provider-verified.json').write_text(json.dumps(result,indent=2)+'\n')
print(json.dumps(result))
