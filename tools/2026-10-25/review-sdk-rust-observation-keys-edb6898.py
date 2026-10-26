"""Bounded source/analysis review; genuine compiler and SDK gates stay separate."""
import ast
import hashlib
import json
import os
from pathlib import Path
import subprocess
import time

BASE = Path('/Users/sclarke/github/oteleq-qualification')
manifest = json.loads(Path('/Users/sclarke/github/otelc-qualification/2026-10-25/rust-drop-observation-keys/source.json').read_text())
ROOT = Path(manifest['root'])
OUT = BASE / '2026-10-25/sdk-rust-observation-keys-edb6898-review'
OUT.mkdir()


def digest(path):
    with Path(path).open('rb') as stream:
        return hashlib.file_digest(stream, 'sha256').hexdigest()


def held():
    assert subprocess.check_output(['git', 'rev-parse', 'HEAD'], cwd=ROOT, text=True).strip() == manifest['head']
    assert not subprocess.check_output(['git', 'status', '--porcelain'], cwd=ROOT, text=True).strip()
    for name, wanted in manifest['source_facts'].items():
        path = ROOT / name; info = path.lstat()
        assert [digest(path), info.st_dev, info.st_ino, info.st_mode, info.st_size, info.st_mtime_ns, info.st_ctime_ns] == wanted, name
        assert [info.st_uid, info.st_gid, info.st_nlink] == manifest['extra_facts'][name], name
    assert digest(manifest['archive']) == manifest['archive_sha256']


def run(label, argv, env):
    tick = time.monotonic()
    with (OUT / (label + '.log')).open('wb') as stream:
        result = subprocess.run(argv, cwd=ROOT, env=env, stdout=stream, stderr=subprocess.STDOUT, timeout=60)
    checks.append({'label': label, 'argv': argv, 'returncode': result.returncode, 'seconds': time.monotonic() - tick})
    assert result.returncode == 0, label


held()
changes = subprocess.check_output(['git', 'diff', '--name-only', manifest['base'], manifest['head']], cwd=ROOT, text=True).splitlines()
assert len(changes) == 9 and 'native/rust/bridge/src/keys_tests.rs' in changes
for name in ('otelc/rust_launch.py', 'otelc/native_benchmark.py', 'otelc/rust_lifetimes.py'):
    assert subprocess.check_output(['git', 'show', manifest['base'] + ':' + name], cwd=ROOT) == (ROOT / name).read_bytes()
assert not subprocess.check_output(['git', 'diff', manifest['base'], manifest['head'], '--', 'native/rust/compiler', 'adapters/native', '.github/workflows'], cwd=ROOT)
for name in changes:
    if name.endswith('.py'): ast.parse((ROOT / name).read_text())
source = (ROOT / 'native/rust/bridge/src/lib.rs').read_text()
assert 'fetch_update(Ordering::Relaxed, Ordering::Relaxed' in source and 'value.checked_add(1)' in source
assert 'key as *const u8' in source and '.map(|previous| previous + 1)' in source
assert 'must not be mixed for the same type' in (ROOT / 'docs/rust-drop-bridge.md').read_text()
assert (ROOT / 'native/rust/bridge/src/keys_tests.rs').read_text().count('#[test]') == 3
checks = []
environment = dict(os.environ, PYTHONDONTWRITEBYTECODE='1', PYTHONPATH=str(ROOT) + ':' + str(ROOT / 'tests'))
for version in ('312', '314'):
    python = str(BASE / f'2026-10-24/python-live-metrics/env-{version}/bin/python')
    data = str(OUT / (version + '.coverage'))
    run(version, [python, '-m', 'coverage', 'run', '--data-file=' + data,
        '--source=otelc.rust_lifetimes,ci.rust_sonar', '-m', 'unittest', 'test_rust_lifetimes', 'test_rust_sonar', '-v'], environment)
    text = (OUT / (version + '.log')).read_text()
    assert 'Ran 17 tests' in text and '... skipped ' not in text
    for name in ('otelc/rust_lifetimes.py', 'ci/rust_sonar.py'):
        run(version + '-' + Path(name).stem, [python, '-m', 'coverage', 'report', '--data-file=' + data,
            '--include=*/' + name, '--show-missing', '--fail-under=80'], environment)
run('rustfmt', ['/Users/sclarke/.rustup/toolchains/1.98.1-aarch64-apple-darwin/bin/rustfmt', '--edition', '2024', '--check', 'native/rust/bridge/src/lib.rs'], environment)
run('markdown', ['/opt/homebrew/Cellar/node@24/24.21.0_2/bin/node', str(BASE / 'work/oteleq-native-generated/ci/markdownlint/node_modules/markdownlint-cli/markdownlint.js'), 'README.md', 'docs/rust-drop-bridge.md', 'native/rust/bridge/README.md'], environment)
run('diff', ['git', 'diff', manifest['base'], manifest['head'], '--check'], environment)
held()
result = {'head': manifest['head'], 'base': manifest['base'], 'status': 'clear for bounded private observation-key component review',
    'findings': [], 'source_files_preserved': len(manifest['source_facts']), 'uid_gid_nlink_preserved': True,
    'archive_sha256': manifest['archive_sha256'], 'checks': checks, 'methods_per_python': 17,
    'sdk_builds': 0, 'compiler_builds': 0, 'application_launches': 0,
    'reviewed_contract': 'Checked monotonic nonzero allocator, permanent exhaustion, explicit single-convention-per-type restriction, unchanged public guards/compiler/native runtime, complete executable/profile maps and separate original/drop/key launch denominators',
    'limits': ['The three compiled key tests and all genuine SDK/Rust harnesses were not run locally; fresh hosted checks remain required',
               'No automatic MIR insertion, general lifetime correctness or public oteleq lifetime admission']}
(OUT / 'review.json').write_text(json.dumps(result, indent=2) + '\n')
print(digest(OUT / 'review.json'))
