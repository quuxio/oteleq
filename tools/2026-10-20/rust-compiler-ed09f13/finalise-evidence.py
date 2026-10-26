"""Independently recheck retained captures and immutable input identities."""
import datetime
import hashlib
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent
REPO = Path('/Users/sclarke/github/oteleq-qualification/work/oteleq-rust-compiler')
sys.path.insert(0, str(REPO / 'tests'))
import qualify_rust_build as qualifier


def digest(path: Path) -> str:
    with path.open('rb') as stream:
        return hashlib.file_digest(stream, 'sha256').hexdigest()


def read(path: Path) -> dict:
    return json.loads(path.read_text())


def save(path: Path, document: dict | list) -> None:
    path.write_text(json.dumps(document, indent=2) + '\n')


runtime = read(ROOT / 'runtime.json')
assert digest(ROOT / 'quux-oteleq') == runtime['cli_sha256']
assert digest(ROOT / 'runtime-source.tar') == runtime['source_archive_sha256']
for name in ('generated', 'fixed', 'semantics', 'legacy'):
    state = read(ROOT / (name + '-state.json'))
    assert state['state'] == 'completed' and state['exit_code'] == 0
    assert state.get('source_unchanged', True)

provider = Path('/Users/sclarke/github/otelc-qualification/2026-10-20/rust-public-compiler/candidate-aca9d5a/provider')
manifest_path = provider.parent / 'manifest.json'
manifest = read(manifest_path)
assert digest(manifest_path) == runtime['provider_manifest_sha256']
assert manifest['commit'] == runtime['provider_commit']
paths = set()
counts = {}
for row in manifest['records']:
    relative = Path(row['path'])
    assert not relative.is_absolute() and '..' not in relative.parts and row['path'] not in paths
    paths.add(row['path'])
    path = provider / relative
    assert path.resolve() == path and path.is_file() and not path.is_symlink()
    assert path.stat().st_size == row['bytes'] and digest(path) == row['sha256']
    counts[row['kind']] = counts.get(row['kind'], 0) + 1
assert len(paths) == 950 and counts['source'] == 413 and counts['product'] == 536
compiler = Path(manifest['external_toolchain']['rustc'])
assert digest(compiler) == manifest['external_toolchain']['rustc_sha256']
save(ROOT / 'provider-verified-after.json', {
    'verified_at': datetime.datetime.now(datetime.timezone.utc).isoformat(),
    'commit': manifest['commit'], 'manifest_sha256': digest(manifest_path),
    'records': len(paths), 'kinds': counts, 'compiler_sha256': digest(compiler),
    'provider_cli_sha256': digest(provider / 'target/debug/quux-otelc'),
    'all_recorded_bytes_unchanged': True,
})

accepted = []
reports = [ROOT / 'generated/comparison/report.json', ROOT / 'generated/export-comparison/report.json']
for name in ('framework.stdout', 'export-framework.stdout'):
    entries = [json.loads(line) for line in (ROOT / 'generated' / name).read_text().splitlines()]
    assert len(entries) == 4
    reports.extend(Path(entry['report']) for entry in entries)
for path in reports:
    report = read(path)
    assert report['source_preserved'] and report['exit_code'] == 0
    for case in report['cases']:
        assert case['comparison']['verdict'] == 'equivalent_observed'
        qualifier.check_case(case, path.parent, 'compiler', None)
        accepted.append(path.parent / case['case'])
assert len(accepted) == 16
commands = [(path, read(path)) for case in accepted for path in case.glob('*/command.json')]
assert len(commands) == 96
for path in sorted((ROOT / 'semantics').rglob('command.json')):
    commands.append((path, read(path)))
assert len(commands) == 104
for folder in sorted((ROOT / 'fixed/rust').glob('*-*')):
    path = folder / 'commands.json'
    if path.exists():
        commands.append((path, read(path)['executed']))
assert len(commands) == 108
for path in sorted((ROOT / 'legacy').rglob('command.json')):
    commands.append((path, read(path)))
assert len(commands) == 132
assert len({json.dumps(command) for _, command in commands}) == 132
assert read(ROOT / 'fixed/rust/comparison.json')['verdict'] == 'equivalent_observed'
for part in ('semantics', 'aliases'):
    comparison = read(ROOT / 'semantics' / part / 'comparison.stdout')
    assert comparison['verdict'] == 'equivalent_observed'
for path in ROOT.rglob('runtime.json'):
    if path == ROOT / 'runtime.json' or 'legacy' in path.relative_to(ROOT).parts:
        continue
    runtime_report = read(path)
    if 'future_observers' in runtime_report:
        assert runtime_report['future_observers'] == {'pending': 0, 'admission_exhausted': False}
controls = read(ROOT / 'retained-controls/controls.json')
assert len(controls['actual_retained_bundle_controls']) == 14 and controls['actual_application_launches'] == 0
records = []
for part in ('generated', 'fixed', 'semantics', 'legacy'):
    for path in sorted((ROOT / part).rglob('*')):
        relative = path.relative_to(ROOT).as_posix()
        if path.is_symlink():
            records.append({'path': relative, 'link': str(path.readlink())})
        elif path.is_file():
            records.append({'path': relative, 'bytes': path.stat().st_size,
                            'mode': oct(path.stat().st_mode & 0o777), 'sha256': digest(path)})
save(ROOT / 'raw-manifest.json', records)
record = {
    'runtime_commit': runtime['runtime_commit'],
    'actual_application_launches': 132,
    'candidate_launches': 108, 'legacy_launches': 24,
    'generated_case_executions': 16, 'generated_application_launches': 96,
    'unique_command_identities': len(commands),
    'retained_record_controls': 14, 'control_application_launches': 0,
    'exact_value_oracles_rechecked': True, 'matching_generated_reports': len(reports),
    'raw_files_and_links': len(records), 'raw_manifest_sha256': digest(ROOT / 'raw-manifest.json'),
    'verification_script_sha256': digest(Path(__file__)), 'application_reruns': 0,
    'source_preserved': True,
    'limit': 'Fixed standard capture retains identities/channels, not detached build directories. Compiler sysroot and OS libraries are outside the content manifest.',
}
save(ROOT / 'verification.json', record)
print(json.dumps(record))
