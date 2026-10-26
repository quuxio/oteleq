"""Seal completed Java startup evidence without launching an application."""
import datetime
from concurrent.futures import ThreadPoolExecutor
import hashlib
import json
import os
from pathlib import Path
import stat
import sys

ROOT = Path(__file__).resolve().parent
RUNTIME = 'bb1fb9696abea1b57b9b1e2ad605c5614f92c387'
FINAL = '6571c7c2b028a4acb9e153550da6dbe91cef3639'
PROFILES = ('stock', 'safe', 'archive')
STARTS = {'both-on', 'collection-off', 'emission-off', 'both-off'}
sys.path.insert(0, str(ROOT / 'source-bb1fb96/tests'))
import qualify_java_startup as startup
import java_startup_receipts as receipts
from qualify_project_tests import command as recorded_command


def comparison_command(arguments, folder, name, expected=0, environment=None):
    assert len(arguments) == 3 and arguments[1] == 'compare-observations'
    assert name == 'startup-recomparison'
    key = hashlib.sha256(str(Path(arguments[-1]).resolve()).encode()).hexdigest()[:24]
    destination = ROOT / 'final-recomparisons-bb1fb96' / key
    destination.mkdir(mode=0o700, parents=True)
    return recorded_command(arguments, destination, name, expected, environment)


startup.command = comparison_command


def read(path: Path) -> dict:
    return json.loads(path.read_bytes())


def digest(path: Path) -> str:
    descriptor = os.open(path, os.O_RDONLY | os.O_NOFOLLOW | os.O_NONBLOCK)
    try:
        before = os.fstat(descriptor)
        assert stat.S_ISREG(before.st_mode), 'Refuse a non-regular evidence input'
        value = hashlib.sha256()
        while block := os.read(descriptor, 1024 * 1024):
            value.update(block)
        after = os.fstat(descriptor)
        identity = lambda item: (item.st_dev, item.st_ino, item.st_size,
            item.st_mtime_ns, item.st_ctime_ns, item.st_mode, item.st_uid)
        assert identity(before) == identity(after), 'Evidence changed while being read'
        return value.hexdigest()
    finally:
        os.close(descriptor)


def fail_walk(error: OSError) -> None:
    raise error


def files(folder: Path):
    for directory, children, names in os.walk(folder, followlinks=False, onerror=fail_walk):
        parent = Path(directory)
        assert not parent.is_symlink()
        for name in children:
            assert not (parent / name).is_symlink(), 'Refuse evidence directory links'
        for name in sorted(names):
            path = parent / name
            assert not path.is_symlink(), 'Refuse evidence file links'
            yield path


def recheck_run(row: dict) -> dict:
    """Recheck every current graph, channel, build and raw receipt afresh."""
    folder = Path(row['folder'])
    states = startup.startup_states(row['startup'])
    actual = startup.recheck(folder, ROOT / 'quux-oteleq-bb1fb96', states)
    workspaces = list((folder / 'corpus/cases').glob('oteleq-run-*/plan.json'))
    assert len(workspaces) == 1
    plan = read(workspaces[0])
    entry = next(item for item in plan['inventory'] if item.get('otelc_function') == 'Counter.identity(int)')
    controls = read(folder / 'evidence-controls/QUALIFICATION.json')
    assert controls['evidence_refusals'] == 14 and controls['actual_applications'] == 0
    receipts.verify(folder / 'evidence-controls/positive', entry)
    for control in controls['controls']:
        try:
            receipts.verify(folder / 'evidence-controls' / ('altered-' + control['name']), entry)
        except ValueError as error:
            assert str(error) == control['reason']
        else:
            raise AssertionError('Previously refused actual evidence was accepted')
    return {'profile': row['profile'], 'startup': row['startup'], 'actual_jvms': actual['actual_jvm_launches'],
        'comparisons_recomputed': actual['typed_comparisons_recomputed'],
        'refusals_rechecked': len(controls['controls']), 'source_preserved': actual['source_preserved']}


