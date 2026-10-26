"""Recheck the immutable legacy provider without modifying or executing it."""
import hashlib
import json
from pathlib import Path

ROOT = Path(__file__).resolve().parent
MANIFEST = Path('/Users/sclarke/github/otelc-qualification/2026-10-20/integrated-provider/d6d03b7/manifest.json')


def digest(path: Path) -> str:
    with path.open('rb') as stream:
        return hashlib.file_digest(stream, 'sha256').hexdigest()


def main() -> None:
    assert digest(MANIFEST) == '2a8dbf239c6444c0fb536dff049993beade7eaed6578c9654c1e2d7233e9431f'
    record = json.loads(MANIFEST.read_text())
    provider = Path(record['source_root'])
    count, links = 0, 0
    for section in ('source_sha256', 'products_sha256'):
        for name, expected in record[section].items():
            path = provider / name
            assert not path.is_symlink() and digest(path) == expected, str(path)
            count += 1
    for name, expected in record['dependencies'].items():
        path = provider / name
        if 'symlink' in expected:
            assert path.is_symlink() and str(path.readlink()) == expected['symlink']
            assert str(path.resolve(strict=True)) == expected['resolved']
            links += 1
        else:
            assert not path.is_symlink() and digest(path) == expected['sha256'], str(path)
        count += 1
    for tool in record['tools'].values():
        assert str(Path(tool['path']).resolve(strict=True)) == tool['resolved']
        assert digest(Path(tool['resolved'])) == tool['sha256']
    assert count == 7360 and links == 11 and len(record['tools']) == 8
    result = {'status': 'verified', 'source_commit': record['source_commit'], 'records': count,
              'symlinks': links, 'tools': len(record['tools']), 'manifest_sha256': digest(MANIFEST)}
    (ROOT / 'provider-verification.json').write_text(json.dumps(result, indent=2) + '\n')
    print(json.dumps(result))


if __name__ == '__main__':
    main()
