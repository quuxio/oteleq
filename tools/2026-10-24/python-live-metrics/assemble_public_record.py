"""Publish only a complete successful sixteen-configuration retained audit."""

import argparse
import hashlib
import itertools
import json
from pathlib import Path

ROOT = Path(__file__).resolve().parent
PROFILES = {'origins': 'python-native-origins-v2', 'caches': 'python-native-cache-origins-v3'}
STARTS = ('both-on', 'collection-off', 'emission-off', 'both-off')
RUNTIME = '5fd7a06bb0186f1e62601a6c9a3be6bbc7a43562'
AUDITOR = 'bf0bbacb2e73db636e7391fbf5b1318a5478850f'
EXPECTED = {'actual_application_launches': 188, 'sdk_processes': 94, 'reports': 38,
    'complete_raw_and_typed_observations': 192, 'copied_original_observations': 4,
    'recomputed_comparisons': 48, 'altered_comparison_refusals': 5,
    'altered_live_evidence_refusals': 9, 'new_application_launches_during_audit': 0}


def read(path: Path) -> dict:
    """Read a retained record without changing the original evidence."""
    return json.loads(path.read_text())


def sha(path: Path) -> str:
    """Hash bounded local proof artefacts without serialising private records."""
    result = hashlib.sha256()
    with path.open('rb') as handle:
        for block in iter(lambda: handle.read(1024 * 1024), b''):
            result.update(block)
    return result.hexdigest()


def source(name: str) -> dict:
    """Recheck the archived source behind each separate executor or reader."""
    path = ROOT / ('source-' + name + '.json')
    index = read(path)
    assert sha(Path(index['archive'])) == index['archive_sha256']
    return {'commit': index['head'], 'source_archive_sha256': index['archive_sha256'],
            'source_files': len(index['files'])}