def main() -> None:
    output = ROOT / 'final-audit-bb1fb96.json'
    assert not output.exists(), 'Do not overwrite an existing final audit'
    matrix = read(ROOT / 'matrix-bb1fb96.json')
    assert matrix['state'] == 'completed' and matrix['exit'] == 0
    runs = matrix['runs']
    assert len(runs) == 12 and all(row['state'] == 'completed' and row['exit'] == 0 for row in runs)
    identities = {(row['profile'], row['startup']) for row in runs}
    assert len(identities) == 12
    assert identities == {(tag + '-methods-v1', start) for tag in PROFILES for start in STARTS}
    assert matrix['executor_commit'] == matrix['verifier_commit'] == RUNTIME
    audit_inputs = {}
    for tag in ('stock', 'safe'):
        path = ROOT / ('partial-' + tag + '-audit-bb1fb96.json')
        audit = read(path)
        assert audit['executor_commit'] == audit['verifier_commit'] == RUNTIME
        assert audit['new_application_launches'] == 0 and audit['source_files_preserved'] == 397
        assert {row['startup'] for row in audit['profiles']} == STARTS
        assert len(audit['profiles']) == 4
        assert (audit['actual_jvms'], audit['refusals_rechecked'], audit['comparisons_recomputed']) == (752, 56, 192)
        audit_inputs[path.name] = digest(path)
    with ThreadPoolExecutor(max_workers=3) as pool:
        fresh = list(pool.map(recheck_run, runs))
    total_jvms = sum(row['actual_jvms'] for row in fresh)
    refusals = sum(row['refusals_rechecked'] for row in fresh)
    comparisons = sum(row['comparisons_recomputed'] for row in fresh)
    assert (total_jvms, refusals, comparisons) == (2256, 168, 576)
    for suffix, commit, count in [('bb1fb96', RUNTIME, 397), ('6571c7c', FINAL, 398)]:
        index = read(ROOT / ('source-' + suffix + '.json'))
        assert index['commit'] == commit and len(index['files']) == count
        assert all(digest(ROOT / ('source-' + suffix) / name) == value
            for name, value in index['files'].items())
    assert digest(ROOT / 'quux-oteleq-bb1fb96') == '59a27ba2a5b95140fd9fddf83f4fec98745fdd56d5372fa1f147c3aaada7aea7'
    assert digest(ROOT / 'quux-oteleq-6571c7c') == '8f619fc5793a66d36f7da89e35ff9688c95a48318936c98a8d7d977a7675ff2d'
    providers = read(ROOT / 'providers-before-bb1fb96.json')
    after = read(ROOT / 'providers-after-bb1fb96.json')
    assert after['source_files_preserved'] == 397 and after['external_tools_preserved'] == 3
    provider_counts = {}
    for row in providers['providers']:
        provider = Path(row['provider'])
        assert not row['symlinks']
        actual = {str(path.relative_to(provider)): digest(path) for path in files(provider)}
        assert actual == row['files']
        provider_counts[row['profile']] = len(actual)
    assert provider_counts == {'stock-methods-v1': 64, 'safe-methods-v1': 150, 'archive-methods-v1': 112}
    assert after['provider_files_preserved'] == provider_counts
    for name, value in providers['external_tools'].items():
        path = Path(name)
        assert str(path.resolve(strict=True)) == value['resolved'] and digest(path.resolve(strict=True)) == value['sha256']
    profiles, bundle_bindings, raw_files = [], {}, {}
    for row in sorted(runs, key=lambda item: (item['profile'], item['startup'])):
        folder = Path(row['folder'])
        qualified = read(folder / 'QUALIFICATION.json')
        assert qualified['java_profile'] == row['profile']
        assert qualified['actual_jvm_launches'] == 188 and qualified['raw_attempt_folders'] == 192
        assert qualified['copied_attempts_excluded'] == 4 and qualified['typed_comparisons_recomputed'] == 48
        assert qualified['qualified_reports'] == 38 and qualified['source_preserved']
        assert qualified['cli_sha256'] == digest(ROOT / 'quux-oteleq-bb1fb96')
        assert qualified['evidence_controls']['evidence_refusals'] == 14
        assert qualified['evidence_controls']['actual_applications'] == 0
        bundles = sorted((folder / 'corpus').rglob('typed-bundle.json'))
        assert len(bundles) == 48
        for path in bundles:
            key = path.relative_to(ROOT).as_posix()
            assert key not in bundle_bindings
            comparison_key = hashlib.sha256(str(path.resolve()).encode()).hexdigest()[:24]
            audit_folder = ROOT / 'final-recomparisons-bb1fb96' / comparison_key
            assert (audit_folder / 'startup-recomparison.exit').is_file()
            actual = read(audit_folder / 'startup-recomparison.stdout')
            expected = read(path.parent / 'comparison.json')
            assert actual == expected
            bundle_bindings[key] = {'bundle_sha256': digest(path),
                'comparison_sha256': digest(path.parent / 'comparison.json'),
                'recomputed_sha256': digest(audit_folder / 'startup-recomparison.stdout')}
        profiles.append({'profile': row['profile'], 'provider_commit': row['provider_commit'],
            'startup': row['startup'], 'qualification_sha256': digest(folder / 'QUALIFICATION.json'),
            'actual_jvms': 188, 'raw_attempts': 192, 'copies_excluded': 4,
            'comparisons_recomputed': 48, 'refusals_rechecked': 14, 'reports_checked': 38})
        for path in files(folder):
            key = path.relative_to(ROOT).as_posix()
            assert key not in raw_files
            raw_files[key] = {'sha256': digest(path), 'size': path.stat().st_size,
                'mode': stat.S_IMODE(path.stat().st_mode)}
    assert len(bundle_bindings) == 576
    manifest = ROOT / 'raw-manifest-bb1fb96.json'
    assert not manifest.exists()
    manifest.write_text(json.dumps({'executor_commit': RUNTIME, 'files': raw_files}, indent=2) + '\n')
    result = {'executor_commit': RUNTIME, 'verifier_commit': RUNTIME,
        'final_code_commit': FINAL, 'complete': True, 'completed_corpora': 12,
        'actual_jvms': total_jvms, 'raw_attempts': 2304, 'copied_attempts_excluded': 48,
        'refusals_rechecked': refusals, 'comparisons_recomputed': comparisons,
        'fresh_profile_rechecks': fresh, 'maximum_parallel_offline_audits': 3,
        'new_application_launches': 0, 'profiles': profiles,
        'partial_audit_sha256': audit_inputs, 'comparison_bindings': bundle_bindings,
        'provider_files_preserved': provider_counts, 'external_tools_preserved': 3,
        'runtime_sources_preserved': 397, 'final_code_sources_preserved': 398,
        'raw_files_sealed': len(raw_files), 'raw_manifest_sha256': digest(manifest),
        'audit_script_sha256': digest(Path(__file__)),
        'provider_after_sha256': digest(ROOT / 'providers-after-bb1fb96.json'),
        'checked_at': datetime.datetime.now(datetime.UTC).isoformat(),
        'scope': 'Twelve recorded synchronous Java startup corpora only. Matrix executedBB; final657code has separate unit/compatibility evidence. No shipping, generic builds or invocation-cookie claim.'}
    output.write_text(json.dumps(result, indent=2) + '\n')
    print(json.dumps({key: value for key, value in result.items()
        if key not in ('comparison_bindings', 'profiles')}), flush=True)


if __name__ == '__main__':
    main()
