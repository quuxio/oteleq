"""Derive the scoped publication record from immutable captures and retained audits."""
import hashlib
import json
from pathlib import Path

ROOT = Path('/Users/sclarke/github/oteleq-qualification/2026-10-24/python-origin-admission')
REPO = Path('/Users/sclarke/github/oteleq-qualification/work/oteleq-python-origin-admission')
def read(path):
    return json.loads(path.read_bytes())
def digest(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()
def seal(value):
    return hashlib.sha256(json.dumps(value, sort_keys=True, separators=(',', ':')).encode()).hexdigest()

runtime = read(ROOT / 'source-a027f10.json')
verifier = read(ROOT / 'source-fc5ebde.json')
changed = sorted(name for name in set(runtime['files']) | set(verifier['files'])
                 if runtime['files'].get(name) != verifier['files'].get(name))
assert all(name.startswith(('tests/', 'docs/')) for name in changed), changed
assert all(digest(REPO / name) == value for name, value in verifier['files'].items())
provider_index = read(Path('/Users/sclarke/github/otelc-qualification/2026-10-24/python-prepared-origins/source-794ccaa.json'))
corpora = []
for label, version in [('312', '3.12.15'), ('314', '3.14.8')]:
    folder = ROOT / ('qualified-a027f10-794ccaa-' + label)
    provider = ROOT / ('provider-794ccaa-' + label)
    assert all(digest(provider / name) == value for name, value in provider_index['files'].items())
    audit = read(folder / 'retained-audit.json')
    assert audit['actual_application_launches'] == 212 and audit['sdk_processes'] == 106
    assert audit['reports'] == 40 and audit['recomputed_comparisons'] == 54
    assert audit['source_preserved'] is audit['inputs_preserved'] is True
    reports = sorted(folder.rglob('report.json'))
    assert len(reports) == 40
    identities = {}
    observations = 0
    for path in reports:
        report = read(path)
        for case in report['cases']:
            for lane in ('baseline', 'instrumented_on'):
                for repeat in range(2):
                    attempt = path.parent / case['case'] / (lane + '-' + str(repeat))
                    actual = Path(read(attempt / 'command.json')[-1]).parent
                    execution = read(actual / 'python-runtime/python-execution.json')
                    row = {'runtime': str(actual / 'python-runtime'), 'plain': execution['plain'],
                           'supervisor_pid': execution['supervisor_pid'],
                           'application_pid': execution['application']['pid'],
                           'sdk_pid': None if execution['plain'] else execution['sdk']['pid']}
                    observations += 1
                    previous = identities.setdefault(row['runtime'], row)
                    assert previous == row
    assert len(identities) == 212 and observations == 216
    assert len({row['application_pid'] for row in identities.values()}) == 212
    assert len({row['supervisor_pid'] for row in identities.values()}) == 212
    assert sum(not row['plain'] for row in identities.values()) == 106
    catalogue = read(folder / 'provider-inputs.json')
    corpora.append({'python': version, 'python_hexversion': audit['python_hexversion'],
                    'actual_application_launches': 212, 'sdk_processes': 106,
                    'reports': 40, 'recomputed_comparisons': 54,
                    'complete_raw_and_typed_observations': 216, 'copied_original_observations': 4,
                    'receiver_workflows': audit['receiver_workflows'],
                    'effects_and_promotion': audit['effects_and_promotion'],
                    'source_preserved': True, 'inputs_preserved': True,
                    'provider_source_files_preserved': len(provider_index['files']),
                    'provider_input_records': len(catalogue),
                    'provider_input_catalogue_sha256': digest(folder / 'provider-inputs.json'),
                    'interpreter_sha256': catalogue['tool:python'],
                    'retained_audit_sha256': digest(folder / 'retained-audit.json'),
                    'launch_identity_set_sha256': seal(sorted(identities.values(), key=lambda row: row['runtime']))})
fixed = []
for label in ('312', '314'):
    path = ROOT / ('qualified-9f82075-794ccaa-' + label) / 'report.json'
    data = read(path)
    assert data['actual_application_launches'] == 12 and data['altered_evidence_refusals'] == 108
    fixed.append({'python': '3.12.15' if label == '312' else '3.14.8',
                  'actual_application_launches': 12, 'actual_sdk_launches': 6,
                  'altered_evidence_refusals': 108, 'report_sha256': digest(path)})
qualifiers = ['tests/qualify_python_generated_origins.py', 'tests/python_origin_effect_workflows.py',
              'tests/sequence_qualification.py', 'tests/python_sequence_fixture.py',
              'tests/qualify_python_sequences.py']
record = {
    'qualification_schema_version': 1, 'date': '2026-10-24',
    'claim': 'equivalence over these tests and observations', 'artefact_class': 'diagnostic',
    'scope_status': 'qualified recorded synchronous generated origin-v2 receiver and scalar/effect/promotion workflows',
    'platform': {'os': 'macOS', 'architecture': 'arm64', 'python': ['3.12.15', '3.14.8']},
    'runtime': {'repository': 'quuxio/oteleq', 'commit': runtime['head'],
                'source_archive_sha256': runtime['archive_sha256'], 'source_files': len(runtime['files']),
                'cli_sha256': digest(ROOT / 'runtime-a027f10/quux-oteleq'),
                'runtime_sources_unchanged_in_verifier': True,
                'later_source_changes': changed},
    'verifier': {'commit': verifier['head'], 'source_archive_sha256': verifier['archive_sha256'],
                 'source_files_preserved': len(verifier['files']),
                 'entrypoint': 'tests/qualify_python_generated_origins.py', 'retained_option': '--recheck',
                 'files_sha256': {name: verifier['files'][name] for name in qualifiers}},
    'execution_drivers': {
        'receivers': {'commit': runtime['head'], 'source_archive_sha256': runtime['archive_sha256']},
        'effects_and_promotion': {'commit': 'e3e39043dac374e42de302dcb0a1fcdd456060bf',
                                  'source_archive_sha256': read(ROOT / 'source-e3e3904.json')['archive_sha256']},
        'note': 'The later verifier corrects receipt and historical source auditing; original captures retain their actual runtime and driver identities.'},
    'provider': {'repository': 'quuxio/otelc', 'commit': provider_index['head'],
                 'source_archive_sha256': provider_index['archive_sha256'],
                 'source_files_preserved_each_runtime': len(provider_index['files']),
                 'profile': 'python-native-origins-v2',
                 'protocols': {'request': 2, 'plan': 2, 'prepared': 2, 'command': 2, 'execution': 2,
                               'journal': 2, 'code': 2, 'health': 2, 'sdk': 1,
                               'code_comparisons': None, 'source_complete': False}},
    'results': {'completed_corpora': 2, 'actual_application_launches': 424,
                'sdk_processes': 212, 'reports': 80, 'recomputed_comparisons': 108,
                'complete_raw_and_typed_observations': 432, 'copied_original_observations': 8,
                'additional_target_applications_in_retained_audits': 0,
                'metadata_only_interpreter_probe_each_audit': 1},
    'corpora': corpora,
    'checked_behaviour': [
        'Independent before-launch target and declared source constructor/factory facts in both lanes',
        'Actual supervisor/application/SDK identities, raw native journal2 relations and all selected SDK joins',
        'Complete independently literal receiver/global/own-static graphs, returned aliases/cycles, recursion and supported exceptions',
        'A deliberate same-return intermediate state difference fails, reduces from7 to0 and stays failed in retained unittest/replay',
        'Generated, replayed, standard-library unittest, source-detached export and reduced retained routes',
        'Three independently generated scalar domain cases per function with complete global graph and fixed return expectation',
        'Literal filesystem before/after bytes, kinds and permissions; scripted binary HTTP request/response and declared headers',
        'Current-source promotion discovers unchanged bodies, changed bodies and a newly added function',
        'All five temporal source plans bind their expected literal body and complete private snapshot; the original application is restored',
        'Every comparison is recomputed; direct OTLP trace/metric and final-health receipts are independently rechecked',
        'All recorded SDK source, native products, installed package catalogues and selected interpreter bytes remain preserved'],
    'separate_fixed_public_transport_and_origin_corpus': {
        'runtime_commit': '9f820758c5c4e1ac25c779dddf61e2a6422bb716',
        'actual_application_launches': 24, 'actual_sdk_launches': 12,
        'altered_evidence_refusals': 216, 'corpora': fixed,
        'scope': 'Ordinary, recursive and handled-exception fixed workloads with binary stdout/stderr and both-lane selected source origins; not generated observer qualification.'},
    'review': {'worker_review_sha256': digest(ROOT / 'independent-review-a027f10.json'),
               'public_reader_review_sha256': digest(ROOT / 'independent-review-9f82075.json'),
               'scope': 'Recorded component and worker reviews; final verifier/publication review and protected main delivery remain separate.'},
    'validation': {'full_gate_commit': 'e3e39043dac374e42de302dcb0a1fcdd456060bf',
                    'full_gate_exit_code': 0, 'generation_tests': 1132,
                    'rust_product_line_coverage_percent': 97.38,
                    'full_gate_result_sha256': digest(ROOT / 'full-gate-e3e3904/result.json'),
                    'full_gate_log_sha256': digest(ROOT / 'full-gate-e3e3904/make-check.log'),
                    'verifier_fix_python_tests_each_runtime': 172, 'shared_qualification_tests': 6,
                    'scope': 'Recorded implementation gate and focused verifier checks; final-head CI/release delivery is separate.'},
    'preserved_failures': [
        {'commit': 'a63b131a68cf9b52faedd454e276e1da36732edd',
         'kind': 'bare CLI import failed because protobuf was imported eagerly',
         'fixed_commit': runtime['head'], 'result_sha256': digest(ROOT / 'full-gate-a63b131/result.json')},
        {'commit': 'e3e39043dac374e42de302dcb0a1fcdd456060bf',
         'kind': 'Combined audit compared historical promotion plans against the restored current source',
         'fixed_commit': verifier['head'],
         'failed_logs_sha256': {label: digest(ROOT / ('append-effects-e3e3904-' + label + '.log')) for label in ('312', '314')},
         'target_applications_repeated_to_fix_audit': 0}],
    'limits': [
        'Only the recorded synchronous source entry and ordinary application-root source loaders are qualified',
        'Cache-only or unsupported loaders, namespace/installed-project integration and complete interpreter/OS/import closure remain open',
        'General object arguments/factories, async/generator/resource actions, live metric controls and per-action attribution remain open',
        'First-execution/source-root identities are not invocation counts; decoded telemetry supplies the separate call totals',
        'The native origin observer and generated diagnostic caller are part of the observed workload; this is not shipping-artefact evidence',
        'Other providers, platforms and callable/build profiles require their own qualification',
        'All remaining21 requirements in docs/completion.md remain in force']}
output = ROOT / 'python-generated-origins-2026-10-24.json'
output.write_text(json.dumps(record, indent=2) + '\n')
print(json.dumps({'output': str(output), 'generated_applications': record['results']['actual_application_launches'],
                  'fixed_applications_separate': 24, 'corpora': len(corpora)}))
