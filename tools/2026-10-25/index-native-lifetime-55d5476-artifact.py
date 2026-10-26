"""Retain selected original captures without extracting SDK binaries or rebinding host identities."""

import hashlib
import json
from pathlib import Path, PurePosixPath
import zipfile

BASE = Path('/Users/sclarke/github/oteleq-qualification/2026-10-25/native-lifetime-build')
ARCHIVE = BASE / 'hosted-55d5476-artifact.zip'
OUT = BASE / 'hosted-55d5476-retained'
EXPECTED = '2425049568007aab4993c00a98fbd70bdcc1a30ac92d07dd759c3c19f2f9193e'
with ARCHIVE.open('rb') as stream:
    assert hashlib.file_digest(stream, 'sha256').hexdigest() == EXPECTED
OUT.mkdir(mode=0o700)
allowed = {'consumer-source.tar', 'provider-source.tar', 'consumer-source-status.txt', 'provider-source-status.txt',
    'expected-lifetimes-before-build.json', 'expected-lifetimes.json', 'health.json', 'http-capture.json',
    'http-responses.json', 'native-application-start.json', 'native-request.json', 'native-verified-lifetimes.json',
    'original-source-facts.json', 'policy.toml', 'qualification.json', 'report.json', 'sdk-original-products.json',
    'shrink.json', 'typed-bundle.json'}
index, hashes, selected_bytes = {}, {}, 0
with zipfile.ZipFile(ARCHIVE) as archive:
    values = archive.infolist()
    assert len({value.filename for value in values}) == len(values)
    for value in values:
        path = PurePosixPath(value.filename)
        assert not path.is_absolute() and '..' not in path.parts and not value.flag_bits & 1
        index[value.filename] = {'bytes': value.file_size, 'compressed_bytes': value.compress_size}
        if value.is_dir() or path.parts[0] != 'native-lifetime-evidence':
            continue
        if path.name not in allowed and not (path.name.startswith('otlp-') and path.suffix == '.protobuf'):
            continue
        assert value.file_size <= 64 * 1024**2
        selected_bytes += value.file_size
        assert selected_bytes <= 256 * 1024**2
        target = OUT.joinpath(*path.parts)
        target.parent.mkdir(mode=0o700, parents=True, exist_ok=True)
        digest = hashlib.sha256()
        count = 0
        with archive.open(value) as source, target.open('xb') as destination:
            target.chmod(0o600)
            while block := source.read(1024 * 1024):
                count += len(block)
                assert count <= value.file_size
                digest.update(block)
                destination.write(block)
        assert count == value.file_size
        hashes[value.filename] = digest.hexdigest()
result = {'run': 40211685995, 'head': '55d5476d93c6a3e642379d0a45372c0de238a4bb',
    'artifact_id': 12610704082, 'archive_sha256': EXPECTED, 'archive_bytes': ARCHIVE.stat().st_size,
    'members': len(index), 'uncompressed_bytes': sum(value['bytes'] for value in index.values()),
    'selected_members': len(hashes), 'selected_bytes': selected_bytes, 'selected_sha256': hashes,
    'scope': 'Original JSON/protobuf/policy/source-tar bytes. Runner OS/file identities remain historical data; no SDK binaries extracted or applications started.'}
(BASE / 'hosted-55d5476-retained-index.json').write_text(json.dumps(result, indent=2) + '\n')
(BASE / 'hosted-55d5476-member-index.json').write_text(json.dumps(index, indent=2) + '\n')
print(json.dumps({key: value for key, value in result.items() if key != 'selected_sha256'}, indent=2))
