"""Seal fresh retained-only startup audits without changing original results."""

import datetime
import hashlib
import json
import os
from pathlib import Path
import stat
import sys

ROOT = Path(__file__).resolve().parent
VERIFIER = 'd0282c49d2c085dd7c265bad5aeeec0be8629839'
RUNTIME = 'bb1fb9696abea1b57b9b1e2ad605c5614f92c387'
FINAL = '6571c7c2b028a4acb9e153550da6dbe91cef3639'
sys.path.insert(0, str(ROOT / 'source-d0282c4/tests'))
import qualify_java_startup as startup


def read(path):
    return json.loads(path.read_bytes())


def digest(path):
    descriptor = os.open(path, os.O_RDONLY | os.O_NOFOLLOW | os.O_NONBLOCK)
    try:
        before = os.fstat(descriptor)
        assert stat.S_ISREG(before.st_mode)
        value = hashlib.sha256()
        while block := os.read(descriptor, 1024 * 1024):
            value.update(block)
        after = os.fstat(descriptor)
        stable = lambda item: (item.st_dev, item.st_ino, item.st_size, item.st_mtime_ns,
            item.st_ctime_ns, item.st_mode, item.st_uid)
        assert stable(before) == stable(after), 'Evidence changed while reading'
        return value.hexdigest()
    finally:
        os.close(descriptor)


def walk_error(error):
    raise error


def files(folder):
    for directory, children, names in os.walk(folder, followlinks=False, onerror=walk_error):
        parent = Path(directory)
        assert not parent.is_symlink()
        assert all(not (parent / name).is_symlink() for name in children)
        for name in sorted(names):
            path = parent / name
            assert not path.is_symlink()
            yield path


def write(path, value):
    with path.open('x') as output:
        output.write(json.dumps(value, indent=2) + '\n')


output = ROOT / 'final-audit-d0282c4.json'
assert not output.exists()
matrix = read(ROOT / 'matrix-bb1fb96.json')
assert matrix['state'] == 'failed_cohort' and matrix['executor_commit'] == RUNTIME
assert len(matrix['runs']) == 12
assert sum(row['exit'] == 0 for row in matrix['runs']) == 8
assert sum(row['exit'] == 1 and row['profile'] == 'archive-methods-v1' for row in matrix['runs']) == 4
recovery = read(ROOT / 'recheck-d0282c4.json')
assert recovery['state'] == 'completed' and recovery['verifier_commit'] == VERIFIER
assert recovery['executor_commit'] == RUNTIME and recovery['new_application_launches'] == 0
assert recovery['original_results_preserved'] is True
assert all(digest(Path(name)) == value for name, value in recovery['original_files_sha256'].items())
identities = {(row['profile'], row['startup']) for row in recovery['runs']}
assert len(recovery['runs']) == len(identities) == 12
assert identities == {(profile + '-methods-v1', start) for profile in ('stock', 'safe', 'archive')
    for start in ('both-on', 'collection-off', 'emission-off', 'both-off')}
sources = {}
for suffix, commit, count in (('bb1fb96', RUNTIME, 397), ('6571c7c', FINAL, 398),
                              ('d0282c4', VERIFIER, 400)):
    index = read(ROOT / ('source-' + suffix + '.json'))
    assert index['commit'] == commit and len(index['files']) == count
    assert all(digest(ROOT / ('source-' + suffix) / name) == value for name, value in index['files'].items())
    sources[commit] = {'preserved_files': count, 'index_sha256': digest(ROOT / ('source-' + suffix + '.json'))}
assert digest(ROOT / 'quux-oteleq-bb1fb96') == '59a27ba2a5b95140fd9fddf83f4fec98745fdd56d5372fa1f147c3aaada7aea7'
assert digest(ROOT / 'quux-oteleq-6571c7c') == '8f619fc5793a66d36f7da89e35ff9688c95a48318936c98a8d7d977a7675ff2d'
providers = read(ROOT / 'providers-before-bb1fb96.json')
provider_counts = {}
for row in providers['providers']:
    provider = Path(row['provider'])
    assert not row['symlinks']
    actual = {str(path.relative_to(provider)): digest(path) for path in files(provider)}
    assert actual == row['files']
    provider_counts[row['profile']] = len(actual)
assert provider_counts == {'stock-methods-v1': 64, 'safe-methods-v1': 150, 'archive-methods-v1': 112}
for name, value in providers['external_tools'].items():
    path = Path(name).resolve(strict=True)
    assert str(path) == value['resolved'] and digest(path) == value['sha256']
write(ROOT / 'providers-after-bb1fb96.json', {'checked_at': datetime.datetime.now(datetime.UTC).isoformat(),
    'provider_files_preserved': provider_counts, 'external_tools_preserved': 3,
    'source_files_preserved': 397, 'before_sha256': digest(ROOT / 'providers-before-bb1fb96.json'),
    'scope': 'Post-terminal byte and exact file-set check. Original failed controller results remain failed.'})