def assemble() -> dict:
    """Require exact terminal receipts and every distinct runtime/profile/startup."""
    final = ROOT / 'final-audits-bf0bbac'
    complete = read(final / 'complete.json')
    configurations = list(itertools.product(('312', '314'), PROFILES, STARTS))
    names = {'-'.join(row) for row in configurations}
    assert complete['configurations'] == 16 and len(complete['completed']) == 16
    assert set(complete['completed']) == names and complete['auditor_head'] == AUDITOR
    assert complete['new_target_applications'] == 0
    runtime_index = read(ROOT / 'source-5fd7a06.json')
    auditor_index = read(ROOT / 'source-bf0bbac.json')
    assert runtime_index['head'] == RUNTIME and auditor_index['head'] == AUDITOR
    production = {name: value for name, value in auditor_index['files'].items()
                  if name.startswith(('src/', 'adapters/', 'examples/'))}
    assert all(runtime_index['files'].get(name) == value for name, value in production.items())
    build = read(ROOT / 'runtime-build-5fd7a06.json')
    assert build['exit_code'] == 0 and build['source_held'] and not build['changed']
    assert build['head'] == RUNTIME and sha(Path(build['binary'])) == build['binary_sha256']
    provider = read(ROOT / 'provider-ce4-source-index.json')
    corpora, catalogues = [], {}
    for runtime, profile, startup in configurations:
        name = '-'.join((runtime, profile, startup))
        first = name == '312-origins-both-off'
        folder = (ROOT / 'qualification-312-origins-both-off-attempt01' if first
                  else ROOT / 'matrix-ff8875c/runs' / name)
        executed_path = (ROOT / 'qualification-312-origins-both-off-attempt01-result.json' if first
                         else ROOT / 'matrix-ff8875c/results' / (name + '.json'))
        execution = read(executed_path)
        assert execution['exit_code'] == 0 and execution['qualifier_source_held'] and not execution['changed']
        expected_driver = source('5fa3c27' if first else 'ff8875c')
        assert execution['qualifier_head'] == expected_driver['commit']
        audit_result = read(final / 'results' / (name + '.json'))
        assert audit_result['configuration'] == name and audit_result['exit_code'] == 0
        assert audit_result['auditor_head'] == AUDITOR and audit_result['auditor_source_held']
        assert not audit_result['changed']
        receipt_path = final / 'audits' / name / 'qualification.json'
        receipt = read(receipt_path)
        assert receipt['profile'] == PROFILES[profile] and receipt['startup'] == startup
        assert receipt['claim'] == 'equivalence over these tests and observations'
        assert receipt['artefact_class'] == 'diagnostic' and receipt['cli_sha256'] == build['binary_sha256']
        assert all(type(receipt[key]) is int and receipt[key] == value for key, value in EXPECTED.items())
        assert receipt['python_hexversion'] == {'312': 51122160, '314': 51251440}[runtime]
        catalogue_path = folder / 'provider-inputs.json'
        catalogue = read(catalogue_path)
        if runtime in catalogues:
            assert catalogue == catalogues[runtime]
        else:
            catalogues[runtime] = catalogue
        corpora.append({'python': {'312': '3.12.15', '314': '3.14.8'}[runtime],
            'profile': PROFILES[profile], 'startup': startup, 'totals': EXPECTED,
            'execution_driver_commit': expected_driver['commit'],
            'execution_result_sha256': sha(executed_path),
            'final_audit_result_sha256': sha(final / 'results' / (name + '.json')),
            'qualification_sha256': sha(receipt_path), 'provider_catalogue_sha256': sha(catalogue_path),
            'original_evidence_files_held': receipt['original_evidence_files_held']})
    audit_source = source('bf0bbac')
    audit_source['files_sha256'] = {name: auditor_index['files'][name] for name in (
        'tests/qualify_python_controls.py', 'tests/python_live_qualification.py',
        'tests/python_live_refusals.py', 'tests/python_sequence_fixture.py')}
    return {'qualification_schema_version': 1, 'date': '2026-10-24',
        'claim': 'equivalence over these tests and observations', 'artefact_class': 'diagnostic',
        'scope_status': 'qualified recorded synchronous origin/cache live metric schedules across all four initial states',
        'platform': {'os': 'macOS', 'architecture': 'arm64', 'python': ['3.12.15', '3.14.8']},
        'runtime': {'repository': 'quuxio/oteleq', **source('5fd7a06'),
                    'cli_sha256': build['binary_sha256'], 'production_sources_unchanged_in_verifier': True},
        'execution_drivers': [source('5fa3c27'), source('ff8875c')],
        'verifier': {**audit_source, 'entrypoint': 'tests/qualify_python_controls.py',
            'retained_options': ['--retained-only', '--audit-dir NEW_EXTERNAL_DIRECTORY'],
            'audit_manager_sha256': sha(ROOT / 'audit_completed_matrix_bf0bbac.py'),
            'assembly_script_sha256': sha(Path(__file__)), 'complete_receipt_sha256': sha(final / 'complete.json')},
        'provider': {'repository': 'quuxio/otelc', 'commit': provider['head'],
            'source_archive_sha256': provider['archive_sha256'], 'source_files': len(provider['files']),
            'profiles': list(PROFILES.values()), 'catalogues': {runtime: {
                'entries_preserved': len(catalogue),
                'installed_files': sum(name.startswith('installed:') for name in catalogue),
                'native_tool_files': sum(name.startswith('build/tools/python-inputs/') for name in catalogue),
                'tools': {name: value for name, value in catalogue.items() if name.startswith('tool')}
            } for runtime, catalogue in catalogues.items()}},
        'results': {'completed_configurations': len(corpora),
                    **{key: sum(row['totals'][key] for row in corpora) for key in EXPECTED}},
        'corpora': corpora,
        'observed': ['Complete literal before/outcome/after receiver, alias/cycle, own-static and module-global graphs',
            'Six declared methods, constructor/factory prefix, recursive calls and expected intermediate errors',
            'Independent live collection/emission, full export-off holds, retained measurements and restored positive control',
            'Actual supervisor/application/SDK identities, native origins, final SDK health and directly decoded OTLP',
            'Generated, replayed, unittest, detached/exported, reduced and original/changed current-source suites'],
        'limits': ['Synchronous diagnostic receiver calls only; explicit prepared profiles and recorded toolchains',
            'Serial trace grouping is separate from per-action invocation cookies',
            'Asynchronous/resource actions, arbitrary roots/loaders/build graphs and general dependency closure remain open',
            'No shipping-artefact, whole-language, exhaustive input/schedule or full-project completion claim'],
        'historical_failures': ['Initial development smoke/configuration failures remain separate from these sixteen completed configurations',
            'The earlier729f2c2 full gate failed two CLI tests;5fd7a06 fixes the lazy telemetry import and passes',
            'First execution uses5fa qualifier; ff adds retained live refusals; bf0 additionally requires every named and promoted route']}


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--output', type=Path, required=True)
    args = parser.parse_args()
    document = assemble()
    with args.output.open('x') as handle:
        json.dump(document, handle, indent=2)
        handle.write('\n')
    print(json.dumps(document['results']))
