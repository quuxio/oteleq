"""Probe Rust output boundaries with compiler/process sentinels, never real builds."""

import hashlib
import json
from pathlib import Path
import sys
import tempfile
from types import SimpleNamespace
from unittest.mock import patch

SOURCE = Path('/Users/sclarke/github/otelc-qualification/work/rust-public-build')
OUT = Path('/Users/sclarke/github/oteleq-qualification/2026-10-25/sdk-rust-public-f32e5f5-review')
OUT.mkdir(exist_ok=False)
INDEX = Path('/Users/sclarke/github/otelc-qualification/2026-10-25/rust-public-build/source-f32e5f5.json')
index = json.loads(INDEX.read_bytes())
sys.path.insert(0, str(SOURCE))
from otelc import rust_build, rust_compiler, rust_launch
from otelc.config import Policy


def fact(path):
    value = path.lstat()
    with path.open('rb') as stream:
        digest = hashlib.file_digest(stream, 'sha256').hexdigest()
    return [digest, value.st_dev, value.st_ino, value.st_mode, value.st_size,
            value.st_mtime_ns, value.st_ctime_ns]


def verify():
    for name, expected in index['original_facts'].items():
        assert fact(SOURCE / name) == expected, name
    for name, expected in index['product_facts'].items():
        assert fact(Path(name)) == expected, name


verify()
results = []
policy = Policy.parse({'schema_version': 3, 'languages': ['rust']})
with tempfile.TemporaryDirectory(dir=OUT) as temporary:
    root = Path(temporary).resolve()
    application = root / 'Application'
    application.mkdir()
    entry = application / 'app.rs'
    entry.write_text('fn main(){}\n')
    alias = root / 'application'
    assert alias.exists() and alias.samefile(application), 'case-alias probe needs a case-insensitive volume'
    tools = {'tools': [{'path': '/unused/rustc'}],
             'products': [{'path': '/unused/driver'}, {'path': '/unused/bridge.rlib'}],
             'sysroot': '/unused/sysroot'}
    output = alias / 'compiled'
    with patch.object(rust_compiler, 'read', return_value=SimpleNamespace(manifest=lambda: tools)), \
            patch.object(rust_build.native_build, 'sdk', return_value={}), \
            patch.object(rust_compiler, 'execute', side_effect=RuntimeError('compiler sentinel')) as compiler:
        try:
            rust_build.build(policy, application, entry, output, tools_directory=root, sdk_directory=root)
        except (ValueError, RuntimeError) as error:
            results.append({'case': 'application-build', 'error': str(error),
                            'compiler_sentinel_reached': compiler.called,
                            'original_source_directory_written': (application / 'compiled').is_dir()})
    built = rust_build.Build(root / 'build', '{}')
    runtime = alias / 'runtime'
    with patch.object(rust_build, 'verify', return_value={'root': str(application)}), \
            patch.object(rust_launch.subprocess, 'Popen', side_effect=RuntimeError('process sentinel')) as process:
        try:
            rust_launch.start(built, policy, runtime, plain=True)
        except (ValueError, RuntimeError) as error:
            results.append({'case': 'application-runtime', 'error': str(error),
                            'process_sentinel_reached': process.called,
                            'original_source_directory_written': (application / 'runtime').is_dir()})
    compiler_source = root / 'native/rust'
    compiler_source.mkdir(parents=True)
    compiler_alias = root / 'native/RUST'
    assert compiler_alias.samefile(compiler_source)
    with patch.object(rust_compiler, 'ROOT', root), \
            patch.object(rust_compiler.shutil, 'which', return_value=None):
        try:
            rust_compiler.build(compiler_alias / 'output')
        except ValueError as error:
            results.append({'case': 'compiler-tools', 'error': str(error),
                            'original_source_directory_written': (compiler_source / 'output').is_dir()})
verify()
result = {'head': index['head'], 'scope': 'Only temporary files and mocked compiler/process sentinels. '
          'No SDK/compiler build or workload process started.', 'cases': results,
          'preservation': {'source': len(index['original_facts']), 'products': len(index['product_facts']),
                           'all_original_full_facts_held': True}}
(OUT / 'boundary-controls.json').write_text(json.dumps(result, indent=2) + '\n')
print(json.dumps(result))
