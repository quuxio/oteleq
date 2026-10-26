"""Publish bounded exact-revision evidence from completed independent corpora."""
import hashlib
import json
from pathlib import Path

ROOT = Path('/Users/sclarke/github/oteleq-qualification/2026-10-24/java-generated-actions')
REPO = Path('/Users/sclarke/github/oteleq-qualification/work/oteleq-java-generated-actions')
SDK_REVIEW = ROOT.parent / 'java-clock-review-45b7564'
RECORD = 'java-generated-actions-2026-10-24.json'

def read(path):
    return json.loads(path.read_bytes())

def sha(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()

provider = read(ROOT / 'provider-clock-45b7564.json')
consumer = read(ROOT / 'source-d53377e.json')
review = read(ROOT / 'independent-review-d53377e.json')
corpora, launches = [], set()
for profile in ('safe', 'archive'):
    name = 'qualified-d53377e-clock-45b7564-' + profile
    folder = ROOT / name
    value, inputs = read(folder / 'qualification.json'), read(folder / 'inputs.json')
    retained = read(ROOT / ('retained-d53377e-clock-45b7564-' + profile + '-314.log'))
    assert retained == value and value['source_preserved']
    assert (value['reports'], value['distinct_application_launches'], value['complete_boundary_graphs'], value['action_scopes'], value['spans'], value['altered_evidence_refusals']) == (19, 80, 564, 94, 426, 16)
    identities = set()
    for route in read(folder / 'routes.json'):
        report_path = Path(route['report'])
        for case in read(report_path)['cases']:
            for lane in ('baseline', 'instrumented_on'):
                for index in range(2):
                    process = read(report_path.parent / case['case'] / (lane + '-' + str(index)) / 'process.json')
                    assert type(process['pid']) is int and process['pid'] > 0
                    identities.add((process['pid'], hashlib.sha256(json.dumps(process['argv']).encode()).hexdigest()))
    assert len(identities) == 80 and not launches.intersection(identities)
    launches.update(identities)
    corpora.append({
        'java_profile': value['java_profile'],
        **{key: value[key] for key in ('reports', 'distinct_application_launches', 'complete_boundary_graphs', 'action_scopes', 'spans', 'altered_evidence_refusals', 'source_preserved')},
        'consumer_inputs_sha256': inputs['consumer'],
        'sdk_input_map_sha256': hashlib.sha256(json.dumps(inputs['sdk'], sort_keys=True, separators=(',', ':')).encode()).hexdigest(),
        'sdk_input_files': sum(not key.startswith('tool:') for key in inputs['sdk']),
        'tool_files': sum(key.startswith('tool:') for key in inputs['sdk']),
        'launch_identity_set_sha256': hashlib.sha256(json.dumps(sorted(identities), separators=(',', ':')).encode()).hexdigest(),
        'qualification_sha256': sha(folder / 'qualification.json'),
        'input_manifest_sha256': sha(folder / 'inputs.json'),
        'route_manifest_sha256': sha(folder / 'routes.json'),
        'refusal_summary_sha256': sha(folder / 'refusals/summary.json'),
        'python_314_retained_audit_sha256': sha(ROOT / ('retained-d53377e-clock-45b7564-' + profile + '-314.log')),
    })
assert len(launches) == 160
inputs = read(ROOT / 'qualified-d53377e-clock-45b7564-safe/inputs.json')
record = {
    'qualification_schema_version': 1,
    'date': '2026-10-24',
    'claim': 'equivalence over these tests and observations',
    'artefact_class': 'diagnostic',
    'scope_status': 'qualified recorded synchronous generated private static and receiver action workflows on the frozen clock-fix provider',
    'platform': {'os': 'macOS', 'architecture': 'arm64', 'jdk': '21.0.12.1', 'execution_host_python': '3.12.15', 'additional_retained_reader_python': '3.14.8'},
    'runtime': {'repository': 'quuxio/oteleq', 'commit': consumer['head'], 'source_archive_sha256': consumer['archive_sha256'], 'source_files_preserved': len(consumer['files']), 'cli_sha256': inputs['cli_sha256'], 'generator_inputs_sha256': inputs['consumer']},
    'verifier': {'commit': '9edbb66f598862443a39b0134229933b21dd0991', 'entrypoint': 'tests/qualify_java_generated_actions.py', 'retained_option': '--retained-only', 'qualifier_files_sha256': inputs['qualifier']},
    'provider': {'repository': 'quuxio/otelc', 'commit': provider['head'], 'base': provider['base'], 'delivery_status': 'recorded candidate; final merged-provider compatibility is separate', 'source_archive_sha256': provider['archive_sha256'], 'source_files_preserved': len(provider['files']), 'products': provider['products'], 'all_products_preserved': True},
    'tools_sha256': {name.removeprefix('tool:'): digest for name, digest in read(ROOT / 'qualified-d53377e-clock-45b7564-archive/inputs.json')['sdk'].items() if name.startswith('tool:')},
    'results': {'completed_corpora': len(corpora), 'reports': 38, 'distinct_application_launches': len(launches), 'complete_literal_boundary_graphs': 1128, 'instrumented_action_scopes': 188, 'instrumented_spans': 852, 'altered_evidence_refusals': 32, 'additional_applications_in_retained_reader_audits': 0},
    'corpora': corpora,
    'checked_behaviour': [
        'Private static and declared receiver target calls through exact typed MethodHandles, with private factory setup outside the action',
        'Four ordered receiver actions with recursive selected-method counts 1, 4, 1, 2, original exception class/message and returned-receiver aliases',
        'Complete independently literal before/after/result graphs in every repeat and lane',
        'All four initial collection/emission combinations in one unchanged application build/process per sequence',
        'Generated suites, source-detached exports, frozen replay, unchanged/changed current-source promotion, scalar shrinking, reduced framework and replay routes',
        'Same return with an intentional instrumented-only global mutation remains a failed equivalence test and shrinks from 7 to 0',
        'Selected-JDK multi-release archive member resolution and a forced application/SDK helper package collision with independently reproduced relocation',
        'Actual compiler/classes, host ready/release and control-history binding, decoded role/method trees, collected function metrics and final global health',
    ],
    'refusal_controls': [row['control'] for row in read(ROOT / 'qualified-d53377e-clock-45b7564-safe/refusals/summary.json')['controls']],
    'detected_provider_defect': {'provider_commit': provider['base'], 'kind': 'telemetry_witness_refusal', 'route': 'source-detached Counter.run generated test', 'child_end_after_parent_ns': 3124, 'strict_parent_interval_check_preserved': True, 'raw_failure_proof_sha256': sha(ROOT / 'main-provider-interval-failure-9edbb66.json'), 'fix_commit': provider['head'], 'independent_unchanged_production_clock_regressions_failed': 3, 'independent_fixed_java_tests_passed': 74, 'independently_rebuilt_provider_classes_matched': 76},
    'review': {'consumer_verdict': review['verdict'], 'consumer_review_sha256': sha(ROOT / 'independent-review-d53377e.json'), 'sdk_component_review_sha256': sha(SDK_REVIEW / 'review.json'), 'sdk_component_scope': 'parent clock and synchronous exception safety; actual generated admission has the separate corpora above'},
    'validation': {'full_gate_commit': consumer['head'], 'generation_tests': 1089, 'rust_product_line_coverage_percent': 97.38, 'full_gate_result_sha256': sha(ROOT / 'full-gate-d53377e/result.json'), 'full_gate_log_sha256': sha(ROOT / 'full-gate-d53377e/make-check.log')},
    'limits': ['Only the recorded synchronous private static and declared receiver fixture shapes are qualified', 'General Java build systems/modules, arbitrary object arguments/factories, asynchronous or virtual-thread attribution and shipping artefacts remain open', 'Other language invocation-scoped witnesses need separate implementation and qualification', 'Historical positive captures remain bounded to their actual executions; the later failed provider capture remains retained', 'All remaining requirements in docs/completion.md remain in force'],
}
path = REPO / 'docs/qualification' / RECORD
assert not path.exists()
path.write_text(json.dumps(record, indent=2) + '\n')
(ROOT / 'publication-draft' / RECORD).write_text(path.read_text())
print(json.dumps({'published_local_record': str(path), 'actual_launches': len(launches), 'corpora': len(corpora), 'record_sha256': sha(path)}))
