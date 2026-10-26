"""Verify the immutable main67 handoff and copy only the standalone LLVM inputs."""
import hashlib
import json
from pathlib import Path, PurePosixPath
import shutil
import subprocess
import tarfile

handoff = Path('/private/tmp/otelc-rust-frontend-provider-9e6eb9e-frozen.json')
raw = handoff.read_bytes()
assert hashlib.sha256(raw).hexdigest() == "217cc3dc07b0862796e091235c4f137e078a87bd2711997d91c105fd00b70255"
manifest = json.loads(raw)
original = Path('/private/tmp/otelc-rust-frontend-9e6eb9e-frozen')
assert manifest['source_root'] == str(original)
assert manifest['head'] == '9e6eb9e3e7d367794c90fffc0053ceda88e673df'
root = Path('/private/tmp/oteleq-llvm-provider-frontend-9e6eb9e')
root.mkdir(mode=0o700, exist_ok=False)


def digest(path):
    result = hashlib.sha256()
    with path.open('rb') as stream:
        for chunk in iter(lambda: stream.read(1024 * 1024), b''):
            result.update(chunk)
    return result.hexdigest()


def regular(path):
    assert path.is_file() and not path.is_symlink() and path.resolve() == path, path


for name, expected in manifest['sources'].items():
    relative = PurePosixPath(name)
    assert not relative.is_absolute() and '..' not in relative.parts
    source, target = original / name, root / name
    regular(source)
    assert digest(source) == expected, name
    target.parent.mkdir(parents=True, exist_ok=True)
    shutil.copy2(source, target)
    assert digest(source) == expected and digest(target) == expected, name
with tarfile.open(root / 'source.tar', 'w') as archive:
    for name in manifest['sources']:
        archive.add(root / name, arcname=name, recursive=False)
products = {'cli': 'target/debug/quux-otelc', 'adapter': 'target/debug/otelc-rust-adapter',
            'profile': 'target/debug/otelc-rust-llvm.json',
            'sdk': 'target/rust-llvm-sdk/debug/libquux_otelc_rust.rlib',
            'plugin': 'target/debug/otelc_rust_pass.dylib', 'frontend': 'target/debug/otelc-rust-frontend'}
assert set(manifest['files']) == set(products)
for label, relative in products.items():
    source, target = original / relative, root / relative
    assert manifest['files'][label]['path'] == str(source)
    regular(source)
    expected = manifest['files'][label]['sha256']
    assert digest(source) == expected
    target.parent.mkdir(parents=True, exist_ok=True)
    subprocess.run(['/bin/cp', '-cp', str(source), str(target)], check=True)
    assert digest(target) == expected and digest(source) == expected
dependencies = original / 'target/rust-llvm-sdk/debug/deps'
assert dependencies.is_dir() and dependencies.resolve() == dependencies
inputs = {path.relative_to(original).as_posix(): digest(path) for path in sorted(dependencies.iterdir())
          if path.suffix in ('.rlib', '.rmeta', '.dylib', '.so', '.dll')}
assert inputs
for relative in inputs:
    regular(original / relative)
target_deps = root / dependencies.relative_to(original)
target_deps.mkdir()
subprocess.run(['/bin/cp', '-cp', *[str(original / name) for name in inputs], str(target_deps)], check=True)
for name, expected in inputs.items():
    assert digest(original / name) == expected and digest(root / name) == expected, name
profile_path = root / products['profile']
source_profile = profile_path.read_bytes()
(root / 'target/debug/otelc-rust-llvm.source.json').write_bytes(source_profile)
profile = json.loads(source_profile)
for field in ('sdk', 'plugin', 'frontend'):
    assert profile[field] == str(original / products[field])
    profile[field] = str(root / products[field])
profile_path.write_text(json.dumps(profile, indent=2) + '\n')
assert profile['protected_source_roots'] == manifest['profile']['protected_source_roots']
assert handoff.read_bytes() == raw
for name, expected in manifest['sources'].items():
    assert digest(original / name) == expected, name
record = {'provider_revision': manifest['head'], 'tree': manifest['tree'],
          'original_handoff_sha256': hashlib.sha256(raw).hexdigest(), 'original_handoff': manifest,
          'source_manifest': manifest['sources'], 'dependencies': inputs,
          'product_manifest': manifest['files'], 'private_profile_sha256': digest(profile_path),
          'changed_fields': ['sdk', 'plugin', 'frontend'], 'qualification': 'verified copy only; execution qualification pending'}
(root / 'OTELEQ-LLVM-SNAPSHOT.json').write_text(json.dumps(record, indent=2) + '\n')
(root / 'OTELEQ-LLVM-HANDOFF.json').write_bytes(raw)
print(json.dumps({'snapshot': str(root), 'source_files': len(manifest['sources']), 'product_files': len(products),
                  'dependency_files': len(inputs), 'private_profile_sha256': digest(profile_path),
                  'original_handoff_sha256': hashlib.sha256(raw).hexdigest()}), flush=True)
