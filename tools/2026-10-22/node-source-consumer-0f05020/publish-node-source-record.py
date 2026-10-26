"""Publish exact bounded qualification facts after verifying all final receipts."""

import hashlib
import json
from pathlib import Path

ROOT = Path(__file__).parent
REPO = Path('/Users/sclarke/github/oteleq-qualification/work/oteleq-node-source-provider')
PRODUCER = Path('/Users/sclarke/github/otelc-qualification/2026-10-22/node-provider-0f05020')


def read(path: Path):
    return json.loads(path.read_bytes())


def digest(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


audit = read(ROOT / 'final-corpus-audit-1800.json')
preservation = read(ROOT / 'provider-after-1800.json')
assert audit['actual_applications'] == 1800 and audit['comparisons_recomputed'] == 456
assert preservation['entries'] == 8284 and preservation['source_files'] == 206
assert preservation['read_only_directories'] == 939 and preservation['links'] == 12
handoff = read(PRODUCER / 'handoff.json')
for record, expected in [('public-protocols.json', handoff['protocol_descriptor_sha256']),
                         ('public-plan.json', handoff['public_plan_sha256']),
                         ('common-defaults.json', handoff['common_defaults_sha256']),
                         ('ci-proof.json', handoff['checks']['required_ci_proof_sha256'])]:
    assert digest(PRODUCER / record) == expected
ci = read(PRODUCER / 'ci-proof.json')
assert ci['head'] == preservation['source_commit']
assert all(row['head_sha'] == ci['head'] and row['status'] == 'completed' and row['conclusion'] == 'success' for row in ci['checks'])
assert set(ci['required_contexts']) <= {row['name'] for row in ci['checks']}

runtime = read(ROOT / 'reviewed-source-3e9614e.json')
verifier = read(ROOT / 'reviewed-source-fbd27fb.json')
files = ['node_project_oracle.py', 'node_source_oracle.py', 'node_collection_oracle.py',
         'node_receiver_oracle.py', 'qualify_node_project.py', 'qualify_node_receivers.py',
         'qualify_node_source_collection.py', 'qualify_node_source_effects.py',
         'qualify_node_source_channels.py']
module_names = ['module-3e-node24-native', 'module-3e-node24-api', 'module-3e-node26-native', 'module-3e-node26-api']
modules = []
for name in module_names:
    data = read(ROOT / name / 'QUALIFICATION.json')
    assert data['actual_application_launches'] == 245 and len(data['cases']) == 14 and len(data['controls']) == 5
    modules.append({'name': name, 'node': data['cases'][0]['node_version'], 'provider': data['node_provider'],
                    'contexts': [row['context'] for row in data['cases']], 'actual_applications': 245,
                    'controls': data['controls']})

categories = {}
for name, prefixes in [('module_context', ('module-',)), ('receivers', ('receivers-',)),
                       ('collection', ('collection-',)), ('effects_and_promotion', ('effects-',)),
                       ('binary_application_channels', ('channels-',))]:
    rows = [row for row in audit['corpora'] if row['corpus'].startswith(prefixes)]
    categories[name] = {'actual_applications': sum(row['actual_applications'] for row in rows), 'corpora': rows}
assert sum(row['actual_applications'] for row in categories.values()) == 1800

record = {
    'qualification_schema_version': 1, 'date': '2026-10-22',
    'claim': 'equivalence over these tests and observations', 'artefact_class': 'diagnostic',
    'scope_status': 'qualified recorded source5/execution1 diagnostic profiles',
    'platform': {'os': 'macOS', 'architecture': 'arm64', 'node_versions': ['24.21.0', '26.11.0'], 'python': '3.14.8'},
    'runtime': {'repository': 'quuxio/oteleq', 'commit': runtime['commit'],
                'source_archive_sha256': runtime['archive_sha256'], 'cli_sha256': audit['cli_sha256'],
                'source_inputs_unchanged_through_verifier': verifier['commit']},
    'verifier': {'commit': verifier['commit'], 'source_archive_sha256': verifier['archive_sha256'],
                 'files': {name: verifier['files']['tests/' + name] for name in files},
                 'final_audit_sha256': digest(ROOT / 'verify-final-node-corpora-1800.py'),
                 'final_audit_receipt_sha256': digest(ROOT / 'final-corpus-audit-1800.json')},
    'provider': {'repository': 'quuxio/otelc', 'commit': preservation['source_commit'],
                 'source_archive_sha256': handoff['source_archive_sha256'],
                 'index_sha256': preservation['index_sha256'], 'all_unchanged': True,
                 'entries': 8284, 'source_files': 206, 'read_only_directories': 939, 'links': 12,
                 'external_tools': preservation['external_tools'], 'protocols': handoff['protocols'],
                 'hosted_checks': ci['checks'], 'preservation_receipt_sha256': digest(ROOT / 'provider-after-1800.json')},
    'actual_application_launches': 1800,
    'raw_application_receipts': sum(row['raw_application_receipts'] for row in audit['corpora']),
    'reports_checked': sum(row['reports_checked'] for row in audit['corpora']),
    'comparisons_recomputed': 456, 'all_recomputed_results_match': True,
    'categories': categories, 'module_profiles': modules,
    'routes': ['direct', 'generated unittest', 'frozen replay', 'detached exported unittest',
               'scalar shrinking', 'current-source promotion', 'changed source', 'new function discovery', 'moved checkout'],
    'checks': ['complete independently expected scalar/receiver graphs and descriptor/alias order',
               'actual application/SDK process and closed drain receipts', 'independently decoded OTLP and cumulative history',
               'source5 raw emission and execution1 body-entry/reentry evidence',
               'bounded collection and actual GC creation link; retained receiver stays inconclusive',
               'seeded filesystem bytes and scripted HTTP request/offered-response bytes',
               'literal nonempty NUL/non-UTF8 stdout/stderr and stdout-only differences',
               'strict fixture/source/protocol/format refusals and source preservation'],
    'collection': {'profiles_per_node': ['JavaScript/native', 'TypeScript/native', 'TypeScript/API', 'retained JavaScript receiver'],
                    'censored_control': 'inconclusive through every route; clearing observer gaps cannot qualify its missing lifetime witness'},
    'local_validation': {'full_gate_commit': 'e33fafe507743279d7563eab4403753fe2b2fabc',
                         'full_gate_distinct_regressions': 981, 'capture_python': 165, 'generation_python': 717,
                         'rust': 74, 'node': 21, 'go_observer': 4, 'rust_product_line_coverage_percent': 97.38,
                         'later_workflow_regressions': 3, 'later_binary_channel_unit_regressions': 3,
                         'fresh_hash_locked_environment_node_tests': 113,
                         'hash_mismatch_control': 'pip refuses a wheel with a deliberately incorrect local hash'},
    'presentation': {'browser_reviewed': ['matching collection', 'censored collection', 'stdout-only difference'],
                     'collection_screenshots': {name: digest(ROOT / name) for name in ['collection-report-match.png', 'collection-report-censored.png']},
                     'binary_channel_screenshot_sha256': digest(ROOT / 'channel-report.png'),
                     'censored_junit_errors': 1, 'binary_output_junit_failures': 1},
    'separate_prior_experiments': ['source4 development and failed contexts', '9113317 precursor matrices',
                                  '742ae0d matrices/receiver corpora before the censoring correction',
                                  'initial collection/censored-oracle development', 'effects replay checker opaque-ID failures'],
    'limits': ['Diagnostic access/entrypoint helpers; no shipping-artefact claim.',
               'Fixed source formats and declared supported own storage; arbitrary object arguments, inherited/private/native storage and dependency/build integration remain incomplete.',
               'Module-body entry is not invocation-scoped action attribution or module completion.',
               'Live Node metric collection/emission control schedules remain unimplemented in the consumer.',
               'Package-manager workspaces, custom/transitive loaders and semantic TypeScript project builds are not qualified.',
               'No GC timing or leak inference; missing requested collection is incomplete evidence.',
               'Observer/root/exception and graph-boundary limits remain as documented.',
               'Downstream receipt and OTLP partial-rejection absence are not inferred from SDK accounting.',
               'External tool hashes do not cover OS libraries or establish container/hostile-code isolation.',
               'Other SDK revisions, platforms, runtime/compiler combinations and application inputs need their own qualification.'],
}
destination = REPO / 'docs/qualification/node-source-provider-2026-10-22.json'
assert not destination.exists()
destination.write_text(json.dumps(record, indent=2) + '\n')
print(json.dumps({'record': str(destination), 'applications': 1800, 'comparisons': 456,
                  'raw_receipts': record['raw_application_receipts'], 'reports': record['reports_checked']}))
