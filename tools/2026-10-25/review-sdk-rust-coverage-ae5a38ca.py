"""Review the bounded coverage-runtime delta without building or launching SDKs."""

import ast
import hashlib
import json
from pathlib import Path
import subprocess

ROOT = Path('/Users/sclarke/github/otelc-qualification/work/rust-application-coverage-runtime')
RECORD = Path('/Users/sclarke/github/otelc-qualification/2026-10-25/rust-application-coverage-runtime/source.json')
OUTPUT = Path('/Users/sclarke/github/oteleq-qualification/2026-10-25/sdk-rust-coverage-ae5a38ca-review')


def digest(path: Path) -> str:
    with path.open('rb') as stream:
        return hashlib.file_digest(stream, 'sha256').hexdigest()


def verify(record: dict) -> None:
    names = subprocess.check_output(['git', 'ls-files', '-z'], cwd=ROOT).decode().rstrip('\0').split('\0')
    assert set(names) == set(record['source_facts']) == set(record['extra_facts'])
    for name in names:
        path = ROOT / name
        info = path.lstat()
        assert not path.is_symlink()
        assert [digest(path), info.st_dev, info.st_ino, info.st_mode, info.st_size,
                info.st_mtime_ns, info.st_ctime_ns] == record['source_facts'][name], name
        assert [info.st_uid, info.st_gid, info.st_nlink] == record['extra_facts'][name], name
    assert digest(Path(record['archive'])) == record['archive_sha256']


def main() -> None:
    record = json.loads(RECORD.read_bytes())
    verify(record)
    assert subprocess.check_output(['git', 'rev-parse', 'HEAD'], cwd=ROOT).decode().strip() == record['head']
    assert not subprocess.check_output(['git', 'status', '--porcelain'], cwd=ROOT).strip()
    changes = subprocess.check_output(['git', 'diff', '--name-only', record['base'], record['head']], cwd=ROOT).decode().splitlines()
    expected = ['ci/check_rust_compiler.py', 'ci/rust_compiler_cases.py', 'ci/rust_drop_cases.py',
                'native/rust/compiler/README.md']
    assert changes == expected
    for name in changes[:3]:
        ast.parse((ROOT / name).read_bytes(), filename=name)
    orchestration = (ROOT / changes[0]).read_text()
    assert "*cases.glob('*.profraw')" in orchestration and "*work.glob('unit-*.profraw')" in orchestration
    assert "'-object=' + str(key_units[0])" in orchestration
    assert "*('-object=' + str(path) for path in sorted(automatic_applications))" in orchestration
    compiler = (ROOT / changes[1]).read_text()
    drop = (ROOT / changes[2]).read_text()
    assert compiler.count("'-C', 'instrument-coverage'") == 2
    assert drop.count("'-C', 'instrument-coverage'") == 1
    assert compiler.count("LLVM_PROFILE_FILE=str(self.output / '%m-%p.profraw')") == 2
    verify(record)
    OUTPUT.mkdir()
    result = {'status': 'no finding in the four-file source delta', 'source': record['head'],
        'base': record['base'], 'source_files_held': len(record['source_facts']),
        'source_archive_sha256': record['archive_sha256'], 'changed_files': changes,
        'python_modules_parsed': 3, 'sdk_builds': 0, 'compiler_builds': 0, 'application_launches': 0,
        'scope': 'Source review of executable profiler instrumentation and unchanged required object/profile maps',
        'remaining': ['Fresh actual compiler/SDK/application run and measured bridge coverage >=80%',
                      'Full automatic MIR semantics review and public Rust lifetime admission']}
    path = OUTPUT / 'review.json'
    path.write_text(json.dumps(result, indent=2) + '\n')
    print(json.dumps({'review': str(path), 'sha256': digest(path), **result}))


if __name__ == '__main__':
    main()