profiles, bundles, raw_files = [], {}, {}
for row in sorted(recovery['runs'], key=lambda item: (item['profile'], item['startup'])):
    assert row['state'] == 'completed' and row['exit'] == 0
    folder, audit = Path(row['folder']), Path(row['audit_directory'])
    assert audit.parent == folder and audit.name.startswith('offline-recheck-')
    result = read(audit / 'QUALIFICATION.json')
    assert digest(audit / 'QUALIFICATION.json') == row['qualification_sha256']
    assert result['mode'] == 'retained_recheck' and result['new_application_launches'] == 0
    assert result['java_profile'] == row['profile'] and result['source_preserved'] is True
    assert (result['actual_jvm_launches'], result['raw_attempt_folders'], result['copied_attempts_excluded'],
            result['typed_comparisons_recomputed'], result['qualified_reports']) == (188, 192, 4, 48, 38)
    assert result['evidence_controls']['evidence_refusals'] == 14
    assert result['evidence_controls']['actual_applications'] == 0
    assert result['cli_sha256'] == digest(ROOT / 'quux-oteleq-bb1fb96')
    workspace = startup.retained_workspace(folder, Path(row['provider']), row['profile'], ROOT / 'quux-oteleq-bb1fb96')
    assert len(startup.route_operations(folder / 'corpus', workspace, ROOT / 'quux-oteleq-bb1fb96')) == 19
    paths = sorted((folder / 'corpus').rglob('typed-bundle.json'))
    assert len(paths) == 48
    for path in paths:
        key = path.relative_to(ROOT).as_posix()
        assert key not in bundles
        comparison_key = hashlib.sha256(str(path.resolve()).encode()).hexdigest()[:24]
        comparison = audit / 'comparisons' / comparison_key
        expected = read(path.parent / 'comparison.json')
        assert read(comparison / 'startup-recomparison.stdout') == expected
        assert (comparison / 'startup-recomparison.exit').read_text().strip() == str(
            int(expected['verdict'] == 'different_observed'))
        bundles[key] = {'bundle_sha256': digest(path),
            'comparison_sha256': digest(path.parent / 'comparison.json'),
            'recomputed_sha256': digest(comparison / 'startup-recomparison.stdout')}
    profiles.append({'profile': row['profile'], 'provider_commit': row['provider_commit'],
        'startup': row['startup'], 'actual_jvms': 188, 'raw_attempts': 192, 'copied_attempts_excluded': 4,
        'reports': 38, 'typed_comparisons_recomputed': 48, 'refusals_rechecked': 14,
        'required_route_commands': 19, 'audit_directory': str(audit.relative_to(ROOT)),
        'qualification_sha256': digest(audit / 'QUALIFICATION.json')})
    for path in files(folder):
        key = path.relative_to(ROOT).as_posix()
        assert key not in raw_files
        raw_files[key] = {'sha256': digest(path), 'size': path.stat().st_size,
            'mode': stat.S_IMODE(path.stat().st_mode)}
assert len(bundles) == 576
manifest = ROOT / 'raw-manifest-d0282c4.json'
write(manifest, {'executor_commit': RUNTIME, 'verifier_commit': VERIFIER, 'files': raw_files})
result = {'executor_commit': RUNTIME, 'verifier_commit': VERIFIER, 'final_production_commit': FINAL,
    'complete_recorded_scope': True, 'completed_corpora': 12, 'actual_jvms': 2256,
    'raw_attempts': 2304, 'copied_attempts_excluded': 48, 'refusals_rechecked': 168,
    'comparisons_recomputed': 576, 'qualified_reports': 456, 'required_route_commands_checked': 228,
    'new_application_launches': 0, 'original_controller_results_preserved': {'success': 8, 'failed_build_audit': 4},
    'profiles': profiles, 'comparison_bindings': bundles, 'sources': sources,
    'provider_files_preserved': provider_counts, 'external_tools_preserved': 3,
    'raw_files_sealed': len(raw_files), 'raw_manifest_sha256': digest(manifest),
    'recheck_index_sha256': digest(ROOT / 'recheck-d0282c4.json'),
    'provider_after_sha256': digest(ROOT / 'providers-after-bb1fb96.json'),
    'audit_script_sha256': digest(Path(__file__)), 'checked_at': datetime.datetime.now(datetime.UTC).isoformat(),
    'scope': 'Twelve recorded synchronous Java startup corpora. Actual applications used BB runtime; final657 cleanup code has separate smoke/unit evidence. No shipping, general build or invocation-cookie claim.'}
write(output, result)
print(json.dumps({key: value for key, value in result.items() if key not in ('profiles', 'comparison_bindings', 'sources')}), flush=True)
